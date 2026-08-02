"""
iv_crawler.py — Cloud-native Implied-Volatility Crawler
========================================================
Replaces the IBKR/TWS dependency for the Sentiment tab's IV series.

Why this exists
---------------
`ibkr_options_crawler.py` + `ibkr_relay.py` require TWS/IB Gateway running on a
local machine plus a paid OPRA subscription, so IV could never refresh in the
cloud (see CLAUDE.md §3, §11). This module derives an equivalent 30-day ATM
implied-volatility series from sources that are reachable from Railway with no
daemon, no broker login, and no new dependency:

  · US equities / ETFs / indices → Yahoo Finance option chains (yfinance)
  · BTC / ETH                    → Deribit public DVOL volatility index

PROVENANCE — READ BEFORE CITING (CLAUDE.md §8)
----------------------------------------------
The equity IV30 figure is **derived, not published**. It is our own
constant-maturity interpolation over Yahoo's per-contract implied vols. It is
NOT a vendor's published IV30 index and must never be cited as one. Deribit
DVOL, by contrast, IS a published index and is labelled separately.

Method (equities/ETFs/indices)
------------------------------
1. Spot = last daily close.
2. Keep expiries >= MIN_DTE days out; pick the two that bracket 30 DTE.
3. Per expiry, take the NEAR_STRIKES contracts closest to spot, calls and puts,
   discard any with a zero bid/ask or an IV outside SANE_IV_RANGE (deep OTM
   quotes carry garbage IV — this filter is load-bearing, not cosmetic), then
   inverse-distance weight them toward the money.
4. Interpolate the two expiries in **total variance** (sigma^2 * t), not in
   sigma, then re-annualise to exactly 30 days.

Validation gate
---------------
A per-ticker value outside SANE_IV_RANGE is dropped. If fewer than
MIN_COVERAGE_RATIO of attempted tickers resolve, the whole run is treated as a
source outage and NOTHING is written — a missing row is honest, a wrong row is
not (CLAUDE.md §9, Newegg/Steam).

Run:
    python3 iv_crawler.py                        # all tickers
    python3 iv_crawler.py --tickers NVDA AMD
    python3 iv_crawler.py --dry-run              # compute + print, no DB write
"""

import argparse
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

from config import DB_PATH, TICKER_MAP, now_hkt as _now_hkt

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)

# ══════════════════════════════════════════════════════════════════════════════
# TUNABLES — every one of these was chosen to defend against a specific failure
# ══════════════════════════════════════════════════════════════════════════════

TARGET_DTE       = 30            # constant maturity, in calendar days
MIN_DTE          = 5             # sub-5d expiries are pinning-dominated and noisy
NEAR_STRIKES     = 4             # strikes each side of the money, per option type
SANE_IV_RANGE    = (5.0, 400.0)  # percent; outside this we assume a bad quote
MIN_COVERAGE_RATIO = 0.60        # below this share of tickers resolving → outage
REQUEST_DELAY_S  = 0.4           # politeness between Yahoo calls

SRC_YF_DERIVED = "derived-yfinance-atm30"   # our interpolation — NOT published
SRC_DERIBIT    = "Deribit DVOL (published)"  # a real published index

# ── Optionability overrides ───────────────────────────────────────────────────
# Several TICKER_MAP symbols have no listed options on Yahoo. Each maps to the
# instrument the desk already uses as its proxy elsewhere in the app, so the IV
# series stays consistent with the price series' own proxy choice.
IV_SYMBOL_OVERRIDES: Dict[str, Tuple[str, str]] = {
    # display name : (optionable yahoo symbol, why)
    "USD":         ("UUP",   "DX-Y.NYB is an index with no listed options; UUP is the DXY-tracking ETF"),
    "Gold":        ("GLD",   "GC=F futures options are not exposed by Yahoo; GLD is the spot-gold ETF"),
    "10YTreasury": ("TLT",   "^TNX is a yield index with no options; TLT is the existing duration proxy"),
    "BRK.A":       ("BRK-B", "BRK-A has no listed options; BRK-B tracks the same underlying business"),
}

# Tickers sourced from Deribit's published DVOL index instead of option chains.
DERIBIT_TICKERS: Dict[str, str] = {"BTC": "BTC", "ETH": "ETH"}

DERIBIT_DVOL_URL = "https://www.deribit.com/api/v2/public/get_volatility_index_data"


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════════════════

def init_iv_tables(conn: sqlite3.Connection) -> None:
    """Idempotent. Schema is identical to ibkr_options_crawler.init_ibkr_tables
    so both writers can coexist — only the `source` column differs."""
    conn.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS options_iv (
            ticker          TEXT    NOT NULL,
            snapshot_date   TEXT    NOT NULL,
            iv_current      REAL,
            iv_1m_avg       REAL,
            iv_1q_avg       REAL,
            iv_6m_avg       REAL,
            iv_1y_avg       REAL,
            iv_pct_vs_1y    REAL,
            iv_52w_high     REAL,
            iv_52w_low      REAL,
            source          TEXT    DEFAULT 'IBKR',
            PRIMARY KEY (ticker, snapshot_date)
        );

        CREATE TABLE IF NOT EXISTS options_iv_history (
            ticker      TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            iv_pct      REAL,
            source      TEXT    DEFAULT 'IBKR',
            PRIMARY KEY (ticker, date)
        );
    """)
    conn.commit()


# ══════════════════════════════════════════════════════════════════════════════
# EQUITY / ETF / INDEX — ATM 30-day IV from Yahoo option chains
# ══════════════════════════════════════════════════════════════════════════════

def _import_yf():
    """Lazy import so the dashboard can load even if yfinance is unavailable."""
    import yfinance as yf
    return yf


def _atm_iv_for_expiry(chain, spot: float) -> Optional[float]:
    """Weighted near-the-money IV (as a decimal) for one expiry, or None."""
    legs: List[float] = []
    for frame in (chain.calls, chain.puts):
        if frame is None or frame.empty:
            continue
        d = frame.dropna(subset=["impliedVolatility"]).copy()
        # Discard structurally untrustworthy quotes before they can pollute the
        # average: no two-sided market, or an IV that is obviously a solver
        # artefact on a deep wing.
        lo, hi = SANE_IV_RANGE[0] / 100.0, SANE_IV_RANGE[1] / 100.0
        d = d[(d["impliedVolatility"] > lo) & (d["impliedVolatility"] < hi)]
        if "bid" in d.columns and "ask" in d.columns:
            d = d[(d["bid"] > 0) & (d["ask"] > 0)]
        if d.empty:
            continue
        d["_dist"] = (d["strike"] - spot).abs()
        near = d.nsmallest(NEAR_STRIKES, "_dist")
        weights = 1.0 / (near["_dist"].to_numpy() + 1e-6)
        legs.append(float(np.average(near["impliedVolatility"].to_numpy(), weights=weights)))
    if not legs:
        return None
    return float(np.mean(legs))   # average the call-side and put-side reads


def fetch_iv30_yahoo(symbol: str) -> Tuple[Optional[float], str]:
    """Return (IV30 in percent, method note). (None, reason) on failure."""
    yf = _import_yf()
    tk = yf.Ticker(symbol)

    hist = tk.history(period="5d")
    if hist is None or hist.empty:
        return None, "no spot price"
    spot = float(hist["Close"].iloc[-1])

    try:
        expiries = list(tk.options or [])
    except Exception as exc:                        # noqa: BLE001
        return None, "option list failed: %s" % type(exc).__name__
    if not expiries:
        return None, "no listed options"

    today = _now_hkt().date()
    dated = []
    for e in expiries:
        try:
            dte = (datetime.strptime(e, "%Y-%m-%d").date() - today).days
        except ValueError:
            continue
        if dte >= MIN_DTE:
            dated.append((e, dte))
    if not dated:
        return None, "no expiry beyond %dd" % MIN_DTE

    below = [x for x in dated if x[1] <= TARGET_DTE]
    above = [x for x in dated if x[1] >= TARGET_DTE]
    picks: List[Tuple[str, int]] = []
    if below:
        picks.append(below[-1])
    if above and above[0] not in picks:
        picks.append(above[0])

    points: List[Tuple[int, float]] = []
    for expiry, dte in picks:
        try:
            iv = _atm_iv_for_expiry(tk.option_chain(expiry), spot)
        except Exception as exc:                    # noqa: BLE001
            log.debug("chain %s %s failed: %s", symbol, expiry, exc)
            iv = None
        if iv:
            points.append((dte, iv))

    if not points:
        return None, "no usable contracts near the money"

    if len(points) == 1:
        dte, iv = points[0]
        return round(iv * 100.0, 2), "single expiry %dd (no bracket)" % dte

    (d1, v1), (d2, v2) = points[0], points[1]
    # Interpolate in TOTAL VARIANCE (sigma^2 * t), the standard constant-maturity
    # construction. Interpolating sigma directly biases the result whenever the
    # term structure is not flat.
    w = 0.0 if d2 == d1 else (TARGET_DTE - d1) / float(d2 - d1)
    total_var = (1.0 - w) * (v1 ** 2 * d1) + w * (v2 ** 2 * d2)
    eff_dte = (1.0 - w) * d1 + w * d2
    if eff_dte <= 0 or total_var <= 0:
        return None, "degenerate interpolation"
    return round(float(np.sqrt(total_var / eff_dte)) * 100.0, 2), "%dd/%dd variance interp" % (d1, d2)


# ══════════════════════════════════════════════════════════════════════════════
# CRYPTO — Deribit DVOL (a genuinely published 30-day IV index)
# ══════════════════════════════════════════════════════════════════════════════

def fetch_dvol_history(currency: str, days: int = 400) -> pd.DataFrame:
    """Daily DVOL closes. Returns an empty frame on any failure — never raises."""
    # UTC, not _now_hkt(): that helper returns a tz-naive HKT wall-clock time, and
    # .timestamp() would then reinterpret it in the HOST's timezone — an 8-hour
    # window shift between this Mac and the Railway container. Deribit wants real
    # epoch millis, so anchor on UTC.
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    try:
        resp = requests.get(
            DERIBIT_DVOL_URL,
            params={
                "currency": currency,
                "start_timestamp": int(start.timestamp() * 1000),
                "end_timestamp": int(end.timestamp() * 1000),
                "resolution": "43200",       # 12h buckets → downsampled to daily
            },
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json().get("result", {}).get("data", []) or []
    except Exception as exc:                        # noqa: BLE001
        log.warning("Deribit DVOL %s failed: %s", currency, exc)
        return pd.DataFrame(columns=["date", "iv_pct"])

    if not rows:
        return pd.DataFrame(columns=["date", "iv_pct"])

    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms").dt.strftime("%Y-%m-%d")
    df = df.groupby("date", as_index=False)["close"].last()
    df = df.rename(columns={"close": "iv_pct"})
    lo, hi = SANE_IV_RANGE
    df = df[(df["iv_pct"] >= lo) & (df["iv_pct"] <= hi)]
    return df[["date", "iv_pct"]]


# ══════════════════════════════════════════════════════════════════════════════
# METRICS — rolling averages / percentile, computed from accumulated history
# ══════════════════════════════════════════════════════════════════════════════

def compute_metrics(hist: pd.DataFrame) -> dict:
    """
    hist: columns [date, iv_pct], ascending. Windows are TRADING-day counts
    applied to the observations we actually hold.

    A window returns None unless enough observations exist to fill it. That is
    deliberate: on day one of accumulation a 252-day average does not exist, and
    printing the 3-day mean under a "1Y avg" label would be a fabricated metric
    of exactly the kind CLAUDE.md §7.3 documents.
    """
    out = {
        "iv_current": None, "iv_1m_avg": None, "iv_1q_avg": None,
        "iv_6m_avg": None, "iv_1y_avg": None, "iv_pct_vs_1y": None,
        "iv_52w_high": None, "iv_52w_low": None,
    }
    if hist is None or hist.empty:
        return out

    s = hist.sort_values("date")["iv_pct"].astype(float).dropna()
    if s.empty:
        return out

    out["iv_current"] = round(float(s.iloc[-1]), 2)

    for key, window in (("iv_1m_avg", 21), ("iv_1q_avg", 63),
                        ("iv_6m_avg", 126), ("iv_1y_avg", 252)):
        if len(s) >= window:
            out[key] = round(float(s.iloc[-window:].mean()), 2)

    # 52-week stats need a meaningful sample, not two points.
    trailing = s.iloc[-252:]
    if len(trailing) >= 21:
        hi, lo = float(trailing.max()), float(trailing.min())
        out["iv_52w_high"] = round(hi, 2)
        out["iv_52w_low"] = round(lo, 2)
        if hi > lo:
            out["iv_pct_vs_1y"] = round((out["iv_current"] - lo) / (hi - lo) * 100.0, 1)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATION
# ══════════════════════════════════════════════════════════════════════════════

def resolve_symbol(display: str) -> Tuple[str, Optional[str]]:
    """(yahoo symbol to query, proxy note or None)."""
    if display in IV_SYMBOL_OVERRIDES:
        sym, why = IV_SYMBOL_OVERRIDES[display]
        return sym, why
    return TICKER_MAP.get(display, display), None


def crawl_iv(tickers: Optional[List[str]] = None,
             dry_run: bool = False,
             db_path: Optional[str] = None) -> dict:
    """Returns a run report dict. Never raises on a single-ticker failure."""
    db_path = db_path or DB_PATH
    targets = tickers or list(TICKER_MAP.keys())
    today = _now_hkt().strftime("%Y-%m-%d")

    resolved: Dict[str, Tuple[float, str, str]] = {}   # ticker → (iv, source, note)
    dvol_frames: Dict[str, pd.DataFrame] = {}
    failures: Dict[str, str] = {}

    for display in targets:
        if display in DERIBIT_TICKERS:
            df = fetch_dvol_history(DERIBIT_TICKERS[display])
            if df.empty:
                failures[display] = "Deribit returned no data"
                log.warning("  %-12s ✗  %s", display, failures[display])
                continue
            dvol_frames[display] = df
            latest = float(df.sort_values("date")["iv_pct"].iloc[-1])
            resolved[display] = (round(latest, 2), SRC_DERIBIT, "DVOL published index")
            log.info("  %-12s ✓  IV=%6.2f%%   (%s, %d days of history)",
                     display, latest, SRC_DERIBIT, len(df))
            continue

        symbol, proxy_note = resolve_symbol(display)
        try:
            iv, note = fetch_iv30_yahoo(symbol)
        except Exception as exc:                    # noqa: BLE001
            iv, note = None, "%s: %s" % (type(exc).__name__, exc)

        if iv is None:
            failures[display] = note
            log.warning("  %-12s ✗  %s  (%s)", display, note, symbol)
        elif not (SANE_IV_RANGE[0] <= iv <= SANE_IV_RANGE[1]):
            failures[display] = "IV %.2f outside sane range" % iv
            log.warning("  %-12s ✗  %s", display, failures[display])
        else:
            label = symbol if not proxy_note else "%s (proxy)" % symbol
            # The proxy is written INTO the source string, not just logged: a
            # reader querying options_iv for "Gold" must be able to see the
            # number is GLD's vol, not gold futures' (CLAUDE.md §8). A proxy
            # that is only visible in a console log is an undisclosed proxy.
            src = SRC_YF_DERIVED if not proxy_note else "%s (proxy:%s)" % (SRC_YF_DERIVED, symbol)
            resolved[display] = (iv, src, note)
            log.info("  %-12s ✓  IV=%6.2f%%   %-12s %s", display, iv, label, note)

        time.sleep(REQUEST_DELAY_S)

    attempted = len(targets)
    coverage = len(resolved) / float(attempted) if attempted else 0.0
    report = {
        "date": today,
        "attempted": attempted,
        "resolved": len(resolved),
        "coverage": round(coverage, 3),
        "failures": failures,
        "written": False,
    }

    # ── Validation gate ───────────────────────────────────────────────────────
    if coverage < MIN_COVERAGE_RATIO:
        log.error(
            "ABORT: only %d/%d tickers resolved (%.0f%% < %.0f%% floor). "
            "Treating as a source outage — nothing written. Existing rows kept.",
            len(resolved), attempted, coverage * 100, MIN_COVERAGE_RATIO * 100,
        )
        return report

    if dry_run:
        log.info("--dry-run: %d values computed, nothing written.", len(resolved))
        return report

    # ── Write ─────────────────────────────────────────────────────────────────
    with sqlite3.connect(db_path) as conn:
        init_iv_tables(conn)

        # Backfill the full published DVOL history for crypto; equities get one
        # observation per run (Yahoo exposes no historical option chains).
        for display, df in dvol_frames.items():
            conn.executemany(
                "INSERT OR REPLACE INTO options_iv_history (ticker,date,iv_pct,source) VALUES (?,?,?,?)",
                [(display, r.date, float(r.iv_pct), SRC_DERIBIT) for r in df.itertuples()],
            )

        for display, (iv, source, _note) in resolved.items():
            if display not in dvol_frames:
                conn.execute(
                    "INSERT OR REPLACE INTO options_iv_history (ticker,date,iv_pct,source) VALUES (?,?,?,?)",
                    (display, today, iv, source),
                )

        conn.commit()

        for display, (_iv, source, _note) in resolved.items():
            hist = pd.read_sql_query(
                "SELECT date, iv_pct FROM options_iv_history WHERE ticker=? ORDER BY date",
                conn, params=(display,),
            )
            m = compute_metrics(hist)
            # Columns named explicitly, never positional: a bare VALUES(?,...)
            # silently rebinds every field if the schema column order is ever
            # touched, which is the same class of failure as CLAUDE.md §7 rule 2.
            conn.execute(
                """INSERT OR REPLACE INTO options_iv
                       (ticker, snapshot_date, iv_current, iv_1m_avg, iv_1q_avg,
                        iv_6m_avg, iv_1y_avg, iv_pct_vs_1y, iv_52w_high,
                        iv_52w_low, source)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (display, today, m["iv_current"], m["iv_1m_avg"], m["iv_1q_avg"],
                 m["iv_6m_avg"], m["iv_1y_avg"], m["iv_pct_vs_1y"],
                 m["iv_52w_high"], m["iv_52w_low"], source),
            )
        conn.commit()

    report["written"] = True
    log.info("✅  Wrote IV for %d/%d tickers to %s", len(resolved), attempted, db_path)
    if failures:
        log.info("    Unresolved: %s", ", ".join(sorted(failures)))
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Cloud-native implied-volatility crawler")
    ap.add_argument("--tickers", nargs="*", default=None, help="display names, e.g. NVDA AMD")
    ap.add_argument("--dry-run", action="store_true", help="compute and print, do not write")
    ap.add_argument("--db", default=None, help="override DB path")
    args = ap.parse_args()

    log.info("IV crawl starting  (target maturity %dd, sane range %.0f–%.0f%%)",
             TARGET_DTE, *SANE_IV_RANGE)
    rep = crawl_iv(tickers=args.tickers, dry_run=args.dry_run, db_path=args.db)
    log.info("Coverage %d/%d (%.0f%%)  written=%s",
             rep["resolved"], rep["attempted"], rep["coverage"] * 100, rep["written"])


if __name__ == "__main__":
    main()
