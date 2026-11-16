"""
api_server.py — the Flask API behind the Next.js UI (WEB-01 Phase 5).
====================================================================
Every HTTP endpoint the project serves that is not a page:

    GET  /health               uptime probe (Railway healthcheck)          public
    GET  /api/db-stats         row counts, freshness, consistency          key if RELAY_API_KEY set
    GET  /api/export-xlsx      whole DB as a workbook (reading copy)       public
    GET  /api/export-db        byte-exact SQLite snapshot (THE backup)     public
    GET  /api/export-bundle    zip of both + README (⬇️ Download Data)     public
    POST /api/upload-iv        IBKR relay receiver                         key
    POST /api/run-crawl        ⚡ Run Crawl (via Next /ui-api/run-crawl)    key REQUIRED

Extracted VERBATIM from dashboard.py (the retired Dash UI, archived 2026-11-16) — the
routes plus exactly the helpers they use (_freshness_report, _consistency_report,
_stale_sources, _build_export_workbook, _snapshot_db). No Dash, no Plotly: Python stays
the owner of every endpoint because they lean on pandas/openpyxl, VACUUM INTO and the
job_heartbeat run lock, none of which should be re-implemented in TypeScript.

startup.sh runs it INTERNALLY (gunicorn api_server:server on 127.0.0.1:8051); Next.js is
public on $PORT and proxies /health + /api/* here (web/next.config.ts). Response bodies
are unchanged from dashboard:server — Product/tests/test_api_contract.py diffs them.

Local run:
    DB_PATH=<a copy of a backup .db> python3 api_server.py      # http://127.0.0.1:8051
"""

import io
import os
import sqlite3
from datetime import datetime

import pandas as pd
from flask import Flask

from ibkr_options_crawler import init_ibkr_tables
from job_heartbeat import job_report, overdue_jobs, scheduler_enabled   # QA F-01
from job_heartbeat import JOB_SPECS, start_manual_run   # WEB-01c

from config import DB_PATH, now_hkt as _now_hkt

server = Flask(__name__)

# ── Persistent-volume status (set by startup.sh — see its volume guard) ───────
# Defaults to OK so local dev and any non-Railway host stay quiet.
VOLUME_OK     = os.environ.get("SEMI_VOLUME_OK", "1") != "0"
VOLUME_REASON = os.environ.get("SEMI_VOLUME_REASON", "ok")


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


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

import hmac
from flask import request as flask_request, jsonify, send_file

# API key for the IBKR relay — set RELAY_API_KEY env var on the cloud host.
# The same key must be set in ibkr_relay.py on your local machine.
_RELAY_API_KEY = os.environ.get("RELAY_API_KEY", "")


@server.route("/api/run-crawl", methods=["POST"])
def run_crawl():
    """Start crawlers on demand (BACKLOG WEB-01c). Write-class route, so a key is
    REQUIRED — and unlike the older `!= os.environ.get(..., "")` pattern, an
    unset RELAY_API_KEY refuses everything instead of accepting an empty header.

    Body (optional JSON): {"jobs": ["market", "iv", "supply_chain"]}; default
    ["market", "supply_chain"] = what the ⚡ button runs. 202 started · 409 a crawl
    is already running (manual or scheduled) · 400 unknown job · 401 bad key.
    """
    key = os.environ.get("RELAY_API_KEY", "")
    sent = flask_request.headers.get("X-API-Key", "")
    if not key or not hmac.compare_digest(sent, key):
        return jsonify({"error": "unauthorized"}), 401
    body = flask_request.get_json(silent=True) or {}
    jobs = body.get("jobs", ["market", "supply_chain"])
    if (not isinstance(jobs, list) or not jobs
            or not all(isinstance(j, str) and j in JOB_SPECS for j in jobs)):
        return jsonify({"error": "unknown job", "allowed": list(JOB_SPECS)}), 400
    if not start_manual_run(jobs):
        return jsonify({"status": "busy", "detail": "a crawl is already running"}), 409
    return jsonify({"status": "started", "jobs": jobs}), 202


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


def _build_export_workbook() -> "io.BytesIO":
    """
    Build the multi-sheet .xlsx of the entire dataset and return it as a buffer.

    Factored out of the route so `/api/export-xlsx` and `/api/export-bundle`
    produce a byte-identical workbook from ONE implementation. Two copies of
    this loop would drift, and the second copy is the one nobody would notice
    going wrong (§6.5's recurring lesson: two surfaces computing the same thing
    separately will eventually disagree).

    Every table is discovered from `sqlite_master`, so tables added later are
    picked up without touching this function. Sheet 1 is a README carrying the
    export timestamp and per-table row counts (CLAUDE.md §8).
    """
    import io

    conn = get_conn()
    try:
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

        buf.seek(0)
        return buf
    finally:
        conn.close()


def _snapshot_db(tmp: str) -> str:
    """
    Write a consistent, byte-exact copy of the live DB to `tmp` and return it.

    `VACUUM INTO` (SQLite >= 3.27) snapshots under a read lock, so it stays
    consistent while the crawlers write. A plain file copy can capture a torn
    page plus an unmerged WAL and yield a file that opens fine and is subtly
    corrupt — a backup that passes every check until the day you need it.

    Shared by `/api/export-db` and `/api/export-bundle` for the same
    one-implementation reason as `_build_export_workbook()`.
    """
    if os.path.exists(tmp):
        os.remove(tmp)

    # Separate short-lived connection: VACUUM INTO cannot run inside a
    # transaction, and get_conn() hands back a shared long-lived handle.
    src = sqlite3.connect(DB_PATH)
    try:
        try:
            src.execute("VACUUM INTO ?", (tmp,))
        except sqlite3.OperationalError:
            # Needs SQLite >= 3.27. If the container ships an older library,
            # fall back to the online-backup API, which is equally consistent
            # (page-by-page under a read lock) and has been in Python since
            # 3.7 — it just does not compact.
            dst = sqlite3.connect(tmp)
            try:
                src.backup(dst)
            finally:
                dst.close()
    finally:
        src.close()

    if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
        raise RuntimeError("snapshot produced no file")
    return tmp


@server.route("/api/export-xlsx")
def export_xlsx():
    """
    Download the entire dataset as a multi-sheet .xlsx (reading copy).

    Public by design — the dashboard already renders this data in charts.
    Kept as its own route because `local/backup_local.sh` and any existing
    bookmark point at it; the navbar button now serves the bundle instead.

    Streamed from an in-memory buffer via send_file — no Dash callback, so the
    payload is never base64-inflated into a callback response.
    """
    try:
        buf = _build_export_workbook()
        fname = f"semiconductor_data_{datetime.utcnow():%Y%m%d_%H%M}.xlsx"
        return send_file(
            buf, as_attachment=True, download_name=fname,
            mimetype="application/vnd.openxmlformats-officedocument."
                     "spreadsheetml.sheet",
        )
    except Exception as exc:                          # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


@server.route("/api/export-bundle")
def export_bundle():
    """
    Download BOTH exports as one .zip — what the navbar button serves.

    Why a zip and not two responses: a single click can only produce one
    download; browsers suppress the second as a popup. One archive is the only
    way to satisfy "click once, get both".

      semiconductor_data_<stamp>.xlsx   reading copy (Excel coerces types)
      semiconductor_data_<stamp>.db     the restorable backup
      README.txt                        which file is which, and the restore recipe

    Public, like `/api/export-xlsx`. The gate this route does NOT have was
    reconsidered deliberately: `/api/export-xlsx` already dumps every table
    discovered from `sqlite_master` with no auth, so the row data is public
    already. Gating the .db protected schema DDL and indexes only — while the
    contents it describes stayed open. That is not a security boundary, it is
    the appearance of one, and an inconsistent gate is worse than none because
    it invites the assumption that the data is protected. If this dataset ever
    needs to be private, BOTH routes must be gated; do not re-gate just this one.

    The .db is deflated inside the zip, so the transfer is comparable to the
    .db.gz that `backup_local.sh` stores, and macOS/Windows unpack it natively.
    """
    import io
    import zipfile

    tmp = "/tmp/semiconductor_bundle.db"
    try:
        stamp = f"{datetime.utcnow():%Y%m%d_%H%M}"
        wb = _build_export_workbook()
        _snapshot_db(tmp)

        readme = (
            "Semiconductor Industry Tracker — full data export\n"
            f"Generated: {datetime.utcnow():%Y-%m-%d %H:%M} UTC\n"
            "\n"
            f"  semiconductor_data_{stamp}.xlsx\n"
            "      Reading copy. Every table as a sheet, README on sheet 1.\n"
            "      NOT a backup: there is no import path back, and Excel\n"
            "      coerces NULL/int/date on the way out.\n"
            "\n"
            f"  semiconductor_data_{stamp}.db\n"
            "      The restorable backup. Byte-exact SQLite snapshot taken\n"
            "      with VACUUM INTO, consistent even under concurrent writes.\n"
            "\n"
            "Restore / inspect:\n"
            f"  sqlite3 semiconductor_data_{stamp}.db \\\n"
            "      \"PRAGMA integrity_check; SELECT COUNT(*) FROM daily_prices;\"\n"
            f"  DB_PATH=semiconductor_data_{stamp}.db python3 api_server.py\n"
        )

        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"README.txt", readme)
            z.writestr(f"semiconductor_data_{stamp}.xlsx", wb.getvalue())
            # write() streams from disk rather than loading the whole DB into
            # memory alongside the zip — the workbook is already buffered, and
            # holding both uncompressed would be the peak-RSS risk on a small
            # Railway container.
            z.write(tmp, arcname=f"semiconductor_data_{stamp}.db")
        zbuf.seek(0)

        return send_file(
            zbuf, as_attachment=True,
            download_name=f"semiconductor_data_{stamp}.zip",
            mimetype="application/zip",
        )
    except Exception as exc:                          # noqa: BLE001
        return jsonify({"error": str(exc)}), 500
    finally:
        # /tmp is the ephemeral container layer, but a 60 MB file per click
        # would still accumulate for the life of the container.
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


@server.route("/api/export-db")
def export_db():
    """
    Download a byte-exact, restorable copy of the SQLite database.

    This is THE backup endpoint. `/api/export-xlsx` is for reading; it is not a
    backup, because there is no import path back from a workbook and Excel
    silently coerces types on the way out (NULL vs "", int -> float, TEXT dates).
    Restoring from it means hand-writing a converter during an outage.

    Kept as a separate route from `/api/export-bundle` so `backup_local.sh` can
    fetch just the database, without paying to build a workbook it discards.

    PUBLIC, matching `/api/export-xlsx` — see the note in `export_bundle()` for
    why gating only this route was security theatre. Uncompressed on the wire;
    the backup script gzips it on arrival.

    Written to /tmp, the ephemeral container layer, so it costs nothing on the
    persistent volume (CLAUDE.md §5.1).
    """
    tmp = "/tmp/semiconductor_snapshot.db"
    try:
        _snapshot_db(tmp)
        fname = f"semiconductor_data_{datetime.utcnow():%Y%m%d_%H%M}.db"
        return send_file(
            tmp, as_attachment=True, download_name=fname,
            mimetype="application/vnd.sqlite3",
        )
    except Exception as exc:                          # noqa: BLE001
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
# ENTRY POINT (local only — prod runs gunicorn api_server:server, see startup.sh)
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print(f"⚠️  Database not found at '{DB_PATH}'.")
    port = int(os.environ.get("API_PORT", "8051"))
    print(f"🚀  API running → http://127.0.0.1:{port}  (DB: {DB_PATH})")
    server.run(host="127.0.0.1", port=port, debug=False)
