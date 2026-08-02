#!/bin/bash
set -e

# ── Ensure the data directory exists ─────────────────────────────────────────
DATA_DIR="$(dirname "$DB_PATH")"
mkdir -p "$DATA_DIR"
echo "=== DB_PATH: $DB_PATH ==="

# ── Persistent-volume guard ──────────────────────────────────────────────────
# Railway injects RAILWAY_VOLUME_MOUNT_PATH at *runtime* whenever a volume is
# attached. If DB_PATH does not live inside that path, `mkdir -p` silently
# creates the directory on the container's ephemeral layer instead: the app
# boots, /health returns ok, the crawlers re-seed, and every accumulated row is
# lost on the next redeploy with no visible symptom. That silent re-seed — not
# the volume itself — is the actual failure mode. Detect it and refuse to
# pretend everything is fine.
#
# Locally (no RAILWAY_* vars) the working directory is genuinely persistent,
# so the guard stays quiet.
VOLUME_OK=1
VOLUME_REASON="ok"

if [ -n "$RAILWAY_VOLUME_MOUNT_PATH" ]; then
    case "$DB_PATH" in
        "$RAILWAY_VOLUME_MOUNT_PATH"/*) ;;
        *)
            VOLUME_OK=0
            VOLUME_REASON="DB_PATH ($DB_PATH) is outside the mounted volume ($RAILWAY_VOLUME_MOUNT_PATH)"
            ;;
    esac
elif [ -n "$RAILWAY_ENVIRONMENT_NAME" ] || [ -n "$RAILWAY_SERVICE_ID" ] \
     || [ -n "$RAILWAY_PROJECT_ID" ]; then
    VOLUME_OK=0
    VOLUME_REASON="running on Railway but no volume is attached (RAILWAY_VOLUME_MOUNT_PATH is unset)"
fi

# Backstop: a real mount sits on a different device than /. If the device IDs
# match, the "volume" is just a directory on the container filesystem.
if [ "$VOLUME_OK" = "1" ] && [ -n "$RAILWAY_VOLUME_MOUNT_PATH" ]; then
    ROOT_DEV="$(stat -c %d /          2>/dev/null || echo unknown-root)"
    DATA_DEV="$(stat -c %d "$DATA_DIR" 2>/dev/null || echo unknown-data)"
    if [ "$ROOT_DEV" = "$DATA_DEV" ]; then
        VOLUME_OK=0
        VOLUME_REASON="$DATA_DIR is on the same device as / — the volume is not actually mounted"
    fi
fi

# Passed to gunicorn via the environment; dashboard.py surfaces it on /health,
# /api/db-stats, and as a red navbar banner.
export SEMI_VOLUME_OK="$VOLUME_OK"
export SEMI_VOLUME_REASON="$VOLUME_REASON"

if [ "$VOLUME_OK" = "0" ]; then
    echo "########################################################################"
    echo "# EPHEMERAL STORAGE DETECTED — DATA WILL NOT SURVIVE THE NEXT REDEPLOY  #"
    echo "# $VOLUME_REASON"
    echo "# Fix: Railway -> service -> Settings -> Volumes. Mount a volume and"
    echo "# make DB_PATH point inside it (e.g. mount /data, DB_PATH=/data/semiconductor_data.db)."
    echo "# Skipping the full seed crawl so this failure stays visible."
    echo "# Set SEMI_ALLOW_EPHEMERAL_SEED=1 to seed anyway (throwaway/preview envs)."
    echo "########################################################################"
else
    echo "=== Volume guard: OK (data directory is persistent) ==="
fi

# ── Always reload curated data (idempotent — INSERT OR REPLACE, zero network) ─
# This ensures curated GPU/CPU/RAM retail prices, DRAM spot, capacity, and
# SEMI B2B data are always current with products_config.py on every deploy,
# regardless of whether the DB was already populated.
echo "--- Reloading curated supply-chain data ---"
python supply_chain_crawler.py --curated-only

# ── Data-integrity purges (idempotent, zero network) ──────────────────────────
# Runs on EVERY deploy, deliberately outside the row-count gate below. The full
# crawl is gated on an empty daily_prices plus an external schedule, so a fix
# that only lives in the crawler never reaches rows already on the volume
# (same lesson as SC-14). Currently NULLs the snapshot P/E and market-cap values
# that were written into historical quarterly rows — QA finding F-02.
echo "--- Running data-integrity purges ---"
python crawler.py --purge-only

# ── Check if database has actual price data (not just an empty schema) ────────
ROW_COUNT=$(python3 -c "
import sqlite3, os
db = os.environ.get('DB_PATH', 'semiconductor_data.db')
try:
    conn = sqlite3.connect(db)
    tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")]
    count = conn.execute('SELECT COUNT(*) FROM daily_prices').fetchone()[0] if 'daily_prices' in tables else 0
    conn.close()
    print(count)
except Exception as e:
    print(0)
" 2>/dev/null)

echo "=== Rows in daily_prices: $ROW_COUNT ==="

# ── Run full crawlers only if database has no price data yet ──────────────────
# On ephemeral storage the seed is skipped: it would burn ~3 min of the
# healthcheck window and, worse, make a broken deploy look completely normal.
if [ "$VOLUME_OK" = "0" ] && [ "$SEMI_ALLOW_EPHEMERAL_SEED" != "1" ]; then
    echo "=== Seed crawl SKIPPED — storage is ephemeral (see volume guard above) ==="
elif [ "$ROW_COUNT" -eq 0 ] 2>/dev/null; then
    echo "=== No price data found — running full crawlers now (takes ~3 min) ==="

    echo "--- Running crawler.py --quick ---"
    python crawler.py --quick

    echo "--- Running supply_chain_crawler.py (full) ---"
    python supply_chain_crawler.py

    echo "=== Crawl complete. Starting web server. ==="
else
    echo "=== Price data found — skipping full crawl ==="
fi

# ── Crawl watchdog (backgrounded, NOT in the healthcheck path) ────────────────
# THIS IS THE SCHEDULE (QA finding F-01). Before this existed, the full crawlers
# ran only when daily_prices was empty — i.e. once, ever — and every subsequent
# refresh depended on a Railway Cron that lived in no file in this repo.
#
# It cannot be a Railway cron service: a volume attaches to exactly ONE service,
# so a sibling service cannot reach /data, and putting cronSchedule in
# railway.toml would turn THIS service into a cron job and take the dashboard
# down. See scheduler.py's header for the full reasoning.
#
# Started here, once, BEFORE `exec gunicorn` — not inside the app — so
# `--workers 2` cannot run two copies of it. scheduler.py also takes an flock,
# so a second instance started by hand exits instead of double-crawling.
# It evaluates on a timer and runs whatever is past its interval, which means a
# deploy landing mid-window recovers the missed run instead of skipping the day.
#
# Skipped on ephemeral storage for the same reason the seed crawl is: crawling
# into a container layer that is about to be discarded makes a broken deploy look
# healthy. Set SEMI_DISABLE_SCHEDULER=1 if an external Railway Cron already
# drives these crawlers and you want exactly one driver.
if [ "$VOLUME_OK" = "1" ] || [ "$SEMI_ALLOW_EPHEMERAL_SEED" = "1" ]; then
    if [ "$SEMI_DISABLE_SCHEDULER" = "1" ]; then
        echo "=== Watchdog DISABLED (SEMI_DISABLE_SCHEDULER=1) — crawls must be driven externally ==="
    else
        echo "--- Starting scheduler.py watchdog in the background ---"
        python scheduler.py &
    fi
else
    echo "=== Watchdog SKIPPED — storage is ephemeral (see volume guard above) ==="
fi

# ── Start the web server ──────────────────────────────────────────────────────
exec gunicorn dashboard:server --bind "0.0.0.0:$PORT" --workers 2 --timeout 120
