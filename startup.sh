#!/bin/bash
set -e

# ── Ensure the data directory exists ─────────────────────────────────────────
# Works whether DB_PATH is /data/semiconductor_data.db (volume) or a local path
DATA_DIR="$(dirname "$DB_PATH")"
mkdir -p "$DATA_DIR"
echo "=== Data directory: $DATA_DIR ==="
echo "=== DB_PATH: $DB_PATH ==="

# ── Run crawlers if database is missing or empty ──────────────────────────────
if [ ! -s "$DB_PATH" ]; then
    echo "=== Database not found — running crawlers now (takes ~3 min) ==="

    echo "--- Running crawler.py --quick ---"
    python crawler.py --quick

    echo "--- Running supply_chain_crawler.py ---"
    python supply_chain_crawler.py

    echo "=== Crawl complete. Starting web server. ==="
else
    echo "=== Database found ($(du -sh "$DB_PATH" | cut -f1)) — skipping crawl ==="
fi

# ── Start the web server ──────────────────────────────────────────────────────
exec gunicorn dashboard:server --bind "0.0.0.0:$PORT" --workers 2 --timeout 120
