#!/bin/bash
# Hermes cron (every 20 min): keep Jarvis's chat and search models loaded so the first reply after idle time is fast.
# (The Ollama app forces a 30-minute idle unload whatever OLLAMA_KEEP_ALIVE says.)
# Load-only requests: they run no prompt, so the model's prompt cache is left intact. Prints nothing on success.
# An embedding model loads through /api/embed, not /api/generate.
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
# Failure messages go through jarvis-notify as "Important problems" (see the other jarvis scripts).
{
  for target in "generate qwen3-4b-instruct-64k" "embed bge-m3"; do
    set -- $target
    extra=""; [ "$1" = embed ] && extra=',"input":[]'
    out=$(curl -s -m 120 "http://127.0.0.1:11434/api/$1" -d "{\"model\":\"$2\",\"keep_alive\":\"2h\"$extra}")
    echo "$out" | grep -q '"done":true\|"embeddings"' || echo "Jarvis keep-warm failed for $2: ${out:-Ollama not reachable}"
  done
  # Health of the app: its server (database, Hermes, Ollama) and the HTTPS front door the phone uses.
  health=$(curl -s -m 15 http://127.0.0.1:8791/api/health)
  echo "$health" | grep -q '"ok": *true' || echo "⚠️ The Jarvis app is unhealthy: ${health:-the app server is not answering}"
  ca="/opt/homebrew/var/lib/caddy/pki/authorities/local/root.crt"
  code=$(curl -s -m 10 --cacert "$ca" -o /dev/null -w '%{http_code}' https://localhost:3444/)
  [ "$code" = 200 ] || echo "⚠️ The Jarvis app's HTTPS address is not answering (Caddy, code ${code:-none})."
} | "$HOME/jarvis-system/.venv/bin/jarvis-notify" problems --one
