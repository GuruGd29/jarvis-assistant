#!/bin/bash
# Replace this server's Jarvis database with a copy from another computer (bin/server.sh move uses it). The copy is
# pg_dump's plain SQL, gzipped, from any Postgres version: lines this server's Postgres can't take (a newer version's
# settings, the vector extension, which is created here) are left out. Run it with Jarvis stopped.
#
#   deploy/server/restore-db.sh COPY.sql.gz [OLD_FILES_FOLDER]
#
# OLD_FILES_FOLDER is where the files were on the other computer (e.g. /Users/me/Jarvis): the index's paths are moved
# to this server's folder, so the files aren't read and indexed all over again.
set -euo pipefail
cd "$(dirname "$0")/../.."
dump="$1"
old_root="${2:-}"
env_get() { grep "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- || true; }
DB_NAME="$(env_get JARVIS_DB_NAME)"; DB_NAME="${DB_NAME:-jarvis}"
DB_USER="$(env_get JARVIS_DB_USER)"; DB_USER="${DB_USER:-jarvis}"
DB_PORT="$(env_get JARVIS_DB_PORT)"; DB_PORT="${DB_PORT:-5432}"
export PGPASSWORD="$(env_get JARVIS_DB_PASSWORD)"
[ -f "$dump" ] || { echo "No such file: $dump" >&2; exit 1; }
! systemctl is-active -q jarvis-web jarvis-hermes || { echo "Stop Jarvis first: sudo systemctl stop jarvis-web jarvis-hermes" >&2; exit 1; }

pg() { (cd /tmp && sudo -u postgres psql -X -q -v ON_ERROR_STOP=1 "$@"); }
pg -c "DROP DATABASE IF EXISTS \"$DB_NAME\" WITH (FORCE)"
pg -c "CREATE DATABASE \"$DB_NAME\" OWNER \"$DB_USER\""
pg -d "$DB_NAME" -c "CREATE EXTENSION vector"
gunzip -c "$dump" \
  | grep -vE '^(SET transaction_timeout|\\restrict |\\unrestrict |CREATE EXTENSION |COMMENT ON EXTENSION )' \
  | psql -X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" >/dev/null

if [ -n "$old_root" ]; then
  .venv/bin/python - "$old_root" <<'PY'
import sys
import psycopg
from jarvis import config

old, new = sys.argv[1].rstrip("/"), str(config.DATA_ROOT).rstrip("/")
with psycopg.connect(config.DB_DSN) as conn:
    moved = conn.execute("UPDATE documents SET path = %s || substr(path, length(%s) + 1) WHERE path LIKE %s",
                         (new, old, old.replace("%", r"\%").replace("_", r"\_") + "/%")).rowcount
print(f"  {moved} indexed files now point to {new}")
PY
fi
.venv/bin/jarvis-migrate >/dev/null   # schema files newer than the copy, if this server's code is newer
echo "  database restored: $(psql -X -tA -h 127.0.0.1 -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
  -c 'SELECT count(*) FROM documents') files indexed"
