#!/bin/bash
#
# backup_local.sh — pull the full production dataset to this Mac.
#
# Off-platform copy of the accumulated backend data. Railway's own volume
# backups (Settings -> Volumes -> Backups) are the first line of defence; this
# script is the second, and it is the only one that survives losing access to
# Railway entirely.
#
# It downloads GET /api/export-xlsx (the same multi-sheet workbook the
# "Download Data" navbar button produces), timestamps it, and prunes old copies.
#
# Usage:
#   ./backup_local.sh                 # write into ./backups
#   BACKUP_DIR=~/Dropbox/semi ./backup_local.sh
#
# Schedule it weekly (Sunday 09:00) with:
#   crontab -e
#   0 9 * * 0 cd "/Users/simpochiu/Documents/Claude - Industry Data Pj" && ./backup_local.sh >> backups/backup.log 2>&1
#
set -euo pipefail

CLOUD_URL="${CLOUD_URL:-https://web-production-e3819.up.railway.app}"
BACKUP_DIR="${BACKUP_DIR:-$(cd "$(dirname "$0")" && pwd)/backups}"
KEEP="${KEEP:-12}"          # how many timestamped copies to retain

mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%d_%H%M)"
OUT="$BACKUP_DIR/semiconductor_data_${STAMP}.xlsx"

echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Backing up from $CLOUD_URL"

# Fail loudly rather than leaving a truncated or HTML-error file on disk.
HTTP_CODE="$(curl -sS -w '%{http_code}' --max-time 300 --fail-with-body \
    -o "$OUT" "$CLOUD_URL/api/export-xlsx" || true)"

if [ "$HTTP_CODE" != "200" ]; then
    echo "ERROR: export returned HTTP $HTTP_CODE — backup aborted." >&2
    [ -f "$OUT" ] && head -c 300 "$OUT" >&2 && echo >&2
    rm -f "$OUT"
    exit 1
fi

# An .xlsx is a zip archive; if it does not start with PK the body is an error page.
if [ "$(head -c 2 "$OUT")" != "PK" ]; then
    echo "ERROR: downloaded file is not a valid .xlsx — backup aborted." >&2
    rm -f "$OUT"
    exit 1
fi

SIZE="$(du -h "$OUT" | cut -f1)"
echo "OK: $OUT ($SIZE)"

# ── Warn if production is running on ephemeral storage ────────────────────────
# A green backup from a host that is silently losing history is a false comfort.
VOL="$(curl -sS --max-time 30 "$CLOUD_URL/health" 2>/dev/null || echo '')"
case "$VOL" in
    *'"volume_ok":false'*)
        echo "WARNING: production reports volume_ok=false — the live DB is on" >&2
        echo "         ephemeral storage and is losing history between deploys." >&2
        ;;
esac

# ── Prune old backups, keeping the most recent $KEEP ──────────────────────────
COUNT="$(ls -1t "$BACKUP_DIR"/semiconductor_data_*.xlsx 2>/dev/null | wc -l | tr -d ' ')"
if [ "$COUNT" -gt "$KEEP" ]; then
    ls -1t "$BACKUP_DIR"/semiconductor_data_*.xlsx | tail -n +$((KEEP + 1)) | \
        while read -r old; do
            echo "Pruning $(basename "$old")"
            rm -f "$old"
        done
fi

echo "Done. $(ls -1 "$BACKUP_DIR"/semiconductor_data_*.xlsx 2>/dev/null | wc -l | tr -d ' ') backup(s) retained."
