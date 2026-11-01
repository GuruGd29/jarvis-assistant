#!/bin/bash
# Put this repo's Jarvis parts into Hermes (~/.hermes): the plugin, the scheduled-job scripts, and SOUL.md with
# your settings from .env filled in ({{LANGUAGES}}). Run it after changing .env or updating Jarvis, then
# restart Hermes (`hermes gateway restart`, or `sudo systemctl restart jarvis-hermes` on a server).
# The repo is the source: edit hermes/ here, never the copies in ~/.hermes.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
hermes_home="${HERMES_HOME:-$HOME/.hermes}"

mkdir -p "$hermes_home/plugins/jarvis" "$hermes_home/scripts"
cp "$repo/hermes/plugins/jarvis/__init__.py" "$repo/hermes/plugins/jarvis/plugin.yaml" "$hermes_home/plugins/jarvis/"
cp "$repo"/hermes/scripts/jarvis-*.sh "$hermes_home/scripts/"
chmod +x "$hermes_home"/scripts/jarvis-*.sh

# SOUL.md with the settings filled in; the previous one is kept next to it.
[ -f "$hermes_home/SOUL.md" ] && cp "$hermes_home/SOUL.md" "$hermes_home/SOUL.md.previous"
cd "$repo" && .venv/bin/python - "$hermes_home/SOUL.md" <<'PY'
import sys
from pathlib import Path
from jarvis import config

soul = Path("hermes/SOUL.md").read_text().replace("{{LANGUAGES}}", config.LANGUAGES)
Path(sys.argv[1]).write_text(soul)
print(f"Jarvis files are in {Path(sys.argv[1]).parent}: languages {config.LANGUAGES!r}, "
      f"{config.LOCALE} {config.CURRENCY}, time zone {config.TIMEZONE}. Restart Hermes to load them.")
PY
