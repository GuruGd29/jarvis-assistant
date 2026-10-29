#!/bin/bash
# Copy the Jarvis parts that live inside ~/.hermes into this repo's hermes/ folder, so git tracks them.
# Run before committing. Hermes's config.yaml, .env, memory and chats are never copied.
set -eu
repo="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$repo/hermes/plugins/jarvis" "$repo/hermes/scripts"
cp "$HOME/.hermes/plugins/jarvis/__init__.py" "$repo/hermes/plugins/jarvis/"
cp "$HOME/.hermes/SOUL.md" "$repo/hermes/"
cp "$HOME"/.hermes/scripts/jarvis-*.sh "$repo/hermes/scripts/"
