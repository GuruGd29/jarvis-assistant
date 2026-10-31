#!/bin/bash
# Encrypted backup of everything Jarvis knows, with restic (same script on the Mac and on a server).
#
#   bin/backup.sh init   create the password file (if missing) and the restic repository
#   bin/backup.sh        back up, then keep 7 daily, 4 weekly and 6 monthly snapshots
#
# Settings come from secrets/backup.env: RESTIC_REPOSITORY (for Oracle Object Storage:
# s3:https://<namespace>.compat.objectstorage.<region>.oraclecloud.com/<bucket>, plus
# AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY from an Oracle "Customer Secret Key").
# The encryption password is secrets/restic-password: without it the backup cannot be read, so the
# user keeps a copy in a password manager. Prints nothing on success (Hermes cron delivers stdout).
set -euo pipefail

SYSTEM="$HOME/jarvis-system"
SECRETS="$SYSTEM/secrets"
DOCKER="${DOCKER:-$(command -v docker || echo /opt/homebrew/bin/docker)}"
RESTIC="${RESTIC:-$(command -v restic || echo /opt/homebrew/bin/restic)}"
export RESTIC_PASSWORD_FILE="$SECRETS/restic-password"
# shellcheck disable=SC1091
[ -f "$SECRETS/backup.env" ] && set -a && . "$SECRETS/backup.env" && set +a

fail() { echo "⚠️ Jarvis backup failed: $1"; exit 1; }
[ -n "${RESTIC_REPOSITORY:-}" ] || fail "no RESTIC_REPOSITORY in secrets/backup.env"

if [ "${1:-}" = "init" ]; then
  if [ ! -f "$RESTIC_PASSWORD_FILE" ]; then
    (umask 077 && openssl rand -base64 32 > "$RESTIC_PASSWORD_FILE")
  fi
  "$RESTIC" snapshots >/dev/null 2>&1 || "$RESTIC" init >/dev/null
  exit 0
fi

staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT
chmod 700 "$staging"

# Databases are copied as consistent snapshots, never as live files.
"$DOCKER" exec jarvis-db pg_dump -U jarvis -d jarvis -Fc > "$staging/jarvis-db.dump" || fail "database dump"
for db in "$HOME"/.hermes/*.db; do
  sqlite3 "$db" ".backup '$staging/hermes-$(basename "$db")'" || fail "copy of $(basename "$db")"
done
if "$DOCKER" ps --format '{{.Names}}' | grep -qx open-webui; then
  "$DOCKER" exec open-webui python3 -c "import sqlite3; s = sqlite3.connect('/app/backend/data/webui.db'); \
d = sqlite3.connect('/tmp/webui-backup.db'); s.backup(d); d.close()" || fail "Open WebUI database"
  "$DOCKER" cp -q open-webui:/tmp/webui-backup.db "$staging/open-webui.db"
  "$DOCKER" exec open-webui rm -f /tmp/webui-backup.db
  "$DOCKER" cp -q open-webui:/app/backend/data/.webui_secret_key "$staging/open-webui-secret-key" 2>/dev/null || true
  "$DOCKER" cp -q open-webui:/app/backend/data/uploads "$staging/open-webui-uploads" 2>/dev/null || true
fi

"$RESTIC" backup --quiet --tag jarvis \
  "$staging" "$HOME/Jarvis" "$SYSTEM" "$HOME/.hermes" \
  --exclude "$SYSTEM/.venv" --exclude "$SYSTEM/models" --exclude "$SYSTEM/logs" \
  --exclude "__pycache__" --exclude "*.egg-info" \
  --exclude "$HOME/.hermes/hermes-agent" --exclude "$HOME/.hermes/installs" --exclude "$HOME/.hermes/tools" \
  --exclude "$HOME/.hermes/cache" --exclude "$HOME/.hermes/audio_cache" --exclude "$HOME/.hermes/image_cache" \
  --exclude "$HOME/.hermes/logs" --exclude "$HOME/.hermes/models_dev_cache.json" \
  --exclude "$HOME/.hermes/*.db" --exclude "$HOME/.hermes/*.db-*" \
  --exclude "$RESTIC_PASSWORD_FILE" --exclude "*.lock" --exclude "*.sock" --exclude "*.pid" || fail "restic backup"

"$RESTIC" forget --quiet --tag jarvis --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune >/dev/null \
  || fail "removing old snapshots"
