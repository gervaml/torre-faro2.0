#!/usr/bin/env bash
set -euo pipefail
: "${DATABASE_URL:?DATABASE_URL is required}"
: "${BACKUP_FILE:?BACKUP_FILE is required}"
TEST_DB="${TEST_DB:-torre_faro_restore_drill}"
ADMIN_URL="${DATABASE_URL%/*}"
psql "$ADMIN_URL/postgres" -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$TEST_DB\"" -c "CREATE DATABASE \"$TEST_DB\""
pg_restore --exit-on-error --dbname="$ADMIN_URL/$TEST_DB" "$BACKUP_FILE"
COUNT=$(psql "$ADMIN_URL/$TEST_DB" -tAc 'SELECT count(*) FROM projects')
printf 'Restore drill OK: %s projects restored into %s\n' "$COUNT" "$TEST_DB"
psql "$ADMIN_URL/postgres" -v ON_ERROR_STOP=1 -c "DROP DATABASE \"$TEST_DB\""
