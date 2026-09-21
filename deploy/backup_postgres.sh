#!/usr/bin/env bash
set -euo pipefail
: "${DATABASE_URL:?DATABASE_URL is required}"
OUT_DIR="${BACKUP_DIR:-./backups}"
mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%d_%H%M%S)"
pg_dump "$DATABASE_URL" --format=custom --file="$OUT_DIR/torre_faro_${STAMP}.dump"
find "$OUT_DIR" -type f -name 'torre_faro_*.dump' -mtime +14 -delete
printf 'Backup OK: %s\n' "$OUT_DIR/torre_faro_${STAMP}.dump"
