"""
job_heartbeat.py — one definition of "which jobs exist, how often they must run,
and when each last succeeded".

WHY THIS MODULE EXISTS (QA finding F-01, 2026-08-02)
────────────────────────────────────────────────────
`startup.sh` runs the full crawlers only when `daily_prices` is empty, so on a
healthy volume they never run again after the first seed. Every subsequent
refresh depended on a Railway Cron that existed in **no file in this repository**
— invisible to code review, unreconstructible from the repo, and with a failure
mode of a completely normal-looking dashboard serving frozen data. Same class as
the volume-mount bug (CLAUDE.md §5.1): infrastructure state asserted, never
verified.

The obvious fix — a second Railway service with `cronSchedule` — is impossible
here: a Railway volume attaches to exactly ONE service, so a sibling cron service
cannot reach `/data/semiconductor_data.db`. Adding `cronSchedule` to the existing
`railway.toml` would instead convert the *web* service into a cron job (Railway
skips executions when the process does not exit), taking the dashboard down.
The cadence therefore has to live inside the same container — see scheduler.py.

WHY THE SPECS LIVE HERE AND NOT IN scheduler.py
───────────────────────────────────────────────
`scheduler.py` reads JOB_SPECS to decide when to RUN; `dashboard.py` reads the
same dict to decide what to REPORT as overdue. Two surfaces that disagree about
the same fact is how a real signal gets ignored — the lesson already recorded for
`_stale_sources()` (CLAUDE.md §6.5) and `_iv_source_meta()` (§9 IV-01). One dict,
both readers.

WHY THE WATCHDOG KEYS ON JOB RUNS, NOT ON DATA FRESHNESS
───────────────────────────────────────────────────────
Deliberate split, and the distinction matters:

  · `_FRESHNESS_SPEC` (dashboard.py) answers "is the DATA current?" — it goes red
    when a *publisher* stops releasing, which is not something we can fix by
    crawling harder.
  · JOB_SPECS below answers "did the JOB run?" — a purely internal fact.

Driving the scheduler off data freshness would mean that when TrendForce stops
publishing, the crawler re-fires on every cycle forever, hammering a source that
has nothing new. The two checks are complementary and must stay separate:
freshness is about the world, heartbeats are about us.

Kept dependency-free on purpose (stdlib + sqlite3 only) so every crawler can
import it without dragging in yfinance/scipy/pandas.
"""

import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

from config import now_hkt as _now_hkt


# ── Job catalogue ─────────────────────────────────────────────────────────────
# interval_hours : how often the job SHOULD run — the watchdog fires when the
#                  last success is older than this.
# overdue_hours  : how long before it is reported as a problem. Deliberately
#                  looser than interval_hours so one skipped cycle (a redeploy
#                  landing mid-window) does not raise an alarm that trains the
#                  reader to ignore the badge — the SC-04 calibration lesson.
# argv           : run as `python <argv...>` from the repo root.
JOB_SPECS: Dict[str, dict] = {
    "market": {
        "argv":           ["crawler.py", "--quick"],
        "interval_hours": 24,
        "overdue_hours":  30,
        "label":          "Prices + financials + sentiment + cycles",
        "timeout_sec":    45 * 60,
    },
    "iv": {
        "argv":           ["iv_crawler.py"],
        "interval_hours": 24,
        "overdue_hours":  30,
        "label":          "Implied volatility (derived ATM30 + Deribit DVOL)",
        "timeout_sec":    30 * 60,
    },
    "supply_chain": {
        # Weekly, not daily: these are scraped third-party pages (PassMark,
        # Steam, TrendForce, TSMC/UMC/Nanya IR) that publish monthly or slower.
        # Daily scraping of a monthly source is rude and buys nothing.
        "argv":           ["supply_chain_crawler.py"],
        "interval_hours": 24 * 7,
        "overdue_hours":  24 * 9,
        "label":          "Supply chain live scrape (PassMark/Steam/TrendForce/IR)",
        "timeout_sec":    45 * 60,
    },
}

# Recorded for visibility but NOT a member of JOB_SPECS: the curated reload runs
# on every deploy and makes zero network calls, so it must never satisfy the
# live-crawl SLA above. Kept distinct so a container that only ever reboots
# cannot look like a container that is actually crawling.
JOB_CURATED = "supply_chain_curated"


# Retry backoff after a FAILED run, in hours. Without this a permanently broken
# job re-fires on every tick (default 15 min) forever, hammering a third-party
# source that is already failing — a scraper storm dressed up as diligence.
# Doubles per consecutive failure and is capped at the job's own interval, so a
# broken job degrades to "tries once per normal cycle" rather than going silent.
_RETRY_BASE_HOURS = 1.0


def _now() -> datetime:
    """
    UTC+8, tzinfo stripped — the storage convention used by every other table in
    this project (`config.now_hkt`). NOT UTC: `_crawl_timestamp()` in dashboard.py
    reads `crawl_runs.finished_at` and stamps it "HKT" onto every source footer,
    so writing UTC here would silently shift every "[Data Last Crawled/Updated]"
    label in the UI by eight hours. Ages are differences between two values from
    this same clock, so they are unaffected either way.
    """
    return _now_hkt()


# ── Schema ────────────────────────────────────────────────────────────────────

def ensure_schema(conn: sqlite3.Connection) -> None:
    """
    Create crawl_runs if absent and add the `job` column if it predates this
    module. Idempotent — safe on every import path and every boot.

    Hard Rule 1: the ADD COLUMN carries a DEFAULT, so it succeeds against a
    table that already holds rows. Existing readers ("newest completed run")
    keep working unchanged because pre-existing rows adopt 'market', which is
    what they were.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS crawl_runs (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at        TEXT NOT NULL,
            finished_at       TEXT,
            status            TEXT DEFAULT 'running',
            tickers_attempted INTEGER DEFAULT 0,
            tickers_ok        INTEGER DEFAULT 0
        )
    """)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(crawl_runs)")}
    if "job" not in cols:
        conn.execute("ALTER TABLE crawl_runs ADD COLUMN job TEXT DEFAULT 'market'")
    if "note" not in cols:
        conn.execute("ALTER TABLE crawl_runs ADD COLUMN note TEXT")
    conn.commit()


# ── Heartbeat write path ──────────────────────────────────────────────────────

def start_job(conn: sqlite3.Connection, job: str, attempted: int = 0) -> Optional[int]:
    """Open a run row and return its id. Never raises — a broken audit log must
    not stop a crawl that would otherwise succeed."""
    try:
        ensure_schema(conn)
        cur = conn.execute(
            "INSERT INTO crawl_runs (started_at, status, tickers_attempted, job) "
            "VALUES (?, 'running', ?, ?)",
            (_now().isoformat(timespec="seconds"), attempted, job),
        )
        conn.commit()
        return cur.lastrowid
    except Exception:
        return None


def finish_job(
    conn: sqlite3.Connection,
    run_id: Optional[int],
    status: str = "completed",
    ok: int = 0,
    note: str = "",
) -> None:
    """
    Close a run row. `status` must be 'completed' only when the job genuinely
    did its work — a run that wrote nothing because every parse gate rejected
    the page is 'failed', not 'completed'. A heartbeat that goes green on a
    failed run is worse than no heartbeat: it actively certifies the outage.
    """
    if run_id is None:
        return
    try:
        conn.execute(
            "UPDATE crawl_runs SET finished_at = ?, status = ?, tickers_ok = ?, note = ? "
            "WHERE id = ?",
            (_now().isoformat(timespec="seconds"), status, ok, note[:500], run_id),
        )
        conn.commit()
    except Exception:
        pass


# ── Heartbeat read path (shared by scheduler.py and dashboard.py) ─────────────

def last_success(conn: sqlite3.Connection, job: str) -> Optional[datetime]:
    try:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT MAX(finished_at) FROM crawl_runs "
            "WHERE job = ? AND status = 'completed' AND finished_at IS NOT NULL",
            (job,),
        ).fetchone()
        if row and row[0]:
            return datetime.fromisoformat(str(row[0]).replace("Z", ""))
    except Exception:
        pass
    return None


def last_attempt(conn: sqlite3.Connection, job: str) -> Optional[datetime]:
    """Newest run of any outcome, successful or not."""
    try:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT MAX(started_at) FROM crawl_runs WHERE job = ?", (job,)
        ).fetchone()
        if row and row[0]:
            return datetime.fromisoformat(str(row[0]).replace("Z", ""))
    except Exception:
        pass
    return None


def consecutive_failures(conn: sqlite3.Connection, job: str) -> int:
    """
    Failed runs since the last success. Drives the retry backoff — a job that is
    broken (a scraper whose page moved, an API returning 403) must not be
    retried every tick against a source that is already refusing us.
    """
    try:
        ensure_schema(conn)
        rows = conn.execute(
            "SELECT status FROM crawl_runs WHERE job = ? AND status != 'running' "
            "ORDER BY id DESC LIMIT 20", (job,)
        ).fetchall()
        n = 0
        for (status,) in rows:
            if status == "completed":
                break
            n += 1
        return n
    except Exception:
        return 0


def retry_backoff_hours(conn: sqlite3.Connection, job: str) -> float:
    """
    Hours to wait after a failure before retrying: 1h, 2h, 4h … capped at the
    job's own interval. Zero when the job is not in a failing streak.
    """
    fails = consecutive_failures(conn, job)
    if fails <= 0:
        return 0.0
    spec = JOB_SPECS.get(job, {})
    cap = float(spec.get("interval_hours", 24))
    return min(cap, _RETRY_BASE_HOURS * (2 ** (fails - 1)))


def job_report(conn: sqlite3.Connection) -> dict:
    """
    Per-job {last_success, age_hours, interval_hours, overdue_hours, due,
    overdue, last_status, never_run}. Never raises — same contract as
    _freshness_report()/_consistency_report() in dashboard.py: a broken
    monitoring helper must not take down the endpoint that reports it.
    """
    out = {}
    now = _now()
    for job, spec in JOB_SPECS.items():
        entry = {
            "label":           spec["label"],
            "interval_hours":  spec["interval_hours"],
            "overdue_hours":   spec["overdue_hours"],
            "last_success":    None,
            "age_hours":       None,
            "due":             True,
            "overdue":         True,
            "never_run":       True,
            "last_status":     None,
        }
        try:
            ts = last_success(conn, job)
            row = conn.execute(
                "SELECT status, started_at FROM crawl_runs WHERE job = ? "
                "ORDER BY id DESC LIMIT 1", (job,)
            ).fetchone()
            if row:
                entry["last_status"] = row[0]
            if ts:
                age = (now - ts).total_seconds() / 3600.0
                entry.update(
                    last_success=ts.isoformat(timespec="seconds"),
                    age_hours=round(age, 1),
                    due=age >= spec["interval_hours"],
                    overdue=age >= spec["overdue_hours"],
                    never_run=False,
                )
        except Exception:
            pass
        out[job] = entry
    return out


def overdue_jobs(report: dict) -> list:
    """Jobs breaching overdue_hours, worst first. Backs both /health and
    /api/db-stats so the two cannot disagree."""
    rows = [(j, e) for j, e in report.items() if e.get("overdue")]
    rows.sort(key=lambda kv: (kv[1]["age_hours"] is not None, kv[1].get("age_hours") or 0),
              reverse=True)
    return [j for j, _ in rows]


def scheduler_enabled() -> bool:
    """
    Default ON. The kill-switch exists for the case where an external Railway
    Cron is already driving these crawlers and you want exactly one driver.
    Double-running is harmless to the DATA (every writer is INSERT OR REPLACE);
    the cost is duplicate third-party requests, which the interval check below
    already suppresses in the common case.
    """
    return os.environ.get("SEMI_DISABLE_SCHEDULER", "0") != "1"
