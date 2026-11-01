#!/bin/bash
# Runs at login (com.jarvis.startup). Ollama reads its settings only when it starts, and
# launchctl setenv is cleared on every reboot, so set them here and restart Ollama once.
set -u
echo "$(date '+%F %T') jarvis startup"

launchctl setenv OLLAMA_CONTEXT_LENGTH 32768
launchctl setenv OLLAMA_FLASH_ATTENTION 1
launchctl setenv OLLAMA_KV_CACHE_TYPE q8_0
launchctl setenv OLLAMA_KEEP_ALIVE 30m     # the app forces 30m anyway; the jarvis-keepwarm cron keeps models loaded
launchctl setenv OLLAMA_MAX_LOADED_MODELS 3
launchctl setenv OLLAMA_NUM_PARALLEL 1
launchctl setenv OLLAMA_NO_CLOUD 1          # local models only

# Docker Desktop: jarvis-db and open-webui have restart policies and come up with it.
[ -d /Applications/Docker.app ] && open -g -a Docker   # only when Postgres runs in Docker (docker-compose.yml)

# Ollama may already have started from its own login item, before the settings existed.
pkill -x Ollama; pkill -f "Ollama.app/Contents/Resources/ollama serve"
sleep 3
open -g -a Ollama
echo "$(date '+%F %T') done"
