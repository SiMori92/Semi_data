#!/bin/bash
set -e

# ── Ensure the data directory exists ─────────────────────────────────────────
DATA_DIR="$(dirname "$DB_PATH")"
mkdir -p "$DATA_DIR"
echo "=== DB_PATH: $DB_PATH ==="

# ── Always reload curated data (idempotent — INSERT OR REPLACE, zero network) ─
# This ensures curated GPU/CPU/RAM retail prices, DRAM spot, capacity, and
# SEMI B2B data are always current with products_config.py on every deploy,
# regardless of whether the DB was already populated.
echo "--- Reloading curated supply-chain data ---"
python supply_chain_crawler.py --curated-only

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
if [ "$ROW_COUNT" -eq 0 ] 2>/dev/null; then
    echo "=== No price data found — running full crawlers now (takes ~3 min) ==="

    echo "--- Running crawler.py --quick ---"
    python crawler.py --quick

    echo "--- Running supply_chain_crawler.py (full) ---"
    python supply_chain_crawler.py

    echo "=== Crawl complete. Starting web server. ==="
else
    echo "=== Price data found — skipping full crawl ==="
fi

# ── Start the web server ──────────────────────────────────────────────────────
exec gunicorn dashboard:server --bind "0.0.0.0:$PORT" --workers 2 --timeout 120
