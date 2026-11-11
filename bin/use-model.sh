#!/bin/bash
# Switch Jarvis's chat model to another model that runs in Ollama (docs/customize.md):
#
#   bin/use-model.sh MODEL        e.g. qwen3.5:9b, gemma3:12b, llama3.1:8b (ollama.com/library)
#   bin/use-model.sh qwen3.5:4b-q4_K_M      back to the tested default
#
# It downloads MODEL into Ollama, builds Jarvis's version of it (a 64k context, which Hermes needs, and the settings
# in deploy/ollama/Modelfile), and points Jarvis and Hermes at it. It also brings Hermes back to this local model if
# you had switched it to a cloud service. Your previous .env and Hermes settings are kept in ~/jarvis-backups/.
# Then restart Jarvis (the command is printed at the end). Pick a model that supports tools, and that fits in your
# memory with about 5 GB to spare for the rest of Jarvis. JARVIS_MODEL_THREADS=N limits the processor cores it uses.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"
hermes_home="${HERMES_HOME:-$HOME/.hermes}"
base="${1:-}"
[ -n "$base" ] || { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
[[ $base =~ ^[A-Za-z0-9._/:-]+$ ]] || { echo "Stopped: '$base' isn't an Ollama model name." >&2; exit 1; }
[ -f .env ] && [ -f "$hermes_home/config.yaml" ] || { echo "Stopped: install Jarvis first (./install.sh)." >&2; exit 1; }

name="qwen3.5-4b-64k"   # the default keeps its usual name; any other model gets its own
[ "$base" = "qwen3.5:4b-q4_K_M" ] || name="$(printf '%s' "$base" | tr ':/' '--' | tr -cd 'A-Za-z0-9._-')-64k"
ollama_url="$(.venv/bin/python -c 'from jarvis import config; print(config.OLLAMA_URL)')"
export OLLAMA_HOST="$ollama_url"   # the ollama command talks to the same Ollama as Jarvis

echo "==> Downloading $base into Ollama at $ollama_url (skipped if it's already there)"
ollama show "$base" >/dev/null 2>&1 || ollama pull "$base"
echo "==> Building $name from it"
modelfile="$(mktemp)"
sed "s#^FROM .*#FROM $base#" deploy/ollama/Modelfile > "$modelfile"
threads="${JARVIS_MODEL_THREADS:-$(grep -m1 '^JARVIS_MODEL_THREADS=' .env | cut -d= -f2- || true)}"
[ -z "$threads" ] || echo "PARAMETER num_thread $threads" >> "$modelfile"
ollama create "$name" -f "$modelfile" >/dev/null
rm -f "$modelfile"

backup="$HOME/jarvis-backups/$(date +%Y%m%d-%H%M%S)-model"
mkdir -p "$backup" && chmod 700 "$backup"
cp .env "$backup/env" && cp "$hermes_home/config.yaml" "$backup/hermes-config.yaml"
echo "==> Pointing Jarvis and Hermes at $name (the previous settings are in $backup)"
.venv/bin/python - "$repo/.env" "$hermes_home/config.yaml" "$base" "$name" "$ollama_url" <<'PY'
import re
import sys
from pathlib import Path

env_file, hermes_file, base, name, ollama_url = sys.argv[1:]

# .env: the model to build from and Jarvis's name for it (install.sh reads both on its next run).
env = Path(env_file)
lines = [l for l in env.read_text().splitlines() if not l.startswith(("JARVIS_CHAT_BASE=", "JARVIS_CHAT_MODEL="))]
env.write_text("\n".join(lines + [f"JARVIS_CHAT_BASE={base}", f"JARVIS_CHAT_MODEL={name}"]) + "\n")

# Hermes: its main model is this local one again, through the "ollama-launch" provider Jarvis set up. Line by line,
# so the comments in the file stay.
cfg = Path(hermes_file)
out, block = [], None
for line in cfg.read_text().splitlines():
    top = re.match(r"^([A-Za-z_]\w*):", line)
    if top:
        block = top.group(1)
    if block == "model" and re.match(r"^  (provider|default|base_url):", line):
        key = line.split(":")[0].strip()
        line = {"provider": "  provider: ollama-launch", "default": f"  default: {name}",
                "base_url": f"  base_url: {ollama_url}/v1"}[key]
    elif block == "providers" and re.match(r"^    default_model: ", line):
        line = f"    default_model: {name}"
    elif block == "providers" and re.match(r"^    api: ", line):
        line = f"    api: {ollama_url}/v1"
    elif block == "providers" and re.match(r"^      - ", line):
        if f"      - {name}" in out:
            continue  # the provider's model list: just this model, once
        line = f"      - {name}"
    out.append(line)
cfg.write_text("\n".join(out) + "\n")
PY

restart="sudo systemctl restart jarvis-hermes jarvis-web"
[ "$(uname -s)" = Darwin ] && restart="hermes gateway restart && launchctl kickstart -k gui/\$(id -u)/com.jarvis.web"
cat <<EOF

Jarvis now uses $name ($base). Restart it to load the model:

  $restart

The first reply then reads Jarvis's instructions afresh (minutes on a small server). Check the memory with
\`free -h\` and \`ollama ps\` after a chat. To go back: bin/use-model.sh qwen3.5:4b-q4_K_M
EOF
