#!/bin/bash
# Install Jarvis on a Linux server or PC: Ubuntu 24.04 or newer, ARM64 or x86-64, 8 GB RAM or more (12 GB is
# comfortable), 25 GB free disk. For example an Oracle Cloud "Always Free" Ampere A1 (2 OCPU, 12 GB).
# Run it as your normal user (not root) from the cloned repo; it uses sudo where needed:
#
#   git clone https://github.com/GuruGd29/jarvis-assistant.git ~/jarvis-system
#   cd ~/jarvis-system && ./install.sh
#
# It asks a few questions (your name, country, languages, optional Telegram bot), then installs Postgres with
# pgvector, the Python packages, Ollama with the models, Hermes Agent, three services that start at boot, and the
# scheduled jobs. Everything is free and open source. Safe to run again: your .env, settings and data are kept and
# only what is missing is added. Takes 15-30 minutes, mostly downloading about 5 GB.
#
# Without questions (scripts, the weekly test): JARVIS_INSTALL_YES=1, with any setting from .env.example given as an
# environment variable. JARVIS_MODEL_THREADS=N limits how many CPU cores the chat model uses.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
HERMES_COMMIT="bf0203a794a07aac3ff764972ab9087baa4e4f4e"   # the Hermes Agent version Jarvis is tested with
HERMES_HOME="$HOME/.hermes"
HERMES_BIN="$HERMES_HOME/hermes-agent/.hermes/bin/hermes"
CHAT_BASE="qwen3:4b-instruct-2507-q4_K_M"
CHAT_MODEL="qwen3-4b-instruct-64k"
ME="$(id -un)"
YES="${JARVIS_INSTALL_YES:-}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[31mStopped: %s\033[0m\n' "$*" >&2; exit 1; }
ask() {  # ask VAR "question" "suggestion": keeps a value already given, else asks (or takes the suggestion)
  local answer
  [ -n "${!1:-}" ] && return
  if [ -n "$YES" ]; then printf -v "$1" '%s' "${3:-}"; return; fi
  read -rp "  $2${3:+ [$3]}: " answer
  printf -v "$1" '%s' "${answer:-${3:-}}"
}
env_set() {  # env_set FILE KEY VALUE: add the setting unless the file has it already (your edits win)
  grep -q "^$2=" "$1" 2>/dev/null || printf '%s=%s\n' "$2" "$3" >> "$1"
}
env_get() { grep "^$2=" "$1" 2>/dev/null | head -1 | cut -d= -f2- || true; }
wait_for() {  # wait_for URL SECONDS
  for _ in $(seq "$2"); do curl -sf "$1" >/dev/null && return 0; sleep 1; done
  return 1
}

# ---------- 1. Checks ----------
say "Checking this computer"
[ "$(id -u)" != 0 ] || fail "run this as your normal user, not root (it asks for sudo when needed)."
[ "$(uname -s)" = Linux ] || fail "this installer is for Linux. On a Mac, follow docs/install-mac.md."
command -v apt-get >/dev/null || fail "this installer needs Ubuntu or Debian (apt-get)."
sudo -v || fail "your user needs sudo rights."
mem_gb=$(awk '/MemTotal/ {printf "%d", $2 / 1000000}' /proc/meminfo)
disk_gb=$(df -Pk "$HOME" | awk 'NR == 2 {printf "%d", $4 / 1000000}')
echo "  $(uname -m), ${mem_gb} GB memory, ${disk_gb} GB free disk"
[ "$mem_gb" -ge 7 ] || echo "  Warning: Jarvis needs about 8 GB of memory; with ${mem_gb} GB the model may not load."
[ "$disk_gb" -ge 20 ] || fail "about 20 GB of free disk is needed (models, packages); ${disk_gb} GB is free."
# The scheduled-job scripts expect the code at ~/jarvis-system.
if [ "$REPO" != "$HOME/jarvis-system" ]; then
  if [ -e "$HOME/jarvis-system" ] && [ "$(readlink -f "$HOME/jarvis-system")" != "$(readlink -f "$REPO")" ]; then
    fail "~/jarvis-system already exists and is a different folder. Clone Jarvis there, or move that folder."
  fi
  ln -sfn "$REPO" "$HOME/jarvis-system"
fi

# ---------- 2. Settings ----------
ENV_FILE="$REPO/.env"
for key in JARVIS_OWNER_NAME JARVIS_LOCALE JARVIS_CURRENCY JARVIS_TIMEZONE JARVIS_LANGUAGES JARVIS_CONTACT_EMAIL \
           JARVIS_MONEY_AI; do
  [ -n "${!key:-}" ] || printf -v "$key" '%s' "$(env_get "$ENV_FILE" "$key")"   # a re-run keeps your answers
done
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-$(env_get "$HERMES_HOME/.env" TELEGRAM_BOT_TOKEN)}"
TELEGRAM_ALLOWED_USERS="${TELEGRAM_ALLOWED_USERS:-$(env_get "$HERMES_HOME/.env" TELEGRAM_ALLOWED_USERS)}"
system_locale="${LANG%%.*}"; [[ $system_locale =~ ^[a-z]{2,3}_[A-Z]{2}$ ]] || system_locale="en_US"
system_tz="$(timedatectl show -p Timezone --value 2>/dev/null || echo UTC)"

say "Your settings (Enter keeps the suggestion; change any of them later in $ENV_FILE)"
ask JARVIS_OWNER_NAME "Your first name, for greetings (Enter for none)" ""
ask JARVIS_LOCALE "Language_COUNTRY for numbers and dates: en_IN India, en_US USA, en_GB UK, de_DE Germany, fr_FR France..." "$system_locale"
ask JARVIS_CURRENCY "Currency code (INR, USD, EUR, GBP...; Enter = your country's own)" ""
ask JARVIS_TIMEZONE "Time zone (e.g. Asia/Kolkata, Europe/London, America/New_York)" "$system_tz"
ask JARVIS_LANGUAGES "Languages you write to Jarvis in (e.g. Tamil and English)" "English"
ask JARVIS_CONTACT_EMAIL "An email for phone notifications; only Apple/Google push services see it (Enter to skip)" ""
ask JARVIS_MONEY_AI "Read bank emails without a built-in reader with the AI: nightly, always or off" "nightly"
ask TELEGRAM_BOT_TOKEN "Telegram bot token from @BotFather, to chat on Telegram too (Enter to skip)" ""
[ -z "$TELEGRAM_BOT_TOKEN" ] || ask TELEGRAM_ALLOWED_USERS "Your Telegram user id, from @userinfobot (only you can use the bot)" ""

touch "$ENV_FILE" && chmod 600 "$ENV_FILE"
env_set "$ENV_FILE" JARVIS_DB_PASSWORD "${JARVIS_DB_PASSWORD:-$(openssl rand -hex 16)}"
env_set "$ENV_FILE" JARVIS_DB_PORT "${JARVIS_DB_PORT:-5432}"
for key in JARVIS_OWNER_NAME JARVIS_LOCALE JARVIS_CURRENCY JARVIS_TIMEZONE JARVIS_LANGUAGES JARVIS_CONTACT_EMAIL \
           JARVIS_MONEY_AI; do
  [ -z "${!key}" ] || env_set "$ENV_FILE" "$key" "${!key}"
done
DB_NAME="${JARVIS_DB_NAME:-jarvis}"; DB_USER="${JARVIS_DB_USER:-jarvis}"
DB_PASSWORD="$(env_get "$ENV_FILE" JARVIS_DB_PASSWORD)"

# Scheduled jobs run on this computer's clock, so it should show your time.
if [ "$system_tz" != "$JARVIS_TIMEZONE" ]; then
  echo "  Setting this computer's time zone to $JARVIS_TIMEZONE, so the morning brief comes at your 7:30."
  sudo timedatectl set-timezone "$JARVIS_TIMEZONE"
fi

# ---------- 3. System packages and the database ----------
say "System packages: Postgres with pgvector, Python, restic (backups)"
sudo apt-get update -q
sudo apt-get install -y -q postgresql python3-venv python3-dev build-essential git curl openssl restic sqlite3
PG="$(ls /usr/lib/postgresql | sort -n | tail -1)"
sudo apt-get install -y -q "postgresql-$PG-pgvector"
sudo systemctl enable --now postgresql

say "Database"
pg() { (cd /tmp && sudo -u postgres psql -X -q -tA "$@"); }
pg -c "SELECT 1 FROM pg_roles WHERE rolname = '$DB_USER'" | grep -q 1 \
  || pg -c "CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASSWORD'"
pg -c "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1 \
  || (cd /tmp && sudo -u postgres createdb -O "$DB_USER" "$DB_NAME")
pg -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS vector"   # needs the database admin, once

# ---------- 4. Jarvis's Python packages ----------
say "Python packages"
[ -x "$REPO/.venv/bin/python" ] || python3 -m venv "$REPO/.venv"
"$REPO/.venv/bin/pip" install -q --upgrade pip
"$REPO/.venv/bin/pip" install -q -r "$REPO/requirements.lock"
"$REPO/.venv/bin/pip" install -q --no-deps -e "$REPO"
cd "$REPO"
.venv/bin/python -c "from jarvis import config as c; print(f'  {c.OWNER_NAME or \"(no name)\"}, {c.LOCALE}, ' \
  f'{c.money(1234567.5)}, {c.TIMEZONE}, {c.LANGUAGES}')" || fail "a setting in $ENV_FILE is not valid (see above)."
.venv/bin/jarvis-migrate
mkdir -p "$HOME/Jarvis"/{documents,finance,health,notes} "$REPO/logs" "$REPO/state" "$REPO/secrets"
chmod 700 "$REPO/secrets"

# ---------- 5. Ollama and the models ----------
say "Ollama and the models (about 4 GB to download)"
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo cp deploy/systemd/ollama-jarvis.conf /etc/systemd/system/ollama.service.d/jarvis.conf
sudo systemctl daemon-reload && sudo systemctl enable ollama >/dev/null 2>&1 && sudo systemctl restart ollama
wait_for http://127.0.0.1:11434/api/version 60 || fail "Ollama did not start (journalctl -u ollama)."
ollama pull "$CHAT_BASE" && ollama pull bge-m3
modelfile="$(mktemp)"; cp deploy/ollama/Modelfile "$modelfile"
[ -z "${JARVIS_MODEL_THREADS:-}" ] || echo "PARAMETER num_thread $JARVIS_MODEL_THREADS" >> "$modelfile"
ollama create "$CHAT_MODEL" -f "$modelfile" >/dev/null && rm -f "$modelfile"

# ---------- 6. Hermes Agent ----------
say "Hermes Agent (the pinned version; its own installer brings its Python)"
mkdir -p "$HERMES_HOME" "$HOME/.local/bin"
[ -d "$HERMES_HOME/hermes-agent/.git" ] \
  || git clone -q --filter=blob:none https://github.com/NousResearch/hermes-agent.git "$HERMES_HOME/hermes-agent"
git -C "$HERMES_HOME/hermes-agent" fetch -q origin
git -C "$HERMES_HOME/hermes-agent" checkout -q "$HERMES_COMMIT"
(cd "$HERMES_HOME/hermes-agent" && bash setup-hermes.sh < /dev/null) > "$REPO/logs/hermes-install.log" 2>&1 \
  || { tail -30 "$REPO/logs/hermes-install.log"; fail "Hermes did not install (log: logs/hermes-install.log)."; }
ln -sfn "$HERMES_BIN" "$HOME/.local/bin/hermes"
# Jarvis's Hermes settings; your own edited config is kept (Jarvis's is recognised by its memory provider).
if ! grep -q "provider: jarvis" "$HERMES_HOME/config.yaml" 2>/dev/null; then
  [ ! -f "$HERMES_HOME/config.yaml" ] || cp "$HERMES_HOME/config.yaml" "$HERMES_HOME/config.yaml.before-jarvis"
  sed "s#__VENV__#$REPO/.venv#" deploy/hermes/config.yaml > "$HERMES_HOME/config.yaml"
fi
touch "$HERMES_HOME/.env" && chmod 600 "$HERMES_HOME/.env"
env_set "$HERMES_HOME/.env" API_SERVER_ENABLED true
env_set "$HERMES_HOME/.env" API_SERVER_KEY "$(openssl rand -hex 24)"
if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
  env_set "$HERMES_HOME/.env" TELEGRAM_BOT_TOKEN "$TELEGRAM_BOT_TOKEN"
  env_set "$HERMES_HOME/.env" TELEGRAM_ALLOWED_USERS "$TELEGRAM_ALLOWED_USERS"
fi
bin/apply-settings.sh

# ---------- 7. Services that start at boot ----------
say "Services: jarvis-hermes (the agent) and jarvis-web (the app)"
for unit in jarvis-hermes jarvis-web; do
  sed -e "s#@USER@#$ME#g" -e "s#@HOME@#$HOME#g" "deploy/systemd/$unit.service" \
    | sudo tee "/etc/systemd/system/$unit.service" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable jarvis-hermes jarvis-web >/dev/null 2>&1
sudo systemctl restart jarvis-hermes
wait_for http://127.0.0.1:8642/health 300 || fail "Hermes did not start (journalctl -u jarvis-hermes)."
sudo systemctl restart jarvis-web
wait_for http://127.0.0.1:8791/api/health 60 || fail "the app server did not start (journalctl -u jarvis-web)."

# ---------- 8. Scheduled jobs ----------
say "Scheduled jobs (reminders, briefings, money, indexing, learning)"
HERMES_BIN="$HERMES_BIN" bin/add-jobs.sh

# ---------- Done ----------
say "Jarvis is installed and running"
cat <<EOF
  Check:     systemctl status jarvis-hermes jarvis-web ollama      (logs: journalctl -u jarvis-web)
  App:       http://127.0.0.1:8791 on this computer; for your phone, see docs/remote-access.md
  Settings:  $ENV_FILE, then:  bin/apply-settings.sh && sudo systemctl restart jarvis-hermes jarvis-web
  Telegram:  $([ -n "$TELEGRAM_BOT_TOKEN" ] && echo "on; message your bot" || echo "off; add it any time by running ./install.sh again")

  Next steps (README, "After installing"):
    1. Put files in ~/Jarvis (documents, finance, health, notes); they are indexed every 15 minutes.
    2. Connect Google for calendar, Gmail and Drive:   docs/google.md
    3. Money from your bank's alert emails:             docs/money.md
    4. Encrypted backups:                               docs/backups.md
EOF
