#!/bin/bash
# Hermes cron (every 20 min): keep Jarvis's chat and search models loaded so the first reply after idle time is fast.
# (The Ollama app forces a 30-minute idle unload whatever OLLAMA_KEEP_ALIVE says.)
# Load-only requests: they run no prompt, so the model's prompt cache is left intact. Prints nothing on success.
# An embedding model loads through /api/embed, not /api/generate.
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
# Failure messages go through jarvis-notify as "Important problems" (see the other jarvis scripts).
{
  for target in "generate qwen3.5-4b-64k" "embed bge-m3"; do
    set -- $target
    extra=""; [ "$1" = embed ] && extra=',"input":[]'
    out=$(curl -s -m 120 "http://127.0.0.1:11434/api/$1" -d "{\"model\":\"$2\",\"keep_alive\":\"2h\"$extra}")
    echo "$out" | grep -q '"done":true\|"embeddings"' || echo "Jarvis keep-warm failed for $2: ${out:-Ollama not reachable}"
  done
  # Health of the app: its server (database, Hermes, Ollama) and the HTTPS front door the phone uses.
  health=$(curl -s -m 15 http://127.0.0.1:8791/api/health)
  echo "$health" | grep -q '"ok": *true' || echo "⚠️ The Jarvis app is unhealthy: ${health:-the app server is not answering}"
  # The front door only where it is set up (docs/remote-access.md): Caddy on a Mac, or on a server's VPN address.
  # A machine without it is not reported every 20 minutes.
  # The server's address is in its Caddyfile: https://10.8.0.1, or :8443 when another program has port 443. The
  # manifest answers without signing in, so this works with the app's sign-in on.
  server_app=$(grep -m1 -oE '^https://10\.8\.0\.1(:[0-9]+)?' /etc/caddy/Caddyfile 2>/dev/null)
  for front in "/opt/homebrew/var/lib/caddy/pki/authorities/local/root.crt https://localhost:3444/manifest.webmanifest" \
               "/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt ${server_app:-https://10.8.0.1}/manifest.webmanifest"; do
    set -- $front
    [ -r "$1" ] || continue
    code=$(curl -s -m 10 --cacert "$1" -o /dev/null -w '%{http_code}' "$2")
    [ "$code" = 200 ] || echo "⚠️ The Jarvis app's HTTPS address is not answering (Caddy, code ${code:-none})."
  done
  # A public name (docs/public-address.md), checked with its real certificate. Asked on the server's own network
  # address, because Oracle doesn't send a server's requests to its own public IP back to it.
  public_name=$(grep -m1 -oE '^https://[a-z0-9.-]+\.[a-z]{2,} \{' /etc/caddy/Caddyfile 2>/dev/null | sed -E 's#^https://##; s# \{$##')
  if [ -n "$public_name" ]; then
    local_ip=$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p')
    code=$(curl -s -m 10 --resolve "$public_name:443:${local_ip:-127.0.0.1}" -o /dev/null -w '%{http_code}' \
      "https://$public_name/manifest.webmanifest")
    [ "$code" = 200 ] || echo "⚠️ The Jarvis app's public address https://$public_name is not answering (Caddy, code ${code:-none})."
  fi
} | "$HOME/jarvis-system/.venv/bin/jarvis-notify" problems --one
# Keep Jarvis's long prompt cached as well, with one throwaway chat in the background (see jarvis-warm-chat), so the
# user never waits minutes for it to be read after a restart, the nightly AI jobs or midnight.
nohup "$HOME/jarvis-system/.venv/bin/jarvis-warm-chat" >> "$HOME/jarvis-system/logs/warm-chat.log" 2>&1 < /dev/null &
