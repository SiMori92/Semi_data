"""
ibkr_options_crawler.py — Interactive Brokers Real-Time Options IV Crawler
===========================================================================
Fetches implied-volatility data for every ticker in the app using the
Interactive Brokers TWS / IB Gateway API (via ib_insync).

Metrics stored per ticker per snapshot date:
  · iv_current    — latest daily IV value  (%)
  · iv_1m_avg     — 21-trading-day rolling average (%)
  · iv_1q_avg     — 63-trading-day rolling average (%)
  · iv_6m_avg     — 126-trading-day rolling average (%)
  · iv_1y_avg     — 252-trading-day rolling average (%)
  · iv_pct_vs_1y  — current IV as a percentile of its 1-year range (0–100)
  · raw daily bars — stored in options_iv_history for charting

Pre-requisites
--------------
1.  pip install ib_insync
2.  TWS or IB Gateway must be running and API access enabled.
    See ibkr_config.json for full setup instructions.
3.  Set "enabled": true in ibkr_config.json

Run:
    python ibkr_options_crawler.py                  # all tickers
    python ibkr_options_crawler.py --tickers NVDA AMD ASML
    python ibkr_options_crawler.py --test-connection
"""

import argparse
import json
import logging
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from config import DB_PATH, TICKER_MAP

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)

CONFIG_PATH = Path(__file__).parent / "ibkr_config.json"
TODAY = datetime.utcnow().strftime("%Y-%m-%d")


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

def load_config() -> dict:
    """Load and validate ibkr_config.json."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"ibkr_config.json not found at {CONFIG_PATH}. "
            "Run the crawler once to generate a template."
        )
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)

    if not cfg.get("enabled", False):
        raise RuntimeError(
            "IBKR integration is disabled. "
            "Set 'enabled': true in ibkr_config.json after configuring TWS/Gateway."
        )
    return cfg


def ibkr_is_enabled() -> bool:
    """Quick check — returns True only if config exists and enabled=true."""
    try:
        if not CONFIG_PATH.exists():
            return False
        with open(CONFIG_PATH) as f:
            return json.load(f).get("enabled", False)
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE — options IV schema
# ══════════════════════════════════════════════════════════════════════════════

def init_ibkr_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        PRAGMA journal_mode=WAL;

        -- Aggregated IV snapshot per ticker per day
        CREATE TABLE IF NOT EXISTS options_iv (
            ticker          TEXT    NOT NULL,
            snapshot_date   TEXT    NOT NULL,
            iv_current      REAL,       -- latest daily IV value (%)
            iv_1m_avg       REAL,       -- 21-day rolling avg (%)
            iv_1q_avg       REAL,       -- 63-day rolling avg (%)
            iv_6m_avg       REAL,       -- 126-day rolling avg (%)
            iv_1y_avg       REAL,       -- 252-day rolling avg (%)
            iv_pct_vs_1y    REAL,       -- current IV percentile in 1-year range (0–100)
            iv_52w_high     REAL,       -- 52-week high IV (%)
            iv_52w_low      REAL,       -- 52-week low IV (%)
            source          TEXT    DEFAULT 'IBKR',
            PRIMARY KEY (ticker, snapshot_date)
        );

        -- Daily IV bar history (for charting period trends)
        CREATE TABLE IF NOT EXISTS options_iv_history (
            ticker      TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            iv_pct      REAL,           -- daily IV value (%)
            source      TEXT    DEFAULT 'IBKR',
            PRIMARY KEY (ticker, date)
        );
    """)
    conn.commit()
    log.info("IBKR options IV tables ready.")


# ══════════════════════════════════════════════════════════════════════════════
# IBKR CONNECTION
# ══════════════════════════════════════════════════════════════════════════════

def _import_ib():
    """Lazy import of ib_insync so the rest of the app loads without it."""
    try:
        from ib_insync import IB, Stock, Index, Crypto, util as ib_util
        return IB, Stock, Index, Crypto, ib_util
    except ImportError:
        raise ImportError(
            "ib_insync is not installed. Run:  pip install ib_insync"
        )


def connect(cfg: dict):
    """Open a synchronous connection to TWS/Gateway. Returns IB instance."""
    IB, *_ = _import_ib()
    conn_cfg = cfg["connection"]
    ib = IB()
    ib.connect(
        host      = conn_cfg["host"],
        port      = conn_cfg["port"],
        clientId  = conn_cfg["client_id"],
        timeout   = conn_cfg.get("timeout_seconds", 30),
        readonly  = conn_cfg.get("readonly", True),
    )
    log.info(
        "✅  Connected to IBKR  %s:%s  clientId=%s  (server v%s)",
        conn_cfg["host"], conn_cfg["port"],
        conn_cfg["client_id"], ib.serverVersion(),
    )
    return ib


def disconnect(ib) -> None:
    try:
        ib.disconnect()
        log.info("Disconnected from IBKR.")
    except Exception:
        pass


def test_connection(cfg: dict) -> bool:
    """Try to connect and immediately disconnect. Prints result."""
    try:
        ib = connect(cfg)
        accts = ib.managedAccounts()
        log.info("Managed accounts visible: %s", accts)
        disconnect(ib)
        print("✅  IBKR connection test PASSED.")
        return True
    except Exception as exc:
        print(f"❌  IBKR connection test FAILED: {exc}")
        print("\nTroubleshooting:")
        print("  • Is TWS or IB Gateway running?")
        print("  • API enabled in TWS: Edit → Global Config → API → Settings")
        print("  • Is 127.0.0.1 listed as Trusted IP?")
        print("  • Does the port in ibkr_config.json match TWS settings?")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# CONTRACT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def build_contract(display_name: str, cfg: dict):
    """
    Construct the correct ib_insync contract object for a ticker.
    Uses ibkr_config.json ticker_contracts section.
    Returns (contract, label) or (None, reason_string).
    """
    IB, Stock, Index, Crypto, _ = _import_ib()
    from ib_insync import Future

    skip_list = cfg.get("skip_tickers", {}).get("list", [])
    if display_name in skip_list:
        return None, f"in skip_tickers list"

    spec = cfg.get("ticker_contracts", {}).get(display_name)
    if not spec:
        return None, f"no contract spec in ibkr_config.json — add it to ticker_contracts"

    ctype    = spec.get("type", "STK").upper()
    symbol   = spec["symbol"]
    exchange = spec.get("exchange", "SMART")
    currency = spec.get("currency", "USD")

    try:
        if ctype == "STK":
            contract = Stock(symbol, exchange, currency)
        elif ctype == "IND":
            contract = Index(symbol, exchange, currency)
        elif ctype == "CRYPTO":
            contract = Crypto(symbol, exchange, currency)
        elif ctype == "FUT":
            expiry = spec.get("expiry", "")   # e.g. "202506"
            contract = Future(symbol, expiry, exchange, currency=currency)
        else:
            return None, f"unsupported contract type '{ctype}'"

        return contract, symbol
    except Exception as exc:
        return None, f"contract build error: {exc}"


# ══════════════════════════════════════════════════════════════════════════════
# IV DATA FETCHER
# ══════════════════════════════════════════════════════════════════════════════

def fetch_iv_history(ib, contract, display_name: str, cfg: dict) -> pd.DataFrame:
    """
    Request 1 year of daily OPTION_IMPLIED_VOLATILITY bars from IBKR.
    Returns a DataFrame with columns: date, iv_pct
    Returns empty DataFrame on failure.
    """
    _, _, _, _, ib_util = _import_ib()
    cs = cfg.get("crawl_settings", {})

    try:
        bars = ib.reqHistoricalData(
            contract,
            endDateTime     = "",           # current time
            durationStr     = cs.get("history_duration", "1 Y"),
            barSizeSetting  = cs.get("bar_size", "1 day"),
            whatToShow      = "OPTION_IMPLIED_VOLATILITY",
            useRTH          = cs.get("use_rth", True),
            formatDate      = 1,
            keepUpToDate    = False,
        )

        if not bars:
            log.warning("  %s — no IV bars returned (no options market or subscription issue)", display_name)
            return pd.DataFrame()

        df = ib_util.df(bars)[["date", "close"]].copy()
        df["date"]   = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df["iv_pct"] = (df["close"] * 100).round(4)   # IBKR returns IV as a fraction
        df = df[["date", "iv_pct"]].dropna()
        log.info("  %s — %d daily IV bars fetched (%.1f%% → %.1f%%)",
                 display_name, len(df), df["iv_pct"].min(), df["iv_pct"].max())
        return df

    except Exception as exc:
        log.warning("  %s — IV history fetch failed: %s", display_name, exc)
        return pd.DataFrame()


def calculate_iv_metrics(df: pd.DataFrame, windows: dict) -> dict:
    """
    From a DataFrame of daily IV values compute all rolling-average metrics.
    windows = {"1_month": 21, "1_quarter": 63, "6_months": 126, "1_year": 252}
    """
    if df.empty or len(df) < 5:
        return {}

    ivs = df["iv_pct"].values
    n   = len(ivs)

    def rolling_avg(days: int):
        tail = ivs[-min(days, n):]
        return round(float(np.mean(tail)), 4) if len(tail) > 0 else None

    iv_current = round(float(ivs[-1]), 4)
    iv_1m      = rolling_avg(windows.get("1_month",    21))
    iv_1q      = rolling_avg(windows.get("1_quarter",  63))
    iv_6m      = rolling_avg(windows.get("6_months",  126))
    iv_1y      = rolling_avg(windows.get("1_year",    252))

    # IV percentile vs 1-year range
    year_ivs = ivs[-min(252, n):]
    lo, hi   = year_ivs.min(), year_ivs.max()
    iv_pct_vs_1y = round(float((iv_current - lo) / (hi - lo) * 100), 1) if hi > lo else 50.0

    return {
        "iv_current":   iv_current,
        "iv_1m_avg":    iv_1m,
        "iv_1q_avg":    iv_1q,
        "iv_6m_avg":    iv_6m,
        "iv_1y_avg":    iv_1y,
        "iv_pct_vs_1y": iv_pct_vs_1y,
        "iv_52w_high":  round(float(year_ivs.max()), 4),
        "iv_52w_low":   round(float(year_ivs.min()), 4),
    }


# ══════════════════════════════════════════════════════════════════════════════
# DB STORAGE
# ══════════════════════════════════════════════════════════════════════════════

def store_iv_snapshot(conn: sqlite3.Connection, display_name: str, metrics: dict) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO options_iv VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        display_name, TODAY,
        metrics.get("iv_current"),
        metrics.get("iv_1m_avg"),
        metrics.get("iv_1q_avg"),
        metrics.get("iv_6m_avg"),
        metrics.get("iv_1y_avg"),
        metrics.get("iv_pct_vs_1y"),
        metrics.get("iv_52w_high"),
        metrics.get("iv_52w_low"),
        "IBKR",
    ))
    conn.commit()


def store_iv_history(conn: sqlite3.Connection, display_name: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    rows = [(display_name, row["date"], row["iv_pct"], "IBKR")
            for _, row in df.iterrows()]
    conn.executemany(
        "INSERT OR IGNORE INTO options_iv_history VALUES (?,?,?,?)",
        rows,
    )
    conn.commit()


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

def crawl_options_iv(tickers: list = None) -> None:
    """
    Main entry point.
    tickers : list of display-name tickers (e.g. ["NVDA","AMD"]).
              Defaults to all tickers in TICKER_MAP.
    """
    cfg = load_config()
    if tickers is None:
        tickers = list(TICKER_MAP.keys())

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    init_ibkr_tables(conn)

    windows  = cfg.get("crawl_settings", {}).get("iv_windows", {})
    delay    = cfg.get("crawl_settings", {}).get("delay_between_requests_s", 1.5)
    retries  = cfg.get("crawl_settings", {}).get("max_retries", 2)

    ib = connect(cfg)
    ok_count = 0
    total    = len(tickers)

    try:
        for i, display_name in enumerate(tickers, 1):
            log.info("[%d/%d] %s", i, total, display_name)

            contract, label = build_contract(display_name, cfg)
            if contract is None:
                log.info("  Skipping %s — %s", display_name, label)
                continue

            # Qualify contract (resolves conId)
            try:
                ib.qualifyContracts(contract)
            except Exception as e:
                log.warning("  %s — qualifyContracts failed: %s", display_name, e)
                continue

            # Fetch IV with retry
            df = pd.DataFrame()
            for attempt in range(1, retries + 1):
                df = fetch_iv_history(ib, contract, display_name, cfg)
                if not df.empty:
                    break
                if attempt < retries:
                    log.info("  Retry %d/%d for %s …", attempt, retries, display_name)
                    time.sleep(delay * 2)

            if df.empty:
                log.warning("  %s — no IV data after %d attempts.", display_name, retries)
                time.sleep(delay)
                continue

            # Compute metrics and persist
            metrics = calculate_iv_metrics(df, windows)
            store_iv_snapshot(conn, display_name, metrics)
            store_iv_history(conn, display_name, df)

            log.info(
                "  ✓ %s  IV=%.1f%%  1m=%.1f%%  1q=%.1f%%  6m=%.1f%%  1y=%.1f%%  pct=%d%%",
                display_name,
                metrics["iv_current"],
                metrics.get("iv_1m_avg") or 0,
                metrics.get("iv_1q_avg") or 0,
                metrics.get("iv_6m_avg") or 0,
                metrics.get("iv_1y_avg") or 0,
                metrics.get("iv_pct_vs_1y") or 0,
            )
            ok_count += 1
            time.sleep(delay)

    finally:
        disconnect(ib)
        conn.close()

    log.info("✅  IBKR options IV crawl complete — %d/%d tickers processed.", ok_count, total)


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Interactive Brokers Options IV Crawler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ibkr_options_crawler.py --test-connection
  python ibkr_options_crawler.py
  python ibkr_options_crawler.py --tickers NVDA AMD ASML TSM MU
        """,
    )
    parser.add_argument(
        "--test-connection", action="store_true",
        help="Test TWS/Gateway connectivity then exit",
    )
    parser.add_argument(
        "--tickers", nargs="+", metavar="TICKER",
        help="Subset of tickers to crawl (display names from config.py TICKER_MAP)",
    )
    args = parser.parse_args()

    try:
        cfg = load_config()
    except RuntimeError as e:
        print(f"\n⚠️  {e}\n")
        raise SystemExit(1)
    except FileNotFoundError as e:
        print(f"\n❌  {e}\n")
        raise SystemExit(1)

    if args.test_connection:
        ok = test_connection(cfg)
        raise SystemExit(0 if ok else 1)

    selected = args.tickers if args.tickers else None
    if selected:
        missing = [t for t in selected if t not in TICKER_MAP]
        if missing:
            print(f"⚠️  These tickers are not in config.py TICKER_MAP: {missing}")
    crawl_options_iv(tickers=selected)
