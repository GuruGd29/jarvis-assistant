#!/bin/bash
# Build a throwaway Jarvis on a GitHub runner: Ollama + models, Hermes at the pinned commit, the Jarvis
# plugin and SOUL, fake data, the app server. Run from the repo root by .github/workflows/weekly-tests.yml.
set -euo pipefail
REPO="$(pwd)"
HERMES_COMMIT="bf0203a794a07aac3ff764972ab9087baa4e4f4e"   # the version running on the Mac
export HERMES_HOME="$HOME/.hermes"

# The plugin and cron scripts expect the code at ~/jarvis-system with its venv inside.
ln -sfn "$REPO" "$HOME/jarvis-system"
python -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.lock
.venv/bin/pip install -q --no-deps -e .

# Ollama, the chat model (64k context, 8-bit KV cache so it fits in 16 GB) and the embedding model.
if ! command -v ollama >/dev/null; then curl -fsSL https://ollama.com/install.sh | sh; fi
sudo systemctl stop ollama 2>/dev/null || true
OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 OLLAMA_KEEP_ALIVE=2h OLLAMA_NO_CLOUD=1 \
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
python -m venv "$RUNNER_TEMP/hermes-venv"
"$RUNNER_TEMP/hermes-venv/bin/pip" install -q -e "$RUNNER_TEMP/hermes-agent"  # Hermes only supports editable installs from source
mkdir -p "$HERMES_HOME/plugins/jarvis"
cp hermes/plugins/jarvis/__init__.py hermes/plugins/jarvis/plugin.yaml "$HERMES_HOME/plugins/jarvis/"
cp hermes/SOUL.md "$HERMES_HOME/SOUL.md"
sed "s#__VENV__#$REPO/.venv#" tests/ci/hermes/config.yaml > "$HERMES_HOME/config.yaml"
printf 'API_SERVER_ENABLED=true\nAPI_SERVER_KEY=%s\n' "$(openssl rand -hex 24)" > "$HERMES_HOME/.env"
nohup "$RUNNER_TEMP/hermes-venv/bin/hermes" gateway run > "$RUNNER_TEMP/hermes.log" 2>&1 &
for _ in $(seq 120); do curl -s -o /dev/null http://127.0.0.1:8642/ && break; sleep 2; done

# The app server.
nohup .venv/bin/jarvis-web > "$RUNNER_TEMP/web.log" 2>&1 &
for _ in $(seq 60); do curl -sf http://127.0.0.1:8791/api/health >/dev/null && break; sleep 1; done

# Load the chat model once so the first test is not charged for the cold start.
curl -s http://127.0.0.1:11434/api/generate -d '{"model": "qwen3-4b-instruct-64k", "prompt": "hi", "stream": false}' >/dev/null
echo "setup done"
