#!/bin/bash
# Build a throwaway Jarvis on a GitHub runner the way the Oracle server will be set up: Postgres from apt, Hermes at the pinned commit, the Jarvis
# plugin and SOUL, fake data, the app server. Run from the repo root by .github/workflows/weekly-tests.yml.
set -euo pipefail
REPO="$(pwd)"
HERMES_COMMIT="bf0203a794a07aac3ff764972ab9087baa4e4f4e"   # the version running on the Mac
export HERMES_HOME="$HOME/.hermes"

# Postgres from apt with pgvector, as on the server (no Docker there).
sudo apt-get update -q && sudo apt-get install -y -q postgresql
PG=$(ls /usr/lib/postgresql | sort -n | tail -1)
sudo apt-get install -y -q "postgresql-$PG-pgvector"
sudo systemctl start postgresql
sudo -u postgres psql -q -c "CREATE ROLE $JARVIS_DB_USER LOGIN PASSWORD '$JARVIS_DB_PASSWORD'"
sudo -u postgres createdb -O "$JARVIS_DB_USER" "$JARVIS_DB_NAME"
sudo -u postgres psql -q -d "$JARVIS_DB_NAME" -c "CREATE EXTENSION vector"   # needs the admin, once

# The plugin and cron scripts expect the code at ~/jarvis-system with its venv inside.
ln -sfn "$REPO" "$HOME/jarvis-system"
python -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.lock
.venv/bin/pip install -q --no-deps -e .

# Ollama, the chat model (64k context; 4-bit KV cache as planned for the 12 GB server) and the embedding model.
if ! command -v ollama >/dev/null; then curl -fsSL https://ollama.com/install.sh | sh; fi
sudo systemctl stop ollama 2>/dev/null || true
OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q4_0 OLLAMA_KEEP_ALIVE=2h OLLAMA_NO_CLOUD=1 \
  nohup ollama serve > "$RUNNER_TEMP/ollama.log" 2>&1 &
until curl -sf http://127.0.0.1:11434/api/version >/dev/null; do sleep 1; done
ollama pull qwen3:4b-instruct-2507-q4_K_M
ollama pull bge-m3
ollama create qwen3-4b-instruct-64k -f tests/ci/Modelfile

# Fake data, then the search index.
.venv/bin/python tests/ci/seed.py
.venv/bin/jarvis-ingest | tail -1

# Hermes Agent at the same commit as the Mac, with the Jarvis plugin, SOUL and a test API key.
git clone -q --filter=blob:none https://github.com/NousResearch/hermes-agent.git "$RUNNER_TEMP/hermes-agent"
git -C "$RUNNER_TEMP/hermes-agent" checkout -q "$HERMES_COMMIT"
# Hermes's own installer (pinned uv, Python and exact packages), the same way the Mac was installed.
(cd "$RUNNER_TEMP/hermes-agent" && bash setup-hermes.sh) > "$RUNNER_TEMP/hermes-install.log" 2>&1 \
  || { echo "Hermes install failed:"; tail -40 "$RUNNER_TEMP/hermes-install.log"; exit 1; }
HERMES_BIN="$RUNNER_TEMP/hermes-agent/.hermes/bin/hermes"
bin/apply-settings.sh   # the plugin, scheduled-job scripts and SOUL.md with the settings filled in
sed "s#__VENV__#$REPO/.venv#" tests/ci/hermes/config.yaml > "$HERMES_HOME/config.yaml"
printf 'API_SERVER_ENABLED=true\nAPI_SERVER_KEY=%s\n' "$(openssl rand -hex 24)" > "$HERMES_HOME/.env"
nohup "$HERMES_BIN" gateway run > "$RUNNER_TEMP/hermes.log" 2>&1 &
up=0; for _ in $(seq 150); do curl -sf http://127.0.0.1:8642/health >/dev/null && { up=1; break; }; sleep 2; done
if [ "$up" != 1 ]; then echo "Hermes did not start:"; tail -60 "$RUNNER_TEMP/hermes.log"; exit 1; fi

# The app server.
nohup .venv/bin/jarvis-web > "$RUNNER_TEMP/web.log" 2>&1 &
for _ in $(seq 60); do curl -s http://127.0.0.1:8791/api/health >/dev/null && break; sleep 1; done
curl -s http://127.0.0.1:8791/api/health; echo

# One untimed chat through Hermes, so the first test case is not charged for the cold start
# (loading the model and reading Hermes's long system prompt took 24 minutes on the first reply).
.venv/bin/python tests/ci/run_tests.py --only CB-01 --out "$RUNNER_TEMP/warmup" >/dev/null 2>&1 || true
echo "setup done"
