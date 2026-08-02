"""
dashboard.py — Semiconductor Industry Interactive Dashboard
===========================================================
Launches a Dash web app that reads from semiconductor_data.db.

Run:
    python dashboard.py
Then open http://127.0.0.1:8050 in your browser.
"""

import os
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html, dash_table
from plotly.subplots import make_subplots
from scipy.signal import argrelextrema

# Supply-chain product lists (for grouping in SC tab)
from products_config import (
    GPU_PRODUCTS, GPU_ENTERPRISE_PRODUCTS,
    CPU_PRODUCTS, CPU_ENTERPRISE_PRODUCTS,
    RAM_PRODUCTS,
    ENTERPRISE_PRODUCT_LAUNCHES,
    SRC_PUBLISHED, SRC_MODELED, CURATED_RETAIL_PROVENANCE,
    DEMAND_INDICATOR_META,
)

# IBKR integration (optional — graceful if not installed / not enabled)
from ibkr_options_crawler import ibkr_is_enabled, init_ibkr_tables
from job_heartbeat import job_report, overdue_jobs, scheduler_enabled   # QA F-01

from config import (
    DB_PATH,
    DASHBOARD_HOST,
    DASHBOARD_PORT,
    SEMI_COMPANIES,
    SEMI_ETFS,
    TICKER_TYPES,
    CHART_COLORS,
    now_hkt as _now_hkt,
)

# ── Colour theme ──────────────────────────────────────────────────────────────
BG       = "#0d1117"
BG2      = "#161b22"
BG3      = "#21262d"
ACCENT   = "#58a6ff"
GREEN    = "#3fb950"
RED      = "#f85149"
YELLOW   = "#d29922"
TEXT     = "#e6edf3"
SUBTEXT  = "#8b949e"

# ── Persistent-volume status (set by startup.sh — see its volume guard) ───────
# Defaults to OK so local dev and any non-Railway host stay quiet.
VOLUME_OK     = os.environ.get("SEMI_VOLUME_OK", "1") != "0"
VOLUME_REASON = os.environ.get("SEMI_VOLUME_REASON", "ok")


def _volume_banner():
    """Full-width red banner shown only when the DB is on ephemeral storage.

    Static (env vars cannot change without a restart), so it is built at layout
    time with no callback — keeps it clear of Hard Rules 3 and 4.
    """
    if VOLUME_OK:
        return None
    return html.Div(
        [
            html.Span("⚠️ EPHEMERAL STORAGE — DATA WILL BE LOST ON REDEPLOY",
                      style={"fontWeight": "700", "marginRight": "12px"}),
            html.Span(VOLUME_REASON, style={"opacity": "0.9"}),
            html.Span(
                "  Fix: Railway → service → Settings → Volumes, then point "
                "DB_PATH inside the mount.",
                style={"opacity": "0.75", "marginLeft": "12px"},
            ),
        ],
        style={
            "background": RED, "color": "#ffffff", "padding": "8px 20px",
            "fontSize": "12.5px", "letterSpacing": "0.2px",
            "borderBottom": "1px solid #7d1d17",
        },
    )

PLOTLY_TEMPLATE = dict(
    layout=dict(
        paper_bgcolor=BG2,
        plot_bgcolor =BG3,
        font         =dict(color=TEXT, family="Inter, Segoe UI, sans-serif"),
        xaxis        =dict(gridcolor="#30363d", linecolor="#30363d", zerolinecolor="#30363d"),
        yaxis        =dict(gridcolor="#30363d", linecolor="#30363d", zerolinecolor="#30363d"),
        legend       =dict(bgcolor=BG2, bordercolor="#30363d"),
        colorway     =CHART_COLORS,
        margin       =dict(l=50, r=20, t=40, b=40),
    )
)


# ══════════════════════════════════════════════════════════════════════════════
# DATA LAYER
# ══════════════════════════════════════════════════════════════════════════════

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def query(sql: str, params=()) -> pd.DataFrame:
    try:
        with get_conn() as c:
            return pd.read_sql_query(sql, c, params=params)
    except Exception:
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# DATA FRESHNESS (BACKLOG SC-03)
# ══════════════════════════════════════════════════════════════════════════════
#
# Row counts are not a health signal. Three separate data outages — the Newegg
# NULL-price rows, the 17-month-frozen Steam survey, and the retired SEMI B2B
# series — all ran with COUNT(*) climbing or steady and every status endpoint
# green. A source that has stopped producing must be distinguishable from one
# that is working, so every table declares the column that carries its
# observation date and an SLA for how old that date may get.
#
#   table -> (date column, granularity, SLA in days)
#
# Granularity matters: 'month' and 'quarter' periods are measured from the END
# of the period, otherwise a figure published for May would count as 30 days
# stale on 1 June through no fault of the source.

_FRESHNESS_SPEC = {
    "daily_prices":         ("date",          "date",      4),
    "market_sentiment":     ("snapshot_date", "date",      4),
    "cycle_analysis":       ("snapshot_date", "date",      4),
    "quarterly_financials": ("period_end",    "date",    120),
    "options_iv":           ("snapshot_date", "date",      4),
    # Written once per ticker per crawl, keyed to the last trading date — so it
    # tracks daily_prices exactly and shares its 4-day SLA. If this goes stale
    # while daily_prices does not, the crawl is running but .info is failing.
    "ticker_valuation_history": ("snapshot_date", "date",  4),
    # sc_dram_spot is intentionally ABSENT: it is reported per product_type via
    # _SC_DRAM_SLA below. A table-level entry would let one fresh series certify
    # the whole table (BACKLOG SC-08) — see the comment there.
    # sc_semi_btb no longer exists — dropped in SC-10 after SC-00 removed its
    # panel. It was the one table deliberately left unmonitored here; deleting it
    # removed the exception rather than the monitoring. Every remaining table is
    # covered, either by an entry above or by a per-key SLA dict below.
    # 120d, not 60d: Valve publishes the survey with a 1–3 month lag, and this
    # SLA must agree with the "As of" badge in _sc_steam_panel() (red at 4+
    # months). Two surfaces disagreeing about the same table is how a real
    # signal gets ignored.
    "sc_market_share":      ("period",        "month",   120),
    # sc_fab_metrics: quarterly company disclosures. 150d because TSMC files
    # ~Q+20d but the hand-transcribed Management Report rows lag further
    # (SC-11); tighten once the live crawler is the only writer.
    "sc_fab_metrics":       ("period",        "quarter", 150),
}

# sc_prices mixes live scrapes and curated history in one table under different
# `source` values, so it gets one entry per source class rather than one overall.
_SC_PRICE_SLA = {"newegg": 7, "passmark": 7, "curated": 45}

# sc_demand_indicators (BACKLOG SC-06) mixes five series at three different
# cadences in one table — same per-key pattern as _SC_PRICE_SLA. tsmc/umc get
# a tight SLA because they have a live crawler; the three curated-only series
# get slack matching how often their source actually publishes.
_SC_DEMAND_SLA = {
    "tsmc_revenue":           40,   # monthly, published ~10th
    "umc_revenue":            40,
    # Nanya files monthly like TSMC/UMC, but its ENGLISH IR page lags: on
    # 2026-08-02 it carried Jan–May while TSMC and UMC already showed June
    # (confirmed by its own accumulated-revenue total, which sums Jan–May exactly,
    # so this is publication lag and not a parse gap). Calibrated to that observed
    # lag rather than to the statutory filing date — an SLA set to what we WISH
    # the lag were fires on day one and trains the reader to ignore the badge
    # (SC-04). Tighten to 40 once the live crawler has two or three months of real
    # evidence about this page's actual cadence; do not guess it lower now.
    "nanya_revenue":          70,
    "korea_chip_exports_20d": 20,   # ~3x/month
    # SLAs are calibrated to each publisher's ACTUAL lag, not to how recent we
    # would like the data to be. A badge that fires while the publisher simply
    # hasn't released yet trains the reader to ignore it (BACKLOG SC-04).
    "wsts_billings":          75,   # monthly, WSTS/SIA release ~2 months in arrears
    "semi_wwsems_billings":  160,   # quarterly; Q1-2026 landed 2026-06-04 = Q+65d,
                                    # so Q2 is not due until ~early September
}
_SC_DEMAND_KIND = {
    "semi_wwsems_billings": "quarter",
}

# sc_dram_spot — per product_type, same per-key pattern as _SC_PRICE_SLA (SC-08).
#
# Why the table-level SLA had to go: on 2026-08-02 this table reported
# days_stale=33, unhealthy=False on the strength of ONE row (the DDR4 2026-06
# anchor SC-04 added), while DDR5's newest observation was 2024-12 — a 20-month
# hole through the largest DRAM upcycle on record. MAX(period) over a table that
# holds several independent series answers "is ANY series fresh?", which is never
# the question worth asking. This is SC-03's own lesson one level down: the fix
# for sc_prices was a per-source SLA, and sc_dram_spot needed the same.
#
# An unlisted product_type falls back to 45d. Add a key when you add a series.
# NOT tightened to ~10d despite crawl_trendforce_spot() going live in SC-15:
# the full supply-chain crawl runs only on an empty DB or a manual ⚡ Run Crawl,
# so today the live crawler fires rarely and a tight SLA would breach constantly
# and train the reader to ignore the badge (the SC-04 calibration lesson).
# Tighten to 10d in the SAME change that adds the Railway Cron schedule —
# a crawler does not make data fresh until something runs it.
_SC_DRAM_SLA = {
    "DDR4":  45,   # TrendForce quotes the mainstream chip weekly
    "DDR5":  45,
    "HBM3":  75,   # withdrawn (SC-09); key retained so a restored series is
    "HBM3E": 75,   # monitored from its first row rather than silently unwatched
}


def _period_end_date(value: str, kind: str):
    """Normalise a stored period to the calendar date it stops describing."""
    if value is None:
        return None
    v = str(value).strip()
    try:
        if kind == "month":                      # "2026-05"
            return (pd.Period(v[:7], freq="M")).end_time.normalize()
        if kind == "quarter":                    # "2025-Q1"
            return (pd.Period(v.replace("-", ""), freq="Q")).end_time.normalize()
        return pd.to_datetime(v[:10]).normalize()
    except Exception:
        return None


def _freshness_report() -> dict:
    """
    Per-source freshness: newest observation, age in days, SLA, breach flag.

    Never raises — a missing table is reported, not fatal. Shared by
    /api/db-stats and the navbar badge so both can never disagree.
    """
    today  = pd.Timestamp.today().normalize()
    report = {}

    def _entry(key, max_period, kind, sla, rows, extra=None):
        end  = _period_end_date(max_period, kind)
        days = int((today - end).days) if end is not None else None
        rec  = {
            "rows":       rows,
            "max_period": str(max_period) if max_period is not None else None,
            "days_stale": days,
            "sla_days":   sla,
            "stale":      (days is not None and days > sla),
        }
        if extra:
            rec.update(extra)
        # A source can be perfectly punctual and still carry nothing — the Newegg
        # scraper wrote a fresh row per product per day, every one of them NULL.
        # Timeliness and content are separate failures; flag both.
        rec["empty"]     = bool(rec.get("null_price_pct", 0) >= 50)
        rec["unhealthy"] = bool(rec["stale"] or rec["empty"])
        report[key] = rec

    for table, (col, kind, sla) in _FRESHNESS_SPEC.items():
        df = query(f"SELECT COUNT(*) AS n, MAX({col}) AS mx FROM {table}")
        if df.empty:
            report[table] = {"rows": "table missing", "max_period": None,
                             "days_stale": None, "sla_days": sla, "stale": False}
            continue
        _entry(table, df["mx"].iloc[0], kind, sla, int(df["n"].iloc[0]))

    # sc_prices — per source, plus the null-price rate that hid the Newegg outage.
    df = query(
        "SELECT source, COUNT(*) AS n, COUNT(price_usd) AS priced, MAX(date) AS mx "
        "FROM sc_prices GROUP BY source"
    )
    for _, r in df.iterrows():
        src   = str(r["source"])
        n     = int(r["n"])
        prc   = int(r["priced"])
        _entry(
            f"sc_prices[{src}]", r["mx"], "date", _SC_PRICE_SLA.get(src, 45), n,
            extra={"null_price_pct": round((n - prc) / n * 100, 1) if n else 0.0},
        )

    # sc_dram_spot — per product_type (BACKLOG SC-08). Reported as
    # sc_dram_spot[ddr5] etc., matching the sc_prices[...] / sc_demand[...] shape
    # already used by the badge, so no caller needs to learn a new key format.
    df = query(
        "SELECT product_type, COUNT(*) AS n, MAX(period) AS mx "
        "FROM sc_dram_spot GROUP BY product_type"
    )
    for _, r in df.iterrows():
        pt = str(r["product_type"])
        _entry(f"sc_dram_spot[{pt.lower()}]", r["mx"], "month",
               _SC_DRAM_SLA.get(pt, 45), int(r["n"]))

    # sc_demand_indicators — per indicator_key (BACKLOG SC-06); table may not
    # exist yet on an old DB, so this must degrade gracefully like the others.
    df = query(
        "SELECT indicator_key, COUNT(*) AS n, MAX(period) AS mx "
        "FROM sc_demand_indicators GROUP BY indicator_key"
    )
    for _, r in df.iterrows():
        key = str(r["indicator_key"])
        kind = _SC_DEMAND_KIND.get(key, "month")
        _entry(f"sc_demand[{key}]", r["mx"], kind, _SC_DEMAND_SLA.get(key, 45), int(r["n"]))

    return report


# ══════════════════════════════════════════════════════════════════════════════
# CROSS-SOURCE CONSISTENCY (BACKLOG SC-12)
# ══════════════════════════════════════════════════════════════════════════════
#
# _freshness_report() answers "is each source still producing?". It cannot answer
# "is what it produced believable?", and every data bug found in this project so
# far was of the second kind:
#
#   SC-01  Newegg wrote a row per product per day, every price NULL
#   SC-02  Steam survey frozen 17 months, panel looked normal
#   SC-04  34 DDR rows decayed 1-2%/month for 17 months, ~18x off the real market
#   SC-09  HBM3E rose exactly +$0.20 every 2 months for 15 steps
#   SC-00  41 rows of an indicator discontinued in 2016
#
# Each was found by a human reading the numbers, never by the system. Worse, on
# 2026-08-02 the DB simultaneously held WSTS billings at +104% YoY and a DRAM spot
# series flat since 2024-12 — mutually impossible, both individually "healthy",
# no warning anywhere.
#
# These rules are ADVISORY: they flag, they never delete. A flag is a prompt to go
# look, not a verdict — real series do occasionally sit flat or move linearly.
_CONSISTENCY_SPEC = {
    # label            table                  series key       period    value            source
    "sc_dram_spot":   ("sc_dram_spot",        "product_type",  "period", "price_usd",      "source"),
    "sc_market_share":("sc_market_share",     "model_name",    "period", "share_pct",      "source"),
    "sc_demand":      ("sc_demand_indicators","indicator_key", "period", "value",          "source"),
    "sc_fab_metrics": ("sc_fab_metrics",      "company",       "period", "value",          "source"),
    "sc_prices":      ("sc_prices",           "model_id",      "date",   "price_usd",      "source"),
    # ── Equity fundamentals (QA finding F-02, added 2026-08-02) ───────────────
    # These two entries exist because the shape checks were pointed only at the
    # supply-chain tables while quarterly_financials carried a textbook `frozen`
    # series: a snapshot P/E and market cap replicated into every historical
    # quarter. The rule that would have caught it on day one was already
    # written — it was simply never aimed here.
    #
    # The crawler now writes NULL to pe_ratio/market_cap, so the first entry
    # normally checks nothing. That is the point: it is a REGRESSION TRIP-WIRE.
    # If anyone re-points these columns at yf.Ticker().info, the frozen rule
    # fires at `high` severity on the next /api/db-stats call.
    #
    # KNOWN LIMIT — state it rather than overclaim: the frozen rule needs
    # _FLAT_MIN_POINTS (6) identical values, and yfinance returns only ~5
    # quarters per call. On a freshly-seeded DB this trip-wire is therefore
    # ARMED BUT NOT YET ABLE TO FIRE. quarterly_financials accumulates across
    # crawls (INSERT OR REPLACE never deletes older quarters), so it becomes
    # effective once a ticker holds 6+ quarters — roughly two quarters of
    # running. It is a guard against reintroduction over time, not a detector
    # that would have caught the original F-02 on day one.
    #
    # quarterly_financials has no source column, so a literal is passed. It
    # deliberately does not contain "modeled"/"curated"/"estimate", which means
    # _shape_severity() rates any flag here HIGH — correct, because a vendor
    # fundamentals feed claiming a frozen series is a defect, not a disclosure.
    "fin_valuation":  ("quarterly_financials", "ticker",       "period_end", "pe_ratio", "'yfinance (vendor feed)'"),
    "fin_revenue":    ("quarterly_financials", "ticker",       "period_end", "revenue",  "'yfinance (vendor feed)'"),
}

# Severity depends on what the series CLAIMS to be, not just on its shape.
#
# A series labelled as a modeled estimate having a modeled shape is self-
# consistent — disclosed, and the reader was told. A series claiming a publisher
# while showing a fabricated shape is the actual defect: that is precisely SC-04,
# where 34 hand-extrapolated rows carried the label "TrendForce (public release)".
#
# Without this split the badge fires ~24 times on day one from the curated retail
# price curves (all correctly labelled SRC_MODELED) and becomes noise — the same
# way an over-tight SLA trains a reader to ignore an alert (SC-04 calibration).
# "expected" flags are still reported in /api/db-stats; they just don't alarm.
_MODELED_MARKERS = ("modeled", "modelled", "estimate", "curated")


def _shape_severity(source: str) -> str:
    s = (source or "").lower()
    return "expected" if any(m in s for m in _MODELED_MARKERS) else "high"

_FLAT_MIN_POINTS     = 6      # identical values in a row before it is suspicious
_GLIDE_MIN_STEPS     = 5      # equal first-differences in a row
_GLIDE_REL_TOL       = 0.01   # "equal" within 1%
_DIVERGE_YOY_PCT     = 20.0   # |WSTS YoY| above this = the market is definitely moving


def _consistency_report() -> dict:
    """
    Shape-based plausibility checks across every curated/scraped series.

    Returns {"flags": [...], "checked": n, "ok": bool}. Never raises — a broken
    check must not take down /api/db-stats (same contract as _freshness_report).
    """
    flags = []
    checked = 0

    try:
        # ── Context: is the market actually moving? Used by the divergence rule.
        wsts_yoy = None
        try:
            w = query(
                "SELECT value, period FROM sc_demand_indicators "
                "WHERE indicator_key='wsts_billings' AND value IS NOT NULL "
                "ORDER BY period"
            )
            if len(w) >= 2:
                first, last = float(w["value"].iloc[0]), float(w["value"].iloc[-1])
                if first > 0:
                    wsts_yoy = (last / first - 1) * 100
        except Exception:
            pass

        for label, (table, key_col, per_col, val_col, src_col) in _CONSISTENCY_SPEC.items():
            try:
                df = query(
                    f"SELECT {key_col} AS k, {per_col} AS p, {val_col} AS v, "
                    f"{src_col} AS s FROM {table} "
                    f"WHERE {val_col} IS NOT NULL ORDER BY k, p"
                )
            except Exception:
                continue                      # table absent on an older DB
            if df.empty:
                continue

            for key, grp in df.groupby("k"):
                vals = [float(x) for x in grp["v"].tolist()]
                pers = [str(x) for x in grp["p"].tolist()]
                if len(vals) < 3:
                    continue
                checked += 1
                sid = f"{label}[{key}]"
                srcs = [str(x) for x in grp["s"].tolist() if x is not None]
                sev  = _shape_severity(max(set(srcs), key=srcs.count) if srcs else "")

                def flag(rule, detail, _sid=sid, _sev=sev):
                    flags.append({"series": _sid, "rule": rule,
                                  "detail": detail, "severity": _sev})

                # RULE 1 — frozen. A live series that stopped moving while still
                # being written. (SC-02: Steam shares identical period after
                # period.) Distinct from staleness: this one keeps producing.
                tail = vals[-_FLAT_MIN_POINTS:]
                if len(tail) >= _FLAT_MIN_POINTS and len(set(tail)) == 1:
                    msg = (f"{len(tail)} consecutive identical values ({tail[-1]:g}) "
                           f"through {pers[-1]}")
                    if wsts_yoy is not None and abs(wsts_yoy) > _DIVERGE_YOY_PCT:
                        msg += f" while WSTS billings moved {wsts_yoy:+.0f}%"
                    flag("frozen", msg)

                # RULE 2 — synthetic glide. The fingerprint shared by SC-04's
                # falsified DDR rows and SC-09's modeled HBM series: a real spot
                # or contract price does not step by a constant amount for months.
                diffs = [b - a for a, b in zip(vals, vals[1:])]
                run, best, best_at = 1, 1, len(diffs) - 1
                for i in range(1, len(diffs)):
                    prev, cur = diffs[i - 1], diffs[i]
                    same = (abs(cur - prev) <= _GLIDE_REL_TOL * max(abs(prev), 1e-9))
                    run = run + 1 if same else 1
                    if run > best:
                        best, best_at = run, i
                if best >= _GLIDE_MIN_STEPS and abs(diffs[best_at]) > 0:
                    flag("synthetic_glide",
                         f"{best} consecutive steps of ~{diffs[best_at]:+g} "
                         f"(<{_GLIDE_REL_TOL:.0%} variation) ending {pers[best_at + 1]}")

                # RULE 2b — geometric glide. SC-04's rows fell a constant ~1.5%
                # every month, so their absolute steps kept shrinking and Rule 2
                # (constant difference) missed them entirely — only the WSTS
                # divergence rule caught that series. A constant RATIO is the
                # other half of the same fingerprint, and unlike Rule 3 it needs
                # no demand-layer context, so it still works if WSTS goes quiet.
                ratios = [b / a for a, b in zip(vals, vals[1:]) if a not in (0,)]
                if len(ratios) >= _GLIDE_MIN_STEPS:
                    rrun, rbest, rat = 1, 1, len(ratios) - 1
                    for i in range(1, len(ratios)):
                        same = abs(ratios[i] - ratios[i - 1]) <= _GLIDE_REL_TOL * abs(ratios[i - 1])
                        rrun = rrun + 1 if same else 1
                        if rrun > rbest:
                            rbest, rat = rrun, i
                    if rbest >= _GLIDE_MIN_STEPS and abs(ratios[rat] - 1.0) > 1e-6:
                        flag("geometric_glide",
                             f"{rbest} consecutive steps of ~{(ratios[rat] - 1) * 100:+.2f}% "
                             f"(<{_GLIDE_REL_TOL:.0%} variation) ending {pers[rat + 1]}")

                # RULE 3 — monotonic decay. SC-04's rows fell every single month
                # for 17 months. Direction alone is weak evidence, so this only
                # fires when the demand layer says the market went the other way.
                if (wsts_yoy is not None and wsts_yoy > _DIVERGE_YOY_PCT
                        and len(diffs) >= _FLAT_MIN_POINTS
                        and all(d < 0 for d in diffs[-_FLAT_MIN_POINTS:])):
                    flag("divergence",
                         f"fell for {_FLAT_MIN_POINTS} consecutive periods to "
                         f"{vals[-1]:g} ({pers[-1]}) while WSTS billings "
                         f"moved {wsts_yoy:+.0f}%")
    except Exception as exc:                  # never take down /api/db-stats
        return {"flags": [], "checked": 0, "ok": True, "error": str(exc)}

    flags.sort(key=lambda f: (f.get("severity") != "high", f["rule"], f["series"]))
    high = [f for f in flags if f.get("severity") == "high"]
    return {
        "flags":    flags,
        "high":     len(high),
        "expected": len(flags) - len(high),
        "checked":  checked,
        # `ok` tracks HIGH only — an "expected" flag is a disclosed modeled series,
        # which is not a defect and must not make the dashboard look broken.
        "ok":       not high,
    }


def _stale_sources(report: dict = None) -> list:
    """
    Sources breaching their SLA *or* returning mostly-empty rows, worst first.

    "Stale" is the shorthand; `unhealthy` is the real test, because a dead
    scraper that still writes a row every day is punctual and useless.
    """
    rep = report if report is not None else _freshness_report()
    bad = [(k, v) for k, v in rep.items() if v.get("unhealthy")]
    bad.sort(key=lambda kv: kv[1].get("days_stale") or 0, reverse=True)
    return [k for k, _ in bad]


def all_tickers() -> list[str]:
    df = query("SELECT DISTINCT ticker FROM daily_prices ORDER BY ticker")
    return df["ticker"].tolist() if not df.empty else []


def last_crawl_time() -> str:
    df = query("SELECT finished_at FROM crawl_runs WHERE status='completed' ORDER BY id DESC LIMIT 1")
    if df.empty or df["finished_at"].iloc[0] is None:
        return "Never"
    try:
        dt = datetime.fromisoformat(df["finished_at"].iloc[0])
        return dt.strftime("%d %b %Y  %H:%M HKT")
    except Exception:
        return df["finished_at"].iloc[0]


def price_data(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    placeholders = ",".join("?" * len(tickers))
    return query(
        f"SELECT ticker,date,open,high,low,close,volume FROM daily_prices "
        f"WHERE ticker IN ({placeholders}) AND date BETWEEN ? AND ? ORDER BY ticker,date",
        tickers + [start, end],
    )


def financials_data(tickers: list[str]) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    placeholders = ",".join("?" * len(tickers))
    return query(
        f"SELECT * FROM quarterly_financials WHERE ticker IN ({placeholders}) ORDER BY ticker,period_end",
        tickers,
    )


def valuation_snapshot_data(tickers: list[str]) -> pd.DataFrame:
    """
    Latest observed valuation snapshot per ticker from ticker_valuation_history.

    Deliberately separate from financials_data(): these figures describe the
    date they were OBSERVED, not a fiscal period. Joining them onto a quarter is
    the F-02 defect. Returns empty (not an error) on a DB predating the table —
    the panel renders an explanatory blank rather than failing.
    """
    if not tickers:
        return pd.DataFrame()
    placeholders = ",".join("?" * len(tickers))
    try:
        return query(
            f"""
            SELECT v.*
            FROM ticker_valuation_history v
            JOIN (
                SELECT ticker, MAX(snapshot_date) AS md
                FROM ticker_valuation_history
                WHERE ticker IN ({placeholders})
                GROUP BY ticker
            ) latest
              ON v.ticker = latest.ticker AND v.snapshot_date = latest.md
            ORDER BY v.ticker
            """,
            tickers,
        )
    except Exception:
        return pd.DataFrame()


def sentiment_data(tickers: list[str]) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    placeholders = ",".join("?" * len(tickers))
    # Latest snapshot per ticker
    return query(
        f"""SELECT s.* FROM market_sentiment s
            INNER JOIN (
                SELECT ticker, MAX(snapshot_date) AS md FROM market_sentiment
                WHERE ticker IN ({placeholders}) GROUP BY ticker
            ) latest ON s.ticker=latest.ticker AND s.snapshot_date=latest.md
            ORDER BY s.ticker""",
        tickers,
    )


def cycle_data(tickers: list[str]) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    placeholders = ",".join("?" * len(tickers))
    return query(
        f"""SELECT c.* FROM cycle_analysis c
            INNER JOIN (
                SELECT ticker, MAX(snapshot_date) AS md FROM cycle_analysis
                WHERE ticker IN ({placeholders}) GROUP BY ticker
            ) latest ON c.ticker=latest.ticker AND c.snapshot_date=latest.md
            ORDER BY c.ticker""",
        tickers,
    )


def company_info_data(tickers: list[str]) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    placeholders = ",".join("?" * len(tickers))
    return query(
        f"SELECT * FROM company_info WHERE ticker IN ({placeholders})",
        tickers,
    )


# ══════════════════════════════════════════════════════════════════════════════
# LAYOUT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _card(children, style=None):
    base = {"background": BG2, "borderRadius": "8px", "padding": "16px",
            "border": f"1px solid #30363d", "marginBottom": "12px"}
    if style:
        base.update(style)
    return html.Div(children, style=base)


def _kpi(label: str, value: str, delta: str = "", color: str = TEXT):
    return html.Div([
        html.Div(label, style={"fontSize": "11px", "color": SUBTEXT, "textTransform": "uppercase", "letterSpacing": "0.5px"}),
        html.Div(value, style={"fontSize": "22px", "fontWeight": "700", "color": color}),
        html.Div(delta, style={"fontSize": "12px", "color": GREEN if delta.startswith("+") else (RED if delta.startswith("-") else SUBTEXT)}),
    ], style={"padding": "8px 0"})


def _section_title(text: str):
    return html.Div(text, style={"fontSize": "13px", "fontWeight": "600",
                                  "color": ACCENT, "textTransform": "uppercase",
                                  "letterSpacing": "1px", "marginBottom": "8px"})


def _crawl_timestamp() -> str:
    """Return last completed crawl time in System Directive format: YYYY-MM-DD HH:MM HKT.
    Falls back to 'Data not available in the latest crawl.' if no record exists."""
    df = query(
        "SELECT finished_at FROM crawl_runs WHERE status='completed' ORDER BY id DESC LIMIT 1"
    )
    if df.empty or df["finished_at"].iloc[0] is None:
        return "Data not available in the latest crawl."
    try:
        dt = datetime.fromisoformat(str(df["finished_at"].iloc[0]))
        return dt.strftime("%Y-%m-%d %H:%M HKT")
    except Exception:
        return str(df["finished_at"].iloc[0])


def _source_footer(source_name: str, notes: str = "") -> html.Div:
    """Return a standardised attribution footer per the System Directive.
    Renders: [Source: <source_name>] · [Data Last Crawled/Updated: YYYY-MM-DD HH:MM HKT]
    """
    ts = _crawl_timestamp()
    text_parts = [
        html.Span(f"[Source: {source_name}]",
                  style={"color": ACCENT, "fontWeight": "600", "marginRight": "12px"}),
        html.Span(f"[Data Last Crawled/Updated: {ts}]",
                  style={"color": SUBTEXT}),
    ]
    if notes:
        text_parts.append(
            html.Span(f"  ·  {notes}", style={"color": SUBTEXT})
        )
    return html.Div(text_parts, style={
        "fontSize": "11px", "marginTop": "10px", "paddingTop": "8px",
        "borderTop": "1px solid #30363d", "fontFamily": "monospace",
    })


def _time_rangeselector(active_index: int = 0) -> dict:
    """Standard 1Y / 3Y / 5Y Plotly rangeselector.
    Buttons are anchored relative to today (stepmode='backward') so they always
    show the correct window regardless of when the dashboard is opened.
    active_index: kept as a parameter for call-site compatibility but is not
    passed to Plotly — the 'active' key is not supported by the installed
    Plotly version (raises ValueError on Rangeselector objects).
    The displayed window is controlled by xaxis.range instead.
    """
    return dict(
        buttons=[
            dict(count=1, label="1Y", step="year", stepmode="backward"),
            dict(count=3, label="3Y", step="year", stepmode="backward"),
            dict(count=5, label="5Y", step="year", stepmode="backward"),
        ],
        activecolor=ACCENT,
        bgcolor=BG2,
        bordercolor="#30363d",
        borderwidth=1,
        font=dict(color=TEXT, size=11),
        # Pinned above the plot area, left-aligned. Plotly's default places the
        # buttons *inside* the top-left of the plot, where they sit on top of the
        # series lines and any top-anchored legend. Always pair with
        # _apply_rangeselector_layout() so the headroom actually exists.
        x=0, xanchor="left", y=1.03, yanchor="bottom",
    )


def _apply_rangeselector_layout(fig, legend_bottom: bool = True,
                                extra_height: int = 70) -> None:
    """Reserve headroom for the 1Y/3Y/5Y rangeselector buttons.

    Call this on EVERY figure that sets `rangeselector=_time_rangeselector(...)`.
    Without it the buttons overlay the chart title, the legend, or the plotted
    lines themselves (see §7.2 in CLAUDE.md).

    - grows the figure so the plot area is not squeezed by the added top margin
    - opens a 95 px top margin: title on the first line, buttons on the second
    - moves the legend below the x-axis (default) so it can never collide with
      the buttons; pass legend_bottom=False to keep the right-hand legend.
    """
    _h = fig.layout.height or 400
    _upd = dict(
        height=_h + extra_height,
        title=dict(y=0.975, yanchor="top", x=0.01, xanchor="left"),
    )
    if legend_bottom:
        _upd["margin"] = dict(l=60, r=25, t=95, b=95)
        _upd["legend"] = dict(
            orientation="h", yanchor="top", y=-0.18, xanchor="left", x=0,
            font=dict(color=TEXT, size=10),
            bgcolor="rgba(0,0,0,0)", bordercolor="#30363d",
        )
    else:
        _upd["margin"] = dict(l=60, r=25, t=95, b=55)
    fig.update_layout(**_upd)


def _range_start(years: int = 1) -> str:
    """Return ISO date string for `years` years before today (system time)."""
    return (_now_hkt() - timedelta(days=365 * years)).strftime("%Y-%m-%d")


def ticker_checklist(group_name: str, tickers: list[str], default_checked: list[str]):
    return html.Div([
        _section_title(group_name),
        dbc.Checklist(
            id=f"chk-{group_name.lower().replace(' ', '-').replace('/', '')}",
            options=[{"label": t, "value": t} for t in tickers],
            value=[t for t in default_checked if t in tickers],
            labelStyle={"display": "block", "fontSize": "13px", "color": TEXT,
                        "margin": "2px 0", "cursor": "pointer"},
            inputStyle={"marginRight": "6px", "accentColor": ACCENT},
        ),
    ], style={"marginBottom": "16px"})


# ── Module-level ticker category helpers (shared by Overview & Sentiment tabs) ─
_CAT_ORDER = {
    "Semi Companies": SEMI_COMPANIES,
    "Semi ETFs":      SEMI_ETFS,
    "Macro / Other":  ["TQQQ", "QQQ", "VIX", "USD", "10YTreasury", "Gold", "BTC", "ETH"],
    "Tech / Mixed":   ["MSFT", "GOOG", "META", "AAPL", "TSLA", "AMZN", "ORCL", "BRK.A"],
}
_SHORT_CAT = {
    "Semi Companies": "Semi",
    "Semi ETFs":      "ETF",
    "Macro / Other":  "Macro",
    "Tech / Mixed":   "Tech",
}
_cat_rank = {
    tkr: (ci, ti)
    for ci, (_, members) in enumerate(_CAT_ORDER.items())
    for ti, tkr in enumerate(members)
}


def _ticker_cat(tkr: str) -> str:
    """Return short category label, e.g. 'Semi', 'ETF', 'Macro', 'Tech'."""
    for cat, members in _CAT_ORDER.items():
        if tkr in members:
            return _SHORT_CAT[cat]
    return "Other"


def _ticker_label(tkr: str) -> str:
    """Return '[Cat] Ticker' label for display, e.g. '[Semi] NVDA'."""
    cat = _ticker_cat(tkr)
    return f"[{cat}] {tkr}" if cat != "Other" else tkr


def _compute_hv30(tickers: list) -> pd.DataFrame:
    """Compute 30-day Historical Volatility (annualised %) from daily_prices.
    Returns a DataFrame with columns [ticker, hv30]."""
    if not tickers:
        return pd.DataFrame(columns=["ticker", "hv30"])
    placeholders = ",".join("?" * len(tickers))
    # Fetch ~50 trading days so we have enough after dropna
    cutoff = (_now_hkt() - timedelta(days=75)).strftime("%Y-%m-%d")
    df = query(
        f"SELECT ticker, date, close FROM daily_prices "
        f"WHERE ticker IN ({placeholders}) AND date >= ? ORDER BY ticker, date",
        tickers + [cutoff],
    )
    if df.empty:
        return pd.DataFrame(columns=["ticker", "hv30"])
    rows = []
    for tkr, grp in df.groupby("ticker"):
        grp = grp.sort_values("date")
        if len(grp) < 10:
            rows.append({"ticker": tkr, "hv30": None})
            continue
        log_ret = grp["close"].pct_change().dropna()
        # Use last 30 observations
        hv = log_ret.tail(30).std() * (252 ** 0.5) * 100
        rows.append({"ticker": tkr, "hv30": round(hv, 1) if pd.notna(hv) else None})
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
# APP DEFINITION
# ══════════════════════════════════════════════════════════════════════════════

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY, dbc.icons.BOOTSTRAP],
    title="Semi Industry Tracker",
    suppress_callback_exceptions=True,
)

# Expose the underlying Flask server so gunicorn can find it:
#   gunicorn dashboard:server --bind 0.0.0.0:$PORT
server = app.server

app.layout = dbc.Container(fluid=True, style={"background": BG, "minHeight": "100vh", "padding": "0"}, children=[

    # ── Top nav bar ───────────────────────────────────────────────────────────
    dbc.Navbar(
        dbc.Container(fluid=True, children=[
            html.Span("⚡ Semiconductor Industry Tracker", style={
                "color": TEXT, "fontSize": "17px", "fontWeight": "700", "letterSpacing": "0.3px"
            }),
            html.Div([
                html.Span("Last crawl: ", style={"color": SUBTEXT, "fontSize": "12px"}),
                html.Span(id="last-crawl-time", style={"color": ACCENT, "fontSize": "12px"}),
                # ── Reload confirmation stamp (updates on every manual refresh) ─
                html.Span(id="reload-stamp", style={
                    "color": GREEN, "fontSize": "11px", "marginLeft": "12px",
                    "opacity": "0.8",
                }),
                # ── Data-freshness badge (BACKLOG SC-03) ───────────────────
                html.Span(id="data-freshness-badge", style={"marginLeft": "20px"}),
                # ── Crawl-schedule badge (QA F-01) ─────────────────────────
                # Deliberately SEPARATE from the freshness chip beside it. That
                # one answers "is the data current?", this one answers "are we
                # still crawling?" — different causes, different fixes, and a
                # publisher going quiet must not look like our scheduler dying.
                html.Span(id="crawl-status-badge", style={"marginLeft": "10px"}),
                # ── IBKR connection badge ──────────────────────────────────
                html.Span(id="ibkr-status-badge", style={"marginLeft": "10px"}),
                dbc.Button("🔄 Reload Charts", id="btn-refresh", color="primary",
                           size="sm", style={"marginLeft": "16px", "fontSize": "12px"},
                           title="Re-read data from the database and redraw all charts"),
                dbc.Button("⚡ Run Crawl", id="btn-run-crawl", color="warning",
                           size="sm", style={"marginLeft": "8px", "fontSize": "12px"},
                           title="Fetch fresh market data from Yahoo Finance (takes ~2 min)"),
                # ── Full-dataset export ────────────────────────────────────
                # Plain anchor, not a Dash callback: the browser streams the
                # file straight from /api/export-xlsx, so the workbook is never
                # base64-inflated through a callback response.
                dbc.Button("⬇️ Download Data", id="btn-download-data",
                           href="/api/export-xlsx", external_link=True,
                           color="success", size="sm",
                           style={"marginLeft": "8px", "fontSize": "12px"},
                           title="Download the full accumulated dataset "
                                 "(all tables, multi-sheet Excel workbook)"),
            ], style={"display": "flex", "alignItems": "center", "gap": "0"}),
            # ── Run-crawl status toast ────────────────────────────────────────
            dbc.Toast(
                id="crawl-toast",
                header="Crawl Status",
                is_open=False,
                dismissable=True,
                icon="success",
                style={"position": "fixed", "top": 66, "right": 16, "width": 320, "zIndex": 9999},
            ),
        ]),
        color=BG2, dark=True,
        style={"borderBottom": f"1px solid #30363d", "padding": "10px 20px"}
    ),

    # ── Ephemeral-storage warning (renders only when the guard tripped) ───────
    _volume_banner(),

    dbc.Row(style={"margin": "0"}, children=[

        # ── Sidebar ───────────────────────────────────────────────────────────
        dbc.Col(width=2, style={"background": BG2, "borderRight": f"1px solid #30363d",
                                 "padding": "16px", "minHeight": "calc(100vh - 56px)",
                                 "overflowY": "auto"}, children=[

            _section_title("Date Range"),
            dcc.DatePickerRange(
                id="date-range",
                start_date=(_now_hkt() - timedelta(days=365)).strftime("%Y-%m-%d"),
                end_date=_now_hkt().strftime("%Y-%m-%d"),
                display_format="DD MMM YYYY",
                style={"fontSize": "12px", "width": "100%"},
            ),
            html.Hr(style={"borderColor": "#30363d", "margin": "12px 0"}),

            ticker_checklist(
                "Semi Companies",
                SEMI_COMPANIES,
                ["NVDA", "AMD", "ASML", "AVGO", "QCOM", "MU", "TSM", "INTC"],
            ),
            ticker_checklist("Semi ETFs",   SEMI_ETFS,   ["SMH", "SOXX"]),
            ticker_checklist("Macro / Other",
                ["TQQQ", "QQQ", "VIX", "USD", "10YTreasury", "Gold", "BTC", "ETH"],
                ["VIX", "10YTreasury", "Gold"],
            ),
            ticker_checklist("Tech / Mixed",
                ["MSFT", "GOOG", "META", "AAPL", "TSLA", "AMZN", "ORCL", "BRK.A"],
                [],
            ),

            html.Hr(style={"borderColor": "#30363d", "margin": "12px 0"}),

            dbc.Button("Select All", id="btn-select-all", color="secondary",
                       outline=True, size="sm", style={"width": "100%", "marginBottom": "6px", "fontSize": "12px"}),
            dbc.Button("Clear All",  id="btn-clear-all",  color="secondary",
                       outline=True, size="sm", style={"width": "100%", "fontSize": "12px"}),

            # Hidden store for selected tickers
            dcc.Store(id="selected-tickers", data=[
                "NVDA", "AMD", "ASML", "AVGO", "QCOM", "MU", "TSM", "INTC",
                "SMH", "SOXX", "VIX", "10YTreasury"
            ]),
        ]),

        # ── Main content ──────────────────────────────────────────────────────
        dbc.Col(style={"padding": "16px", "overflowY": "auto",
                       "maxHeight": "calc(100vh - 56px)"}, children=[

            dbc.Tabs(id="main-tabs", active_tab="tab-overview", children=[
                dbc.Tab(label="📊 Overview",       tab_id="tab-overview"),
                dbc.Tab(label="💰 Financials",     tab_id="tab-financials"),
                dbc.Tab(label="🌡️ Sentiment",      tab_id="tab-sentiment"),
                dbc.Tab(label="🔄 Cycles",         tab_id="tab-cycles"),
                dbc.Tab(label="⚖️ Period Compare", tab_id="tab-compare"),
                dbc.Tab(label="🏭 Supply Chain",   tab_id="tab-supplychain"),
            ], style={"marginBottom": "16px",
                      "--bs-nav-tabs-border-color": "#30363d"}),

            dcc.Loading(
                id="tab-loading",
                type="circle",
                color=ACCENT,
                children=html.Div(id="tab-content"),
            ),
        ]),
    ]),

    # Interval for auto-refresh status
    dcc.Interval(id="status-interval", interval=30_000, n_intervals=0),
    # Store for crawl-job state (polled by status-interval)
    dcc.Store(id="crawl-job-store", data={"running": False, "message": ""}),
])


# ══════════════════════════════════════════════════════════════════════════════
# CALLBACKS — ticker selection sync
# ══════════════════════════════════════════════════════════════════════════════

@app.callback(
    Output("selected-tickers", "data"),
    Input("chk-semi-companies",  "value"),
    Input("chk-semi-etfs",       "value"),
    Input("chk-macro--other",    "value"),
    Input("chk-tech--mixed",     "value"),
    prevent_initial_call=False,
)
def sync_tickers(semi, etfs, macro, tech):
    result = []
    for lst in [semi, etfs, macro, tech]:
        if lst:
            result.extend(lst)
    return result


@app.callback(
    Output("chk-semi-companies", "value"),
    Output("chk-semi-etfs",      "value"),
    Output("chk-macro--other",   "value"),
    Output("chk-tech--mixed",    "value"),
    Input("btn-select-all",      "n_clicks"),
    Input("btn-clear-all",       "n_clicks"),
    prevent_initial_call=True,
)
def select_clear_all(select_clicks, clear_clicks):
    from dash import ctx
    if ctx.triggered_id == "btn-select-all":
        return (
            SEMI_COMPANIES,
            SEMI_ETFS,
            ["TQQQ", "QQQ", "VIX", "USD", "10YTreasury", "Gold", "BTC", "ETH"],
            ["MSFT", "GOOG", "META", "AAPL", "TSLA", "AMZN", "ORCL", "BRK.A"],
        )
    # Clear All
    return [], [], [], []


@app.callback(
    Output("last-crawl-time", "children"),
    Input("status-interval", "n_intervals"),
    Input("btn-refresh", "n_clicks"),
)
def update_crawl_time(*_):
    return last_crawl_time()


@app.callback(
    Output("reload-stamp", "children"),
    Input("btn-refresh", "n_clicks"),
    prevent_initial_call=True,
)
def show_reload_stamp(_):
    """Show 'Reloaded HH:MM HKT' next to Last Crawl after each manual refresh."""
    return f"✓ Reloaded {_now_hkt().strftime('%H:%M')} HKT"


@app.callback(
    Output("crawl-toast",     "children"),
    Output("crawl-toast",     "is_open"),
    Output("crawl-toast",     "icon"),
    Output("last-crawl-time", "children", allow_duplicate=True),
    Input("btn-run-crawl",    "n_clicks"),
    prevent_initial_call=True,
)
def trigger_crawl(_):
    """Start a background crawl and notify the user."""
    import threading, subprocess, sys, os as _os
    from dash import no_update

    # Check if already running
    if _crawl_running.get("active"):
        return "Crawl already in progress — please wait.", True, "warning", no_update

    def _run_crawl():
        _crawl_running["active"] = True
        try:
            script_dir = _os.path.dirname(_os.path.abspath(__file__))
            py = sys.executable
            subprocess.run([py, _os.path.join(script_dir, "crawler.py"), "--quick"],
                           timeout=360, cwd=script_dir)
            subprocess.run([py, _os.path.join(script_dir, "supply_chain_crawler.py")],
                           timeout=360, cwd=script_dir)
        except Exception:
            pass
        finally:
            _crawl_running["active"] = False

    threading.Thread(target=_run_crawl, daemon=True).start()
    return (
        "Crawl started — prices & supply-chain data refreshing (~2 min). "
        "Last Crawl timestamp will update when complete.",
        True, "primary",
        last_crawl_time(),
    )


# Module-level dict to track crawl state across gunicorn requests
_crawl_running: dict = {"active": False}



@app.callback(
    Output("crawl-status-badge", "children"),
    Input("status-interval", "n_intervals"),
)
def update_crawl_badge(_):
    """
    Navbar chip reporting whether the crawlers are still running (QA F-01).

    Reads the same job_report() the scheduler uses to decide what to run, so
    the badge and the schedule cannot drift apart — the rule already learned for
    _stale_sources() (§6.5) and _iv_source_meta() (§9 IV-01).

    Same navbar-level Output / status-interval pattern as the two chips beside
    it; never nested inside tab-content (§7 rules 3 & 4).
    """
    def _chip(icon, text, colour, tip):
        return html.Span(
            [html.Span(icon, style={"marginRight": "4px"}), text],
            style={"fontSize": "11px", "color": colour,
                   "border": f"1px solid {colour}", "borderRadius": "4px",
                   "padding": "2px 8px"},
            title=tip,
        )

    try:
        conn = get_conn()
        rep  = job_report(conn)
        conn.close()
    except Exception as exc:                       # noqa: BLE001
        return _chip("⚠️", "crawl: error", YELLOW, f"Heartbeat check failed: {exc}")

    late = overdue_jobs(rep)
    lines = []
    for j, e in rep.items():
        age = "never" if e["never_run"] else f"{e['age_hours']:.0f}h ago"
        lines.append(f"{j}: {age} (every {e['interval_hours']}h) — {e['label']}")
    if not scheduler_enabled():
        lines.append("Watchdog DISABLED via SEMI_DISABLE_SCHEDULER=1 — "
                     "crawls must be driven externally.")
    tip = "\n".join(lines)

    if late:
        return _chip("🔴", f"crawl: {len(late)} overdue", RED,
                     "These jobs have not succeeded within their window:\n"
                     + "\n".join(f"  · {j}" for j in late) + "\n\n" + tip)
    if not scheduler_enabled():
        return _chip("🟡", "crawl: external", YELLOW, tip)
    return _chip("🟢", "crawl: on schedule", GREEN, tip)


@app.callback(
    Output("data-freshness-badge", "children"),
    Input("status-interval", "n_intervals"),
)
def update_freshness_badge(_):
    """
    Navbar chip naming every source past its SLA (BACKLOG SC-03).

    Deliberately mirrors the IBKR badge: navbar-level Output, driven by
    status-interval, never nested inside tab-content (CLAUDE.md §7 rules 3 & 4).
    The point is that a source going quiet has to cost someone a glance — three
    outages ran for months because nothing on screen changed when data stopped.
    """
    try:
        report = _freshness_report()
        stale  = _stale_sources(report)
    except Exception as exc:
        return html.Span(
            [html.Span("⚠️", style={"marginRight": "4px"}), "freshness: error"],
            style={"fontSize": "11px", "color": YELLOW,
                   "border": f"1px solid {YELLOW}", "borderRadius": "4px",
                   "padding": "2px 8px"},
            title=f"Freshness check failed: {exc}",
        )

    # Shape flags are advisory and never override a freshness breach: a stale
    # source is a fact, a suspicious shape is a prompt to look. Red wins over
    # amber so the badge keeps meaning one thing (BACKLOG SC-12).
    try:
        cons = _consistency_report()
    except Exception:
        cons = {"flags": []}
    cflags = cons.get("flags", [])

    if not stale and not cflags:
        return html.Span(
            [html.Span("🟢", style={"marginRight": "4px"}), "data: fresh"],
            style={"fontSize": "11px", "color": GREEN,
                   "border": f"1px solid {GREEN}", "borderRadius": "4px",
                   "padding": "2px 8px"},
            title=(f"Every tracked source is within its freshness SLA, and "
                   f"{cons.get('checked', 0)} series passed the shape checks."),
        )

    if not stale:
        detail = "\n".join(f"{f['series']} [{f['rule']}]: {f['detail']}" for f in cflags)
        return html.Span(
            [html.Span("🟡", style={"marginRight": "4px"}),
             f"{len(cflags)} shape flag{'s' if len(cflags) > 1 else ''}"],
            style={"fontSize": "11px", "color": YELLOW,
                   "border": f"1px solid {YELLOW}", "borderRadius": "4px",
                   "padding": "2px 8px", "cursor": "help"},
            title=("Every source is fresh, but these series look implausible — "
                   "verify against the publisher before trusting them:\n\n" + detail),
        )

    def _why(k):
        r = report[k]
        if r.get("empty"):
            return (f"{k}: {r['null_price_pct']}% of rows have no price "
                    f"— scraper writing empty rows")
        return (f"{k}: {r['max_period']} — {r['days_stale']}d old "
                f"(SLA {r['sla_days']}d)")

    detail = "\n".join(_why(k) for k in stale)
    return html.Span(
        [html.Span("🔴", style={"marginRight": "4px"}),
         f"{len(stale)} stale/empty source{'s' if len(stale) > 1 else ''}"],
        style={"fontSize": "11px", "color": RED,
               "border": f"1px solid {RED}", "borderRadius": "4px",
               "padding": "2px 8px", "cursor": "help"},
        title="Sources past their freshness SLA — see /api/db-stats:\n\n" + detail,
    )


@app.callback(
    Output("ibkr-status-badge", "children"),
    Input("status-interval", "n_intervals"),
)
def update_ibkr_badge(_):
    """Navbar chip reporting whether an IV series EXISTS and where it came from.

    Previously this reported IBKR *enablement*, which was the wrong question: it
    read ⚫ disabled while a perfectly good derived IV series was populating the
    Sentiment tab. A status chip must describe the data, not one possible
    producer of it.
    """
    latest = query(
        "SELECT source, MAX(snapshot_date) AS d, COUNT(DISTINCT ticker) AS n "
        "FROM options_iv "
        "WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM options_iv) "
        "GROUP BY source ORDER BY n DESC"
    )

    if latest.empty:
        return html.Span(
            [html.Span("⚫", style={"marginRight": "4px"}), "IV: none"],
            style={"fontSize": "11px", "color": SUBTEXT,
                   "border": "1px solid #30363d", "borderRadius": "4px",
                   "padding": "2px 8px", "cursor": "help"},
            title=("No rows in options_iv.\n"
                   "Run: python3 iv_crawler.py   (no broker or subscription needed)"),
        )

    short, desc, published = _iv_source_meta(latest.iloc[0]["source"])
    tickers = int(latest["n"].sum())
    as_of = latest.iloc[0]["d"]
    detail = "\n".join(
        "%s — %d tickers" % (_iv_source_meta(r["source"])[1], int(r["n"]))
        for _, r in latest.iterrows()
    )
    # Derived series get YELLOW, published get GREEN. Same convention as the
    # HV30 fallback badge: colour encodes provenance strength, not freshness.
    colour = GREEN if published else YELLOW
    return html.Span(
        [html.Span("🟢" if published else "🟡", style={"marginRight": "4px"}),
         "IV: %s (%d)" % (short, tickers)],
        style={"fontSize": "11px", "color": colour,
               "border": f"1px solid {colour}", "borderRadius": "4px",
               "padding": "2px 8px", "cursor": "help"},
        title="As of %s\n%s\n\n%s" % (
            as_of, detail,
            "Published index." if published
            else "✳ Derived metric — our own construction, not a published index."),
    )


# ══════════════════════════════════════════════════════════════════════════════
# CALLBACKS — tab content
# ══════════════════════════════════════════════════════════════════════════════

@app.callback(
    Output("tab-content", "children"),
    Input("main-tabs",        "active_tab"),
    Input("selected-tickers", "data"),
    Input("date-range",       "start_date"),
    Input("date-range",       "end_date"),
    Input("btn-refresh",      "n_clicks"),
)
def render_tab(active_tab, tickers, start_date, end_date, _refresh):
    if not tickers:
        return _card(html.P("Select at least one ticker from the sidebar.", style={"color": SUBTEXT}))

    start = start_date[:10] if start_date else "2023-01-01"
    end   = end_date[:10]   if end_date   else _now_hkt().strftime("%Y-%m-%d")

    _TAB_MAP = {
        "tab-overview":     lambda: tab_overview(tickers, start, end),
        "tab-financials":   lambda: tab_financials(tickers),
        "tab-sentiment":    lambda: tab_sentiment(tickers),
        "tab-cycles":       lambda: tab_cycles(tickers),
        "tab-compare":      lambda: tab_compare(tickers),
        "tab-supplychain":  lambda: tab_supply_chain(),
    }

    fn = _TAB_MAP.get(active_tab)
    if fn is None:
        return html.Div("Select a tab.")

    try:
        return fn()
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        return _card([
            _section_title("⚠️ Tab Error"),
            html.P(f"{type(exc).__name__}: {exc}",
                   style={"color": RED, "fontWeight": "600", "marginBottom": "8px"}),
            html.Pre(tb, style={"color": SUBTEXT, "fontSize": "11px",
                                "overflowX": "auto", "whiteSpace": "pre-wrap"}),
        ])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════

def tab_overview(tickers, start, end):
    prices = price_data(tickers, start, end)
    sent   = sentiment_data(tickers)

    if prices.empty:
        return _card(html.P("No price data found. Run crawler.py first.", style={"color": RED}))

    # ── KPI cards (latest price + 1m performance) ─────────────────────────
    kpi_cards = []
    for tkr in tickers:
        df = prices[prices["ticker"] == tkr].sort_values("date")
        if df.empty:
            continue
        latest = df["close"].iloc[-1]
        p1m_row = sent[sent["ticker"] == tkr]["perf_1m"].values if not sent.empty else []
        p1m  = p1m_row[0] if len(p1m_row) > 0 and p1m_row[0] is not None else None
        delta = (f"+{p1m:.1f}%" if p1m and p1m >= 0 else f"{p1m:.1f}%") if p1m is not None else ""
        col   = GREEN if p1m and p1m >= 0 else RED if p1m and p1m < 0 else TEXT
        kpi_cards.append(
            dbc.Col(width=2, children=_card(_kpi(tkr, f"${latest:,.2f}", delta, col),
                                            style={"textAlign": "center"}))
        )

    # ── Merged Price + Volume subplot (shared X axis, auto-synced) ───────────
    # Always fetch 5 Y so 1Y / 3Y / 5Y rangeselector buttons have full data.
    _price_start_5y = (_now_hkt() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")
    prices_5y = price_data(tickers, _price_start_5y, end)

    fig_price = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.68, 0.32],
        subplot_titles=("Price Performance (Base=100 at range start)", "Trading Volume"),
    )

    # Row 1 — normalised price lines
    for i, tkr in enumerate(tickers):
        df = prices_5y[prices_5y["ticker"] == tkr].sort_values("date")
        if df.empty or len(df) < 2:
            continue
        base = df["close"].iloc[0]
        if base == 0:
            continue
        norm = df["close"] / base * 100
        fig_price.add_trace(go.Scatter(
            x=df["date"], y=norm, name=tkr, mode="lines",
            line=dict(width=2, color=CHART_COLORS[i % len(CHART_COLORS)]),
            hovertemplate=f"<b>{tkr}</b><br>Date: %{{x}}<br>Indexed: %{{y:.1f}}<extra></extra>",
        ), row=1, col=1)

    # Row 2 — volume bars (full 5 Y so they sync with the price range)
    for i, tkr in enumerate(tickers[:8]):   # cap at 8 for readability
        df = prices_5y[prices_5y["ticker"] == tkr].sort_values("date")
        if df.empty:
            continue
        fig_price.add_trace(go.Bar(
            x=df["date"], y=df["volume"], name=tkr,
            marker_color=CHART_COLORS[i % len(CHART_COLORS)],
            showlegend=False,   # legend already shown by price trace above
            hovertemplate=f"<b>{tkr}</b><br>%{{x}}<br>Vol: %{{y:,.0f}}<extra></extra>",
        ), row=2, col=1)

    # Default view: last 1 year; rangeselector drives both rows via shared xaxis
    _1y_ago = (_now_hkt() - timedelta(days=365)).strftime("%Y-%m-%d")

    _base_layout = PLOTLY_TEMPLATE["layout"].copy()
    fig_price.update_layout(
        **_base_layout,
        height=620,
        hovermode="x unified",
        barmode="overlay",
        bargap=0.1,
    )
    # Shared x-axis lives on xaxis (row 1); xaxis2 (row 2) inherits the range
    fig_price.update_xaxes(
        range=[_1y_ago, end],
        rangeselector=_time_rangeselector(active_index=0),
        rangeslider=dict(visible=False),
        type="date",
        row=1, col=1,
    )
    # Subplot titles already occupy the top strip — keep the legend on the right
    # here and just open the top margin for the buttons.
    _apply_rangeselector_layout(fig_price, legend_bottom=False, extra_height=40)
    fig_price.update_yaxes(title_text="Index (Base=100)", row=1, col=1,
                            gridcolor="#21262d", color=TEXT)
    fig_price.update_yaxes(title_text="Volume", row=2, col=1,
                            gridcolor="#21262d", color=TEXT)
    # Style the subplot title annotations to match the dark theme
    for ann in fig_price.layout.annotations:
        ann.update(font=dict(color=TEXT, size=13))

    # ── Performance heatmap — with sidebar category labels ───────────────
    # Uses module-level _CAT_ORDER, _SHORT_CAT, _ticker_label, _cat_rank
    if not sent.empty:
        cols_perf = ["perf_5d", "perf_10d", "perf_1m"]
        hm_data = sent[["ticker"] + cols_perf].set_index("ticker")
        hm_data = hm_data.apply(pd.to_numeric, errors="coerce")

        # Sort rows by category order so same-group tickers appear together
        sorted_idx = sorted(hm_data.index, key=lambda t: _cat_rank.get(t, (99, 99)))
        hm_data = hm_data.loc[sorted_idx]

        y_labels  = [_ticker_label(t) for t in hm_data.index]

        fig_hm = go.Figure(go.Heatmap(
            z=hm_data.values,
            x=["5-Day %", "10-Day %", "1-Month %"],
            y=y_labels,
            colorscale=[[0, RED], [0.5, BG3], [1, GREEN]],
            zmid=0,
            text=hm_data.round(1).astype(str).values + "%",
            texttemplate="%{text}",
            hovertemplate="<b>%{y}</b><br>%{x}: %{z:.2f}%<extra></extra>",
        ))
        fig_hm.update_layout(**PLOTLY_TEMPLATE["layout"],
                              title="Return Heatmap",
                              height=max(280, len(tickers) * 30))
        heatmap_section = dcc.Graph(figure=fig_hm, config={"displayModeBar": False})
    else:
        heatmap_section = html.P("Sentiment data not yet available.", style={"color": SUBTEXT})

    return html.Div([
        dbc.Row(kpi_cards, className="g-2", style={"marginBottom": "12px"}),
        _card(dcc.Graph(figure=fig_price, config={"displayModeBar": True})),
        _card(heatmap_section),
        _card(_source_footer("Yahoo Finance / yfinance",
                              "OHLCV daily price data and 1-month performance. "
                              "Prices are as-of market close.")),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — FINANCIALS
# ══════════════════════════════════════════════════════════════════════════════

def _valuation_snapshot_panel(tickers) -> html.Div:
    """
    Point-in-time valuation, sourced from ticker_valuation_history (QA F-02).

    Every column here is stamped with the date it was OBSERVED. That stamp is
    the whole point of the panel: the previous design put these same numbers in
    a table headed by a fiscal quarter, which silently asserted a history the
    free feed cannot supply.

    The series starts empty and fills forward one row per crawl. When it is
    empty the panel says so and says why, rather than rendering nothing — the
    IV-03 principle: an empty column that explains itself is honest, a filled
    one built from a proxy is not.
    """
    vdf = valuation_snapshot_data(list(tickers))

    if vdf.empty:
        return _card([
            _section_title("Valuation Snapshot"),
            html.Div(
                "No valuation snapshot recorded yet. This series is observed, "
                "not historical — it starts on the first crawl after this panel "
                "shipped and gains one row per ticker per crawl. It cannot be "
                "backfilled: the free feed exposes no historical trailing P/E "
                "or market cap, and reconstructing one would restate today's "
                "multiple as the past (the defect this panel replaced).",
                style={"color": SUBTEXT, "fontSize": "13px", "lineHeight": "1.6"},
            ),
            _source_footer(
                "Yahoo Finance (yfinance .info snapshot)",
                "Observed values only — no point-in-time history available.",
            ),
        ])

    show = vdf.copy()
    as_of_vals = sorted(set(show["snapshot_date"].dropna().astype(str)))
    as_of_label = as_of_vals[-1] if len(as_of_vals) == 1 else (
        f"{as_of_vals[0]} → {as_of_vals[-1]}" if as_of_vals else "—"
    )

    def _fmt_cap(x):
        return f"${x/1e9:,.1f}B" if pd.notna(x) else "—"

    def _fmt_num(x):
        return f"{x:,.2f}" if pd.notna(x) else "—"

    out = pd.DataFrame({
        "ticker":        show["ticker"],
        "snapshot_date": show["snapshot_date"],
        "close_price":   show["close_price"].map(_fmt_num),
        "market_cap":    show["market_cap"].map(_fmt_cap),
        "trailing_pe":   show["trailing_pe"].map(_fmt_num),
        "forward_pe":    show["forward_pe"].map(_fmt_num),
        "trailing_eps":  show["trailing_eps"].map(_fmt_num),
        "price_to_book": show["price_to_book"].map(_fmt_num),
    })

    labels = {
        "ticker":        "Ticker",
        "snapshot_date": "Observed On",
        "close_price":   "Price",
        "market_cap":    "Market Cap",
        "trailing_pe":   "P/E (TTM)",
        "forward_pe":    "P/E (Fwd, est.)",
        "trailing_eps":  "EPS (TTM)",
        "price_to_book": "P/B",
    }

    # Per-row staleness: the snapshot is keyed to the last trading date, so
    # anything more than a few sessions old means the crawl stopped running.
    try:
        newest = pd.to_datetime(max(as_of_vals))
        age_days = (pd.Timestamp(_now_hkt()).tz_localize(None) - newest).days
    except Exception:
        age_days = None

    stale_note = None
    if age_days is not None and age_days > 4:
        stale_note = html.Div(
            f"⚠️  Newest snapshot is {age_days} days old. These are observed "
            f"values from {as_of_label} — not current quotes. Do not read them "
            f"as live pricing.",
            style={"color": YELLOW, "fontSize": "12px", "marginBottom": "8px",
                   "padding": "8px 10px", "border": f"1px solid {YELLOW}",
                   "borderRadius": "4px"},
        )

    tbl = dash_table.DataTable(
        data=out.to_dict("records"),
        columns=[{"name": labels[c], "id": c} for c in out.columns],
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": BG3, "color": TEXT, "border": "1px solid #30363d",
                    "fontSize": "13px", "padding": "6px 10px"},
        style_header={"backgroundColor": BG2, "color": ACCENT, "fontWeight": "600",
                      "border": "1px solid #30363d"},
        style_data_conditional=[{"if": {"row_index": "odd"}, "backgroundColor": BG2}],
        page_size=20,
    )

    return _card([
        _section_title(f"Valuation Snapshot  ·  Observed {as_of_label}"),
        stale_note if stale_note else html.Div(),
        html.Div(
            "Point-in-time only. Each figure describes the date in the "
            "“Observed On” column, not any fiscal quarter above — trailing P/E, "
            "market cap and TTM EPS have no historical series in this feed. "
            "Forward P/E is the vendor's consensus-derived estimate, not a "
            "reported figure.",
            style={"color": SUBTEXT, "fontSize": "12px", "marginBottom": "10px"},
        ),
        tbl,
        _source_footer(
            "Yahoo Finance (yfinance .info snapshot)",
            "Observed, not point-in-time history. Vendor-normalised; not primary filings.",
        ),
    ])


def tab_financials(tickers):
    """Render the Financials tab (all available data, up to 5 years)."""
    df = financials_data(tickers)
    if df.empty:
        return _card(html.P("No quarterly financial data. Run crawler.py — financials are only available for listed companies.", style={"color": SUBTEXT}))

    df["period_end"] = pd.to_datetime(df["period_end"])
    df = df.sort_values("period_end")

    # Show up to 5 years of data.
    _cutoff_5y = pd.Timestamp(_now_hkt() - timedelta(days=365 * 5))
    df_view = df[df["period_end"] >= _cutoff_5y]

    # Quarterly label used as categorical x-axis — evenly-spaced bars regardless
    # of how many tickers are grouped.
    def _qlabel(ts) -> str:
        return f"{ts.year}-Q{ts.quarter}"

    def metric_chart(col: str, title: str, pct: bool = False):
        fig = go.Figure()
        for i, tkr in enumerate(tickers):
            sub = df_view[df_view["ticker"] == tkr].dropna(subset=[col])
            if sub.empty:
                continue
            vals  = sub[col] / 1e9 if not pct else sub[col]
            xlbls = sub["period_end"].apply(_qlabel)
            fig.add_trace(go.Bar(
                x=xlbls, y=vals, name=tkr,
                marker_color=CHART_COLORS[i % len(CHART_COLORS)],
                hovertemplate=f"<b>{tkr}</b><br>%{{x}}<br>{title}: %{{y:{',.1f' if pct else ',.2f'}}}"
                              + ("%" if pct else "B") + "<extra></extra>",
            ))
        suffix = "%" if pct else " (USD Billions)"
        fig.update_layout(
            **PLOTLY_TEMPLATE["layout"],
            title=title + suffix, barmode="group",
            height=320, yaxis_title=title,
        )
        return dcc.Graph(figure=fig, config={"displayModeBar": False})

    def trend_chart(col: str, title: str, pct: bool = False):
        fig = go.Figure()
        for i, tkr in enumerate(tickers):
            sub = df_view[df_view["ticker"] == tkr].dropna(subset=[col])
            if sub.empty:
                continue
            xlbls = sub["period_end"].apply(_qlabel)
            fig.add_trace(go.Scatter(
                x=xlbls, y=sub[col], name=tkr, mode="lines+markers",
                line=dict(width=2, color=CHART_COLORS[i % len(CHART_COLORS)]),
                hovertemplate=f"<b>{tkr}</b><br>%{{x}}<br>{title}: %{{y:.2f}}{'%' if pct else ''}<extra></extra>",
            ))
        fig.update_layout(
            **PLOTLY_TEMPLATE["layout"],
            title=title + (" (%)" if pct else ""),
            height=280,
        )
        return dcc.Graph(figure=fig, config={"displayModeBar": False})

    # Latest financials table
    #
    # pe_ratio and market_cap are deliberately ABSENT (QA finding F-02). They
    # are properties of the observation date, not of period_end; the crawler now
    # writes NULL here and the real values live in the Valuation Snapshot panel
    # below, stamped with the date they were actually observed. Do not re-add
    # them to this table — a snapshot in a column headed by a fiscal quarter is
    # the defect, regardless of whether the newest row happens to be correct.
    latest_cols = ["ticker", "period_end", "revenue", "gross_margin",
                   "op_margin", "net_margin", "eps"]
    latest = df_view.sort_values("period_end").groupby("ticker").last().reset_index()
    tbl_data = latest[[c for c in latest_cols if c in latest.columns]].copy()
    for col in ["revenue"]:
        if col in tbl_data:
            tbl_data[col] = (tbl_data[col] / 1e9).map(lambda x: f"${x:,.1f}B" if pd.notna(x) else "—")
    for col in ["gross_margin", "op_margin", "net_margin"]:
        if col in tbl_data:
            tbl_data[col] = tbl_data[col].map(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
    for col in ["eps"]:
        if col in tbl_data:
            tbl_data[col] = tbl_data[col].map(lambda x: f"{x:.2f}" if pd.notna(x) else "—")
    if "period_end" in tbl_data:
        tbl_data["period_end"] = tbl_data["period_end"].dt.strftime("%Y-%m-%d")

    _FIN_COL_LABELS = {
        "period_end":   "Period End",
        "gross_margin": "Gross Margin",
        "op_margin":    "Operating Margin",
        "net_margin":   "Net Margin",
        "eps":          "EPS (Diluted, Quarter)",
    }

    tbl = dash_table.DataTable(
        data=tbl_data.to_dict("records"),
        columns=[{"name": _FIN_COL_LABELS.get(c, c.replace("_", " ").title()), "id": c}
                 for c in tbl_data.columns],
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": BG3, "color": TEXT, "border": "1px solid #30363d",
                    "fontSize": "13px", "padding": "6px 10px"},
        style_header={"backgroundColor": BG2, "color": ACCENT, "fontWeight": "600",
                      "border": "1px solid #30363d"},
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": BG2},
        ],
        page_size=20,
    )

    return html.Div([
        _card([_section_title("Latest Quarter Summary"), tbl]),
        _valuation_snapshot_panel(tickers),
        dbc.Row([
            dbc.Col(_card(metric_chart("revenue",        "Revenue")),        width=6),
            dbc.Col(_card(metric_chart("gross_profit",   "Gross Profit")),   width=6),
        ]),
        dbc.Row([
            dbc.Col(_card(metric_chart("operating_profit", "Operating Profit")), width=6),
            dbc.Col(_card(metric_chart("rd_expense",       "R&D Expense")),     width=6),
        ]),
        dbc.Row([
            dbc.Col(_card(metric_chart("net_profit",  "Net Profit")),  width=6),
            dbc.Col(_card(trend_chart("gross_margin", "Gross Margin", pct=True)), width=6),
        ]),
        dbc.Row([
            dbc.Col(_card(trend_chart("op_margin",  "Operating Margin", pct=True)), width=4),
            dbc.Col(_card(trend_chart("net_margin", "Net Margin",       pct=True)), width=4),
            dbc.Col(_card(trend_chart("rd_to_revenue", "R&D / Revenue", pct=True)), width=4),
        ]),
        dbc.Row([
            dbc.Col(_card(trend_chart("ar_turnover",        "Accounts Receivable Turnover")), width=6),
            dbc.Col(_card(trend_chart("inventory_turnover", "Inventory Turnover")),           width=6),
        ]),
        _card(_source_footer("Yahoo Finance / yfinance",
                              f"Quarterly financials sourced from SEC EDGAR filings via yfinance. "
                              f"Showing up to 5 years of quarterly data. "
                              f"Revenue, profit, margins, R&D, AR and inventory turnover ratios.")),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — MARKET SENTIMENT
# ══════════════════════════════════════════════════════════════════════════════

# ── IV provenance labelling ──────────────────────────────────────────────────
# options_iv is written by TWO producers with identical schemas (iv_crawler.py
# and the IBKR relay), distinguished only by `source`. Nothing in the UI may
# hardcode a producer name — that is how the old "IBKR Real-Time" titles ended
# up sitting above derived Yahoo numbers.
_IV_SOURCE_META = {
    # source-column prefix : (short badge label, long description, is_published)
    "derived-yfinance-atm30": (
        "IV30*",
        "Derived — 30d ATM constant-maturity interpolation over Yahoo option chains",
        False,
    ),
    "Deribit DVOL": (
        "DVOL",
        "Deribit DVOL 30-day implied-volatility index (published)",
        True,
    ),
    "IBKR": (
        "IBKR",
        "Interactive Brokers real-time IV (relayed from local TWS/Gateway)",
        True,
    ),
    "relay": (
        "IBKR",
        "Interactive Brokers real-time IV (relayed from local TWS/Gateway)",
        True,
    ),
}


def _iv_source_meta(source_value):
    """Map an options_iv.source string to (short label, description, is_published).

    Matched by PREFIX, because iv_crawler.py appends a proxy suffix — e.g.
    'derived-yfinance-atm30 (proxy:GLD)' for Gold, whose IV is really GLD's.
    Unknown values fall through to the raw string rather than being silently
    relabelled as something recognised: mislabelling a source is the §8
    violation this whole helper exists to prevent.
    """
    if not isinstance(source_value, str) or not source_value:
        return ("IV", "Unlabelled source", False)
    for prefix, meta in _IV_SOURCE_META.items():
        if source_value.startswith(prefix):
            return meta
    return (source_value[:12], source_value, False)


def _iv_source_summary(iv_df):
    """One banner line describing every source actually present in the frame."""
    if iv_df is None or iv_df.empty or "source" not in iv_df.columns:
        return "—", False
    metas = [_iv_source_meta(s) for s in sorted(iv_df["source"].dropna().unique())]
    descriptions = []
    for _short, desc, _pub in metas:
        if desc not in descriptions:
            descriptions.append(desc)
    all_published = all(pub for _s, _d, pub in metas) if metas else False
    return " · ".join(descriptions), all_published


def _ibkr_iv_data(tickers: list) -> pd.DataFrame:
    """Load IV snapshots for selected tickers (latest row per ticker).

    Named for IBKR historically; it is now source-agnostic — iv_crawler.py and
    the IBKR relay write the same schema and are distinguished by `source`.
    """
    if not tickers:
        return pd.DataFrame()
    ph = ",".join("?" * len(tickers))
    return query(
        f"""SELECT i.* FROM options_iv i
            INNER JOIN (
                SELECT ticker, MAX(snapshot_date) AS md
                FROM options_iv WHERE ticker IN ({ph}) GROUP BY ticker
            ) latest ON i.ticker=latest.ticker AND i.snapshot_date=latest.md
            ORDER BY i.ticker""",
        tickers,
    )


def _ibkr_iv_history(tickers: list) -> pd.DataFrame:
    """Load full IBKR daily IV history for selected tickers."""
    if not tickers:
        return pd.DataFrame()
    ph = ",".join("?" * len(tickers))
    return query(
        f"SELECT * FROM options_iv_history WHERE ticker IN ({ph}) ORDER BY ticker, date",
        tickers,
    )


def tab_sentiment(tickers):
    sent    = sentiment_data(tickers)
    ibkr_iv = _ibkr_iv_data(tickers)
    has_ibkr = not ibkr_iv.empty

    if sent.empty and not has_ibkr:
        return _card(html.P("No sentiment data found. Run crawler.py first.", style={"color": SUBTEXT}))

    # ── Data source banner ────────────────────────────────────────────────
    iv_src_desc, iv_all_published = _iv_source_summary(ibkr_iv)
    source_note = (
        html.Div([
            html.Span("📡 Options IV source: ", style={"color": SUBTEXT, "fontSize": "12px"}),
            html.Span(
                iv_src_desc if has_ibkr else "Yahoo Finance snapshot IV (crawler.py) / HV30 fallback",
                style={"color": ACCENT if iv_all_published else YELLOW,
                       "fontSize": "12px", "fontWeight": "600"},
            ),
            # An asterisked series is DERIVED, not published. Saying so here is
            # not decoration: it is the §8 zero-hallucination rule applied to a
            # metric this app computes itself (cf. SRC_MODELED in the SC tab).
            html.Span(
                "  ✳ derived metric — our own constant-maturity construction, not a published index"
                if (has_ibkr and not iv_all_published) else
                ("" if has_ibkr else " — run python3 iv_crawler.py to populate a 30d ATM IV series"),
                style={"color": SUBTEXT, "fontSize": "11px"},
            ),
        ], style={"marginBottom": "12px"})
    )

    # ══════════════════════════════════════════════════════════════════════
    # SECTION A — IMPLIED VOLATILITY (IBKR preferred, yfinance fallback)
    # ══════════════════════════════════════════════════════════════════════

    if has_ibkr:
        # ── A1: IV Term Structure grouped bar (current, 1m, 1q, 6m, 1y) ──
        iv_cols   = ["iv_current", "iv_1m_avg", "iv_1q_avg", "iv_6m_avg", "iv_1y_avg"]
        iv_labels = ["Current", "1-Month Avg", "1-Quarter Avg", "6-Month Avg", "1-Year Avg"]
        iv_colors = [ACCENT,     "#74C0FC",     "#51CF66",       YELLOW,       "#CC5DE8"]

        fig_term = go.Figure()
        for col, lbl, col_color in zip(iv_cols, iv_labels, iv_colors):
            sub = ibkr_iv.dropna(subset=[col])
            if sub.empty:
                continue
            fig_term.add_trace(go.Bar(
                name=lbl,
                x=sub["ticker"],
                y=sub[col].round(1),
                marker_color=col_color,
                hovertemplate=f"<b>%{{x}}</b><br>{lbl}: %{{y:.1f}}%<extra></extra>",
            ))
        fig_term.update_layout(
            **PLOTLY_TEMPLATE["layout"],
            title="Options IV — Term Structure per Ticker",
            barmode="group", height=380,
            xaxis_title="Ticker", yaxis_title="Implied Volatility (%)",
        )

        # ── A2: IV vs 52-week range (percentile gauge bars) ───────────────
        pct_df = ibkr_iv.dropna(subset=["iv_pct_vs_1y", "iv_current",
                                         "iv_52w_low", "iv_52w_high"])
        fig_pct = go.Figure()
        if not pct_df.empty:
            fig_pct.add_trace(go.Bar(
                x=pct_df["ticker"],
                y=pct_df["iv_pct_vs_1y"],
                marker_color=[
                    RED    if v > 80 else
                    YELLOW if v > 50 else
                    GREEN
                    for v in pct_df["iv_pct_vs_1y"]
                ],
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "IV Percentile (1Y): %{y:.0f}%<br>"
                    "<extra></extra>"
                ),
                customdata=pct_df[["iv_current", "iv_52w_low", "iv_52w_high"]].values,
            ))
            fig_pct.update_traces(
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "IV Percentile (1Y): %{y:.0f}%<br>"
                    "Current IV: %{customdata[0]:.1f}%<br>"
                    "52W Low: %{customdata[1]:.1f}%  |  52W High: %{customdata[2]:.1f}%"
                    "<extra></extra>"
                )
            )
        fig_pct.add_hline(y=80, line_dash="dot", line_color=RED,    line_width=1,
                          annotation_text="High fear zone (>80th pct)", annotation_font_color=RED)
        fig_pct.add_hline(y=20, line_dash="dot", line_color=GREEN,  line_width=1,
                          annotation_text="Low vol zone (<20th pct)",   annotation_font_color=GREEN)
        fig_pct.update_layout(
            **PLOTLY_TEMPLATE["layout"],
            title="IV Percentile vs 1-Year Range — Where is IV sitting today?",
            height=300, showlegend=False,
            xaxis_title="Ticker", yaxis_title="IV Percentile (%)",
        )

        # ── A3: IV history line chart for selected tickers ────────────────
        iv_hist = _ibkr_iv_history(tickers)
        fig_ivh = go.Figure()
        if not iv_hist.empty:
            for i, (tkr, grp) in enumerate(iv_hist.groupby("ticker")):
                grp = grp.sort_values("date")
                fig_ivh.add_trace(go.Scatter(
                    x=grp["date"], y=grp["iv_pct"],
                    name=tkr, mode="lines",
                    line=dict(width=2, color=CHART_COLORS[i % len(CHART_COLORS)]),
                    hovertemplate=f"<b>{tkr}</b><br>Date: %{{x}}<br>IV: %{{y:.1f}}%<extra></extra>",
                ))
        fig_ivh.update_layout(
            **PLOTLY_TEMPLATE["layout"],
            title="Daily Implied Volatility History",
            height=340, xaxis_title="Date", yaxis_title="IV (%)",
            hovermode="x unified",
        )
        fig_ivh.update_xaxes(
            type="date",
            rangeselector=_time_rangeselector(active_index=0),   # 1Y default
            range=[_range_start(1), _now_hkt().strftime("%Y-%m-%d")],
            rangeslider=dict(visible=False),
        )
        _apply_rangeselector_layout(fig_ivh)

        # ── A4: IV snapshot table ─────────────────────────────────────────
        iv_tbl = ibkr_iv[["ticker", "snapshot_date", "iv_current",
                           "iv_1m_avg", "iv_1q_avg", "iv_6m_avg",
                           "iv_1y_avg", "iv_pct_vs_1y",
                           "iv_52w_low", "iv_52w_high"]].copy()
        for col in ["iv_current", "iv_1m_avg", "iv_1q_avg",
                    "iv_6m_avg", "iv_1y_avg", "iv_52w_low", "iv_52w_high"]:
            iv_tbl[col] = iv_tbl[col].map(
                lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
        iv_tbl["iv_pct_vs_1y"] = iv_tbl["iv_pct_vs_1y"].map(
            lambda x: f"{x:.0f}th" if pd.notna(x) else "—")
        iv_tbl.columns = ["Ticker", "Date", "IV Current",
                          "1M Avg", "1Q Avg", "6M Avg",
                          "1Y Avg", "1Y Pct", "52W Low", "52W High"]
        iv_table = dash_table.DataTable(
            data=iv_tbl.to_dict("records"),
            columns=[{"name": c, "id": c} for c in iv_tbl.columns],
            sort_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"backgroundColor": BG3, "color": TEXT,
                        "border": "1px solid #30363d",
                        "fontSize": "12px", "padding": "5px 10px"},
            style_header={"backgroundColor": BG2, "color": ACCENT,
                          "fontWeight": "600", "border": "1px solid #30363d"},
            style_data_conditional=[
                {"if": {"row_index": "odd"}, "backgroundColor": BG2},
            ],
        )

        iv_section = html.Div([
            _card([
                _section_title("Options IV — Snapshot Table"),
                iv_table,
                html.Div(
                    "Source: " + iv_src_desc,
                    style={"color": SUBTEXT, "fontSize": "11px", "marginTop": "6px"},
                ),
                # Blank averages are correct, not broken: an option chain is
                # point-in-time, so the equity series cannot be backfilled and a
                # "1Y Avg" does not exist until 252 snapshots accumulate.
                # Printing a 3-day mean under that header is the fabricated-metric
                # failure in §7.3. Crypto (DVOL) has real published history and
                # populates immediately.
                html.Div(
                    "Blank averages/percentiles accumulate daily — option chains cannot be backfilled.",
                    style={"color": SUBTEXT, "fontSize": "11px", "fontStyle": "italic"},
                ),
            ]),
            _card(dcc.Graph(figure=fig_term, config={"displayModeBar": True})),
            dbc.Row([
                dbc.Col(_card(dcc.Graph(figure=fig_pct, config={"displayModeBar": False})), width=6),
                dbc.Col(_card(dcc.Graph(figure=fig_ivh, config={"displayModeBar": True})), width=6),
            ]),
        ])

    else:
        # ── Fallback: yfinance ATM IV ──────────────────────────────────────
        # iv_df: rows where IV was successfully fetched (may be a subset of tickers)
        iv_df = sent.dropna(subset=["implied_volatility"]) if not sent.empty else pd.DataFrame()

        if not iv_df.empty:
            # Sort descending so highest-IV tickers are most prominent
            iv_df = iv_df.sort_values("implied_volatility", ascending=False)
            fig_iv = go.Figure(go.Bar(
                x=iv_df["ticker"],
                y=iv_df["implied_volatility"].round(1),
                marker_color=[
                    RED    if v > 60 else
                    YELLOW if v > 30 else
                    GREEN
                    for v in iv_df["implied_volatility"]
                ],
                text=iv_df["implied_volatility"].map(lambda v: f"{v:.1f}%"),
                textposition="outside",
                hovertemplate="<b>%{x}</b><br>IV (ATM): %{y:.1f}%<extra></extra>",
            ))
            fig_iv.update_layout(
                **PLOTLY_TEMPLATE["layout"],
                title=f"Implied Volatility — ATM Estimate via yfinance "
                      f"({len(iv_df)} of {len(sent)} tickers have IV data)",
                height=320, showlegend=False,
                xaxis_title="Ticker", yaxis_title="Implied Volatility (%)",
            )
            fig_iv.update_yaxes(rangemode="tozero")

            # Tickers where IV is genuinely missing (ETFs, bonds, crypto, etc.)
            missing = sent[sent["implied_volatility"].isna()]["ticker"].tolist()
            missing_note = (
                f"IV not available for: {', '.join(missing[:12])}"
                + (" …" if len(missing) > 12 else "")
            ) if missing else ""

            iv_section = _card([
                dcc.Graph(figure=fig_iv, config={"displayModeBar": False}),
                html.Div([
                    html.Span(
                        "⚠️ Source: yfinance ATM snapshot (annualised) — "
                        "no historical period averages.  ",
                        style={"color": YELLOW, "fontSize": "12px"},
                    ),
                    html.Span(
                        "Connect Interactive Brokers for full IV term structure.",
                        style={"color": SUBTEXT, "fontSize": "12px"},
                    ),
                ], style={"marginTop": "8px"}),
                html.P(missing_note, style={"color": SUBTEXT, "fontSize": "11px",
                                            "marginTop": "4px"}) if missing_note else html.Span(),
            ])

        else:
            # IV column is entirely NULL — likely a --quick crawl with old crawler
            # that never tried the fast path. Show an informative placeholder.
            iv_section = _card([
                _section_title("Implied Volatility — ATM Estimate"),
                html.Div([
                    html.P(
                        "IV data is not yet in the database.",
                        style={"color": YELLOW, "fontWeight": "600", "fontSize": "13px",
                               "margin": "0 0 6px 0"},
                    ),
                    html.P(
                        "The crawler now fetches IV automatically on every crawl "
                        "(including --quick mode). "
                        "Trigger a fresh crawl with the ⚡ Run Crawl button in the navbar "
                        "and then reload — IV data will appear for US-listed stocks "
                        "(ETFs, bonds, and crypto may still show N/A).",
                        style={"color": SUBTEXT, "fontSize": "12px", "margin": "0"},
                    ),
                ], style={"padding": "20px", "textAlign": "center"}),
            ])

    # ══════════════════════════════════════════════════════════════════════
    # SECTION B — PRICE PERFORMANCE SENTIMENT (unchanged)
    # ══════════════════════════════════════════════════════════════════════

    if sent.empty:
        return html.Div([source_note, iv_section])

    drop_df    = sent.dropna(subset=["days_since_large_drop"]).sort_values("days_since_large_drop")
    fig_drop   = go.Figure(go.Bar(
        x=drop_df["ticker"],
        y=drop_df["days_since_large_drop"],
        marker_color=[GREEN if v > 90 else YELLOW if v > 30 else RED
                      for v in drop_df["days_since_large_drop"]],
        hovertemplate="<b>%{x}</b><br>Days since ≥5% drop: %{y}<extra></extra>",
    ))
    fig_drop.update_layout(**PLOTLY_TEMPLATE["layout"],
                            title="Days Since Last Large Single-Day Drop (≥5%)",
                            height=280, showlegend=False)

    perf_df    = sent.dropna(subset=["perf_5d", "perf_1m"])
    fig_scatter= go.Figure()
    if not perf_df.empty:
        fig_scatter.add_trace(go.Scatter(
            x=perf_df["perf_5d"], y=perf_df["perf_1m"],
            mode="markers+text", text=perf_df["ticker"],
            textposition="top center",
            marker=dict(size=14,
                        color=[GREEN if r > 0 else RED for r in perf_df["perf_1m"]],
                        line=dict(width=1, color="#30363d")),
            hovertemplate="<b>%{text}</b><br>5-Day: %{x:.1f}%<br>1-Month: %{y:.1f}%<extra></extra>",
        ))
        fig_scatter.add_hline(y=0, line_dash="dash", line_color=SUBTEXT, line_width=1)
        fig_scatter.add_vline(x=0, line_dash="dash", line_color=SUBTEXT, line_width=1)
    fig_scatter.update_layout(**PLOTLY_TEMPLATE["layout"],
                               title="5-Day vs 1-Month Return (%)",
                               height=360, xaxis_title="5-Day Return (%)",
                               yaxis_title="1-Month Return (%)")

    # ── Performance + IV summary table ───────────────────────────────────
    tbl_df = sent[["ticker", "close_price", "perf_5d", "perf_10d", "perf_1m",
                   "days_since_large_drop"]].copy()

    # 1. Category column — add & sort by sidebar order
    tbl_df["category"] = tbl_df["ticker"].map(_ticker_cat)
    tbl_df["_sort_key"] = tbl_df["ticker"].map(lambda t: _cat_rank.get(t, (99, 99)))
    tbl_df = tbl_df.sort_values("_sort_key").drop(columns=["_sort_key"])

    # 2. IV column — options_iv preferred; yfinance snapshot next; HV30 last.
    # The badge text comes from the ROW's own source, never a run-level constant:
    # a mixed frame (derived equities + published DVOL crypto) must not label all
    # of them with whichever producer happened to write the first row.
    if has_ibkr:
        iv_now = ibkr_iv[["ticker", "iv_current", "source"]].rename(
            columns={"iv_current": "_iv_val"})
        tbl_df = tbl_df.merge(iv_now, on="ticker", how="left")
        tbl_df["iv_source"] = tbl_df.apply(
            lambda r: _iv_source_meta(r["source"])[0] if pd.notna(r["_iv_val"]) else "N/A",
            axis=1,
        )
        tbl_df = tbl_df.drop(columns=["source"], errors="ignore")
    else:
        tbl_df = tbl_df.merge(sent[["ticker", "implied_volatility"]].rename(
            columns={"implied_volatility": "_iv_val"}), on="ticker", how="left")
        # Where yfinance IV is NULL, substitute HV30
        hv_df  = _compute_hv30(tbl_df["ticker"].tolist())
        tbl_df = tbl_df.merge(hv_df, on="ticker", how="left")
        def _pick_iv(row):
            if pd.notna(row["_iv_val"]):
                return row["_iv_val"], "IV"
            if pd.notna(row.get("hv30")):
                return row["hv30"], "HV30"
            return None, "N/A"
        tbl_df[["_iv_val", "iv_source"]] = tbl_df.apply(
            lambda r: pd.Series(_pick_iv(r)), axis=1)
        tbl_df = tbl_df.drop(columns=["hv30"], errors="ignore")

    # 3. Format numeric columns as strings (enables colour-conditional styling)
    for col in ["perf_5d", "perf_10d", "perf_1m"]:
        tbl_df[col] = tbl_df[col].map(lambda x: f"{x:+.1f}%" if pd.notna(x) else "—")
    tbl_df["_iv_val"] = tbl_df["_iv_val"].map(
        lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
    tbl_df["close_price"]           = tbl_df["close_price"].map(
        lambda x: f"${x:,.2f}" if pd.notna(x) else "—")
    tbl_df["days_since_large_drop"] = tbl_df["days_since_large_drop"].map(
        lambda x: str(int(x)) if pd.notna(x) else "—")

    # Reorder & rename columns for display
    tbl_df = tbl_df.rename(columns={
        "ticker":               "Ticker",
        "category":             "Category",
        "close_price":          "Close Price",
        "perf_5d":              "Perf 5D",
        "perf_10d":             "Perf 10D",
        "perf_1m":              "Perf 1M",
        "days_since_large_drop":"Days Since Drop",
        "_iv_val":              "Vol %",
        "iv_source":            "Vol Source",
    })
    display_cols = ["Ticker", "Category", "Close Price",
                    "Perf 5D", "Perf 10D", "Perf 1M",
                    "Days Since Drop", "Vol %", "Vol Source"]
    tbl_df = tbl_df[[c for c in display_cols if c in tbl_df.columns]]

    # 4. Conditional styles: green/red for perf columns; source badge colours
    perf_cols = ["Perf 5D", "Perf 10D", "Perf 1M"]
    cond_styles = [{"if": {"row_index": "odd"}, "backgroundColor": BG2}]
    for col in perf_cols:
        cond_styles += [
            {"if": {"filter_query": f'{{{col}}} contains "+"', "column_id": col},
             "color": GREEN, "fontWeight": "600"},
            {"if": {"filter_query": f'{{{col}}} contains "-"', "column_id": col},
             "color": RED,   "fontWeight": "600"},
        ]
    # Vol Source badge colouring
    cond_styles += [
        {"if": {"filter_query": '{Vol Source} = "IBKR"',  "column_id": "Vol Source"},
         "color": GREEN,  "fontWeight": "600"},
        {"if": {"filter_query": '{Vol Source} = "DVOL"',  "column_id": "Vol Source"},
         "color": GREEN,  "fontWeight": "600"},
        # Derived, so ACCENT rather than GREEN — visually distinct from a
        # published index at a glance.
        {"if": {"filter_query": '{Vol Source} = "IV30*"', "column_id": "Vol Source"},
         "color": ACCENT, "fontWeight": "600"},
        {"if": {"filter_query": '{Vol Source} = "IV"',    "column_id": "Vol Source"},
         "color": ACCENT, "fontWeight": "600"},
        {"if": {"filter_query": '{Vol Source} = "HV30"',  "column_id": "Vol Source"},
         "color": YELLOW, "fontWeight": "600"},
        {"if": {"filter_query": '{Vol Source} = "N/A"',   "column_id": "Vol Source"},
         "color": SUBTEXT},
    ]

    tbl = dash_table.DataTable(
        data=tbl_df.to_dict("records"),
        columns=[{"name": c, "id": c} for c in tbl_df.columns],
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": BG3, "color": TEXT, "border": "1px solid #30363d",
                    "fontSize": "13px", "padding": "6px 10px"},
        style_header={"backgroundColor": BG2, "color": ACCENT, "fontWeight": "600",
                      "border": "1px solid #30363d"},
        style_data_conditional=cond_styles,
    )

    iv_source = ("Interactive Brokers TWS — real-time options IV term structure"
                 if has_ibkr else
                 "Yahoo Finance / yfinance — delayed ATM IV estimate (no period averages)")
    return html.Div([
        source_note,
        _card([_section_title("Sentiment Snapshot"), tbl]),
        iv_section,
        dbc.Row([
            dbc.Col(_card(dcc.Graph(figure=fig_drop,    config={"displayModeBar": False})), width=6),
            dbc.Col(_card(dcc.Graph(figure=fig_scatter, config={"displayModeBar": True})),  width=6),
        ]),
        _card(_source_footer(iv_source,
                              "Performance metrics (5d/10d/1m) from Yahoo Finance / yfinance.")),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — CYCLE ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

_CYCLE_WINDOW = 15   # trading days — matches crawler.py CYCLE_DETECTION_WINDOW


def _build_cycle_chart(ticker: str) -> go.Figure:
    """Return a Plotly figure: price line + green/red shading per cycle segment.
    Fetches up to 5 years of data; rangeselector lets user switch 1Y/3Y/5Y view.
    """
    # Fetch 5 years so the 5Y button is fully populated
    cutoff = (_now_hkt() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")
    df = query(
        "SELECT date, close FROM daily_prices WHERE ticker=? AND date>=? ORDER BY date",
        [ticker, cutoff],
    )
    fig = go.Figure()
    fig.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title=f"{ticker} — Cycle Detection  (window = {_CYCLE_WINDOW} trading days)",
        height=400, xaxis_title="Date", yaxis_title="Price (USD)",
        hovermode="x unified",
    )
    if df.empty or len(df) < _CYCLE_WINDOW * 3:
        fig.add_annotation(
            text="Not enough price history for cycle detection (need ≥ 2 years).",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
            font=dict(color=SUBTEXT, size=13),
        )
        return fig

    closes = df["close"].values.astype(float)
    dates  = pd.to_datetime(df["date"]).values

    peaks   = argrelextrema(closes, np.greater_equal, order=_CYCLE_WINDOW)[0]
    troughs = argrelextrema(closes, np.less_equal,    order=_CYCLE_WINDOW)[0]

    # Build sorted event list: (index, type)
    events = sorted(
        [(i, "peak")   for i in peaks] +
        [(i, "trough") for i in troughs],
        key=lambda e: e[0],
    )

    # Shade each segment between consecutive events
    for k in range(len(events) - 1):
        i0, t0 = events[k]
        i1, t1 = events[k + 1]
        d0, d1 = dates[i0], dates[i1]
        p0, p1 = closes[i0], closes[i1]

        if t0 == "trough" and t1 == "peak":
            pct   = (p1 / p0 - 1) * 100
            color = GREEN
            label = f"+{pct:.0f}%"
        elif t0 == "peak" and t1 == "trough":
            pct   = (p1 / p0 - 1) * 100
            color = RED
            label = f"{pct:.0f}%"
        else:
            color = SUBTEXT
            label = ""

        fig.add_vrect(
            x0=str(d0)[:10], x1=str(d1)[:10],
            fillcolor=color, opacity=0.10, line_width=0,
            annotation_text=label,
            annotation_position="top left",
            annotation_font=dict(color=color, size=9),
        )

    # Price line
    fig.add_trace(go.Scatter(
        x=[str(d)[:10] for d in dates],
        y=closes,
        name=ticker,
        line=dict(color=ACCENT, width=2),
        hovertemplate="<b>%{x}</b>  $%{y:,.2f}<extra></extra>",
    ))

    # Peak markers
    if len(peaks):
        fig.add_trace(go.Scatter(
            x=[str(dates[i])[:10] for i in peaks],
            y=closes[peaks],
            mode="markers", name="Peak",
            marker=dict(symbol="triangle-up", color=GREEN, size=10,
                        line=dict(width=1, color=BG3)),
            hovertemplate="<b>Peak</b>  $%{y:,.2f}<extra></extra>",
        ))

    # Trough markers
    if len(troughs):
        fig.add_trace(go.Scatter(
            x=[str(dates[i])[:10] for i in troughs],
            y=closes[troughs],
            mode="markers", name="Trough",
            marker=dict(symbol="triangle-down", color=RED, size=10,
                        line=dict(width=1, color=BG3)),
            hovertemplate="<b>Trough</b>  $%{y:,.2f}<extra></extra>",
        ))

    # 1Y / 3Y / 5Y rangeselector — default view is 2Y so full context is visible
    _cyc_today = _now_hkt().strftime("%Y-%m-%d")
    fig.update_xaxes(
        type="date",
        rangeselector=_time_rangeselector(active_index=1),   # 3Y default
        range=[_range_start(2), _cyc_today],
        rangeslider=dict(visible=False),
    )
    _apply_rangeselector_layout(fig)

    return fig


def tab_cycles(tickers):
    cyc = cycle_data(tickers)

    if cyc.empty:
        return _card(html.P("No cycle data found. Run crawler.py with ≥2 years of price history.",
                            style={"color": SUBTEXT}))

    cyc = cyc.dropna(subset=["up_cycle_magnitude", "down_cycle_magnitude"], how="all")

    # ── Summary table — with Category column, sorted by sidebar order ────
    tbl_df = cyc[["ticker", "up_cycle_magnitude", "up_cycle_duration",
                  "down_cycle_magnitude", "down_cycle_duration",
                  "vol_diff_last_cycle"]].copy()

    tbl_df["category"]  = tbl_df["ticker"].map(_ticker_cat)
    tbl_df["_sort_key"] = tbl_df["ticker"].map(lambda t: _cat_rank.get(t, (99, 99)))
    tbl_df = tbl_df.sort_values("_sort_key").drop(columns=["_sort_key"])
    tbl_df = tbl_df[["ticker", "category", "up_cycle_magnitude", "up_cycle_duration",
                      "down_cycle_magnitude", "down_cycle_duration", "vol_diff_last_cycle"]]

    for col in ["up_cycle_magnitude", "down_cycle_magnitude"]:
        tbl_df[col] = tbl_df[col].map(lambda x: f"+{x:.1f}%" if pd.notna(x) and x >= 0
                                      else (f"{x:.1f}%" if pd.notna(x) else "—"))
    tbl_df["vol_diff_last_cycle"] = tbl_df["vol_diff_last_cycle"].map(
        lambda x: f"{x:+.1f}%" if pd.notna(x) else "—")
    for col in ["up_cycle_duration", "down_cycle_duration"]:
        tbl_df[col] = tbl_df[col].map(lambda x: f"{int(x)}d" if pd.notna(x) else "—")

    tbl_df = tbl_df.rename(columns={
        "ticker":               "Ticker",
        "category":             "Category",
        "up_cycle_magnitude":   "↑ Magnitude",
        "up_cycle_duration":    "↑ Duration",
        "down_cycle_magnitude": "↓ Magnitude",
        "down_cycle_duration":  "↓ Duration",
        "vol_diff_last_cycle":  "Vol Δ vs Prior Cycle",
    })

    # Conditional colour: green for positive magnitudes/vol, red for negative
    tbl_cond = [{"if": {"row_index": "odd"}, "backgroundColor": BG2}]
    for col in ["↑ Magnitude", "Vol Δ vs Prior Cycle"]:
        tbl_cond += [
            {"if": {"filter_query": f'{{{col}}} contains "+"', "column_id": col},
             "color": GREEN, "fontWeight": "600"},
        ]
    for col in ["↓ Magnitude", "Vol Δ vs Prior Cycle"]:
        tbl_cond += [
            {"if": {"filter_query": f'{{{col}}} contains "-"', "column_id": col},
             "color": RED, "fontWeight": "600"},
        ]

    tbl = dash_table.DataTable(
        data=tbl_df.to_dict("records"),
        columns=[{"name": c, "id": c} for c in tbl_df.columns],
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": BG3, "color": TEXT, "border": "1px solid #30363d",
                    "fontSize": "13px", "padding": "6px 10px"},
        style_header={"backgroundColor": BG2, "color": ACCENT, "fontWeight": "600",
                      "border": "1px solid #30363d"},
        style_data_conditional=tbl_cond,
    )

    # ── Up vs Down cycle magnitude ────────────────────────────────────────
    # Sort bars by category order for the bar charts too
    cyc_sorted = cyc.copy()
    cyc_sorted["_sk"] = cyc_sorted["ticker"].map(lambda t: _cat_rank.get(t, (99, 99)))
    cyc_sorted = cyc_sorted.sort_values("_sk").drop(columns=["_sk"])

    fig_mag = go.Figure()
    fig_mag.add_trace(go.Bar(
        name="Up Cycle (%)", x=cyc_sorted["ticker"], y=cyc_sorted["up_cycle_magnitude"],
        marker_color=GREEN,
        hovertemplate="<b>%{x}</b><br>Up: +%{y:.1f}%<extra></extra>",
    ))
    fig_mag.add_trace(go.Bar(
        name="Down Cycle (%)", x=cyc_sorted["ticker"], y=cyc_sorted["down_cycle_magnitude"],
        marker_color=RED,
        hovertemplate="<b>%{x}</b><br>Down: %{y:.1f}%<extra></extra>",
    ))
    fig_mag.update_layout(**PLOTLY_TEMPLATE["layout"],
                           title="Last Cycle Magnitude (Up vs Down)",
                           barmode="group", height=350)

    # ── Cycle duration ────────────────────────────────────────────────────
    fig_dur = go.Figure()
    fig_dur.add_trace(go.Bar(
        name="Up Duration (days)", x=cyc_sorted["ticker"], y=cyc_sorted["up_cycle_duration"],
        marker_color=GREEN,
        hovertemplate="<b>%{x}</b><br>Up: %{y} days<extra></extra>",
    ))
    fig_dur.add_trace(go.Bar(
        name="Down Duration (days)", x=cyc_sorted["ticker"], y=cyc_sorted["down_cycle_duration"],
        marker_color=RED,
        hovertemplate="<b>%{x}</b><br>Down: %{y} days<extra></extra>",
    ))
    fig_dur.update_layout(**PLOTLY_TEMPLATE["layout"],
                           title="Last Cycle Duration (trading days)",
                           barmode="group", height=300)

    # ── Volume difference vs last cycle ───────────────────────────────────
    vol_df = cyc_sorted.dropna(subset=["vol_diff_last_cycle"])
    fig_vol = go.Figure(go.Bar(
        x=vol_df["ticker"], y=vol_df["vol_diff_last_cycle"],
        marker_color=[GREEN if v > 0 else RED for v in vol_df["vol_diff_last_cycle"]],
        hovertemplate="<b>%{x}</b><br>Vol Δ vs last cycle: %{y:+.1f}%<extra></extra>",
    ))
    fig_vol.update_layout(**PLOTLY_TEMPLATE["layout"],
                           title="Volume Change vs Previous Cycle (%)",
                           showlegend=False, height=280)
    fig_vol.add_hline(y=0, line_dash="dash", line_color=SUBTEXT, line_width=1)

    # ── Per-ticker cycle price chart ──────────────────────────────────────
    default_ticker = tickers[0] if tickers else ""
    initial_fig    = _build_cycle_chart(default_ticker) if default_ticker else go.Figure()

    cycle_chart_section = _card([
        _section_title("Cycle Price Chart"),
        html.Div([
            html.Label("Select ticker:", style={"color": SUBTEXT, "fontSize": "12px",
                                                 "marginRight": "8px"}),
            dcc.Dropdown(
                id="cycles-ticker-select",
                options=[{"label": t, "value": t} for t in tickers],
                value=default_ticker,
                clearable=False,
                style={"width": "200px", "display": "inline-block",
                       "backgroundColor": BG3, "color": TEXT,
                       "border": "1px solid #30363d"},
            ),
        ], style={"marginBottom": "10px"}),
        html.Div([
            html.Span("🟢 Green shading = up cycle  ", style={"color": GREEN, "fontSize": "12px"}),
            html.Span("🔴 Red shading = down cycle  ", style={"color": RED, "fontSize": "12px"}),
            html.Span("▲ Peak  ▼ Trough — % label shows magnitude of each cycle segment",
                      style={"color": SUBTEXT, "fontSize": "11px"}),
        ], style={"marginBottom": "8px"}),
        dcc.Graph(id="cycles-price-chart", figure=initial_fig,
                  config={"displayModeBar": True}),
    ])

    return html.Div([
        _card([_section_title("Cycle Summary"), tbl]),
        cycle_chart_section,
        _card(dcc.Graph(figure=fig_mag, config={"displayModeBar": True})),
        dbc.Row([
            dbc.Col(_card(dcc.Graph(figure=fig_dur, config={"displayModeBar": False})), width=7),
            dbc.Col(_card(dcc.Graph(figure=fig_vol, config={"displayModeBar": False})), width=5),
        ]),
        _card(_source_footer("Yahoo Finance / yfinance — scipy.signal.argrelextrema",
                              "Cycle peaks/troughs detected via rolling local extrema "
                              f"(window={_CYCLE_WINDOW} trading days). "
                              "Volume Δ = current up-cycle avg volume vs prior up-cycle.")),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — PERIOD COMPARISON
# ══════════════════════════════════════════════════════════════════════════════

def tab_compare(tickers):
    """Side-by-side comparison of any two calendar quarters."""

    # Period selector controls (rendered first; comparison triggered by callback)
    return html.Div([
        _card([
            _section_title("Select Two Periods to Compare"),
            dbc.Row([
                dbc.Col([
                    html.Label("Period A", style={"color": SUBTEXT, "fontSize": "12px"}),
                    dcc.DatePickerRange(
                        id="cmp-period-a",
                        start_date=(_now_hkt() - timedelta(days=180)).strftime("%Y-%m-%d"),
                        end_date=(_now_hkt() - timedelta(days=91)).strftime("%Y-%m-%d"),
                        display_format="DD MMM YYYY",
                    ),
                ], width=5),
                dbc.Col([
                    html.Label("Period B", style={"color": SUBTEXT, "fontSize": "12px"}),
                    dcc.DatePickerRange(
                        id="cmp-period-b",
                        start_date=(_now_hkt() - timedelta(days=90)).strftime("%Y-%m-%d"),
                        end_date=_now_hkt().strftime("%Y-%m-%d"),
                        display_format="DD MMM YYYY",
                    ),
                ], width=5),
                dbc.Col([
                    html.Div(style={"height": "20px"}),
                    dbc.Button("Compare →", id="btn-compare", color="primary",
                               style={"marginTop": "4px"}),
                ], width=2),
            ]),
        ]),
        html.Div(id="cmp-output"),
        # Pass tickers down via store
        dcc.Store(id="cmp-tickers", data=tickers),
    ])


@app.callback(
    Output("cycles-price-chart", "figure"),
    Input("cycles-ticker-select", "value"),
    prevent_initial_call=True,
)
def update_cycle_price_chart(ticker):
    if not ticker:
        return go.Figure()
    return _build_cycle_chart(ticker)


@app.callback(
    Output("cmp-output", "children"),
    Input("btn-compare", "n_clicks"),
    State("cmp-period-a",  "start_date"),
    State("cmp-period-a",  "end_date"),
    State("cmp-period-b",  "start_date"),
    State("cmp-period-b",  "end_date"),
    State("cmp-tickers",   "data"),
    prevent_initial_call=True,
)
def run_comparison(_, a_start, a_end, b_start, b_end, tickers):
    if not tickers:
        return html.P("No tickers selected.", style={"color": SUBTEXT})

    a_start = (a_start or "")[:10]
    a_end   = (a_end   or "")[:10]
    b_start = (b_start or "")[:10]
    b_end   = (b_end   or "")[:10]

    # ── Price-based comparison ────────────────────────────────────────────
    pa = price_data(tickers, a_start, a_end)
    pb = price_data(tickers, b_start, b_end)

    def period_return(prices_df):
        out = {}
        for tkr in tickers:
            sub = prices_df[prices_df["ticker"] == tkr].sort_values("date")
            if len(sub) >= 2:
                out[tkr] = (sub["close"].iloc[-1] / sub["close"].iloc[0] - 1) * 100
        return out

    ra, rb = period_return(pa), period_return(pb)
    common = [t for t in tickers if t in ra and t in rb]

    fig_ret = go.Figure()
    fig_ret.add_trace(go.Bar(
        name=f"Period A ({a_start} → {a_end})",
        x=common, y=[ra[t] for t in common],
        marker_color=ACCENT,
        hovertemplate="<b>%{x}</b><br>Period A: %{y:+.1f}%<extra></extra>",
    ))
    fig_ret.add_trace(go.Bar(
        name=f"Period B ({b_start} → {b_end})",
        x=common, y=[rb[t] for t in common],
        marker_color=YELLOW,
        hovertemplate="<b>%{x}</b><br>Period B: %{y:+.1f}%<extra></extra>",
    ))
    fig_ret.add_hline(y=0, line_dash="dash", line_color=SUBTEXT, line_width=1)
    fig_ret.update_layout(**PLOTLY_TEMPLATE["layout"],
                           title="Price Return — Period A vs B",
                           barmode="group", height=380)

    # ── Financial metrics comparison (Revenue, Gross Profit, Net Profit) ──
    fin_a_rows = query(
        f"SELECT ticker, AVG(revenue) as rev, AVG(gross_profit) as gp, "
        f"AVG(net_profit) as np FROM quarterly_financials "
        f"WHERE ticker IN ({','.join('?'*len(tickers))}) "
        f"AND period_end BETWEEN ? AND ? GROUP BY ticker",
        tickers + [a_start, a_end],
    )
    fin_b_rows = query(
        f"SELECT ticker, AVG(revenue) as rev, AVG(gross_profit) as gp, "
        f"AVG(net_profit) as np FROM quarterly_financials "
        f"WHERE ticker IN ({','.join('?'*len(tickers))}) "
        f"AND period_end BETWEEN ? AND ? GROUP BY ticker",
        tickers + [b_start, b_end],
    )

    charts = [_card(dcc.Graph(figure=fig_ret, config={"displayModeBar": True}))]

    for metric, label in [("rev", "Avg Revenue"), ("gp", "Avg Gross Profit"), ("np", "Avg Net Profit")]:
        if fin_a_rows.empty and fin_b_rows.empty:
            break
        merged = pd.merge(fin_a_rows[["ticker", metric]].rename(columns={metric: "A"}),
                          fin_b_rows[["ticker", metric]].rename(columns={metric: "B"}),
                          on="ticker", how="outer").dropna(subset=["A", "B"])
        if merged.empty:
            continue
        fig_f = go.Figure()
        fig_f.add_trace(go.Bar(name=f"Period A", x=merged["ticker"],
                                y=merged["A"]/1e9, marker_color=ACCENT,
                                hovertemplate="<b>%{x}</b><br>A: $%{y:.2f}B<extra></extra>"))
        fig_f.add_trace(go.Bar(name=f"Period B", x=merged["ticker"],
                                y=merged["B"]/1e9, marker_color=YELLOW,
                                hovertemplate="<b>%{x}</b><br>B: $%{y:.2f}B<extra></extra>"))
        fig_f.update_layout(**PLOTLY_TEMPLATE["layout"],
                             title=f"{label} (USD Bn) — Period A vs B",
                             barmode="group", height=300)
        charts.append(_card(dcc.Graph(figure=fig_f, config={"displayModeBar": False})))

    return html.Div(charts)


# ══════════════════════════════════════════════════════════════════════════════
# SUPPLY CHAIN — DB HELPERS
# ══════════════════════════════════════════════════════════════════════════════

# ── Modeled vs observed rendering (BACKLOG SC-16) ─────────────────────────────
#
# SC-12's shape checks found that 25 of 26 curated retail series are formula-
# generated: R9-7950X falls exactly -$5.00/month for 12 months, Xeon-8490H runs
# 40 consecutive steps at a constant ratio. They are honestly labelled
# SRC_MODELED — but a reader takes direction and rate-of-change from a LINE
# regardless of its footnote, which is the argument that retired the HBM series
# in SC-09.
#
# So modeled series are drawn as markers with a faint dotted connector, never as
# a solid line. The difference has to be visible at a glance, without reading a
# legend or a footer: a solid line means somebody observed those points.
#
# Enterprise GPU/CPU (A100/H100/H200/B200/MI300X, EPYC, Xeon) can ONLY ever be
# modeled — no free source publishes accelerator contract ASPs — so they keep
# their values and lose the line. Consumer series additionally accumulate real
# PassMark observations, which are drawn solid on top of the same axes.
_MODELED_LINE = dict(width=1, dash="dot")
_MODELED_MARKER = dict(size=6, symbol="circle-open")


def _trace_style(is_modeled: bool, color: str, width: float = 2.0) -> dict:
    """Plotly kwargs for one series. Observed = solid line; modeled = open
    markers on a dotted connector. Use for EVERY sc_prices trace so the two can
    never be confused, and so a future chart inherits the convention for free."""
    if is_modeled:
        return {
            "mode": "lines+markers",
            "line": dict(color=color, **_MODELED_LINE),
            "marker": dict(color=color, **_MODELED_MARKER),
            "opacity": 0.85,
        }
    return {
        "mode": "lines+markers",
        "line": dict(color=color, width=width),
        "marker": dict(color=color, size=4),
    }


_MODELED_SUFFIX = "  (modeled)"


def _modeled_note(what: str) -> html.Div:
    """Standard in-panel disclosure for a chart carrying modeled series."""
    return html.Div(
        f"⚠️ {what} are MODELED estimates, not observations — drawn as open markers on a "
        "dotted connector so they cannot be read as measured data. The month-to-month "
        "shape is an author's assumption (several run at a constant step or constant "
        "percentage for 10+ months); read the level, not the trend. Solid lines elsewhere "
        "on this dashboard are observed. See BACKLOG SC-16.",
        style={"color": YELLOW, "fontSize": "11px", "border": f"1px solid {YELLOW}",
               "borderRadius": "4px", "padding": "6px 10px", "marginBottom": "10px"},
    )


def sc_prices_query(category: str, source: str = None) -> pd.DataFrame:
    """Return price history for all products in a category
    (GPU/GPU-Enterprise/CPU/CPU-Enterprise/RAM)."""
    model_ids = list(
        ({**GPU_PRODUCTS}            if category == "GPU" else
         {**GPU_ENTERPRISE_PRODUCTS} if category == "GPU-Enterprise" else
         {**CPU_PRODUCTS}            if category == "CPU" else
         {**CPU_ENTERPRISE_PRODUCTS} if category == "CPU-Enterprise" else
         {**RAM_PRODUCTS}).keys()
    )
    if not model_ids:
        return pd.DataFrame()
    ph = ",".join("?" * len(model_ids))
    src_clause = f"AND source='{source}'" if source else ""
    return query(
        f"SELECT p.model_id, p.date, p.source, p.price_usd, p.passmark_score, "
        f"p.price_perf, p.in_stock, c.name, c.brand "
        f"FROM sc_prices p LEFT JOIN sc_products c ON p.model_id=c.model_id "
        f"WHERE p.model_id IN ({ph}) {src_clause} ORDER BY p.date, p.model_id",
        model_ids,
    )


def sc_dram_query() -> pd.DataFrame:
    return query("SELECT * FROM sc_dram_spot ORDER BY product_type, period")


# ── Memory unit normalization: USD/die → USD/GB ───────────────────────────────
# `sc_dram_spot` stores TWO different price units in the same `price_usd` column:
#   DDR4 / DDR5 / LPDDR5X → USD per benchmark DIE (one bare chip)
#   HBM3 / HBM3E          → USD per GB of stack capacity
# Comparing commodity DRAM against HBM on a single axis therefore requires
# converting die prices to USD/GB. The divisor is a constant per product_type
# because TrendForce quotes a fixed benchmark die density for each generation.
# If a new benchmark die density is adopted upstream, update this map — a missing
# entry silently falls back to 1.0 GB and understates the $/GB figure.
_MEM_DIE_GB = {
    "DDR4":    1.0,   # 8Gb  1Gx8 die = 1 GB
    "DDR5":    2.0,   # 16Gb 2Gx8 die = 2 GB
    "LPDDR5X": 2.0,   # 16Gb die      = 2 GB
    "HBM3":    1.0,   # already quoted per GB
    "HBM3E":   1.0,   # already quoted per GB
}

# Shared colour palette for every memory series. Used by BOTH the enterprise
# price chart and the native-unit inline chart so the same generation is never
# drawn in two different colours on the same page.
_MEM_COLORS = {
    "DDR4": "#74C0FC", "DDR5": "#51CF66",
    "HBM3": "#CC5DE8", "HBM3E": "#FF6B6B",
    "LPDDR5X": "#FFD43B",
}

# Native price unit per product_type (for the un-normalized inline chart).
_MEM_UNIT_LABEL = {
    "DDR4": "$/die", "DDR5": "$/die", "LPDDR5X": "$/die",
    "HBM3": "$/GB",  "HBM3E": "$/GB",
}

# Device-level JEDEC specs. NOTE the bandwidth basis differs by class and is
# stated explicitly in `bw_basis` — commodity DRAM bandwidth is only meaningful
# per DIMM (64-bit bus), HBM only per stack (1024-bit bus). Never present these
# numbers without the basis text.
#   DDR4-3200 DIMM : 64-bit  × 3200 MT/s / 8 =   25.6 GB/s
#   DDR5-6400 DIMM : 64-bit  × 6400 MT/s / 8 =   51.2 GB/s
#   HBM3   8-Hi    : 1024-bit × 6400 MT/s / 8 =  819.2 GB/s
#   HBM3E 12-Hi    : 1024-bit × 9200 MT/s / 8 = 1177.6 GB/s
_MEM_SPECS = {
    "DDR4":  {"bandwidth_gbs":   25.6, "capacity_gb": 1,  "config": "8Gb 1Gx8 die",
              "bw_basis": "per DDR4-3200 DIMM (64-bit bus)",   "class": "Commodity DRAM"},
    "DDR5":  {"bandwidth_gbs":   51.2, "capacity_gb": 2,  "config": "16Gb 2Gx8 die",
              "bw_basis": "per DDR5-6400 DIMM (64-bit bus)",   "class": "Commodity DRAM"},
    "HBM3":  {"bandwidth_gbs":  819.0, "capacity_gb": 48, "config": "8-Hi stack",
              "bw_basis": "per 8-Hi stack (1024-bit bus)",     "class": "HBM"},
    "HBM3E": {"bandwidth_gbs": 1177.0, "capacity_gb": 96, "config": "12-Hi stack",
              "bw_basis": "per 12-Hi stack (1024-bit bus)",    "class": "HBM"},
}

# Order series consistently: commodity DRAM first, then HBM generations.
_MEM_ORDER = ["DDR4", "DDR5", "HBM3", "HBM3E", "LPDDR5X"]


def _mem_normalize_usd_per_gb(df: pd.DataFrame) -> pd.DataFrame:
    """Add a `price_usd_gb` column to an sc_dram_spot frame.

    Divides per-die prices by the benchmark die capacity (see `_MEM_DIE_GB`);
    HBM rows pass through unchanged because they are already quoted per GB.
    Also adds `period_dt` for date-axis plotting. Returns a copy — the caller's
    frame is never mutated.
    """
    out = df.copy()
    out["price_usd"] = pd.to_numeric(out["price_usd"], errors="coerce")
    out["die_gb"] = out["product_type"].map(_MEM_DIE_GB).fillna(1.0)
    out["price_usd_gb"] = out["price_usd"] / out["die_gb"]
    out["period_dt"] = pd.to_datetime(out["period"].astype(str).str[:7] + "-01")
    return out.sort_values(["product_type", "period"])


_MEM_GAP_MONTHS = 3


def _mem_break_gaps(grp: pd.DataFrame, gap_months: int = _MEM_GAP_MONTHS) -> pd.DataFrame:
    """Insert a NaN row wherever a series skips more than `gap_months`.

    Plotly joins consecutive points regardless of the distance between them, so a
    series with a hole reads as a smooth move across the hole. `sc_dram_spot` has
    exactly that shape after the fabricated 2025-01 → 2026-05 DDR rows were
    withdrawn (BACKLOG SC-04): DDR4 runs 2024-12 ($2.65) then 2026-06 ($36.00),
    and an unbroken line between them would draw an 18-month climb that never
    happened. The NaN forces Plotly to lift the pen — the gap stays visible as a
    gap, which is the honest rendering of "we do not know".
    """
    grp = grp.sort_values("period_dt")
    if len(grp) < 2:
        return grp
    out, prev = [], None
    for _, row in grp.iterrows():
        if prev is not None:
            months = ((row["period_dt"].year - prev["period_dt"].year) * 12
                      + row["period_dt"].month - prev["period_dt"].month)
            if months > gap_months:
                blank = prev.copy()
                blank["period_dt"] = prev["period_dt"] + pd.DateOffset(months=1)
                for c in ("price_usd", "price_usd_gb"):
                    if c in blank.index:
                        blank[c] = float("nan")
                out.append(blank)
        out.append(row)
        prev = row
    return pd.DataFrame(out)


def _mem_yoy(grp: pd.DataFrame, price_col: str = "price_usd_gb"):
    """Year-on-year change anchored to the SERIES' own latest period.

    Returns (latest_row, price_1y_ago, yoy_pct) with the latter two None when no
    genuine ~12-month-earlier observation exists.

    Anchoring on the series rather than on *today* matters: a superseded series
    (HBM3 stops at 2023-12) otherwise matches its own final row as the "1Y ago"
    price and reports a fabricated +0.0%.
    """
    grp = grp.sort_values("period_dt").dropna(subset=[price_col])
    if grp.empty:
        return None, None, None
    latest = grp.iloc[-1]
    target = latest["period_dt"] - pd.DateOffset(months=12)
    # Accept an anchor within a 12–15 month lookback; anything older is not a
    # year-on-year comparison and is reported as "—".
    #
    # The floor was 18 months and had to be tightened (BACKLOG SC-04): after the
    # fabricated 2025-01 → 2026-05 DDR rows were withdrawn, DDR4's nearest anchor
    # to its 2026-06 reading was 2024-12 — exactly 18 months back, so it passed
    # and the table printed "+1258.5% YoY" for what is an 18-month move. A 15-
    # month ceiling still admits the bi-monthly HBM series while rejecting that.
    floor = latest["period_dt"] - pd.DateOffset(months=15)
    prior = grp[(grp["period_dt"] <= target) & (grp["period_dt"] >= floor)]
    if prior.empty:
        return latest, None, None
    p_prev = prior.iloc[-1][price_col]
    if not pd.notna(p_prev) or p_prev <= 0 or not pd.notna(latest[price_col]):
        return latest, None, None
    return latest, p_prev, (latest[price_col] / p_prev - 1) * 100


def sc_demand_query() -> pd.DataFrame:
    """Macro demand indicators (BACKLOG SC-06 / SC-00 fix B) — replaces sc_btb_query()."""
    return query("SELECT * FROM sc_demand_indicators ORDER BY indicator_key, period")


def sc_steam_query() -> pd.DataFrame:
    """Latest Steam HW Survey GPU shares."""
    return query("""
        SELECT s.model_name, s.share_pct, s.period
        FROM sc_market_share s
        INNER JOIN (SELECT MAX(period) AS mp FROM sc_market_share) latest
          ON s.period = latest.mp
        ORDER BY s.share_pct DESC
    """)


# ── Price Index vs SOXX ETF Correlation Chart ────────────────────────────────

def _sc_vs_etf_panel():
    """
    Overlay the enterprise GPU / CPU / RAM (HBM) price indices (monthly avg,
    normalised to base=100) against SOXX (iShares Semiconductor ETF).
    Falls back to SMH if SOXX has not been crawled yet.
    GPU = NVIDIA/AMD AI accelerators (A100 → H100 → H200 → B200 + MI300X).
    CPU = Intel Xeon Platinum + AMD EPYC server-class CPUs.
    RAM = withdrawn (BACKLOG SC-09). The HBM per-stack rows were the modeled
    per-GB series × stack capacity, so the "RAM" line was a rescaled copy of a
    fabricated series, not corroboration. `_HBM_PRODUCTS` stays registered and
    the `if df.empty: continue` guard below drops the category cleanly.
    Vertical markers indicate when each new generation reached GA.
    """

    # ── 1. Build monthly price indices for each category ─────────────────────
    # RAM: restrict to HBM-class enterprise memory only (HBM3 + HBM3E stacks)
    _HBM_PRODUCTS = {k: v for k, v in RAM_PRODUCTS.items()
                     if v.get("type") in ("HBM3", "HBM3E")}
    CATEGORIES = [
        ("GPU", GPU_ENTERPRISE_PRODUCTS, "#76b900"),
        ("CPU", CPU_ENTERPRISE_PRODUCTS, "#0071C5"),
        ("RAM", _HBM_PRODUCTS,           "#ED1C24"),
    ]

    price_series: dict[str, pd.Series] = {}

    for cat, products, _ in CATEGORIES:
        model_ids = list(products.keys())
        if not model_ids:
            continue
        ph = ",".join("?" * len(model_ids))
        # Include all sources (curated + passmark + newegg) so that each
        # crawler run automatically extends the index with the latest data point.
        # Monthly resampling (mean) handles multi-source overlap gracefully:
        # curated rows provide the historical backbone; live crawl rows extend
        # the rightmost bin each time the crawler runs.
        df = query(
            f"SELECT date, price_usd FROM sc_prices "
            f"WHERE model_id IN ({ph}) "
            f"AND price_usd IS NOT NULL "
            f"ORDER BY date",
            model_ids,
        )
        if df.empty:
            continue
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df["price_usd"] = pd.to_numeric(df["price_usd"], errors="coerce")
        # Monthly average across all models in the category
        monthly = (
            df.set_index("date")["price_usd"]
            .resample("MS")          # Month Start
            .mean()
            .dropna()
        )
        if monthly.empty or len(monthly) < 2:
            continue
        price_series[cat] = monthly

    # ── 2. Fetch SOXX (fallback: SMH) from daily_prices ──────────────────────
    etf_ticker = None
    for candidate in ("SOXX", "SMH"):
        df_etf = query(
            "SELECT date, close FROM daily_prices WHERE ticker=? ORDER BY date",
            [candidate],
        )
        if not df_etf.empty:
            etf_ticker = candidate
            break

    etf_monthly: pd.Series | None = None
    if etf_ticker is not None and not df_etf.empty:
        df_etf["date"]  = pd.to_datetime(df_etf["date"], errors="coerce")
        df_etf["close"] = pd.to_numeric(df_etf["close"], errors="coerce")
        etf_monthly = (
            df_etf.set_index("date")["close"]
            .resample("MS")
            .last()             # Use month-end close as the ETF reference price
            .dropna()
        )
        if etf_monthly.empty or len(etf_monthly) < 2:
            etf_monthly = None

    # ── 3. If no data at all — return placeholder ────────────────────────────
    if not price_series and etf_monthly is None:
        return _card([
            _section_title("Price Index vs SOXX ETF — Correlation"),
            html.P(
                "No supply-chain price or ETF data yet. "
                "Run: python supply_chain_crawler.py && python crawler.py --quick",
                style={"color": SUBTEXT, "fontSize": "12px"},
            ),
        ])

    # ── 4. Determine common date range and normalise to base=100 ─────────────
    all_starts = [s.index.min() for s in price_series.values()]
    if etf_monthly is not None:
        all_starts.append(etf_monthly.index.min())
    common_start = max(all_starts) if all_starts else None

    def _normalise(series: pd.Series, base_date) -> pd.Series:
        """Slice from base_date and rebase to 100."""
        s = series[series.index >= base_date].copy()
        base = s.iloc[0] if not s.empty and s.iloc[0] != 0 else None
        return (s / base * 100) if base else s

    CAT_COLORS = {"GPU": "#76b900", "CPU": "#00A3E0", "RAM": "#ED1C24"}

    # ── 5. Build normalised overlay chart ────────────────────────────────────
    fig = go.Figure()

    # ETF first (drawn behind)
    if etf_monthly is not None and common_start is not None:
        etf_norm = _normalise(etf_monthly, common_start)
        fig.add_trace(go.Scatter(
            x=etf_norm.index,
            y=etf_norm.values.round(2),
            name=f"{etf_ticker} ETF",
            mode="lines",
            line=dict(width=3, color=ACCENT, dash="solid"),
            hovertemplate=f"<b>{etf_ticker}</b><br>%{{x|%b %Y}}<br>Index: %{{y:.1f}}<extra></extra>",
        ))
        # Shade area under ETF
        fig.add_trace(go.Scatter(
            x=etf_norm.index, y=etf_norm.values.round(2),
            mode="none",
            fill="tozeroy",
            fillcolor=f"rgba(88,166,255,0.07)",
            showlegend=False, hoverinfo="skip",
        ))

    # Price indices
    for cat, _, _col in CATEGORIES:
        if cat not in price_series:
            continue
        s = price_series[cat]
        s_norm = _normalise(s, common_start) if common_start else _normalise(s, s.index.min())
        col = CAT_COLORS.get(cat, ACCENT)
        # SC-16: these indices are built entirely from modeled enterprise ASPs —
        # no free source publishes accelerator contract prices — while the ETF
        # they are plotted against is real market data. Open markers on a dotted
        # connector keep that asymmetry visible; a dotted line alone did not,
        # because the eye still reads a continuous path as a measured trend.
        fig.add_trace(go.Scatter(
            x=s_norm.index,
            y=s_norm.values.round(2),
            name=f"{cat} Price Index{_MODELED_SUFFIX}",
            **_trace_style(True, col),
            hovertemplate=(f"<b>{cat} Price Index</b> (modeled)<br>"
                           f"%{{x|%b %Y}}<br>Index: %{{y:.1f}}<extra></extra>"),
        ))

    # Reference line at 100
    fig.add_hline(y=100, line_dash="dash", line_color=SUBTEXT, line_width=1,
                  annotation_text="Base = 100", annotation_position="right",
                  annotation_font_color=SUBTEXT, annotation_font_size=10)

    # ── Product-generation launch markers ─────────────────────────────────────
    # Alternate annotation positions so labels don't overlap when launches
    # cluster (e.g. Nov 2022 has both H100 GA and Genoa GA).
    _LAUNCH_CAT_COLOR = {"GPU": "#76b900", "CPU": "#0071C5", "RAM": "#ED1C24"}
    _launch_positions = ["top left", "top right", "top left", "top right",
                         "top left", "top right", "top left", "top right",
                         "top left"]
    for _i, (lcat, lshort, _ldesc, ldate) in enumerate(ENTERPRISE_PRODUCT_LAUNCHES):
        _lcol = _LAUNCH_CAT_COLOR.get(lcat, SUBTEXT)
        # Use add_shape + add_annotation instead of add_vline:
        # add_vline with annotation_text has a Plotly bug where it tries to
        # average int(0) with the x value, crashing on both str and datetime.
        fig.add_shape(
            type="line",
            x0=ldate, x1=ldate,
            y0=0, y1=1,
            xref="x", yref="paper",
            line=dict(color=_lcol, width=1, dash="dot"),
        )
        _yanchor = "top" if "top" in _launch_positions[_i % len(_launch_positions)] else "bottom"
        fig.add_annotation(
            x=ldate,
            y=0.98 if _yanchor == "top" else 0.02,
            xref="x", yref="paper",
            text=f"▲ {lshort}",
            showarrow=False,
            font=dict(color=_lcol, size=9),
            textangle=-90,
            xanchor="right" if "right" in _launch_positions[_i % len(_launch_positions)] else "left",
            yanchor=_yanchor,
        )

    fig.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title=(
            f"Enterprise AI Hardware Price Index vs {etf_ticker} ETF — Normalised to 100"
            if etf_ticker else "Enterprise AI Hardware Price Index — Normalised to 100"
        ),
        height=480,
        xaxis_title="Month",
        yaxis_title="Index (Base = 100 at common start)",
        hovermode="x unified",
    )
    # Default view: 2Y so curated supply-chain indices (ending ~2025-05) and
    # the live ETF series are both visible on initial load.
    # ETF right-edge stays at today; 1Y/3Y/5Y buttons step backward from there.
    fig.update_xaxes(
        type="date",
        rangeselector=_time_rangeselector(active_index=0),   # 1Y default
        range=[_range_start(2), _now_hkt().strftime("%Y-%m-%d")],
        rangeslider=dict(visible=False),
    )
    _apply_rangeselector_layout(fig)

    # ── 6. Rolling 3-month correlation bar chart (GPU / CPU / RAM vs ETF) ────
    corr_cards = []
    if etf_monthly is not None and common_start is not None:
        etf_s = etf_monthly[etf_monthly.index >= common_start]
        for cat, _, _ in CATEGORIES:
            if cat not in price_series:
                continue
            s = price_series[cat]
            combined = pd.concat(
                [s.rename("price"), etf_s.rename("etf")], axis=1
            ).dropna()
            if len(combined) < 4:
                continue
            corr = combined["price"].corr(combined["etf"])
            col  = (GREEN if corr >= 0.6 else YELLOW if corr >= 0.2
                    else RED if corr <= -0.2 else SUBTEXT)
            corr_cards.append(dbc.Col(
                _card([
                    html.Div(cat, style={"fontSize": "11px", "color": SUBTEXT,
                                         "textTransform": "uppercase", "letterSpacing": "0.5px"}),
                    html.Div(
                        f"r = {corr:+.2f}",
                        style={"fontSize": "26px", "fontWeight": "700", "color": col},
                    ),
                    html.Div(
                        "vs " + etf_ticker,
                        style={"fontSize": "11px", "color": SUBTEXT},
                    ),
                    html.Div(
                        ("Strong +ve" if corr >= 0.6 else
                         "Moderate +ve" if corr >= 0.2 else
                         "Weak / No" if corr > -0.2 else "Negative") + " correlation",
                        style={"fontSize": "11px", "color": col, "marginTop": "2px"},
                    ),
                ], style={"textAlign": "center"}),
                width=4,
            ))

    # Rolling 6-month window correlation line chart
    fig_roll = None
    if etf_monthly is not None and common_start is not None:
        etf_s = etf_monthly[etf_monthly.index >= common_start]
        fig_roll = go.Figure()
        has_roll = False
        for cat, _, _ in CATEGORIES:
            if cat not in price_series:
                continue
            s = price_series[cat]
            combined = pd.concat(
                [s.rename("price"), etf_s.rename("etf")], axis=1
            ).dropna()
            if len(combined) < 6:
                continue
            rolling_corr = (
                combined["price"]
                .rolling(window=6, min_periods=4)
                .corr(combined["etf"])
            )
            col = CAT_COLORS.get(cat, ACCENT)
            fig_roll.add_trace(go.Scatter(
                x=rolling_corr.index,
                y=rolling_corr.values.round(3),
                name=f"{cat} vs {etf_ticker}",
                mode="lines",
                line=dict(width=2, color=col),
                hovertemplate=(
                    f"<b>{cat} vs {etf_ticker}</b><br>"
                    "%{x|%b %Y}<br>6M Rolling r: %{y:.2f}<extra></extra>"
                ),
            ))
            has_roll = True

        if has_roll:
            fig_roll.add_hline(y=0,    line_dash="dash", line_color=SUBTEXT,  line_width=1)
            fig_roll.add_hline(y=0.6,  line_dash="dot",  line_color=GREEN,    line_width=1,
                               annotation_text="Strong +ve (0.6)", annotation_font_color=GREEN,
                               annotation_font_size=10, annotation_position="right")
            fig_roll.add_hline(y=-0.6, line_dash="dot",  line_color=RED,      line_width=1,
                               annotation_text="Strong −ve (−0.6)", annotation_font_color=RED,
                               annotation_font_size=10, annotation_position="right")
            fig_roll.update_layout(
                **PLOTLY_TEMPLATE["layout"],
                title=f"6-Month Rolling Correlation: Price Index vs {etf_ticker}",
                height=280,
                xaxis_title="Month",
                yaxis_title="Pearson r",
                hovermode="x unified",
            )
            fig_roll.update_yaxes(range=[-1.05, 1.05])
            # 2Y default so rolling-corr data (limited by curated SC series)
            # is visible on initial load alongside the live ETF series.
            fig_roll.update_xaxes(
                type="date",
                rangeselector=_time_rangeselector(active_index=0),   # 1Y default
                range=[_range_start(2), _now_hkt().strftime("%Y-%m-%d")],
                rangeslider=dict(visible=False),
            )
            _apply_rangeselector_layout(fig_roll, legend_bottom=False,
                                        extra_height=45)
        else:
            fig_roll = None

    # ── 7. Latest price snapshot table ───────────────────────────────────────
    tbl_rows = []
    for cat, _, _ in CATEGORIES:
        if cat not in price_series:
            continue
        s = price_series[cat]
        if len(s) < 2:
            continue
        latest_price = s.iloc[-1]
        prev_price   = s.iloc[-2]
        mom          = (latest_price / prev_price - 1) * 100
        yoy_price    = s.iloc[-13] if len(s) >= 13 else None
        yoy          = ((latest_price / yoy_price - 1) * 100) if yoy_price else None
        tbl_rows.append({
            "Category": cat,
            "Period": s.index[-1].strftime("%Y-%m"),
            "Avg Price (USD)": f"${latest_price:,.0f}",
            "MoM Δ": f"{mom:+.1f}%",
            "YoY Δ": f"{yoy:+.1f}%" if yoy is not None else "—",
        })
    if etf_monthly is not None:
        s = etf_monthly
        if len(s) >= 2:
            lp  = s.iloc[-1]; pp = s.iloc[-2]
            mom = (lp / pp - 1) * 100
            yoy_p = s.iloc[-13] if len(s) >= 13 else None
            yoy   = ((lp / yoy_p - 1) * 100) if yoy_p else None
            tbl_rows.append({
                "Category": f"{etf_ticker} ETF",
                "Period": s.index[-1].strftime("%Y-%m"),
                "Avg Price (USD)": f"${lp:,.2f}",
                "MoM Δ": f"{mom:+.1f}%",
                "YoY Δ": f"{yoy:+.1f}%" if yoy is not None else "—",
            })

    tbl_df = pd.DataFrame(tbl_rows)
    snapshot_tbl = None
    if not tbl_df.empty:
        snapshot_tbl = dash_table.DataTable(
            data=tbl_df.to_dict("records"),
            columns=[{"name": c, "id": c} for c in tbl_df.columns],
            sort_action="native",
            style_table={"overflowX": "auto"},
            style_cell={
                "backgroundColor": BG3, "color": TEXT,
                "border": "1px solid #30363d", "fontSize": "13px", "padding": "6px 12px",
            },
            style_header={
                "backgroundColor": BG2, "color": ACCENT,
                "fontWeight": "600", "border": "1px solid #30363d",
            },
            style_data_conditional=[
                {"if": {"filter_query": '{MoM Δ} contains "+"'}, "color": GREEN},
                {"if": {"filter_query": '{MoM Δ} contains "-"'},  "color": RED},
                {"if": {"filter_query": '{YoY Δ} contains "+"'}, "color": GREEN},
                {"if": {"filter_query": '{YoY Δ} contains "-"'},  "color": RED},
                {"if": {"row_index": "odd"}, "backgroundColor": BG2},
            ],
        )

    # ── 8. Assemble panel ────────────────────────────────────────────────────
    note_etf = (
        f"Comparing enterprise AI hardware price trends against "
        f"{etf_ticker} (iShares Semiconductor ETF) as a proxy for semiconductor "
        f"industry equity performance. "
        f"GPU = NVIDIA/AMD AI accelerators (A100 → H100 → H200 → B200, MI300X); "
        f"CPU = Intel Xeon Platinum + AMD EPYC server flagship SKUs. "
        f"The RAM (HBM) index has been WITHDRAWN — those rows were the per-GB "
        f"modeled series multiplied by stack capacity, not an independent "
        f"observation (BACKLOG SC-09). "
        f"▲ markers indicate when each new product generation reached GA — "
        f"the index tracks the full portfolio across generations."
    )

    children = [
        _section_title(f"Enterprise AI Hardware Price Index vs {etf_ticker} ETF — Industry Correlation"),
        _modeled_note("The GPU and CPU price indices on this chart"),
        html.P(note_etf, style={"color": SUBTEXT, "fontSize": "12px", "marginBottom": "12px"}),
        dcc.Graph(figure=fig, config={"displayModeBar": True}),
    ]

    if corr_cards:
        children += [
            html.Div(style={"marginTop": "8px"}),
            _section_title("Full-Period Pearson Correlation"),
            dbc.Row(corr_cards, className="g-2"),
        ]

    if fig_roll is not None:
        children.append(_card(dcc.Graph(figure=fig_roll, config={"displayModeBar": True})))

    if snapshot_tbl is not None:
        children += [
            html.Div(style={"marginTop": "8px"}),
            _section_title("Category-Level Monthly Avg Price & ETF Snapshot"),
            html.P(
                "Category-level average enterprise ASP for the most recent month — "
                "mean across all tracked models per category: "
                "GPU = AI accelerators (A100/H100/H200/B200 + MI300X); "
                "CPU = Intel Xeon Platinum + AMD EPYC server SKUs. "
                "RAM (HBM) withdrawn — see BACKLOG SC-09.",
                style={"color": SUBTEXT, "fontSize": "12px", "marginBottom": "8px"},
            ),
            snapshot_tbl,
        ]

    etf_note = (f"SOXX (iShares Semiconductor ETF)" if etf_ticker == "SOXX"
                else f"{etf_ticker} (VanEck Semiconductor ETF — SOXX proxy until SOXX is crawled)")
    children.append(_source_footer(
        f"NVIDIA/AMD/Intel launch ODP (baseline) + {SRC_MODELED} (GPU/CPU contract-price trend)  ·  "
        f"Yahoo Finance / yfinance ({etf_note})",
        "GPU index = avg contract ASP across A100/H100/H200/B200/MI300X per month.  "
        "CPU index = avg ODP-derived ASP across Xeon Platinum + EPYC server SKUs.  "
        "⚠ RAM index REMOVED 2026-08-02: the HBM per-stack rows were CURATED_DRAM_SPOT's "
        "modeled per-GB series × 48/96 GB — a restatement of one modeled series, presented "
        "as a second corroborating one (BACKLOG SC-09).  "
        f"All series normalised to 100 at common start: "
        f"{common_start.strftime('%Y-%m') if common_start else 'N/A'}.  "
        "▲ markers = product generation GA dates.",
    ))

    return _card(children)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — SUPPLY CHAIN
# ══════════════════════════════════════════════════════════════════════════════

def tab_supply_chain():
    """
    Supply Chain tab — category sub-tabs (GPU / CPU / RAM) using dbc.Tabs
    with content pre-rendered directly in each tab child (no server callback
    needed — Dash handles show/hide via CSS). This avoids the Dash anti-pattern
    of having a callback output nested inside another callback's output.
    """

    _TAB_STYLE = {"--bs-nav-tabs-border-color": "#30363d"}

    def _safe_price_section(cat):
        try:
            return _sc_price_section(cat)
        except Exception as exc:
            return _card(html.P(
                f"Error loading {cat} price data: {exc}",
                style={"color": RED, "fontSize": "13px"},
            ))

    def _safe_enterprise_gpu():
        try:
            return _sc_enterprise_gpu_section()
        except Exception as exc:
            return _card(html.P(
                f"Error loading Enterprise GPU data: {exc}",
                style={"color": RED, "fontSize": "13px"},
            ))

    def _safe_enterprise_cpu():
        try:
            return _sc_enterprise_cpu_section()
        except Exception as exc:
            return _card(html.P(
                f"Error loading Enterprise CPU data: {exc}",
                style={"color": RED, "fontSize": "13px"},
            ))

    def _safe_enterprise_ram():
        try:
            return _sc_enterprise_ram_section()
        except Exception as exc:
            return _card(html.P(
                f"Error loading Enterprise RAM data: {exc}",
                style={"color": RED, "fontSize": "13px"},
            ))

    # dbc.Tabs renders tab content directly — no server round-trip required.
    # All three sections are built once when the Supply Chain tab is opened.
    # GPU tab: enterprise data-center GPUs (A100/H100/H200/B200/MI300X).
    # CPU tab: enterprise server CPUs (EPYC Genoa/Turin + Xeon SPR/EMR).
    # RAM tab: enterprise HBM (HBM3/HBM3E) with consumer DRAM section below.
    price_tabs = dbc.Tabs(
        [
            dbc.Tab(_safe_enterprise_gpu(), label="🖥️  GPU (Enterprise)", tab_id="sc-tab-gpu",
                    label_style={"fontSize": "13px", "color": TEXT},
                    active_label_style={"color": ACCENT, "fontWeight": "600"}),
            dbc.Tab(_safe_enterprise_cpu(), label="⚙️  CPU (Enterprise)", tab_id="sc-tab-cpu",
                    label_style={"fontSize": "13px", "color": TEXT},
                    active_label_style={"color": ACCENT, "fontWeight": "600"}),
            dbc.Tab(_safe_enterprise_ram(), label="💾  RAM (Enterprise)", tab_id="sc-tab-ram",
                    label_style={"fontSize": "13px", "color": TEXT},
                    active_label_style={"color": ACCENT, "fontWeight": "600"}),
        ],
        active_tab="sc-tab-gpu",
        style=_TAB_STYLE,
    )

    return html.Div([
        _card([
            _section_title("Supply Chain Intelligence — Enterprise Focus"),
            html.P(
                "Enterprise AI hardware supply chain metrics. "
                "GPU: NVIDIA AI accelerators (A100 → H100 → H200 → B200) + AMD MI300X — "
                "contract/spot ASP, generation era pricing, FP16 TFLOPS/$ efficiency. "
                "CPU: Intel Xeon Platinum + AMD EPYC server flagship SKUs — "
                "ODP-derived ASP, core count vs price, generation transitions. "
                "RAM: HBM3 / HBM3E per-stack contract price (SK Hynix / Samsung / Micron) + "
                "consumer DDR4/DDR5 spot context. "
                "Macro: TSMC/UMC monthly revenue, Korea chip exports, WSTS global billings, "
                "SEMI WWSEMS equipment billings — genuinely published demand indicators, "
                "not modeled estimates. "
                "Fab utilisation: TSMC / Samsung / SK Hynix / Micron / Intel from earnings calls.",
                style={"color": SUBTEXT, "fontSize": "12px", "margin": "0"},
            ),
            _source_footer(
                f"NVIDIA / AMD / Intel launch ODP · SK Hynix / Samsung / Micron Earnings · "
                f"Valve Steam HW Survey · {SRC_PUBLISHED} / {SRC_MODELED} (see panels)",
                "Each panel carries its own source attribution below — some series are "
                "transcribed from a public release, others are this project's modeled "
                "estimate; the per-panel footer states which.",
            ),
        ]),

        # ── PANEL 1 + 2: Price Index & In-Stock (GPU / CPU / RAM sub-tabs) ───
        _card([_section_title("Product Category — Price Index & Availability"), price_tabs]),

        # ── PANEL 3: Price Index vs SOXX ETF Correlation ─────────────────────
        _sc_vs_etf_panel(),

        # ── PANEL 4: Sales Volume — Steam Survey ──────────────────────────────
        _sc_steam_panel(),

        # ── PANEL 5: Macro Demand Indicators (replaces SEMI B2B — SC-00/SC-06)
        _sc_demand_panel(),

        # ── PANEL 5 + 6: Manufacturer Capacity & Occupancy ───────────────────
        _sc_fab_metrics_panel(),
        # Note: DRAM & HBM Spot Prices are now embedded in the RAM sub-tab above
    ])


def _sc_dram_inline(height: int = 360) -> html.Div:
    """DRAM & HBM spot price chart + YoY table — embedded inside the RAM tab."""
    df = sc_dram_query()
    if df.empty:
        return _card(html.P(
            "DRAM spot price data not yet loaded. Run: python supply_chain_crawler.py",
            style={"color": SUBTEXT, "fontSize": "12px"},
        ))

    df["price_usd"] = pd.to_numeric(df["price_usd"], errors="coerce")
    df = df.sort_values("period")

    df["period_dt"] = pd.to_datetime(df["period"].astype(str).str[:7] + "-01")

    fig = go.Figure()
    for ptype in [p for p in _MEM_ORDER if p in set(df["product_type"])]:
        grp  = df[df["product_type"] == ptype]
        unit = _MEM_UNIT_LABEL.get(ptype, "USD")
        for spec, sub in grp.groupby("spec_label"):
            sub = _mem_break_gaps(sub)      # never draw across a hole — SC-04
            fig.add_trace(go.Scatter(
                x=sub["period_dt"], y=sub["price_usd"],
                name=f"{ptype} — {spec}",
                mode="lines+markers",
                line=dict(width=2, color=_MEM_COLORS.get(ptype, ACCENT)),
                hovertemplate=(
                    f"<b>{ptype}</b> {spec}<br>"
                    f"%{{x}}<br>$%{{y:.2f}} {unit}<extra></extra>"
                ),
            ))
    fig.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="DRAM & HBM Spot / Contract Prices — DDR4/DDR5 (USD/die) · HBM3/HBM3E (USD/GB)",
        height=height, xaxis_title="Month", yaxis_title="Price (USD, mixed units)",
    )
    # Anchor x-range to actual data end so the initial view is not empty when
    # curated data lags today.  stepmode="backward" buttons stay relative to
    # the right edge, so 1Y/3Y/5Y still work correctly.
    # Default is 5Y, NOT 1Y: HBM3 pricing stops at 2023-12, so a trailing-1Y
    # window renders its legend entry with no visible line.
    _dram_end_dt  = pd.to_datetime(df.sort_values("period")["period"].iloc[-1][:7] + "-01")
    _dram_rend    = (_dram_end_dt + pd.DateOffset(months=2)).strftime("%Y-%m-%d")
    _dram_rstart  = (_dram_end_dt - pd.DateOffset(years=5)).strftime("%Y-%m-%d")
    fig.update_xaxes(
        type="date",
        rangeselector=_time_rangeselector(active_index=2),   # 5Y default
        range=[_dram_rstart, _dram_rend],
        rangeslider=dict(visible=False),
    )
    _apply_rangeselector_layout(fig)

    # YoY delta table. Anchored per-series via `_mem_yoy` — anchoring on the
    # global max period instead makes a superseded series (HBM3 ends 2023-12)
    # match its own final row and report a fabricated +0.0%.
    _dfy = df.copy()
    _dfy["period_dt"] = pd.to_datetime(_dfy["period"].astype(str).str[:7] + "-01")
    _newest = _dfy["period"].max()
    rows_tbl = []
    for (ptype, spec), grp in _dfy.groupby(["product_type", "spec_label"]):
        latest, p_prev, yoy = _mem_yoy(grp, price_col="price_usd")
        rows_tbl.append({
            "Type": ptype, "Spec": spec, "Period": str(latest["period"]),
            "Unit": _MEM_UNIT_LABEL.get(ptype, "USD"),
            "Spot Price": (f"${latest['price_usd']:.2f}"
                           if pd.notna(latest["price_usd"]) else "—"),
            "YoY Δ": f"{yoy:+.1f}%" if yoy is not None else "—",
            # Zero-hallucination default (§8/SC-05): an unlabeled row must never
            # silently read as a published TrendForce figure — fall back to the
            # more conservative "modeled" label, not the institutional name.
            "Source": latest.get("source", SRC_MODELED),
        })
    tbl_df = pd.DataFrame(rows_tbl)
    tbl = dash_table.DataTable(
        data=tbl_df.to_dict("records"),
        columns=[{"name": c, "id": c} for c in tbl_df.columns],
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": BG3, "color": TEXT, "border": "1px solid #30363d",
                    "fontSize": "13px", "padding": "6px 10px"},
        style_header={"backgroundColor": BG2, "color": ACCENT, "fontWeight": "600",
                      "border": "1px solid #30363d"},
        style_data_conditional=[
            {"if": {"filter_query": '{YoY Δ} contains "+"', "column_id": "YoY Δ"},
             "color": GREEN, "fontWeight": "600"},
            {"if": {"filter_query": '{YoY Δ} contains "-"', "column_id": "YoY Δ"},
             "color": RED, "fontWeight": "600"},
            {"if": {"filter_query": '{Period} != "%s"' % _newest, "column_id": "Period"},
             "color": YELLOW, "fontWeight": "600"},
            # SC-05: visibly distinguish published vs. modeled provenance per row.
            {"if": {"filter_query": '{Source} = "%s"' % SRC_MODELED, "column_id": "Source"},
             "color": YELLOW},
            {"if": {"filter_query": '{Source} = "%s"' % SRC_PUBLISHED, "column_id": "Source"},
             "color": GREEN},
            {"if": {"row_index": "odd"}, "backgroundColor": BG2},
        ],
    )

    dram_note = html.P(
        "This chart shows each series in its ORIGINAL quoted unit — for a like-for-like "
        "comparison see the normalized USD/GB chart above. "
        "DDR4 (8Gb die) and DDR5 (16Gb die) are quoted in USD per benchmark die — "
        "the single bare chip that OEMs solder onto a DIMM; these prices move with "
        "consumer PC demand and inventory cycles. "
        "HBM3/HBM3E (USD per GB of stack capacity) is no longer plotted — see the "
        "withdrawal notice above. An amber period marks a series that is no longer quoted.",
        style={"color": SUBTEXT, "fontSize": "12px", "marginBottom": "10px"},
    )

    # Withdrawn-data disclosure. The DDR series has a deliberate 17-month hole;
    # without saying so, a reader sees a broken line and assumes a rendering bug
    # rather than a data decision. (BACKLOG SC-04)
    dram_gap_note = html.Div(
        "⚠️ DDR4/DDR5 data between Jan 2025 and early 2026 has been WITHDRAWN, not lost. Those "
        "rows decayed ~1–2% every month for 17 straight months while TrendForce reported "
        "conventional DRAM contract prices rising 93–98% QoQ in 1Q26 — the series was "
        "synthetic and is now deleted rather than shown. The break in the line is the gap; "
        "the 2024 and 2026 points are not continuous. The 2026 points are individually "
        "sourced TrendForce spot observations (date stamped in the Source column), not a "
        "backfill — DDR5 currently has a single 2026 anchor, so read it as a level check, "
        "not a trend (BACKLOG SC-04 / SC-08). "
        "⚠️ ALL HBM3/HBM3E rows have also been WITHDRAWN (BACKLOG SC-09): HBM3E rose exactly "
        "+$0.20 every two-month step for 15 consecutive steps and never once deviated — the "
        "same synthetic shape as the DDR rows above, and probably the wrong direction, since "
        "HBM3E contract prices fell from their H1-2025 peak before a mid-2026 rebound. No "
        "citable per-GB anchor was found, so nothing replaces them rather than an estimate "
        "being shown.",
        style={
            "color": YELLOW, "fontSize": "11px", "fontWeight": "600",
            "border": f"1px solid {YELLOW}", "borderRadius": "4px",
            "padding": "6px 10px", "marginBottom": "10px",
        },
    )

    return html.Div([
        _card([
            _section_title("DRAM & HBM Spot / Contract Prices"),
            dram_gap_note,
            dram_note,
            dcc.Graph(figure=fig, config={"displayModeBar": True}),
        ]),
        _card([
            _section_title("DRAM & HBM — Latest Spot Prices & Year-on-Year Change"),
            tbl,
            _source_footer(f"{SRC_PUBLISHED} (DDR4/DDR5)",
                           "DDR4 8Gb 1Gx8 & DDR5 16Gb 2Gx8: transcribed from TrendForce/DRAMeXchange's free "
                           "weekly spot-price articles (USD/die) — a public release, not a licensed feed. "
                           "HBM3 8-Hi / HBM3E 12-Hi: WITHDRAWN 2026-08-02 — HBM contract prices are not "
                           "publicly quoted per GB, and this project's own estimate of them was synthetic "
                           "(BACKLOG SC-09). The series returns only when a dated primary release quotes an "
                           "explicit figure. "
                           "YoY is anchored to each series' own latest observation, so a superseded series reports "
                           "'—' rather than a false 0.0%. "
                           "Update CURATED_DRAM_SPOT in products_config.py monthly."),
        ]),
    ])


def _sc_enterprise_gpu_section():
    """
    Enterprise / Data-Center GPU price index with:
    - Per-card contract price history for A100, H100, H200, B200, MI300X
    - Flagship-era shaded bands (Ampere → Hopper → Hopper+ → Blackwell)
    - Product launch / GA vertical annotations
    - FP16 TFLOPS vs latest price scatter (instead of consumer PassMark)
    - YoY price change table
    """
    df_curated = sc_prices_query("GPU-Enterprise", source="curated")

    # ── Generation milestone definitions ─────────────────────────────────────
    # (era_label, x0, x1, fill_rgba, text_color, text)
    FLAGSHIP_ERAS = [
        ("Ampere Era (A100)",  "2020-11-01", "2022-10-31", "rgba(139,92,246,0.07)",  "#9d7dea", "Ampere"),
        ("Hopper Era (H100)",  "2022-11-01", "2024-05-31", "rgba(0,163,224,0.07)",   "#0071C5", "Hopper"),
        ("Hopper+ (H200)",     "2024-06-01", "2024-11-30", "rgba(0,200,180,0.07)",   "#00C8B4", "H200"),
        ("Blackwell (B200)",   "2024-12-01", "2026-07-31", "rgba(118,185,0,0.07)",   "#76b900", "Blackwell"),
    ]
    # (model_id, ga_date, label, color)
    GA_MARKERS = [
        ("A100-SXM4-80GB",  "2020-11-01", "A100 Launch",    "#9d7dea"),
        ("H100-SXM5-80GB",  "2022-11-01", "H100 GA",        "#0071C5"),
        ("MI300X-192GB",    "2024-01-01", "MI300X GA",      "#ED1C24"),
        ("H200-SXM-141GB",  "2024-06-01", "H200 GA",        "#00C8B4"),
        ("B200-SXM-192GB",  "2024-12-01", "B200 GA",        "#76b900"),
    ]
    COLOR_BY_MODEL = {
        "A100-SXM4-80GB":  "#9d7dea",
        "H100-SXM5-80GB":  "#0071C5",
        "H200-SXM-141GB":  "#00C8B4",
        "B200-SXM-192GB":  "#76b900",
        "MI300X-192GB":    "#ED1C24",
    }

    # ── Price history line chart ───────────────────────────────────────────────
    fig_price = go.Figure()

    if not df_curated.empty:
        for mid, grp in df_curated.groupby("model_id"):
            grp = grp.sort_values("date")
            prod_name = grp["name"].iloc[0] if "name" in grp.columns else mid
            col = COLOR_BY_MODEL.get(mid, CHART_COLORS[0])
            fig_price.add_trace(go.Scatter(
                x=grp["date"], y=grp["price_usd"],
                name=prod_name + _MODELED_SUFFIX,
                **_trace_style(True, col),          # SC-16: modeled, never a solid line
                hovertemplate=(
                    f"<b>{prod_name}</b> (modeled)<br>%{{x|%b %Y}}<br>"
                    f"Price: $%{{y:,.0f}}<extra></extra>"
                ),
            ))

    fig_price.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="Enterprise GPU — Estimated Contract/Spot Price (USD/card)",
        height=400, xaxis_title="", yaxis_title="Price (USD / card)",
    )

    # Flagship-era shaded backgrounds
    for (era_label, x0, x1, fill, tc, short) in FLAGSHIP_ERAS:
        fig_price.add_vrect(
            x0=x0, x1=x1, fillcolor=fill, line_width=0,
            annotation_text=short, annotation_position="top left",
            annotation=dict(font_size=10, font_color=tc, yshift=-14),
        )

    # Product GA vertical dashed lines
    for (mid, ga_date, label, col) in GA_MARKERS:
        fig_price.add_vline(
            x=ga_date, line_dash="dot", line_color=col, line_width=1.5,
            annotation_text=f"◆ {label}",
            annotation_position="top right",
            annotation=dict(font_size=9, font_color=col, textangle=-90, yshift=-10),
        )

    # Anchor x-axis to data
    if not df_curated.empty:
        _pr_end_dt = pd.to_datetime(df_curated["date"].max())
        _pr_rend   = (_pr_end_dt + pd.DateOffset(months=2)).strftime("%Y-%m-%d")
        _pr_rstart = (_pr_end_dt - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
    else:
        _pr_rend   = _now_hkt().strftime("%Y-%m-%d")
        _pr_rstart = _range_start(1)
    fig_price.update_xaxes(
        type="date",
        rangeselector=_time_rangeselector(active_index=1),   # 3Y default
        range=[_pr_rstart, _pr_rend],
        rangeslider=dict(visible=False),
    )
    _apply_rangeselector_layout(fig_price, extra_height=90)

    # ── FP16 TFLOPS vs Latest Price scatter ──────────────────────────────────
    # Use specs from GPU_ENTERPRISE_PRODUCTS.tflops_fp16_dense
    fig_perf = go.Figure()
    if not df_curated.empty:
        latest_price = (
            df_curated.sort_values("date")
            .groupby("model_id")[["price_usd", "name"]]
            .last()
            .reset_index()
        )
        for _, row in latest_price.iterrows():
            mid   = row["model_id"]
            prod  = GPU_ENTERPRISE_PRODUCTS.get(mid, {})
            tflops = prod.get("tflops_fp16_dense")
            if tflops is None or pd.isna(row["price_usd"]):
                continue
            col       = COLOR_BY_MODEL.get(mid, CHART_COLORS[0])
            prod_name = row["name"] if pd.notna(row.get("name", None)) else mid
            fig_perf.add_trace(go.Scatter(
                x=[row["price_usd"]], y=[tflops],
                mode="markers+text",
                name=prod_name,
                text=[prod_name],
                textposition="top center",
                textfont=dict(size=9),
                marker=dict(size=14, color=col, line=dict(width=1, color="#30363d")),
                hovertemplate=(
                    f"<b>{prod_name}</b><br>Latest price: $%{{x:,.0f}}<br>"
                    f"FP16 Dense: {tflops} TFLOPS<extra></extra>"
                ),
            ))
    fig_perf.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="Enterprise GPU — FP16 Dense TFLOPS vs Latest Price",
        height=360, xaxis_title="Latest Contract Price (USD/card)",
        yaxis_title="FP16 Dense TFLOPS", showlegend=False,
    )

    # ── YoY price change table ─────────────────────────────────────────────────
    yoy_section = html.Span()
    if not df_curated.empty:
        latest_snap = (
            df_curated.sort_values("date")
            .groupby("model_id")
            .last()
            .reset_index()[["model_id", "date", "price_usd"]]
        )
        _cutoff_1y = (pd.Timestamp(_now_hkt()) - pd.DateOffset(months=12)).strftime("%Y-%m-%d")
        hist_1y = (
            df_curated[df_curated["date"] <= _cutoff_1y]
            .sort_values("date")
            .groupby("model_id")["price_usd"]
            .last()
            .rename("price_1y_ago")
        )
        yoy_df = (
            latest_snap
            .merge(df_curated[["model_id", "name"]].drop_duplicates("model_id"),
                   on="model_id", how="left")
            .merge(hist_1y, on="model_id", how="left")
        )
        yoy_df["YoY Δ"] = yoy_df.apply(
            lambda r: f"{(r['price_usd'] / r['price_1y_ago'] - 1) * 100:+.1f}%"
                      if pd.notna(r["price_1y_ago"]) and r["price_1y_ago"] > 0 else "—",
            axis=1,
        )
        yoy_df["Generation"] = yoy_df["model_id"].map({
            "A100-SXM4-80GB": "Ampere",
            "H100-SXM5-80GB": "Hopper",
            "H200-SXM-141GB": "Hopper+",
            "B200-SXM-192GB": "Blackwell",
            "MI300X-192GB":   "CDNA3 (AMD)",
        }).fillna("—")
        yoy_df["FP16 TFLOPS"] = yoy_df["model_id"].map(
            {mid: str(p.get("tflops_fp16_dense", "—"))
             for mid, p in GPU_ENTERPRISE_PRODUCTS.items()}
        ).fillna("—")
        yoy_df = yoy_df.rename(columns={
            "name": "Product", "date": "As of",
            "price_usd": "Latest Price (USD)", "price_1y_ago": "Price 1Y Ago (USD)",
        })
        yoy_df["Latest Price (USD)"] = yoy_df["Latest Price (USD)"].map(
            lambda x: f"${x:,.0f}" if pd.notna(x) else "—")
        yoy_df["Price 1Y Ago (USD)"] = yoy_df["Price 1Y Ago (USD)"].map(
            lambda x: f"${x:,.0f}" if pd.notna(x) else "—")
        yoy_df = yoy_df[[
            "Product", "Generation", "FP16 TFLOPS",
            "Latest Price (USD)", "Price 1Y Ago (USD)", "YoY Δ",
        ]]
        yoy_tbl = dash_table.DataTable(
            data=yoy_df.to_dict("records"),
            columns=[{"name": c, "id": c} for c in yoy_df.columns],
            sort_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"backgroundColor": BG3, "color": TEXT,
                        "border": "1px solid #30363d",
                        "fontSize": "13px", "padding": "6px 10px"},
            style_header={"backgroundColor": BG2, "color": ACCENT,
                          "fontWeight": "600", "border": "1px solid #30363d"},
            style_data_conditional=[
                {"if": {"row_index": "odd"}, "backgroundColor": BG2},
                {"if": {"filter_query": '{YoY Δ} contains "+"', "column_id": "YoY Δ"},
                 "color": GREEN, "fontWeight": "600"},
                {"if": {"filter_query": '{YoY Δ} contains "-"', "column_id": "YoY Δ"},
                 "color": RED, "fontWeight": "600"},
            ],
        )
        yoy_section = _card([
            _section_title("Enterprise GPU — Latest Prices & Year-on-Year Change"),
            yoy_tbl,
        ])

    return html.Div([
        dbc.Row([
            dbc.Col(_card([_modeled_note("Enterprise GPU contract prices (A100 / H100 / H200 / B200 / MI300X)"), dcc.Graph(figure=fig_price, config={"displayModeBar": True})]), width=7),
            dbc.Col(_card(dcc.Graph(figure=fig_perf,  config={"displayModeBar": True})), width=5),
        ]),
        yoy_section,
        _card(_source_footer(
            f"NVIDIA / AMD Official Specs (hardware) · {SRC_MODELED} (pricing)",
            "Hardware specs (VRAM, FP16 Dense TFLOPS — no sparsity multiplier) are from "
            "official datasheets — a primary source. "
            "Contract/spot PRICES are this project's modeled estimate, informed by TrendForce "
            "enterprise-GPU channel commentary, public cloud GPU spot pricing, and analyst "
            "research (Goldman Sachs / Wells Fargo) — none of those are a licensed feed this "
            "project holds, so treat price levels as directional, not quoted. "
            "Not retail — enterprise GPUs are sold via OEM/cloud channels. "
            "Flagship eras: Ampere (A100) → Hopper (H100) → Hopper+ (H200) → Blackwell (B200). "
            "Update GPU_ENTERPRISE_PRODUCTS in products_config.py monthly.",
        )),
    ])


def _sc_enterprise_cpu_section():
    """
    Enterprise / Data-Center CPU price index with:
    - Per-SKU contract ASP history for EPYC Genoa, Xeon SPR, Xeon EMR, EPYC Turin
    - Generation era shaded bands (Genoa/SPR → EMR/Turin)
    - CPU GA vertical annotations
    - Core count vs latest price scatter (enterprise proxy for performance/$ value)
    - YoY price change table
    """
    df_curated = sc_prices_query("CPU-Enterprise", source="curated")

    # ── Generation era definitions ────────────────────────────────────────────
    CPU_ERAS = [
        ("Genoa + SPR Era",  "2022-11-01", "2023-12-31", "rgba(237,28,36,0.06)",   "#ED1C24", "Genoa/SPR"),
        ("EMR + Turin Era",  "2024-01-01", "2026-07-31", "rgba(0,113,197,0.06)",   "#0071C5", "EMR/Turin"),
    ]
    CPU_GA_MARKERS = [
        ("2022-11-01", "EPYC 9654 GA\n(Genoa, Zen 4)",         "#ED1C24"),
        ("2023-01-01", "Xeon 8490H GA\n(Sapphire Rapids)",     "#9d7dea"),
        ("2024-01-01", "Xeon 8592+ GA\n(Emerald Rapids)",      "#0071C5"),
        ("2024-10-01", "EPYC 9965 GA\n(Turin, Zen 5)",         "#FF9E1B"),
    ]
    # Warm hues = AMD, cool hues = Intel, so vendor is readable at a glance.
    # EPYC-9965 is deliberately amber, NOT the teal it used to be: it tracks
    # within $800 of Xeon-8592+ for every one of their 20 shared months, and
    # teal-next-to-blue made that the least separable pair on the chart.
    COLOR_BY_MODEL = {
        "EPYC-9654":  "#ED1C24",   # AMD red
        "EPYC-9965":  "#FF9E1B",   # AMD amber
        "Xeon-8490H": "#9d7dea",   # Intel violet
        "Xeon-8592+": "#0071C5",   # Intel blue
    }
    # Colour still is not enough on its own, so pair every colour with a
    # distinct dash pattern + marker symbol — this keeps the series readable
    # where they converge, in greyscale, and for colour-blind users.
    # Labels are deliberately short — the DB `name` is verbose ("AMD EPYC 9654
    # (96-core, Genoa)") and four of those in a horizontal legend wrap over the
    # chart title. These still carry SKU, core count and generation.
    STYLE_BY_MODEL = {
        # model_id:   (dash,      marker symbol,  legend label)
        "EPYC-9654":  ("solid",   "circle",       "EPYC 9654 · 96C Genoa"),
        "Xeon-8490H": ("dash",    "square",       "Xeon 8490H · 60C SPR"),
        "Xeon-8592+": ("dot",     "diamond",      "Xeon 8592+ · 60C EMR"),
        "EPYC-9965":  ("dashdot", "triangle-up",  "EPYC 9965 · 192C Turin"),
    }

    # ── Price history line chart ──────────────────────────────────────────────
    fig_price = go.Figure()
    if not df_curated.empty:
        # Sort traces so the legend reads in a stable, vendor-grouped order
        # rather than whatever order groupby happens to yield.
        _order = list(STYLE_BY_MODEL.keys())
        _groups = sorted(
            df_curated.groupby("model_id"),
            key=lambda kv: (_order.index(kv[0]) if kv[0] in _order else 99, kv[0]),
        )
        for mid, grp in _groups:
            grp = grp.sort_values("date")
            prod_name = grp["name"].iloc[0] if "name" in grp.columns else mid
            col = COLOR_BY_MODEL.get(mid, CHART_COLORS[0])
            dash, symbol, legend_name = STYLE_BY_MODEL.get(
                mid, ("solid", "circle", prod_name))
            fig_price.add_trace(go.Scatter(
                x=grp["date"], y=grp["price_usd"],
                name=legend_name + _MODELED_SUFFIX,
                mode="lines+markers",
                # SC-16: modeled — dotted connector, open marker. `symbol` still
                # distinguishes the vendor; "-open" is appended so the modeled
                # convention survives whatever symbol this series uses.
                line=dict(width=1, color=col, dash="dot"),
                marker=dict(size=7, symbol=str(symbol).replace("-open", "") + "-open",
                            color=col),
                opacity=0.85,
                hovertemplate=(
                    f"<b>{prod_name}</b> (modeled)<br>%{{x|%b %Y}}<br>"
                    f"Price: $%{{y:,.0f}}<extra></extra>"
                ),
            ))

    fig_price.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="Enterprise CPU — Estimated ODP / Contract ASP (USD/socket)",
        height=400, xaxis_title="", yaxis_title="Price (USD / socket)",
    )

    for (era_label, x0, x1, fill, tc, short) in CPU_ERAS:
        fig_price.add_vrect(
            x0=x0, x1=x1, fillcolor=fill, line_width=0,
            annotation_text=short, annotation_position="top left",
            annotation=dict(font_size=10, font_color=tc, yshift=-14),
        )
    for (ga_date, label, col) in CPU_GA_MARKERS:
        fig_price.add_vline(
            x=ga_date, line_dash="dot", line_color=col, line_width=1.5,
            annotation_text=f"◆ {label}",
            annotation_position="top right",
            annotation=dict(font_size=9, font_color=col, textangle=-90, yshift=-10),
        )

    if not df_curated.empty:
        _pr_end_dt = pd.to_datetime(df_curated["date"].max())
        _pr_rend   = (_pr_end_dt + pd.DateOffset(months=2)).strftime("%Y-%m-%d")
        _pr_rstart = (_pr_end_dt - pd.DateOffset(years=2)).strftime("%Y-%m-%d")
    else:
        _pr_rend   = _now_hkt().strftime("%Y-%m-%d")
        _pr_rstart = _range_start(2)
    fig_price.update_xaxes(
        type="date",
        rangeselector=_time_rangeselector(active_index=1),   # 3Y default
        range=[_pr_rstart, _pr_rend],
        rangeslider=dict(visible=False),
    )
    _apply_rangeselector_layout(fig_price, extra_height=90)

    # ── Core Count vs Latest Price scatter (enterprise perf/$) ──────────────
    fig_perf = go.Figure()
    if not df_curated.empty:
        latest_price = (
            df_curated.sort_values("date")
            .groupby("model_id")[["price_usd", "name"]]
            .last()
            .reset_index()
        )
        for _, row in latest_price.iterrows():
            mid  = row["model_id"]
            prod = CPU_ENTERPRISE_PRODUCTS.get(mid, {})
            cores = prod.get("cores")
            if cores is None or pd.isna(row["price_usd"]):
                continue
            col       = COLOR_BY_MODEL.get(mid, CHART_COLORS[0])
            prod_name = row["name"] if pd.notna(row.get("name")) else mid
            tdp       = prod.get("tdp_w", "—")
            fig_perf.add_trace(go.Scatter(
                x=[row["price_usd"]], y=[cores],
                mode="markers+text",
                name=prod_name,
                text=[prod_name],
                textposition="top center",
                textfont=dict(size=9),
                marker=dict(size=14, color=col, line=dict(width=1, color="#30363d")),
                hovertemplate=(
                    f"<b>{prod_name}</b><br>Latest price: $%{{x:,.0f}}<br>"
                    f"Cores: {cores}  TDP: {tdp}W<extra></extra>"
                ),
            ))
    fig_perf.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="Enterprise CPU — Core Count vs Latest Price",
        height=360,
        xaxis_title="Latest Contract ASP (USD / socket)",
        yaxis_title="Physical Cores",
        showlegend=False,
    )

    # ── YoY price change table ────────────────────────────────────────────────
    yoy_section = html.Span()
    if not df_curated.empty:
        latest_snap = (
            df_curated.sort_values("date")
            .groupby("model_id")
            .last()
            .reset_index()[["model_id", "date", "price_usd"]]
        )
        _cutoff_1y = (pd.Timestamp(_now_hkt()) - pd.DateOffset(months=12)).strftime("%Y-%m-%d")
        hist_1y = (
            df_curated[df_curated["date"] <= _cutoff_1y]
            .sort_values("date")
            .groupby("model_id")["price_usd"]
            .last()
            .rename("price_1y_ago")
        )
        yoy_df = (
            latest_snap
            .merge(df_curated[["model_id", "name"]].drop_duplicates("model_id"),
                   on="model_id", how="left")
            .merge(hist_1y, on="model_id", how="left")
        )
        yoy_df["YoY Δ"] = yoy_df.apply(
            lambda r: f"{(r['price_usd'] / r['price_1y_ago'] - 1) * 100:+.1f}%"
                      if pd.notna(r.get("price_1y_ago")) and r["price_1y_ago"] > 0 else "—",
            axis=1,
        )
        yoy_df["Generation"] = yoy_df["model_id"].map({
            "EPYC-9654":  "Genoa (Zen 4)",
            "Xeon-8490H": "Sapphire Rapids",
            "Xeon-8592+": "Emerald Rapids",
            "EPYC-9965":  "Turin (Zen 5)",
        }).fillna("—")
        yoy_df["Cores"] = yoy_df["model_id"].map(
            {mid: str(p.get("cores", "—")) for mid, p in CPU_ENTERPRISE_PRODUCTS.items()}
        ).fillna("—")
        yoy_df["TDP (W)"] = yoy_df["model_id"].map(
            {mid: str(p.get("tdp_w", "—")) for mid, p in CPU_ENTERPRISE_PRODUCTS.items()}
        ).fillna("—")
        yoy_df = yoy_df.rename(columns={
            "name": "Product", "date": "As of",
            "price_usd": "Latest Price (USD)", "price_1y_ago": "Price 1Y Ago (USD)",
        })
        yoy_df["Latest Price (USD)"]  = yoy_df["Latest Price (USD)"].map(
            lambda x: f"${x:,.0f}" if pd.notna(x) else "—")
        yoy_df["Price 1Y Ago (USD)"]  = yoy_df["Price 1Y Ago (USD)"].map(
            lambda x: f"${x:,.0f}" if pd.notna(x) else "—")
        yoy_df = yoy_df[[
            "Product", "Generation", "Cores", "TDP (W)",
            "Latest Price (USD)", "Price 1Y Ago (USD)", "YoY Δ",
        ]]
        yoy_tbl = dash_table.DataTable(
            data=yoy_df.to_dict("records"),
            columns=[{"name": c, "id": c} for c in yoy_df.columns],
            sort_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"backgroundColor": BG3, "color": TEXT,
                        "border": "1px solid #30363d",
                        "fontSize": "13px", "padding": "6px 10px"},
            style_header={"backgroundColor": BG2, "color": ACCENT,
                          "fontWeight": "600", "border": "1px solid #30363d"},
            style_data_conditional=[
                {"if": {"row_index": "odd"}, "backgroundColor": BG2},
                {"if": {"filter_query": '{YoY Δ} contains "+"', "column_id": "YoY Δ"},
                 "color": GREEN, "fontWeight": "600"},
                {"if": {"filter_query": '{YoY Δ} contains "-"', "column_id": "YoY Δ"},
                 "color": RED, "fontWeight": "600"},
            ],
        )
        yoy_section = _card([
            _section_title("Enterprise CPU — Latest Prices & Year-on-Year Change"),
            yoy_tbl,
        ])

    return html.Div([
        dbc.Row([
            dbc.Col(_card([_modeled_note("Enterprise CPU ODP / contract ASPs (Xeon, EPYC)"), dcc.Graph(figure=fig_price, config={"displayModeBar": True})]), width=7),
            dbc.Col(_card(dcc.Graph(figure=fig_perf,  config={"displayModeBar": True})), width=5),
        ]),
        yoy_section,
        _card(_source_footer(
            f"AMD / Intel Official Launch ODP (baseline) · {SRC_MODELED} (ASP trend)",
            "Launch-date list price (Official Distributor Price) and core counts are from "
            "official product launch data — a primary source. "
            "The monthly ASP TREND is this project's modeled estimate, informed by TrendForce "
            "server-CPU channel commentary and Gartner/IDC server-market research — none of "
            "those are a licensed feed this project holds, so treat price levels as "
            "directional, not quoted. "
            "Not consumer/retail — enterprise CPUs are sold direct to OEMs and hyperscalers. "
            "Generations: Genoa (EPYC 9004, Nov 2022) → Sapphire Rapids (Xeon Gen 4, Jan 2023) → "
            "Emerald Rapids (Xeon Gen 5, Jan 2024) → Turin (EPYC 9005, Oct 2024). "
            "Update CPU_ENTERPRISE_PRODUCTS in products_config.py quarterly.",
        )),
    ])


def _sc_enterprise_ram_section():
    """
    Enterprise memory price index covering BOTH commodity DRAM and HBM:
    - DDR4 / DDR5 / HBM3 / HBM3E price history normalized to USD per GB
      (see `_mem_normalize_usd_per_gb` — DDR is quoted per die upstream)
    - HBM generation era shading + GA vertical annotations
    - Memory bandwidth vs latest price scatter (log y: DRAM and HBM differ ~46x)
    - YoY price change table with an "As of" column so superseded series are
      visibly stale rather than silently presented as current
    - Native-unit DRAM inline section below for context
    """
    df_all = sc_dram_query()
    df_mem = df_all[df_all["product_type"].isin(_MEM_SPECS.keys())].copy()
    if not df_mem.empty:
        df_mem = _mem_normalize_usd_per_gb(df_mem)

    # ── Generation era definitions ────────────────────────────────────────────
    HBM_ERAS = [
        ("HBM3 Era",  "2022-06-01", "2023-12-31", "rgba(204,93,232,0.07)", "#CC5DE8", "HBM3"),
        ("HBM3E Era", "2024-01-01", "2026-07-31", "rgba(255,107,107,0.07)", "#FF6B6B", "HBM3E"),
    ]
    HBM_MARKERS = [
        ("2022-06-01", "HBM3 GA (SK Hynix)",    "#CC5DE8"),
        ("2024-01-01", "HBM3E GA (H100/MI300X)", "#FF6B6B"),
    ]

    # ── Price history line chart (all series on one USD/GB axis) ──────────────
    fig_price = go.Figure()
    if not df_mem.empty:
        for ptype in [p for p in _MEM_ORDER if p in set(df_mem["product_type"])]:
            grp = df_mem[df_mem["product_type"] == ptype].sort_values("period_dt")
            grp = _mem_break_gaps(grp)      # never draw across a hole — SC-04
            spec = _MEM_SPECS.get(ptype, {})
            col  = _MEM_COLORS.get(ptype, CHART_COLORS[0])
            is_hbm = spec.get("class") == "HBM"
            fig_price.add_trace(go.Scatter(
                x=grp["period_dt"], y=grp["price_usd_gb"],
                name=f"{ptype} ({spec.get('config', '')})",
                mode="lines+markers",
                line=dict(width=2.5, color=col,
                          dash="solid" if is_hbm else "dot"),
                marker=dict(size=5),
                hovertemplate=(
                    f"<b>{ptype}</b> — {spec.get('class', '')}<br>%{{x|%b %Y}}<br>"
                    f"$%{{y:.2f}} / GB<extra></extra>"
                ),
            ))

    fig_price.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="Enterprise Memory — DRAM & HBM Price, Normalized (USD per GB)",
        height=400, xaxis_title="", yaxis_title="Price (USD / GB)",
    )

    # Only shade an era whose series actually has data. After SC-09 withdrew the
    # HBM rows, an unconditional band would paint a labelled "HBM3E Era" region
    # with no line inside it — which reads as a rendering fault, or worse, as a
    # series the reader failed to spot. Same §7.3 principle as the viewport bug.
    _mem_types = set(df_mem["product_type"]) if not df_mem.empty else set()
    for (era_label, x0, x1, fill, tc, short) in HBM_ERAS:
        if short not in _mem_types:
            continue
        fig_price.add_vrect(
            x0=x0, x1=x1, fillcolor=fill, line_width=0,
            annotation_text=short, annotation_position="top left",
            annotation=dict(font_size=10, font_color=tc, yshift=-14),
        )
    for (ga_date, label, col) in HBM_MARKERS:
        if not _mem_types:
            break
        fig_price.add_vline(
            x=ga_date, line_dash="dot", line_color=col, line_width=1.5,
            annotation_text=f"◆ {label}",
            annotation_position="top right",
            annotation=dict(font_size=9, font_color=col, textangle=-90, yshift=-10),
        )

    # Anchor to data end; default 5Y view. This MUST stay wide enough to cover
    # the oldest series: HBM3 ends 2023-12, so a trailing-1Y window pushed it
    # entirely off-screen — the legend entry rendered but the line did not.
    if not df_mem.empty:
        _end_dt  = df_mem["period_dt"].max()
        _rend    = (_end_dt + pd.DateOffset(months=2)).strftime("%Y-%m-%d")
        _rstart  = (_end_dt - pd.DateOffset(years=5)).strftime("%Y-%m-%d")
    else:
        _rend   = _now_hkt().strftime("%Y-%m-%d")
        _rstart = _range_start(5)
    fig_price.update_xaxes(
        type="date",
        rangeselector=_time_rangeselector(active_index=2),   # 5Y default
        range=[_rstart, _rend],
        rangeslider=dict(visible=False),
    )
    _apply_rangeselector_layout(fig_price, extra_height=90)

    # ── Bandwidth vs Latest Price scatter ─────────────────────────────────────
    # Log y-axis: commodity DIMM bandwidth (25.6 GB/s) and HBM stack bandwidth
    # (1177 GB/s) span ~46x, which flattens DDR4/DDR5 to the axis on a linear
    # scale. Bandwidth bases differ by class — see `_MEM_SPECS.bw_basis`.
    fig_perf = go.Figure()
    if not df_mem.empty:
        for ptype in [p for p in _MEM_ORDER if p in set(df_mem["product_type"])]:
            grp = df_mem[df_mem["product_type"] == ptype]
            specs = _MEM_SPECS.get(ptype)
            latest, _, _ = _mem_yoy(grp)
            if specs is None or pd.isna(latest["price_usd_gb"]):
                continue
            col = _MEM_COLORS.get(ptype, CHART_COLORS[0])
            bw  = specs["bandwidth_gbs"]
            cap = specs["capacity_gb"]
            cfg = specs["config"]
            fig_perf.add_trace(go.Scatter(
                x=[latest["price_usd_gb"]], y=[bw],
                mode="markers+text",
                name=ptype,
                text=[ptype],
                # DDR4/DDR5 sit within ~$0.04 of each other on the x-axis, so
                # centre-anchored labels collide; offset them sideways.
                textposition="top center" if specs["class"] == "HBM" else "middle right",
                textfont=dict(size=10),
                marker=dict(
                    size=16, color=col,
                    symbol="circle" if specs["class"] == "HBM" else "diamond",
                    line=dict(width=1, color="#30363d"),
                ),
                hovertemplate=(
                    f"<b>{ptype} ({cfg})</b> — {specs['class']}<br>"
                    f"Price: $%{{x:.2f}}/GB (as of {latest['period']})<br>"
                    f"Bandwidth: {bw:g} GB/s {specs['bw_basis']}<br>"
                    f"Capacity: {cap} GB per device<extra></extra>"
                ),
            ))
    fig_perf.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="DRAM vs HBM — Memory Bandwidth vs Price per GB",
        height=360,
        xaxis_title="Latest Price (USD / GB)",
        yaxis_title="Bandwidth (GB/s per DIMM ◆ / per stack ●, log)",
        showlegend=False,
    )
    fig_perf.update_yaxes(type="log")

    # ── YoY price change table ────────────────────────────────────────────────
    yoy_section = html.Span()
    if not df_mem.empty:
        _newest_period = df_mem["period"].max()
        _hbm3e_price = None
        rows = []
        for ptype in [p for p in _MEM_ORDER if p in set(df_mem["product_type"])]:
            grp = df_mem[df_mem["product_type"] == ptype]
            specs = _MEM_SPECS.get(ptype, {})
            latest, p_prev, yoy = _mem_yoy(grp)
            if ptype == "HBM3E":
                _hbm3e_price = latest["price_usd_gb"]
            rows.append({
                "Class": specs.get("class", "—"),
                "Generation": ptype,
                "Device": specs.get("config", "—"),
                "Bandwidth (GB/s)": f"{specs['bandwidth_gbs']:g}" if specs else "—",
                "Capacity (GB)": str(specs.get("capacity_gb", "—")),
                "Price (USD/GB)": (f"${latest['price_usd_gb']:.2f}"
                                   if pd.notna(latest["price_usd_gb"]) else "—"),
                "Price 1Y Ago (USD/GB)": f"${p_prev:.2f}" if p_prev is not None else "—",
                "YoY Δ": f"{yoy:+.1f}%" if yoy is not None else "—",
                "As of": str(latest["period"]),
                "Source": latest.get("source", SRC_MODELED),
            })
        yoy_df = pd.DataFrame(rows)
        yoy_tbl = dash_table.DataTable(
            data=yoy_df.to_dict("records"),
            columns=[{"name": c, "id": c} for c in yoy_df.columns],
            sort_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"backgroundColor": BG3, "color": TEXT,
                        "border": "1px solid #30363d",
                        "fontSize": "13px", "padding": "6px 10px"},
            style_header={"backgroundColor": BG2, "color": ACCENT,
                          "fontWeight": "600", "border": "1px solid #30363d"},
            style_data_conditional=[
                {"if": {"row_index": "odd"}, "backgroundColor": BG2},
                {"if": {"filter_query": '{YoY Δ} contains "+"', "column_id": "YoY Δ"},
                 "color": GREEN, "fontWeight": "600"},
                {"if": {"filter_query": '{YoY Δ} contains "-"', "column_id": "YoY Δ"},
                 "color": RED, "fontWeight": "600"},
                # Flag superseded series: any row whose latest observation is
                # older than the newest period in the table is NOT current data.
                {"if": {"filter_query": '{As of} != "%s"' % _newest_period,
                        "column_id": "As of"},
                 "color": YELLOW, "fontWeight": "600"},
                {"if": {"filter_query": '{Class} eq "HBM"', "column_id": "Generation"},
                 "fontWeight": "600"},
            ],
        )
        # Headline ratio: the whole point of normalizing to USD/GB.
        _ddr5 = df_mem[df_mem["product_type"] == "DDR5"]
        premium_note = html.Span()
        if _hbm3e_price and not _ddr5.empty:
            _d5_latest, _, _ = _mem_yoy(_ddr5)
            if pd.notna(_d5_latest["price_usd_gb"]) and _d5_latest["price_usd_gb"] > 0:
                premium_note = html.P(
                    f"HBM3E carries a {_hbm3e_price / _d5_latest['price_usd_gb']:.1f}× "
                    f"price premium over commodity DDR5 on a per-GB basis "
                    f"(${_hbm3e_price:.2f} vs ${_d5_latest['price_usd_gb']:.2f} per GB).",
                    style={"color": SUBTEXT, "fontSize": "12px", "marginBottom": "8px"},
                )
        yoy_section = _card([
            _section_title("DRAM & HBM — Latest Prices per GB & Year-on-Year Change"),
            premium_note,
            yoy_tbl,
        ])

    return html.Div([
        dbc.Row([
            dbc.Col(_card(dcc.Graph(figure=fig_price, config={"displayModeBar": True})), width=7),
            dbc.Col(_card(dcc.Graph(figure=fig_perf,  config={"displayModeBar": True})), width=5),
        ]),
        yoy_section,
        _card(_source_footer(
            f"{SRC_PUBLISHED} (DDR4/DDR5) / {SRC_MODELED} (HBM3/HBM3E) · "
            "SK Hynix / Samsung / Micron Earnings Transcripts",
            "⚠ DERIVED FIGURES — DDR4/DDR5 are sourced as USD per benchmark die (transcribed "
            "from a TrendForce/DRAMeXchange public release) and are "
            "converted here to USD/GB by dividing by the die's own capacity "
            "(DDR4 8Gb 1Gx8 die = 1 GB; DDR5 16Gb 2Gx8 die = 2 GB). HBM3/HBM3E are "
            "sourced already quoted per GB of stack capacity and pass through unchanged — "
            "contract pricing here is never publicly quoted, so it is this project's modeled "
            "estimate (see the per-row Source column in the table above). "
            "Bandwidth bases are NOT comparable device-for-device: commodity DRAM is quoted "
            "per DIMM (64-bit bus), HBM per stack (1024-bit bus) — see the ◆/● markers. "
            "Bandwidth from JEDEC spec: speed_MT/s × bus width / 8. "
            "HBM is sold only to hyperscalers and AI chip OEMs (NVIDIA, AMD, Google, Microsoft). "
            "HBM3 era: Jun 2022 – Dec 2023; HBM3E era: Jan 2024 onward (12-Hi, 96 GB, H200/MI300X). "
            "An amber 'As of' date marks a superseded series that is no longer quoted — "
            "HBM3 pricing stops at 2023-12 and is shown for generational context only. "
            "Update CURATED_DRAM_SPOT in products_config.py monthly.",
        )),
        html.Div(style={"marginTop": "8px"}),
        _sc_dram_inline(),   # consumer DDR4/DDR5 spot prices for context
    ])


def _sc_price_section(category: str):
    """Price Index + Estimated Delivery (in-stock) for one category."""
    df_pass    = sc_prices_query(category, source="passmark")
    df_new     = sc_prices_query(category, source="newegg")
    df_curated = sc_prices_query(category, source="curated")

    cat_label = {"GPU": "GPU", "GPU-Enterprise": "Enterprise GPU",
                 "CPU": "CPU", "RAM": "RAM Memory"}[category]
    COLOR_MAP = {
        "NVIDIA": "#76b900", "AMD": "#ED1C24", "Intel": "#0071C5",
        "Samsung": "#1428A0", "SK Hynix": "#F15A24", "Micron": "#E31837",
    }

    # ── Price history line chart — synced date range with DRAM panel ─────
    # Priority: PassMark historical > Curated (for RAM) > Newegg (bar, fallback)
    # SC-16: show BOTH sources rather than picking one. The curated backbone is
    # modeled (open markers, dotted) and the PassMark observations are drawn solid
    # on the same axes, so the point where real data starts is visible. Previously
    # this chose df_pass OR df_curated, which hid whichever it did not pick and
    # made a modeled series indistinguishable from a measured one.
    fig_price = go.Figure()
    _hist_parts = [(df_curated, True), (df_pass, False)]
    _colors = {}
    if any(not d.empty for d, _ in _hist_parts):
        for d, is_modeled in _hist_parts:
            if d.empty:
                continue
            for mid, grp in d.groupby("model_id"):
                grp   = grp.sort_values("date")
                short = grp["name"].iloc[0] if "name" in grp.columns else mid
                col   = _colors.setdefault(mid, CHART_COLORS[len(_colors) % len(CHART_COLORS)])
                fig_price.add_trace(go.Scatter(
                    x=grp["date"], y=grp["price_usd"],
                    name=short + (_MODELED_SUFFIX if is_modeled else "  (PassMark)"),
                    legendgroup=mid,
                    **_trace_style(is_modeled, col),
                    hovertemplate=(f"<b>{short}</b>"
                                   f"{' (modeled)' if is_modeled else ' (PassMark observed)'}"
                                   f"<br>Date: %{{x}}<br>Price: $%{{y:.0f}}<extra></extra>"),
                ))
    df_hist = df_pass if not df_pass.empty else df_curated
    _plotted = any(not d.empty for d, _ in _hist_parts)
    if not _plotted and not df_new.empty:
        latest = df_new.sort_values("date").groupby("model_id").last().reset_index()
        fig_price.add_trace(go.Bar(
            x=latest["name"] if "name" in latest else latest["model_id"],
            y=latest["price_usd"],
            marker_color=ACCENT,
            hovertemplate="<b>%{x}</b><br>Price: $%{y:.0f}<extra></extra>",
        ))
    fig_price.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title=f"{cat_label} — Price Index (USD)",
        height=360, xaxis_title="Date", yaxis_title="Retail Price (USD)",
    )
    # Anchor range to actual data end so the default 1Y view is not empty
    # when curated prices lag today.
    if not df_hist.empty:
        _pr_end_dt   = pd.to_datetime(df_hist["date"].max())
        _pr_rend     = (_pr_end_dt + pd.DateOffset(months=2)).strftime("%Y-%m-%d")
        _pr_rstart   = (_pr_end_dt - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
    else:
        _pr_rend   = _now_hkt().strftime("%Y-%m-%d")
        _pr_rstart = _range_start(1)
    fig_price.update_xaxes(
        type="date",
        rangeselector=_time_rangeselector(active_index=0),   # 1Y default
        range=[_pr_rstart, _pr_rend],
        rangeslider=dict(visible=False),
    )
    _apply_rangeselector_layout(fig_price)

    # ── Performance / Price scatter ───────────────────────────────────────
    fig_pp = go.Figure()
    if category == "RAM":
        # RAM has no PassMark scores — show Speed (MHz) vs Latest Price scatter
        _pp_title    = f"{cat_label} — Speed vs Price (MHz / USD)"
        _pp_y_label  = "Speed (MHz)"
        # Get latest curated price per product
        _ram_latest: dict = {}
        if not df_curated.empty:
            _ram_grp = (df_curated.sort_values("date")
                        .groupby("model_id").last()
                        .reset_index())
            for _, _r in _ram_grp.iterrows():
                _ram_latest[_r["model_id"]] = float(_r["price_usd"])
        _type_color = {
            "DDR5":    CHART_COLORS[0],
            "DDR4":    CHART_COLORS[1],
            "HBM3E":   CHART_COLORS[2],
            "HBM3":    CHART_COLORS[3],
            "LPDDR5X": CHART_COLORS[4],
        }
        for i, (mid, prod) in enumerate(RAM_PRODUCTS.items()):
            speed = prod.get("speed_mhz")
            price = _ram_latest.get(mid) or prod.get("msrp_usd")
            if speed is None or price is None:
                continue  # skip HBM stacks with no retail price
            rtype = prod.get("type", "")
            col   = _type_color.get(rtype, CHART_COLORS[i % len(CHART_COLORS)])
            label = prod.get("name", mid)
            cap   = prod.get("capacity_gb", "?")
            fig_pp.add_trace(go.Scatter(
                x=[price], y=[speed],
                mode="markers+text",
                name=label,
                text=[label],
                textposition="top center",
                textfont=dict(size=9),
                marker=dict(size=12, color=col, line=dict(width=1, color="#30363d")),
                hovertemplate=(
                    f"<b>{label}</b><br>Price: $%{{x:.0f}}"
                    f"<br>Speed: %{{y:,}} MHz"
                    f"<br>Capacity: {cap} GB"
                    f"<br>Type: {rtype}<extra></extra>"
                ),
            ))
    else:
        _pp_title   = f"{cat_label} — Performance vs Price (PassMark Score / USD)"
        _pp_y_label = "PassMark Score"
        if not df_pass.empty:
            latest_pass = df_pass.dropna(subset=["passmark_score", "price_usd"])
            latest_pass = (latest_pass.sort_values("date")
                           .groupby("model_id").last()
                           .reset_index())
            if not latest_pass.empty:
                for i, row in latest_pass.iterrows():
                    brand = row.get("brand", "")
                    col   = COLOR_MAP.get(brand, CHART_COLORS[i % len(CHART_COLORS)])
                    fig_pp.add_trace(go.Scatter(
                        x=[row["price_usd"]], y=[row["passmark_score"]],
                        mode="markers+text",
                        name=row.get("name", row["model_id"]),
                        text=[row.get("name", row["model_id"])],
                        textposition="top center",
                        textfont=dict(size=9),
                        marker=dict(size=12, color=col, line=dict(width=1, color="#30363d")),
                        hovertemplate=(
                            f"<b>%{{text}}</b><br>Price: $%{{x:.0f}}"
                            f"<br>Score: %{{y:,.0f}}<extra></extra>"
                        ),
                    ))
    fig_pp.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title=_pp_title,
        height=320, xaxis_title="Retail Price (USD)",
        yaxis_title=_pp_y_label, showlegend=False,
    )

    # ── Latest Prices & Year-on-Year Change table ─────────────────────────
    yoy_section = html.Span()   # empty by default; skipped for RAM (DRAM inline section serves this role)
    if category != "RAM" and not df_hist.empty:
        # Latest price per product and price ~12 months prior
        latest_snap = (df_hist.sort_values("date")
                       .groupby("model_id")
                       .last()
                       .reset_index()[["model_id", "date", "price_usd"]])
        _cutoff_1y = (pd.Timestamp(_now_hkt()) - pd.DateOffset(months=12)).strftime("%Y-%m-%d")
        hist_1y = (df_hist[df_hist["date"] <= _cutoff_1y]
                   .sort_values("date")
                   .groupby("model_id")["price_usd"]
                   .last()
                   .rename("price_1y_ago"))
        yoy_df = latest_snap.merge(
            df_hist[["model_id", "name"]].drop_duplicates("model_id"),
            on="model_id", how="left",
        ).merge(hist_1y, on="model_id", how="left")
        yoy_df["YoY Δ"] = yoy_df.apply(
            lambda r: f"{(r['price_usd'] / r['price_1y_ago'] - 1) * 100:+.1f}%"
                      if pd.notna(r["price_1y_ago"]) and r["price_1y_ago"] > 0 else "—",
            axis=1,
        )
        yoy_df = yoy_df.rename(columns={
            "name": "Product", "date": "As of",
            "price_usd": "Latest Price (USD)", "price_1y_ago": "Price 1Y Ago (USD)",
        })
        yoy_df["Latest Price (USD)"] = yoy_df["Latest Price (USD)"].map(
            lambda x: f"${x:,.0f}" if pd.notna(x) else "—")
        yoy_df["Price 1Y Ago (USD)"] = yoy_df["Price 1Y Ago (USD)"].map(
            lambda x: f"${x:,.0f}" if pd.notna(x) else "—")
        yoy_df = yoy_df[["Product", "As of", "Latest Price (USD)",
                          "Price 1Y Ago (USD)", "YoY Δ"]]
        yoy_tbl = dash_table.DataTable(
            data=yoy_df.to_dict("records"),
            columns=[{"name": c, "id": c} for c in yoy_df.columns],
            sort_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"backgroundColor": BG3, "color": TEXT,
                        "border": "1px solid #30363d",
                        "fontSize": "13px", "padding": "6px 10px"},
            style_header={"backgroundColor": BG2, "color": ACCENT,
                          "fontWeight": "600", "border": "1px solid #30363d"},
            style_data_conditional=[
                {"if": {"row_index": "odd"}, "backgroundColor": BG2},
                {"if": {"filter_query": '{YoY Δ} contains "+"', "column_id": "YoY Δ"},
                 "color": GREEN, "fontWeight": "600"},
                {"if": {"filter_query": '{YoY Δ} contains "-"', "column_id": "YoY Δ"},
                 "color": RED, "fontWeight": "600"},
            ],
        )
        yoy_section = _card([
            _section_title(f"{cat_label} — Latest Prices & Year-on-Year Change"),
            yoy_tbl,
        ])

    # ── In-stock / Estimated Delivery table (Newegg) ─────────────────────
    delivery_section = html.Span()  # hidden if no Newegg data
    if not df_new.empty:
        latest_new = df_new.sort_values("date").groupby("model_id").last().reset_index()
        latest_new["Status"]  = latest_new["in_stock"].map(
            {1: "✅ In Stock", 0: "❌ Out of Stock"}).fillna("❓ Unknown")
        latest_new["Price"]   = latest_new["price_usd"].map(
            lambda x: f"${x:,.0f}" if pd.notna(x) else "—")
        tbl_df = latest_new[["name", "Price", "Status", "date"]].rename(
            columns={"name": "Product", "date": "Checked"})
        tbl = dash_table.DataTable(
            data=tbl_df.to_dict("records"),
            columns=[{"name": c, "id": c} for c in tbl_df.columns],
            sort_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"backgroundColor": BG3, "color": TEXT, "border": "1px solid #30363d",
                        "fontSize": "13px", "padding": "6px 10px"},
            style_header={"backgroundColor": BG2, "color": ACCENT, "fontWeight": "600",
                          "border": "1px solid #30363d"},
            style_data_conditional=[
                {"if": {"filter_query": '{Status} contains "In Stock"'}, "color": GREEN},
                {"if": {"filter_query": '{Status} contains "Out of Stock"'}, "color": RED},
            ],
        )
        delivery_section = _card([
            _section_title(f"Estimated Delivery — {cat_label} (Newegg Stock Status)"),
            tbl,
        ])

    # ── For RAM: embed DRAM & HBM spot prices inline (expanded height) ───
    dram_section = html.Span()
    if category == "RAM":
        dram_section = _sc_dram_inline(height=500)

    return html.Div([
        dbc.Row([
            dbc.Col(_card([_modeled_note("The curated price backbone on this chart"), dcc.Graph(figure=fig_price, config={"displayModeBar": True})]), width=7),
            dbc.Col(_card(dcc.Graph(figure=fig_pp,    config={"displayModeBar": True})), width=5),
        ]),
        yoy_section,
        dram_section,
        delivery_section,
        _card(_source_footer(
            f"PassMark / Newegg (live) · {CURATED_RETAIL_PROVENANCE} (historical curated pricing)",
            "Today's price + stock status: live PassMark benchmark database / Newegg listing. "
            "Historical/pre-launch price trend (source='curated' rows): this project's modeled "
            "reconstruction from public retail listings — not a licensed TrendForce feed. "
            "YoY: latest vs same month prior year. "
            "Performance/Price scatter: PassMark Score vs retail USD. "
            "Run supply_chain_crawler.py to refresh.",
        )),
    ])


# ── Steam HW Survey (Sales Volume proxy) ─────────────────────────────────────

def _sc_steam_panel():
    df = sc_steam_query()

    if df.empty:
        return _card([
            _section_title("Sales Volume — GPU Market Share (Steam Hardware Survey)"),
            html.P("No Steam survey data yet. Run: python supply_chain_crawler.py",
                   style={"color": SUBTEXT, "fontSize": "12px"}),
        ])

    # Top 20 GPUs by share
    top = df.head(20).copy()
    top["vendor"] = top["model_name"].apply(
        lambda x: "NVIDIA" if "NVIDIA" in x.upper() or "RTX" in x.upper() or "GTX" in x.upper()
        else ("AMD" if "AMD" in x.upper() or "RADEON" in x.upper() or "RX " in x.upper()
              else ("Intel" if "INTEL" in x.upper() or "ARC" in x.upper() else "Other"))
    )
    color_map = {"NVIDIA": "#76b900", "AMD": "#ED1C24", "Intel": "#0071C5", "Other": SUBTEXT}

    fig = go.Figure(go.Bar(
        x=top["share_pct"],
        y=top["model_name"],
        orientation="h",
        marker_color=[color_map.get(v, SUBTEXT) for v in top["vendor"]],
        hovertemplate="<b>%{y}</b><br>Market Share: %{x:.2f}%<extra></extra>",
    ))
    fig.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title=f"GPU Installed-Base Market Share — Steam HW Survey ({top['period'].iloc[0]})",
        height=480, xaxis_title="% of Steam Users",
        showlegend=False,
    )
    fig.update_yaxes(autorange="reversed")

    # Vendor pie
    vendor_agg = (
        df.assign(vendor=df["model_name"].apply(
            lambda x: "NVIDIA" if "NVIDIA" in x.upper() or "RTX" in x.upper() or "GTX" in x.upper()
            else ("AMD" if "AMD" in x.upper() or "RX " in x.upper() else "Other")
        )).groupby("vendor")["share_pct"].sum().reset_index()
    )
    fig_pie = go.Figure(go.Pie(
        labels=vendor_agg["vendor"],
        values=vendor_agg["share_pct"].round(1),
        marker_colors=["#76b900", "#ED1C24", SUBTEXT],
        hole=0.45,
        hovertemplate="<b>%{label}</b>: %{value:.1f}%<extra></extra>",
    ))
    fig_pie.update_layout(**PLOTLY_TEMPLATE["layout"],
                           title="GPU Vendor Share", height=300)

    # Observation date must be visible: this panel sat on a 17-month-old snapshot
    # with no on-screen indication it had stopped updating (CLAUDE.md §7.3,
    # BACKLOG SC-02). `period` is the survey's own month, never today's date.
    _as_of = str(df["period"].max())
    try:
        _months_old = (pd.Timestamp.today().to_period("M")
                       - pd.Period(_as_of, freq="M")).n
    except Exception:
        _months_old = None
    # Valve publishes with a 1–3 month lag, so only flag at 4+ months — a badge
    # that cries wolf on normal publication lag gets ignored when it matters.
    _stale = _months_old is not None and _months_old >= 4
    _as_of_badge = html.Div(
        [
            html.Span(f"As of {_as_of}", style={"fontWeight": "700"}),
            html.Span(
                f"  ·  {_months_old} months old — live crawl may have stopped; see BACKLOG SC-02"
                if _stale else "  ·  current",
                style={"opacity": "0.85"},
            ),
        ],
        style={
            "color": RED if _stale else SUBTEXT, "fontSize": "11px",
            "marginBottom": "8px",
            "border": f"1px solid {RED}" if _stale else "none",
            "borderRadius": "4px", "padding": "4px 8px" if _stale else "0",
        },
    )

    return _card([
        _section_title("Consumer GPU Market Share — Steam Hardware Survey (Context Only)"),
        _as_of_badge,
        html.P(
            "⚠ This panel shows consumer/gaming GPU installed-base share — not enterprise datacenter shipments. "
            "It is included as a vendor market-presence proxy: NVIDIA's dominant gaming share (≈90 %) "
            "reinforces its pricing power in enterprise AI channels. "
            "For enterprise GPU unit shipments, refer to IDC / Mercury Research datacenter reports.",
            style={"color": YELLOW, "fontSize": "12px", "marginBottom": "10px",
                   "padding": "8px", "border": f"1px solid {YELLOW}",
                   "borderRadius": "4px", "backgroundColor": "rgba(255,200,0,0.05)"},
        ),
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig,     config={"displayModeBar": False}), width=8),
            dbc.Col(dcc.Graph(figure=fig_pie, config={"displayModeBar": False}), width=4),
        ]),
        html.P(
            "Steam survey reflects installed base of active gamers (~120M users), not monthly units shipped. "
            "Use as a relative vendor market-presence proxy only; "
            "enterprise AI GPU shipment volumes require IDC / Mercury Research data.",
            style={"color": SUBTEXT, "fontSize": "11px", "marginTop": "8px"},
        ),
        _source_footer(f"Valve / Steam Hardware Survey — survey month {_as_of}",
                       "Monthly survey of ~120M active Steam users. Consumer/gaming data — not enterprise "
                       "AI GPU shipments. Shares are of ALL Steam users (the page's per-DirectX-class "
                       "tables show shares within a class and are deliberately excluded)."),
    ])


# ── SEMI Book-to-Bill (Order Volume) ─────────────────────────────────────────

def _sc_demand_panel():
    """
    Macro Demand Indicators (BACKLOG SC-06 / SC-00 fix B) — replaces the
    retired sc_semi_btb panel. Four free, authoritative series in place of the
    consumer-retail proxies (Newegg/PassMark/Steam) used elsewhere in this tab:
    TSMC + UMC monthly revenue (live crawl), Korea MOTIE 20-day chip exports,
    WSTS/SIA global billings, and SEMI WWSEMS quarterly equipment billings —
    all genuinely published, not modeled (see DEMAND_INDICATOR_META).
    """
    df = sc_demand_query()

    if df.empty:
        return _card([
            _section_title("Macro Demand Indicators"),
            html.P("No demand-indicator data. Run: python supply_chain_crawler.py",
                   style={"color": SUBTEXT, "fontSize": "12px"}),
        ])

    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["yoy_pct"] = pd.to_numeric(df["yoy_pct"], errors="coerce")

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            "TSMC / UMC Monthly Revenue (NT$B)",
            "Korea Semiconductor Exports, 1st 20 Days (USD B)",
            "WSTS Global Semiconductor Sales (USD B, 3MMA)",
            "SEMI WWSEMS Equipment Billings (USD B, Quarterly)",
        ),
    )

    _tsmc = df[df["indicator_key"] == "tsmc_revenue"].sort_values("period")
    _umc  = df[df["indicator_key"] == "umc_revenue"].sort_values("period")
    fig.add_trace(go.Scatter(
        x=_tsmc["period"], y=_tsmc["value"], name="TSMC", mode="lines+markers",
        line=dict(width=2, color="#0071C5"),
        hovertemplate="<b>TSMC</b> %{x}<br>NT$%{y:.1f}B<extra></extra>",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=_umc["period"], y=_umc["value"], name="UMC", mode="lines+markers",
        line=dict(width=2, color="#76b900"),
        hovertemplate="<b>UMC</b> %{x}<br>NT$%{y:.1f}B<extra></extra>",
    ), row=1, col=1)

    _kr = df[df["indicator_key"] == "korea_chip_exports_20d"].sort_values("period")
    fig.add_trace(go.Bar(
        x=_kr["period"], y=_kr["value"], name="Korea Exports (20d)",
        marker_color=ACCENT, showlegend=False,
        hovertemplate="<b>Korea chip exports (1-20)</b> %{x}<br>$%{y:.1f}B<extra></extra>",
    ), row=1, col=2)

    _wsts = df[df["indicator_key"] == "wsts_billings"].sort_values("period")
    fig.add_trace(go.Scatter(
        x=_wsts["period"], y=_wsts["value"], name="WSTS", mode="lines+markers",
        line=dict(width=2, color=GREEN), showlegend=False,
        hovertemplate="<b>WSTS</b> %{x}<br>$%{y:.1f}B<extra></extra>",
    ), row=2, col=1)

    _semi = df[df["indicator_key"] == "semi_wwsems_billings"].sort_values("period")
    fig.add_trace(go.Bar(
        x=_semi["period"], y=_semi["value"], name="SEMI WWSEMS",
        marker_color=YELLOW, showlegend=False,
        hovertemplate="<b>SEMI WWSEMS</b> %{x}<br>$%{y:.1f}B<extra></extra>",
    ), row=2, col=2)

    fig.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="Macro Demand Indicators", height=620, showlegend=True,
    )

    # ── Latest-value summary table ────────────────────────────────────────
    rows_tbl = []
    for key, grp in df.groupby("indicator_key"):
        latest = grp.sort_values("period").iloc[-1]
        meta = DEMAND_INDICATOR_META.get(key, {})
        rows_tbl.append({
            "Indicator": meta.get("label", key),
            "Period": latest["period"],
            "Value": f"{latest['value']:.2f} {latest['unit']}" if pd.notna(latest["value"]) else "—",
            "YoY Δ": f"{latest['yoy_pct']:+.1f}%" if pd.notna(latest["yoy_pct"]) else "—",
            "Seq Δ": f"{latest['seq_pct']:+.1f}%" if pd.notna(latest["seq_pct"]) else "—",
            "Source": latest["source"],
        })
    tbl_df = pd.DataFrame(rows_tbl)
    tbl = dash_table.DataTable(
        data=tbl_df.to_dict("records"),
        columns=[{"name": c, "id": c} for c in tbl_df.columns],
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": BG3, "color": TEXT, "border": "1px solid #30363d",
                    "fontSize": "13px", "padding": "6px 10px"},
        style_header={"backgroundColor": BG2, "color": ACCENT, "fontWeight": "600",
                      "border": "1px solid #30363d"},
        style_data_conditional=[
            {"if": {"filter_query": '{YoY Δ} contains "+"', "column_id": "YoY Δ"},
             "color": GREEN, "fontWeight": "600"},
            {"if": {"filter_query": '{YoY Δ} contains "-"', "column_id": "YoY Δ"},
             "color": RED, "fontWeight": "600"},
            {"if": {"row_index": "odd"}, "backgroundColor": BG2},
        ],
    )

    return _card([
        _section_title("Macro Demand Indicators"),
        html.P(
            "Four free, authoritative demand series in place of consumer-retail proxies: "
            "TSMC + UMC monthly revenue (real-time foundry signal, live crawl), Korea MOTIE "
            "1st-20-days chip exports (~3-week leading indicator), WSTS/SIA global "
            "semiconductor billings (industry-standard demand series), and SEMI WWSEMS "
            "quarterly equipment billings (capex cycle — replaces the retired B2B panel, "
            "BACKLOG SC-00).",
            style={"color": SUBTEXT, "fontSize": "12px", "marginBottom": "8px"},
        ),
        dcc.Graph(figure=fig, config={"displayModeBar": True}),
        html.Div(style={"marginTop": "12px"}),
        tbl,
        _source_footer(
            "TSMC IR · UMC IR · Korea MOTIE/KITA · WSTS/SIA · SEMI WWSEMS",
            "TSMC/UMC monthly revenue: live crawl of each company's IR page, falls back to "
            "the curated seed on a fetch/parse failure. Korea chip exports, WSTS billings, "
            "and SEMI WWSEMS billings: curated from each source's press release — no stable "
            "per-period table exists to crawl (WSTS's monthly data sits behind a members-only "
            "portal; Korea MOTIE and SEMI publish one-off articles, not an archive page). "
            "Update CURATED_DEMAND_INDICATORS in products_config.py as each source releases "
            "new data.",
        ),
    ])


# ── Manufacturer Capacity & Occupancy ────────────────────────────────────────

def _sc_fab_metrics_panel():
    """
    Manufacturer disclosures — ONLY figures a company actually publishes.

    Replaced _sc_capacity_panel() (BACKLOG SC-11). The old panel charted per-node
    capacity and utilisation footnoted to earnings calls that never contained
    them. What foundries do publish is revenue, margins, wafer shipments, revenue
    mix by node and capex — so that is what this shows, and nothing else.
    """
    df = query("SELECT * FROM sc_fab_metrics ORDER BY company, metric_key, period")
    if df.empty:
        return _card([
            _section_title("Manufacturer Disclosures"),
            html.P("No fab metrics loaded. Run: python supply_chain_crawler.py",
                   style={"color": SUBTEXT, "fontSize": "12px"}),
        ])

    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])

    _LABELS = {
        "revenue_usd_b":        "Net Revenue",
        "gross_margin_pct":     "Gross Margin",
        "operating_margin_pct": "Operating Margin",
        "wafer_shipments_kpcs": "Wafer Shipments",
        "node_revenue_pct":     "Revenue by Node",
        "capex_usd_b":          "Capital Expenditure",
        "utilisation_pct":      "Utilisation (as stated)",
    }

    # Revenue + margin trend, per company. One trace per (company, metric) so a
    # company with only one disclosed quarter renders a point rather than an
    # implied line — the §7.3 lesson about not drawing what was not observed.
    fig = go.Figure()
    trend = df[df["metric_key"].isin(["revenue_usd_b", "gross_margin_pct",
                                      "operating_margin_pct"])]
    for (company, mkey), grp in trend.groupby(["company", "metric_key"]):
        grp = grp.sort_values("period")
        fig.add_trace(go.Scatter(
            x=grp["period"], y=grp["value"], mode="lines+markers",
            name=f"{company} — {_LABELS.get(mkey, mkey)}",
            yaxis="y2" if mkey.endswith("_pct") else "y",
            hovertemplate=(f"<b>{company}</b> {_LABELS.get(mkey, mkey)}<br>"
                           "%{x}<br>%{y:.2f}<extra></extra>"),
        ))
    fig.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="Quarterly Disclosures — Revenue and Margins",
        height=420,
        yaxis2=dict(title="Margin (%)", overlaying="y", side="right",
                    showgrid=False, color=SUBTEXT),
    )
    fig.update_yaxes(title_text="Net Revenue (US$B)")

    # Detail table — every row carries the document it came from, because the
    # entire point of SC-11 is that the citation has to be checkable.
    show = df.copy()
    show["Metric"] = show["metric_key"].map(lambda k: _LABELS.get(k, k))
    show.loc[show["detail"] != "", "Metric"] = (
        show.loc[show["detail"] != "", "Metric"] + " — " + show.loc[show["detail"] != "", "detail"]
    )
    show["Value"] = show.apply(lambda r: f"{r['value']:,.2f} {r['unit'] or ''}".strip(), axis=1)
    tbl_df = show[["company", "period", "Metric", "Value", "source"]].rename(
        columns={"company": "Company", "period": "Period", "source": "Source Document"})
    tbl = dash_table.DataTable(
        data=tbl_df.to_dict("records"),
        columns=[{"name": c, "id": c} for c in tbl_df.columns],
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": BG3, "color": TEXT, "border": "1px solid #30363d",
                    "fontSize": "12px", "padding": "6px 10px", "textAlign": "left"},
        style_header={"backgroundColor": BG2, "color": ACCENT, "fontWeight": "600",
                      "border": "1px solid #30363d"},
        style_data_conditional=[{"if": {"row_index": "odd"}, "backgroundColor": BG2}],
        page_size=15,
    )

    note = html.Div(
        "ℹ️ This panel replaced the former Capacity & Occupancy chart (BACKLOG SC-11). "
        "That chart plotted per-node wafer capacity and fab utilisation footnoted to "
        "specific earnings calls — figures no foundry discloses at node granularity, so "
        "the citations named documents that did not contain them. Those 31 rows were "
        "deleted rather than relabelled. Only companies whose disclosures have actually "
        "been read appear below; Samsung, SK Hynix, Micron and Intel are blank on purpose "
        "until someone opens their filings.",
        style={"color": SUBTEXT, "fontSize": "11px", "border": f"1px solid {SUBTEXT}",
               "borderRadius": "4px", "padding": "6px 10px", "marginBottom": "10px"},
    )

    return html.Div([
        _card([
            _section_title("Manufacturer Disclosures"),
            note,
            dcc.Graph(figure=fig, config={"displayModeBar": True}),
        ]),
        _card([
            _section_title("Disclosure Detail — every figure with its source document"),
            tbl,
            _source_footer(
                "Company IR pages and quarterly reports (see the Source Document column)",
                "Revenue and margins are live-crawled from TSMC's Quarterly Results page; "
                "wafer shipments and revenue-mix-by-node are transcribed by hand from the "
                "Management Report PDF. Before adding a row to CURATED_FAB_METRICS, open "
                "the cited document and find the number — a blank series is honest, a "
                "modelled one dressed as a disclosure is not."),
        ]),
    ])





# ── DRAM Spot Prices ──────────────────────────────────────────────────────────

def _sc_dram_panel():
    df = sc_dram_query()

    if df.empty:
        return _card([
            _section_title("RAM Memory — DRAM & HBM Spot Prices"),
            html.P("No DRAM data. Run: python supply_chain_crawler.py",
                   style={"color": SUBTEXT, "fontSize": "12px"}),
        ])

    df["price_usd"] = pd.to_numeric(df["price_usd"], errors="coerce")
    df = df.sort_values("period")

    DRAM_COLORS = {
        "DDR4": "#74C0FC", "DDR5": "#51CF66", "HBM3E": "#FF6B6B",
        "HBM3": "#CC5DE8", "LPDDR5X": "#FFD43B",
    }
    _UNIT_LABEL = {
        "DDR4": "$/die", "DDR5": "$/die",
        "HBM3": "$/GB",  "HBM3E": "$/GB",
        "LPDDR5X": "$/die",
    }

    fig = go.Figure()
    for ptype, grp in df.groupby("product_type"):
        unit = _UNIT_LABEL.get(ptype, "USD")
        for spec, sub in grp.groupby("spec_label"):
            fig.add_trace(go.Scatter(
                x=sub["period"], y=sub["price_usd"],
                name=f"{ptype} — {spec}",
                mode="lines+markers",
                line=dict(width=2, color=DRAM_COLORS.get(ptype, ACCENT)),
                hovertemplate=(
                    f"<b>{ptype}</b> {spec}<br>"
                    f"%{{x}}<br>${{y:.2f}} {unit}<extra></extra>"
                ),
            ))

    fig.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title="RAM Memory — DRAM & HBM Spot / Contract Prices — DDR4/DDR5 (USD/die) · HBM3E (USD/GB)",
        height=380, xaxis_title="Month", yaxis_title="Price (USD)",
    )

    # YoY delta table
    latest = df.sort_values("period").groupby(["product_type", "spec_label"]).last()
    prior  = df[df["period"] <= (pd.to_datetime(df["period"].max()) - pd.DateOffset(months=12))
                .strftime("%Y-%m")].groupby(["product_type", "spec_label"])["price_usd"].last()
    rows_tbl = []
    for idx, row in latest.iterrows():
        p_now  = row["price_usd"]
        p_prev = prior.get(idx)
        yoy    = ((p_now / p_prev - 1) * 100) if p_prev and p_prev > 0 else None
        rows_tbl.append({
            "Type": idx[0], "Spec": idx[1], "Period": row["period"],
            "Price (USD)": f"${p_now:.2f}",
            "YoY Δ": f"{yoy:+.1f}%" if yoy is not None else "—",
            "Source": row.get("source", ""),
        })
    tbl_df = pd.DataFrame(rows_tbl)
    tbl = dash_table.DataTable(
        data=tbl_df.to_dict("records"),
        columns=[{"name": c, "id": c} for c in tbl_df.columns],
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": BG3, "color": TEXT, "border": "1px solid #30363d",
                    "fontSize": "13px", "padding": "6px 10px"},
        style_header={"backgroundColor": BG2, "color": ACCENT, "fontWeight": "600",
                      "border": "1px solid #30363d"},
        style_data_conditional=[
            {"if": {"filter_query": '{YoY Δ} contains "+"'}, "color": GREEN},
            {"if": {"filter_query": '{YoY Δ} contains "-"'}, "color": RED},
            {"if": {"row_index": "odd"}, "backgroundColor": BG2},
        ],
    )

    return _card([
        _section_title("RAM Memory — DRAM & HBM Spot Prices"),
        html.P(
            "DDR4 (8Gb die) and DDR5 (16Gb die) prices are quoted in USD per benchmark die. "
            "HBM3E is quoted in USD per GB of stack capacity — a hyperscaler contract price "
            "driven by AI accelerator demand (NVIDIA H100/H200/B200). "
            "⚠ The two series use different units; compare trends within a series, "
            "not absolute levels across series.",
            style={"color": SUBTEXT, "fontSize": "12px", "marginBottom": "10px"},
        ),
        dcc.Graph(figure=fig, config={"displayModeBar": True}),
        html.Div(style={"marginTop": "12px"}),
        _section_title("Latest Prices & Year-on-Year Change"),
        tbl,
        _source_footer(f"{SRC_PUBLISHED} (DDR4/DDR5) / {SRC_MODELED} (HBM3E)",
                       "DDR4 8Gb 1Gx8 & DDR5 16Gb 2Gx8: weekly spot benchmark die price (USD/die), "
                       "transcribed from TrendForce/DRAMeXchange's free public release. "
                       "HBM3E 12-Hi: contract price per GB (USD/GB) — never publicly quoted, "
                       "so this project's own modeled estimate. "
                       "Update CURATED_DRAM_SPOT in products_config.py monthly."),
    ])


# ══════════════════════════════════════════════════════════════════════════════
# FLASK / RELAY ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

import os
import json
import hashlib
import hmac
from flask import request as flask_request, jsonify, send_file

# API key for the IBKR relay — set RELAY_API_KEY env var on the cloud host.
# The same key must be set in ibkr_relay.py on your local machine.
_RELAY_API_KEY = os.environ.get("RELAY_API_KEY", "")


@server.route("/health")
def health():
    """Health-check endpoint used by Railway / Render / Fly.io uptime probes.

    `db: true` only means the file exists — it is true on ephemeral storage too,
    which is exactly how a wiped volume used to pass unnoticed. `volume_ok`
    reports whether that file is actually on a persistent mount. The probe still
    returns 200 when the volume is bad: the deploy should stay up and shout,
    not fall over (the dashboard is read-mostly and still usable).
    """
    payload = {
        "status":        "ok",
        "db":            os.path.exists(DB_PATH),
        "volume_ok":     VOLUME_OK,
        "volume_reason": VOLUME_REASON,
    }
    # Per-job crawl heartbeats (QA F-01). This is the field that answers "is
    # anything actually refreshing this database?" — the question /health could
    # not answer before, and the reason a dead schedule was invisible. Reported
    # here (not only on the authenticated /api/db-stats) precisely because this
    # is the endpoint an uptime probe already polls.
    try:
        conn = get_conn()
        rep  = job_report(conn)
        conn.close()
        payload["jobs"] = {
            j: {"last_success": e["last_success"], "age_hours": e["age_hours"],
                "overdue": e["overdue"], "never_run": e["never_run"]}
            for j, e in rep.items()
        }
        payload["overdue_jobs"]  = overdue_jobs(rep)
        payload["scheduler_on"]  = scheduler_enabled()
        # crawl_ok is SEPARATE from data_ok and shape_ok, for the same reason
        # those two are separate from each other: "we stopped crawling" and "the
        # publisher stopped publishing" have different fixes, and one boolean
        # meaning both would be actionable for neither.
        payload["crawl_ok"] = (len(payload["overdue_jobs"]) == 0)
    except Exception as exc:                       # noqa: BLE001
        payload["jobs"] = {"error": str(exc)}

    # Still 200 on an overdue crawl, same rationale as the volume guard: a
    # read-mostly dashboard serving known-stale data beats an outage, provided
    # the staleness is loud. Railway must not restart-loop over it.
    return jsonify(payload), 200


# ── Full-dataset export ───────────────────────────────────────────────────────
# Sheet-name overrides: Excel caps sheet names at 31 chars and forbids []:*?/\
_EXPORT_SHEET_NAMES = {
    "quarterly_financials": "Quarterly Financials",
    "market_sentiment":     "Market Sentiment",
    "cycle_analysis":       "Cycle Analysis",
    "daily_prices":         "Daily Prices",
    "company_info":         "Company Info",
    "crawl_runs":           "Crawl Runs",
    "sc_prices":            "SC Prices",
    "sc_products":          "SC Products",
    "sc_market_share":      "SC Market Share",
    "sc_dram_spot":         "SC DRAM Spot",
    "sc_fab_metrics":       "SC Fab Metrics",
    "sc_demand_indicators": "SC Demand Indicators",
    "options_iv":           "Options IV",
    "options_iv_history":   "Options IV History",
}


def _export_sheet_name(table: str) -> str:
    """Map a table name to a legal, readable Excel sheet name (<=31 chars)."""
    name = _EXPORT_SHEET_NAMES.get(table, table.replace("_", " ").title())
    for bad in "[]:*?/\\":
        name = name.replace(bad, "-")
    return name[:31]


@server.route("/api/export-xlsx")
def export_xlsx():
    """
    Download the entire accumulated backend dataset as a multi-sheet .xlsx.

    Public by design — the dashboard already renders this data in charts.
    Every table in the DB is exported (discovered dynamically, so tables added
    later are picked up without touching this route). Sheet 1 is a README
    carrying the export timestamp and per-table row counts, satisfying the
    timestamp requirement in CLAUDE.md §8.

    Streamed from an in-memory buffer via send_file — no Dash callback, so the
    payload is never base64-inflated into a callback response.
    """
    import io

    try:
        conn = get_conn()
        tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]

        stamp_utc = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        buf = io.BytesIO()
        summary = []

        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            # Placeholder so the README lands on sheet 1; rewritten after the loop.
            pd.DataFrame().to_excel(writer, sheet_name="README", index=False)

            for t in tables:
                try:
                    df = pd.read_sql_query(f"SELECT * FROM {t}", conn)
                except Exception as exc:            # one bad table must not abort
                    summary.append({"table": t, "rows": 0, "columns": 0,
                                    "note": f"skipped: {exc}"})
                    continue

                # Excel hard limit is 1,048,576 rows per sheet.
                truncated = ""
                if len(df) > 1_000_000:
                    df = df.tail(1_000_000)
                    truncated = "TRUNCATED to most recent 1,000,000 rows"

                df.to_excel(writer, sheet_name=_export_sheet_name(t), index=False)
                summary.append({"table": t, "rows": len(df),
                                "columns": len(df.columns), "note": truncated})

            readme = pd.DataFrame(
                [{"table": "EXPORT GENERATED", "rows": stamp_utc,
                  "columns": "", "note": "Semiconductor Industry Tracker"},
                 {"table": "", "rows": "", "columns": "", "note": ""}]
                + summary
            )
            readme.to_excel(writer, sheet_name="README", index=False)

        conn.close()
        buf.seek(0)

        fname = f"semiconductor_data_{datetime.utcnow():%Y%m%d_%H%M}.xlsx"
        return send_file(
            buf, as_attachment=True, download_name=fname,
            mimetype="application/vnd.openxmlformats-officedocument."
                     "spreadsheetml.sheet",
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@server.route("/api/upload-iv", methods=["POST"])
def upload_iv():
    """
    Relay endpoint: receives IV snapshots POSTed by ibkr_relay.py running locally.

    Expected JSON body:
    {
      "snapshots": [
        {
          "ticker": "NVDA",
          "iv_current": 0.52,
          "iv_1m_avg": 0.48,
          "iv_1q_avg": 0.50,
          "iv_6m_avg": 0.47,
          "iv_1y_avg": 0.45,
          "iv_pct_vs_1y": 72.0,
          "iv_52w_high": 0.75,
          "iv_52w_low": 0.28,
          "as_of": "2025-03-15T10:30:00"
        },
        ...
      ]
    }
    """
    # ── Auth ──────────────────────────────────────────────────────────────────
    if _RELAY_API_KEY:
        auth = flask_request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(auth, _RELAY_API_KEY):
            return jsonify({"error": "Unauthorized"}), 401

    # ── Parse ─────────────────────────────────────────────────────────────────
    try:
        payload = flask_request.get_json(force=True)
        snapshots = payload.get("snapshots", [])
    except Exception as e:
        return jsonify({"error": f"Bad JSON: {e}"}), 400

    if not snapshots:
        return jsonify({"error": "Empty snapshots list"}), 400

    # ── Store ─────────────────────────────────────────────────────────────────
    try:
        conn = get_conn()
        # Ensure IBKR tables exist (first upload may precede any local ibkr crawl)
        try:
            init_ibkr_tables(conn)
        except Exception:
            pass

        now_str = _now_hkt().strftime("%Y-%m-%d")
        cur = conn.cursor()
        for s in snapshots:
            ticker        = s.get("ticker", "")
            snapshot_date = (s.get("as_of") or now_str)[:10]   # accept either key; take date part only
            cur.execute("""
                INSERT OR REPLACE INTO options_iv
                    (ticker, snapshot_date, iv_current, iv_1m_avg, iv_1q_avg, iv_6m_avg,
                     iv_1y_avg, iv_pct_vs_1y, iv_52w_high, iv_52w_low, source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                ticker,
                snapshot_date,
                s.get("iv_current"),
                s.get("iv_1m_avg"),
                s.get("iv_1q_avg"),
                s.get("iv_6m_avg"),
                s.get("iv_1y_avg"),
                s.get("iv_pct_vs_1y"),
                s.get("iv_52w_high"),
                s.get("iv_52w_low"),
                "relay",
            ))
        conn.commit()
        conn.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok", "stored": len(snapshots)}), 200


@server.route("/api/db-stats")
def db_stats():
    """Return row counts for all key tables — useful for monitoring crawl health."""
    auth = flask_request.headers.get("X-API-Key", "")
    if _RELAY_API_KEY and not hmac.compare_digest(auth, _RELAY_API_KEY):
        return jsonify({"error": "Unauthorized"}), 401

    tables = [
        "daily_prices", "quarterly_financials", "market_sentiment",
        "cycle_analysis", "company_info", "crawl_runs",
        "sc_prices", "sc_market_share",
        "sc_dram_spot", "sc_fab_metrics", "options_iv",
        "sc_demand_indicators", "ticker_valuation_history",
    ]
    stats = {
        "volume_ok":     VOLUME_OK,
        "volume_reason": VOLUME_REASON,
        "db_path":       DB_PATH,
    }
    try:
        conn = get_conn()
        for t in tables:
            try:
                stats[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except Exception:
                stats[t] = "table missing"
        # Last crawl info
        try:
            row = conn.execute(
                "SELECT started_at, finished_at, status, tickers_ok "
                "FROM crawl_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            stats["last_crawl"] = dict(zip(
                ["started_at", "finished_at", "status", "tickers_ok"], row
            )) if row else None
        except Exception:
            stats["last_crawl"] = None

        # ── Per-job heartbeats (QA F-01) ──────────────────────────────────────
        # `last_crawl` above is the newest run of ANY job, which is exactly why
        # it could not detect a dead schedule: one healthy curated reload on
        # every deploy kept it looking recent while nothing was being crawled.
        # These fields are per-job and read the SAME job_report() the scheduler
        # uses to decide what to run, so the two cannot disagree.
        try:
            jrep = job_report(conn)
            stats["jobs"]          = jrep
            stats["overdue_jobs"]  = overdue_jobs(jrep)
            stats["overdue_count"] = len(stats["overdue_jobs"])
            stats["crawl_ok"]      = (stats["overdue_count"] == 0)
            stats["scheduler_on"]  = scheduler_enabled()
        except Exception as exc:                   # noqa: BLE001
            stats["jobs"] = {"error": str(exc)}
        conn.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # ── Freshness (BACKLOG SC-03) ─────────────────────────────────────────────
    # Row counts above are kept for backward compatibility, but they cannot tell
    # a live source from a dead one. These fields can.
    try:
        report = _freshness_report()
        stale  = _stale_sources(report)
        stats["freshness"]     = report
        stats["stale_sources"] = stale
        stats["stale_count"]   = len(stale)
        stats["data_ok"]       = (len(stale) == 0)
    except Exception as e:
        stats["freshness"] = {"error": str(e)}

    # ── Consistency (BACKLOG SC-12) ───────────────────────────────────────────
    # Reported SEPARATELY from data_ok on purpose. Freshness is a fact (the SLA
    # is breached or it is not); consistency is a suspicion, and folding a
    # suspicion into the same boolean would make a green data_ok mean two
    # different things and eventually get ignored.
    try:
        cons = _consistency_report()
        stats["consistency"]       = cons
        stats["consistency_flags"] = len(cons.get("flags", []))
        stats["shape_ok"]          = cons.get("ok", True)
    except Exception as e:
        stats["consistency"] = {"error": str(e)}

    return jsonify(stats), 200


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print(f"⚠️  Database not found at '{DB_PATH}'.")
        print("   Run  python crawler.py --quick  first to fetch data.\n")

    print(f"🚀  Dashboard running → http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT, debug=False)
