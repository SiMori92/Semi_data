"""
scheduler.py — in-container crawl watchdog (QA finding F-01).

WHY THIS IS NOT A RAILWAY CRON SERVICE
──────────────────────────────────────
The textbook answer to "put the schedule in the repo" on Railway is a second
service with `cronSchedule` in its config. That is impossible for this project,
for two independent reasons:

  1. A Railway VOLUME ATTACHES TO EXACTLY ONE SERVICE. A sibling cron service
     therefore cannot see /data/semiconductor_data.db at all — it would crawl
     into its own empty ephemeral copy and exit, forever.
  2. Putting `cronSchedule` in the EXISTING railway.toml would convert the web
     service itself into a cron job. Railway requires a cron service to
     terminate on completion and skips executions while a previous one is still
     running — gunicorn never exits, so the dashboard would go down and the
     schedule would never fire.

So the cadence has to run inside the same container that holds the volume. This
file is that cadence, and unlike the arrangement it replaces it is checked in,
reviewable, and reconstructible from the repo alone.

WHY A WATCHDOG AND NOT WALL-CLOCK CRON TIMES
────────────────────────────────────────────
A wall-clock scheduler ("weekdays 06:00 UTC") silently skips a day whenever the
container happens to restart across the trigger — which is precisely F-01's
failure shape in a new costume, and containers here restart on every deploy.

This loop instead asks a question with a self-healing answer: *is any job older
than its interval?* If a deploy lands at 06:05 and the 06:00 slot was missed,
the job is overdue and runs immediately. If an external Railway Cron already ran
it, nothing is overdue and this loop stays idle — which is also why leaving both
drivers enabled is harmless.

SINGLE INSTANCE
───────────────
Launched once from startup.sh BEFORE `exec gunicorn`, so `--workers 2` cannot
double-fire it (an in-app APScheduler would run once per worker). An flock on a
lockfile enforces that even if it is started twice by hand; the lock is held by
the process and released by the kernel on death, so a crash cannot wedge it.

Run manually:
    python scheduler.py --once      # evaluate every job once, run what is due
    python scheduler.py --status    # print the job report and exit
    python scheduler.py --dry-run   # say what WOULD run, execute nothing
"""

import argparse
import fcntl
import logging
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime

from config import DB_PATH, now_hkt as _now
from job_heartbeat import (
    JOB_SPECS,
    consecutive_failures,
    ensure_schema,
    job_report,
    last_attempt,
    last_success,
    retry_backoff_hours,
    scheduler_enabled,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [scheduler] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

REPO_DIR = os.path.dirname(os.path.abspath(__file__))

# How often the loop wakes to re-evaluate. Deliberately short relative to the
# 24h job intervals: the cost of waking is one SQLite read, and a tight tick
# means a missed window is recovered in minutes rather than at the next slot.
TICK_SECONDS = int(os.environ.get("SEMI_SCHEDULER_TICK_SEC", 15 * 60))

# Lockfile lives beside the DB, i.e. on the volume when one is mounted.
LOCK_PATH = os.environ.get(
    "SEMI_SCHEDULER_LOCK", os.path.join(os.path.dirname(DB_PATH) or ".", ".scheduler.lock")
)


def acquire_singleton_lock():
    """
    Return the held lock file object, or None if another instance owns it.
    Caller must keep the returned object alive for the process lifetime.
    """
    try:
        fh = open(LOCK_PATH, "w")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.write(str(os.getpid()))
        fh.flush()
        return fh
    except (OSError, IOError):
        return None


def due_jobs(conn: sqlite3.Connection) -> list:
    """
    Jobs whose last SUCCESS is older than their interval, in JOB_SPECS
    declaration order.

    Declaration order is the dependency order and is intentional: `market` runs
    first because sentiment, cycle_analysis and ticker_valuation_history are all
    derived from the price history it writes. Sorting by age instead would let a
    never-run supply_chain scrape delay the crawl everything else depends on.
    """
    now = _now()
    out = []
    for job, spec in JOB_SPECS.items():
        ts = last_success(conn, job)
        age = float("inf") if ts is None else (now - ts).total_seconds() / 3600.0
        if age < spec["interval_hours"]:
            continue

        # Retry backoff. A job that is genuinely broken — a scraper whose page
        # moved, an IR site returning 403 — is due on every single tick, and
        # without this it would be re-launched every 15 minutes indefinitely
        # against a source already refusing us. Backoff turns that into 1h, 2h,
        # 4h … capped at the job's own interval, so it keeps trying but stops
        # hammering. Surfaced in the log so a suppressed retry is never silent.
        backoff = retry_backoff_hours(conn, job)
        if backoff > 0:
            att = last_attempt(conn, job)
            if att is not None:
                since = (now - att).total_seconds() / 3600.0
                if since < backoff:
                    log.info(
                        "Job '%s' is due but in retry backoff (%d consecutive "
                        "failures, waiting %.1fh, %.1fh elapsed) — skipping.",
                        job, consecutive_failures(conn, job), backoff, since,
                    )
                    continue
        out.append(job)
    return out


def run_job(job: str, dry_run: bool = False) -> bool:
    """
    Run one crawler as a subprocess. Returns True if it exited 0.

    Subprocess, not import: a crawler that segfaults, hangs, or leaks a socket
    cannot take the watchdog with it, and `timeout_sec` bounds a hung scrape.
    The crawler writes its OWN heartbeat — this function deliberately does not,
    so a job that exits 0 having written nothing (the IV coverage gate) is still
    recorded as failed by the code that actually knows.
    """
    spec = JOB_SPECS[job]
    cmd = [sys.executable] + spec["argv"]
    if dry_run:
        log.info("DRY-RUN would execute: %s", " ".join(cmd))
        return True

    log.info("Starting job '%s' — %s", job, spec["label"])
    started = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=REPO_DIR, timeout=spec["timeout_sec"],
            stdout=None, stderr=None,      # inherit → Railway deploy logs
        )
        ok = proc.returncode == 0
        log.info("Job '%s' finished rc=%s in %.0fs", job, proc.returncode, time.time() - started)
        if not ok:
            log.error("JOB '%s' FAILED (rc=%s). Data will go stale until this is fixed.",
                      job, proc.returncode)
        return ok
    except subprocess.TimeoutExpired:
        log.error("JOB '%s' TIMED OUT after %ds — killed.", job, spec["timeout_sec"])
        return False
    except Exception as exc:                      # noqa: BLE001
        log.error("JOB '%s' could not be started: %s", job, exc)
        return False


def tick(dry_run: bool = False) -> list:
    """One evaluation pass. Returns the jobs it ran.

    Jobs run SEQUENTIALLY and never in parallel: they share one SQLite file and
    the same third-party rate limits, so concurrency buys nothing and risks
    `database is locked`.
    """
    ran = []
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        ensure_schema(conn)
        pending = due_jobs(conn)
        conn.close()
    except Exception as exc:                      # noqa: BLE001
        log.error("Could not evaluate schedule: %s", exc)
        return ran

    if not pending:
        return ran

    log.info("Due: %s", ", ".join(pending))
    for job in pending:
        run_job(job, dry_run=dry_run)
        ran.append(job)
    return ran


def print_status() -> None:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    ensure_schema(conn)
    rep = job_report(conn)
    conn.close()
    print(f"{'JOB':<16}{'LAST SUCCESS':<22}{'AGE(h)':>8}{'EVERY':>8}{'STATE':>12}")
    for job, e in rep.items():
        state = "NEVER RUN" if e["never_run"] else ("OVERDUE" if e["overdue"]
                 else ("due" if e["due"] else "ok"))
        print(f"{job:<16}{str(e['last_success'] or '—'):<22}"
              f"{('—' if e['age_hours'] is None else e['age_hours']):>8}"
              f"{e['interval_hours']:>8}{state:>12}")


def main() -> None:
    ap = argparse.ArgumentParser(description="In-container crawl watchdog (QA F-01)")
    ap.add_argument("--once", action="store_true", help="evaluate once and exit")
    ap.add_argument("--status", action="store_true", help="print job report and exit")
    ap.add_argument("--dry-run", action="store_true", help="report what would run; execute nothing")
    args = ap.parse_args()

    if args.status:
        print_status()
        return

    if not scheduler_enabled():
        log.warning("SEMI_DISABLE_SCHEDULER=1 — watchdog is OFF. Crawls must be "
                    "driven externally; /api/db-stats will still report staleness.")
        return

    if args.once or args.dry_run:
        tick(dry_run=args.dry_run)
        return

    lock = acquire_singleton_lock()
    if lock is None:
        log.warning("Another scheduler instance holds %s — exiting.", LOCK_PATH)
        return

    log.info("Watchdog started (tick %ds). Jobs: %s",
             TICK_SECONDS, ", ".join(f"{j}/{s['interval_hours']}h"
                                     for j, s in JOB_SPECS.items()))
    while True:
        try:
            tick()
        except Exception as exc:                  # noqa: BLE001
            # The loop must outlive any single failure — a watchdog that dies on
            # an unexpected exception reintroduces F-01 silently.
            log.error("Tick failed: %s", exc)
        time.sleep(TICK_SECONDS)


if __name__ == "__main__":
    main()
