#!/bin/bash
set -e

# ── Ensure the data directory exists ─────────────────────────────────────────
DATA_DIR="$(dirname "$DB_PATH")"
mkdir -p "$DATA_DIR"
echo "=== DB_PATH: $DB_PATH ==="

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

# ── Run crawlers if database is empty ─────────────────────────────────────────
if [ "$ROW_COUNT" -eq 0 ] 2>/dev/null; then
    echo "=== No data found — running crawlers now (takes ~3 min) ==="

    echo "--- Running crawler.py --quick ---"
    python crawler.py --quick

    echo "--- Running supply_chain_crawler.py ---"
    python supply_chain_crawler.py

    echo "=== Crawl complete. Starting web server. ==="
else
    echo "=== Data found — skipping crawl ==="
fi

# ── Start the web server ──────────────────────────────────────────────────────
exec gunicorn dashboard:server --bind "0.0.0.0:$PORT" --workers 2 --timeout 120
