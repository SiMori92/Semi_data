#!/bin/bash
# startup.sh — Run on Railway every deploy.
# If the database doesn't exist yet, launch both crawlers in the background
# so the web server starts immediately and data populates within ~5 minutes.

if [ ! -f "$DB_PATH" ]; then
    echo "=== First run: database not found at $DB_PATH ==="
    echo "=== Starting crawlers in background... ==="
    python crawler.py --quick > /tmp/crawl.log 2>&1 &
    python supply_chain_crawler.py > /tmp/sc_crawl.log 2>&1 &
    echo "=== Crawlers running in background. Dashboard will show data in ~5 min. ==="
else
    echo "=== Database found at $DB_PATH — skipping crawl ==="
fi

# Start the web server immediately (don't wait for crawlers)
exec gunicorn dashboard:server --bind 0.0.0.0:$PORT --workers 2 --timeout 120
