#!/bin/bash
# (Re)create the Open WebUI container, pinned to an exact image so an upstream update can't change it overnight.
# Chats and settings live in the "open-webui" volume; the login key in that volume keeps everyone signed in.
# To upgrade on purpose: pull a new version, test it, then put its digest here.
set -euo pipefail
IMAGE="ghcr.io/open-webui/open-webui@sha256:096c8f3d3132016210ca87b0b4dff01d2d66d9fe4fee088fae13fc30f9ac54f3"  # main, 25 Oct 2026 (v0.12.4)
DOCKER="${DOCKER:-$(command -v docker || echo /opt/homebrew/bin/docker)}"

"$DOCKER" rm -f open-webui >/dev/null 2>&1 || true
"$DOCKER" run -d --name open-webui --restart always \
  -p 127.0.0.1:3000:8080 \
  -v open-webui:/app/backend/data \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -e WEBUI_SECRET_KEY_FILE=/app/backend/data/.webui_secret_key \
  "$IMAGE"
