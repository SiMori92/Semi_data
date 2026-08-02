"""
crawler.py — Semiconductor Industry Data Crawler
=================================================
Fetches data for all tickers defined in config.py using yfinance and stores
results in a local SQLite database (semiconductor_data.db).

Run directly:
    python crawler.py               # crawl all tickers
    python crawler.py --tickers NVDA AMD TSMC   # crawl specific tickers
    python crawler.py --quick       # skip options IV (faster)
"""

import argparse
import logging
import sqlite3
import time
from datetime import datetime
from config import now_hkt as _now_hkt   # UTC+8 timestamp helper
from job_heartbeat import start_job, finish_job   # QA F-01 — run heartbeats

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.signal import argrelextrema

from config import (
    TICKER_MAP,
    DB_PATH,
    PRICE_HISTORY_PERIOD,
    LARGE_DROP_THRESHOLD,
    CYCLE_DETECTION_WINDOW,
    REQUEST_DELAY_SECONDS,
)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE SETUP
# ══════════════════════════════════════════════════════════════════════════════

def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't already exist."""
    conn.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS crawl_runs (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at        TEXT NOT NULL,
            finished_at       TEXT,
            status            TEXT DEFAULT 'running',
            tickers_attempted INTEGER DEFAULT 0,
            tickers_ok        INTEGER DEFAULT 0
        );

        -- Static company / instrument metadata
        CREATE TABLE IF NOT EXISTS company_info (
            ticker          TEXT PRIMARY KEY,
            display_name    TEXT,
            company_name    TEXT,
            exchange        TEXT,
            hq_country      TEXT,
            sector          TEXT,
            industry        TEXT,
            currency        TEXT,
            updated_at      TEXT
        );

        -- Daily OHLCV prices (insert-or-ignore keeps history intact)
        CREATE TABLE IF NOT EXISTS daily_prices (
            ticker  TEXT    NOT NULL,
            date    TEXT    NOT NULL,
            open    REAL,
            high    REAL,
            low     REAL,
            close   REAL,
            volume  REAL,
            PRIMARY KEY (ticker, date)
        );

        -- Quarterly income-statement + balance-sheet metrics
        CREATE TABLE IF NOT EXISTS quarterly_financials (
            ticker              TEXT    NOT NULL,
            period_end          TEXT    NOT NULL,
            revenue             REAL,
            gross_profit        REAL,
            gross_margin        REAL,
            operating_profit    REAL,
            op_margin           REAL,
            rd_expense          REAL,
            rd_to_revenue       REAL,
            net_profit          REAL,
            net_margin          REAL,
            eps                 REAL,
            pe_ratio            REAL,
            market_cap          REAL,
            accounts_receivable REAL,
            ar_turnover         REAL,
            inventory           REAL,
            inventory_turnover  REAL,
            PRIMARY KEY (ticker, period_end)
        );

        -- Market-sentiment snapshot (one row per ticker per crawl date)
        CREATE TABLE IF NOT EXISTS market_sentiment (
            ticker                  TEXT    NOT NULL,
            snapshot_date           TEXT    NOT NULL,
            close_price             REAL,
            trading_volume          REAL,
            implied_volatility      REAL,
            iv_1m_avg               REAL,
            iv_3m_avg               REAL,
            iv_6m_avg               REAL,
            iv_1y_avg               REAL,
            days_since_large_drop   INTEGER,
            perf_5d                 REAL,
            perf_10d                REAL,
            perf_1m                 REAL,
            PRIMARY KEY (ticker, snapshot_date)
        );

        -- Point-in-time valuation snapshot (one row per ticker per crawl date).
        --
        -- WHY THIS TABLE EXISTS (QA finding F-02, 2026-08-02): these three
        -- figures come from yf.Ticker().info, which is a SNAPSHOT of *today* —
        -- there is no historical equivalent in the free feed. They were
        -- previously written into every historical quarterly_financials row,
        -- which made P/E and market-cap history a flat line at today's value.
        --
        -- A snapshot belongs in a table keyed by the date it was OBSERVED, not
        -- by the fiscal period it is being attached to. Unlike option chains
        -- (see CLAUDE.md §11 / IV-03) a valuation snapshot CAN legitimately
        -- accumulate: every crawl appends one honest observation, so a genuine
        -- P/E series builds forward from the day this shipped. It cannot be
        -- backfilled — do not try. An empty history that says why is honest.
        CREATE TABLE IF NOT EXISTS ticker_valuation_history (
            ticker              TEXT    NOT NULL,
            snapshot_date       TEXT    NOT NULL,
            trailing_pe         REAL,
            forward_pe          REAL,
            trailing_eps        REAL,
            market_cap          REAL,
            shares_outstanding  REAL,
            price_to_book       REAL,
            close_price         REAL,
            source              TEXT,
            PRIMARY KEY (ticker, snapshot_date)
        );

        -- Cycle analysis (one row per ticker per crawl date)
        CREATE TABLE IF NOT EXISTS cycle_analysis (
            ticker                  TEXT    NOT NULL,
            snapshot_date           TEXT    NOT NULL,
            up_cycle_magnitude      REAL,
            up_cycle_duration       INTEGER,
            down_cycle_magnitude    REAL,
            down_cycle_duration     INTEGER,
            vol_diff_last_cycle     REAL,
            PRIMARY KEY (ticker, snapshot_date)
        );
    """)
    conn.commit()
    log.info("Database schema ready — %s", DB_PATH)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _safe(val):
    """Return None instead of NaN/inf so SQLite accepts it."""
    try:
        if val is None:
            return None
        f = float(val)
        return None if (np.isnan(f) or np.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _row(df: pd.DataFrame, label: str, col):
    """Safely extract a cell from a DataFrame by row label and column."""
    try:
        if label in df.index and col in df.columns:
            return _safe(df.loc[label, col])
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
# COMPANY INFO
# ══════════════════════════════════════════════════════════════════════════════

def fetch_company_info(display_name: str, yf_symbol: str) -> dict:
    try:
        info = yf.Ticker(yf_symbol).info
        return {
            "ticker":       display_name,
            "display_name": display_name,
            "company_name": info.get("longName") or info.get("shortName") or display_name,
            "exchange":     info.get("exchange", ""),
            "hq_country":   info.get("country", ""),
            "sector":       info.get("sector", ""),
            "industry":     info.get("industry", ""),
            "currency":     info.get("currency", "USD"),
            "updated_at":   _now_hkt().isoformat(),
        }
    except Exception as exc:
        log.warning("  company_info failed for %s: %s", yf_symbol, exc)
        return {
            "ticker": display_name, "display_name": display_name,
            "company_name": display_name, "exchange": "", "hq_country": "",
            "sector": "", "industry": "", "currency": "USD",
            "updated_at": _now_hkt().isoformat(),
        }


def upsert_company_info(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute("""
        INSERT INTO company_info
            (ticker, display_name, company_name, exchange, hq_country,
             sector, industry, currency, updated_at)
        VALUES
            (:ticker, :display_name, :company_name, :exchange, :hq_country,
             :sector, :industry, :currency, :updated_at)
        ON CONFLICT(ticker) DO UPDATE SET
            company_name = excluded.company_name,
            exchange     = excluded.exchange,
            hq_country   = excluded.hq_country,
            sector       = excluded.sector,
            industry     = excluded.industry,
            currency     = excluded.currency,
            updated_at   = excluded.updated_at
    """, row)
    conn.commit()


# ══════════════════════════════════════════════════════════════════════════════
# DAILY PRICES
# ══════════════════════════════════════════════════════════════════════════════

def fetch_and_store_prices(
    conn: sqlite3.Connection,
    display_name: str,
    yf_symbol: str,
    period: str = PRICE_HISTORY_PERIOD,
) -> pd.DataFrame:
    """Download OHLCV history; insert new rows (skip duplicates)."""
    try:
        hist = yf.Ticker(yf_symbol).history(period=period, auto_adjust=True)
        if hist.empty:
            log.warning("  No price data for %s", yf_symbol)
            return pd.DataFrame()

        hist = hist.reset_index()
        hist["ticker"] = display_name
        hist["date"]   = pd.to_datetime(hist["Date"]).dt.strftime("%Y-%m-%d")
        rows = hist[["ticker", "date", "Open", "High", "Low", "Close", "Volume"]].rename(
            columns={"Open": "open", "High": "high", "Low": "low",
                     "Close": "close", "Volume": "volume"}
        )
        # OR REPLACE (not OR IGNORE): yfinance retroactively re-adjusts the full
        # OHLCV history after a stock split. With OR IGNORE the pre-split rows
        # would survive forever, leaving a permanent artificial cliff in every
        # chart at the split date. REPLACE keeps the series internally consistent
        # and is still idempotent — PK is (ticker, date).
        conn.executemany(
            "INSERT OR REPLACE INTO daily_prices VALUES (?,?,?,?,?,?,?)",
            rows.itertuples(index=False, name=None),
        )
        conn.commit()
        log.info("  prices  : %d rows stored for %s", len(rows), display_name)
        return rows
    except Exception as exc:
        log.warning("  prices failed for %s: %s", yf_symbol, exc)
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# QUARTERLY FINANCIALS
# ══════════════════════════════════════════════════════════════════════════════

def fetch_and_store_financials(
    conn: sqlite3.Connection,
    display_name: str,
    yf_symbol: str,
) -> None:
    try:
        t    = yf.Ticker(yf_symbol)
        info = t.info

        try:
            income = t.quarterly_income_stmt
        except Exception:
            income = pd.DataFrame()

        try:
            balance = t.quarterly_balance_sheet
        except Exception:
            balance = pd.DataFrame()

        # Store the point-in-time valuation snapshot BEFORE the early exit
        # below: ETFs, crypto and macro tickers have no quarterly income
        # statement but do have a market cap / price, and returning first would
        # silently exclude them. Reuses the `info` already fetched above — this
        # adds no extra network call.
        store_valuation_snapshot(conn, display_name, info)

        if income.empty:
            log.info("  financials: no quarterly income data for %s", display_name)
            return

        records = []
        for col in income.columns:
            period_end = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)

            # Income statement lines
            revenue   = _row(income, "Total Revenue", col)
            gp        = _row(income, "Gross Profit", col)
            op        = _row(income, "Operating Income", col)
            rd        = _row(income, "Research And Development", col)
            net       = _row(income, "Net Income", col)
            eps       = _row(income, "Diluted EPS", col)

            # Balance sheet lines
            ar        = _row(balance, "Accounts Receivable", col) if not balance.empty else None
            inv       = _row(balance, "Inventory", col)           if not balance.empty else None

            # Derived ratios
            gm        = _safe(gp  / revenue * 100) if revenue and gp  else None
            op_margin = _safe(op  / revenue * 100) if revenue and op  else None
            net_margin= _safe(net / revenue * 100) if revenue and net else None
            rd_ratio  = _safe(rd  / revenue * 100) if revenue and rd  else None
            ar_turn   = _safe(revenue / ar)        if revenue and ar  else None
            cogs      = _safe(revenue - gp)        if revenue and gp  else None
            inv_turn  = _safe(cogs / inv)          if cogs and inv    else None

            # ── QA F-02: eps / pe_ratio / market_cap are deliberately NOT
            # sourced from `info` here. `info` is a single snapshot of TODAY,
            # fetched once above; writing it into every historical quarter made
            # P/E and market-cap history a flat line at today's value, and the
            # `eps or trailingEps` fallback injected a TRAILING-TWELVE-MONTH
            # figure into a single quarter's row (~4x overstatement).
            #
            # `eps` now carries the quarter's own Diluted EPS or NULL. pe_ratio
            # and market_cap are always NULL — they have no point-in-time value
            # in the free feed and are therefore unknowable for a past quarter.
            # The snapshot lives in ticker_valuation_history, keyed by the date
            # it was observed. Columns retained (not dropped) per Hard Rule 2:
            # dashboard.py and /api/export-xlsx read this shape by name.
            records.append((
                display_name, period_end,
                revenue, gp, gm, op, op_margin, rd, rd_ratio, net, net_margin,
                eps,        # quarterly Diluted EPS only — never the TTM fallback
                None,       # pe_ratio    — see ticker_valuation_history
                None,       # market_cap  — see ticker_valuation_history
                ar, ar_turn, inv, inv_turn,
            ))

        conn.executemany("""
            INSERT OR REPLACE INTO quarterly_financials VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, records)
        conn.commit()
        log.info("  financials: %d quarters stored for %s", len(records), display_name)

    except Exception as exc:
        log.warning("  financials failed for %s: %s", yf_symbol, exc)


# ══════════════════════════════════════════════════════════════════════════════
# POINT-IN-TIME VALUATION SNAPSHOT  (QA finding F-02)
# ══════════════════════════════════════════════════════════════════════════════

def _last_price_date(conn: sqlite3.Connection, display_name: str) -> str:
    """
    Newest date in daily_prices for this ticker, else today (UTC+8).

    Keying the snapshot on the last TRADING date rather than the wall-clock
    crawl date makes the write idempotent across weekend/holiday runs: a
    Saturday and a Sunday crawl both describe Friday's close, so they collapse
    onto one row via INSERT OR REPLACE instead of creating two rows that claim
    to be independent observations of a market that was shut.
    """
    try:
        row = conn.execute(
            "SELECT MAX(date) FROM daily_prices WHERE ticker = ?", (display_name,)
        ).fetchone()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    return _now_hkt().strftime("%Y-%m-%d")


def store_valuation_snapshot(
    conn: sqlite3.Connection,
    display_name: str,
    info: dict,
) -> None:
    """
    Append one observed valuation snapshot for this ticker.

    Every figure here is a property of the OBSERVATION DATE, never of a fiscal
    period. Do not join this table to quarterly_financials.period_end and do
    not backfill it — the free feed exposes no historical trailing P/E, and
    fabricating one is exactly the defect (F-02) this table was created to
    undo. The series is empty on day one and fills forward, one row per crawl.
    """
    try:
        snapshot_date = _last_price_date(conn, display_name)
        row = (
            display_name,
            snapshot_date,
            _safe(info.get("trailingPE")),
            _safe(info.get("forwardPE")),
            _safe(info.get("trailingEps")),
            _safe(info.get("marketCap")),
            _safe(info.get("sharesOutstanding")),
            _safe(info.get("priceToBook")),
            _safe(info.get("currentPrice") or info.get("regularMarketPreviousClose")),
            "yfinance .info snapshot (observed, not point-in-time history)",
        )
        # Nothing resolved => write nothing. A row of all-NULLs is the SC-01
        # failure shape: it inflates COUNT(*) and reads as a healthy crawl.
        if all(v is None for v in row[2:9]):
            log.info("  valuation : no snapshot fields resolved for %s; row skipped",
                     display_name)
            return

        conn.execute(
            "INSERT OR REPLACE INTO ticker_valuation_history VALUES (?,?,?,?,?,?,?,?,?,?)",
            row,
        )
        conn.commit()
        log.info("  valuation : snapshot stored for %s @ %s (P/E=%s, cap=%s)",
                 display_name, snapshot_date,
                 f"{row[2]:.1f}" if row[2] else "n/a",
                 f"{row[5]/1e9:.1f}B" if row[5] else "n/a")
    except Exception as exc:
        log.warning("  valuation failed for %s: %s", display_name, exc)


def purge_contaminated_valuation_cols(conn: sqlite3.Connection) -> None:
    """
    NULL out quarterly_financials.pe_ratio / market_cap wherever they still
    hold a snapshot value (QA finding F-02). Idempotent, zero network — safe to
    run on every deploy, mirroring purge_null_price_rows() (BACKLOG SC-01).

    This exists because the fixed crawler alone does not clean production: the
    full crawl is gated behind a row-count check in startup.sh and an external
    schedule, so contaminated rows written months ago would otherwise survive
    indefinitely on the Railway volume. Same lesson as SC-14 — a correction
    that only lives in the writer never reaches rows already on disk.

    Deletes nothing and touches no other column: a wrong number is worse than
    no number (CLAUDE.md §8), but the surrounding revenue/margin figures in
    these rows are genuine and must survive.
    """
    try:
        cur = conn.execute("""
            UPDATE quarterly_financials
            SET pe_ratio = NULL, market_cap = NULL
            WHERE pe_ratio IS NOT NULL OR market_cap IS NOT NULL
        """)
        conn.commit()
        if cur.rowcount:
            log.info("Purged snapshot contamination from %d quarterly_financials "
                     "row(s) — see ticker_valuation_history (F-02).", cur.rowcount)
    except sqlite3.OperationalError as exc:
        # Table may not exist yet on a brand-new DB — not an error.
        log.info("purge_contaminated_valuation_cols skipped: %s", exc)


# ══════════════════════════════════════════════════════════════════════════════
# MARKET SENTIMENT
# ══════════════════════════════════════════════════════════════════════════════

def _iv_fast(yf_symbol: str) -> float | None:
    """
    Quick IV estimate from yf.Ticker.info — always available, no options-chain
    request needed.  Returns annualised IV in percent (e.g. 45.2 for 45.2 %),
    or None if the field is absent / zero (common for ETFs, bonds, crypto).
    """
    try:
        info = yf.Ticker(yf_symbol).info
        iv = info.get("impliedVolatility")
        if iv and float(iv) > 0:
            return round(float(iv) * 100, 2)
        return None
    except Exception:
        return None


def _iv_options_chain(yf_symbol: str) -> float | None:
    """
    Accurate ATM IV from the nearest-expiry options chain.  Slower (~2-4 s per
    ticker) — only called when fetch_iv=True and the fast path returned None.
    Returns annualised IV in percent or None on failure.
    """
    try:
        t     = yf.Ticker(yf_symbol)
        dates = t.options
        if not dates:
            return None
        chain = t.option_chain(dates[0])
        calls = chain.calls
        if calls.empty:
            return None
        info  = t.info
        price = _safe(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
        if price and price > 0:
            idx = (calls["strike"] - price).abs().idxmin()
            iv  = _safe(calls.loc[idx, "impliedVolatility"]) or None
            return iv * 100 if iv else None
        return _safe(calls["impliedVolatility"].mean()) * 100
    except Exception:
        return None


def fetch_and_store_sentiment(
    conn: sqlite3.Connection,
    display_name: str,
    yf_symbol: str,
    prices_df: pd.DataFrame,
    fetch_iv: bool = True,
) -> None:
    try:
        if prices_df.empty or len(prices_df) < 22:
            log.info("  sentiment : not enough price data for %s", display_name)
            return

        df      = prices_df.sort_values("date").copy()
        closes  = df["close"].values.astype(float)
        vols    = df["volume"].values.astype(float)
        today   = df["date"].iloc[-1]
        returns = pd.Series(closes).pct_change()

        # Days since last large drop
        drops = returns[returns < LARGE_DROP_THRESHOLD]
        days_since = int(len(returns) - 1 - drops.index[-1]) if not drops.empty else len(returns)

        # Short-term performance
        p5  = _safe((closes[-1] / closes[-6]  - 1) * 100) if len(closes) >= 6  else None
        p10 = _safe((closes[-1] / closes[-11] - 1) * 100) if len(closes) >= 11 else None
        p1m = _safe((closes[-1] / closes[-22] - 1) * 100) if len(closes) >= 22 else None

        # ── Implied Volatility ─────────────────────────────────────────────────
        # Fast path: t.info["impliedVolatility"] — always attempted, no extra
        # network call beyond what fetch_company_info already makes.
        iv = _iv_fast(yf_symbol)

        # Slow path: ATM IV from nearest-expiry options chain.  Only runs if
        # the fast path returned nothing AND fetch_iv=True (non-quick mode).
        if iv is None and fetch_iv:
            iv = _iv_options_chain(yf_symbol)

        # Historical IV averages not available from yfinance free tier.
        iv1m = iv3m = iv6m = iv1y = None

        conn.execute("""
            INSERT OR REPLACE INTO market_sentiment VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            display_name, today,
            _safe(closes[-1]), _safe(vols[-1]),
            iv, iv1m, iv3m, iv6m, iv1y,
            days_since, p5, p10, p1m,
        ))
        conn.commit()
        log.info("  sentiment : stored for %s  (IV=%s%%)", display_name,
                 f"{iv:.1f}" if iv else "n/a")

    except Exception as exc:
        log.warning("  sentiment failed for %s: %s", yf_symbol, exc)


# ══════════════════════════════════════════════════════════════════════════════
# CYCLE ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def fetch_and_store_cycles(
    conn: sqlite3.Connection,
    display_name: str,
    prices_df: pd.DataFrame,
) -> None:
    try:
        if prices_df.empty or len(prices_df) < CYCLE_DETECTION_WINDOW * 3:
            log.info("  cycles    : not enough data for %s", display_name)
            return

        df     = prices_df.sort_values("date").copy()
        closes = df["close"].values.astype(float)
        vols   = df["volume"].values.astype(float)
        today  = df["date"].iloc[-1]
        w      = CYCLE_DETECTION_WINDOW

        peaks   = argrelextrema(closes, np.greater_equal, order=w)[0]
        troughs = argrelextrema(closes, np.less_equal,    order=w)[0]

        up_mag = up_dur = dn_mag = dn_dur = vol_diff = None

        # Last up-cycle: most-recent trough → next peak
        if len(peaks) >= 1 and len(troughs) >= 1:
            last_peak = peaks[-1]
            prior_troughs = troughs[troughs < last_peak]
            if len(prior_troughs) >= 1:
                last_trough = prior_troughs[-1]
                up_mag = _safe((closes[last_peak] / closes[last_trough] - 1) * 100)
                up_dur = int(last_peak - last_trough)

                # Volume change vs previous up-cycle
                # Previous up-cycle = prior_troughs[-2] → most-recent peak before last_peak
                curr_vol = float(np.mean(vols[last_trough:last_peak + 1]))
                if len(prior_troughs) >= 2:
                    prev_trough = prior_troughs[-2]
                    prev_peaks  = peaks[peaks < last_peak]
                    if len(prev_peaks) >= 1:          # relaxed from >= 2 → >= 1
                        prev_peak = prev_peaks[-1]    # use the immediately-prior peak
                        prev_vol  = float(np.mean(vols[prev_trough:prev_peak + 1]))
                        vol_diff  = _safe((curr_vol / prev_vol - 1) * 100) if prev_vol else None

        # Last down-cycle: most-recent peak → next trough
        if len(peaks) >= 1 and len(troughs) >= 1:
            last_trough2 = troughs[-1]
            prior_peaks  = peaks[peaks < last_trough2]
            if len(prior_peaks) >= 1:
                last_peak2 = prior_peaks[-1]
                dn_mag = _safe((closes[last_trough2] / closes[last_peak2] - 1) * 100)
                dn_dur = int(last_trough2 - last_peak2)

        conn.execute("""
            INSERT OR REPLACE INTO cycle_analysis VALUES (?,?,?,?,?,?,?)
        """, (display_name, today, up_mag, up_dur, dn_mag, dn_dur, vol_diff))
        conn.commit()
        log.info("  cycles    : stored for %s  (↑%.1f%% / %s days, ↓%.1f%% / %s days)",
                 display_name,
                 up_mag if up_mag else 0, up_dur,
                 dn_mag if dn_mag else 0, dn_dur)

    except Exception as exc:
        log.warning("  cycles failed for %s: %s", display_name, exc)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN CRAWL ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

def crawl(tickers=None, fetch_iv: bool = True) -> None:
    """
    Main entry point.
    tickers : dict {display_name: yf_symbol} — defaults to full TICKER_MAP
    fetch_iv: whether to fetch implied-volatility from options chain (slow)
    """
    if tickers is None:
        tickers = TICKER_MAP

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    purge_contaminated_valuation_cols(conn)   # F-02 — idempotent, see startup.sh

    # Heartbeat (QA F-01): records that the MARKET job ran, which is what the
    # scheduler and /health both key on. Written via the shared helper so the
    # `job` column is populated — a bare INSERT here would default to 'market'
    # and work by accident, which is not the same as working on purpose.
    run_id = start_job(conn, "market", attempted=len(tickers))

    ok_count = 0
    total    = len(tickers)

    for i, (display_name, yf_symbol) in enumerate(tickers.items(), 1):
        log.info("[%d/%d] Crawling %s (%s) …", i, total, display_name, yf_symbol)

        # 1. Company info
        info_row = fetch_company_info(display_name, yf_symbol)
        upsert_company_info(conn, info_row)

        # 2. Daily prices (returned for downstream use)
        prices = fetch_and_store_prices(conn, display_name, yf_symbol)

        # 3. Quarterly financials (companies & some ETFs)
        fetch_and_store_financials(conn, display_name, yf_symbol)

        # 4. Market sentiment (needs price history)
        fetch_and_store_sentiment(conn, display_name, yf_symbol, prices, fetch_iv=fetch_iv)

        # 5. Cycle analysis
        fetch_and_store_cycles(conn, display_name, prices)

        ok_count += 1
        time.sleep(REQUEST_DELAY_SECONDS)

    # Finalise run record. A run that resolved fewer than half its tickers is
    # recorded as FAILED, not completed: a heartbeat that goes green on a
    # degraded run certifies the outage instead of reporting it (F-01).
    _ok = ok_count >= max(1, total // 2)
    finish_job(
        conn, run_id,
        status="completed" if _ok else "failed",
        ok=ok_count,
        note=f"{ok_count}/{total} tickers resolved",
    )
    conn.close()

    log.info("✅  Crawl complete — %d/%d tickers OK. Data saved to %s", ok_count, total, DB_PATH)


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Semiconductor Industry Data Crawler")
    parser.add_argument(
        "--tickers", nargs="+", metavar="TICKER",
        help="Subset of display-name tickers to crawl (e.g. NVDA AMD TSM)",
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Skip options implied-volatility fetch (much faster)",
    )
    parser.add_argument(
        "--purge-only", action="store_true",
        help="Run idempotent data-integrity purges only (no network calls). "
             "Used by startup.sh on every deploy — see F-02.",
    )
    args = parser.parse_args()

    if args.purge_only:
        _conn = sqlite3.connect(DB_PATH)
        init_db(_conn)
        purge_contaminated_valuation_cols(_conn)
        _conn.close()
        log.info("✅  Purge-only pass complete — no network calls made.")
        raise SystemExit(0)

    if args.tickers:
        selected = {k: v for k, v in TICKER_MAP.items() if k in args.tickers}
        if not selected:
            print(f"❌  None of {args.tickers} found in config.py TICKER_MAP")
            raise SystemExit(1)
    else:
        selected = TICKER_MAP

    crawl(tickers=selected, fetch_iv=not args.quick)
