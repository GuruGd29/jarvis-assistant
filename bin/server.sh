#!/bin/bash
# Move Jarvis from this Mac to your own Ubuntu 24.04 server and look after it from here (docs/server.md).
#
#   bin/server.sh key        make the SSH key for the server; prints the public half for the server's sign-up form
#   bin/server.sh setup IP   prepare the server (updates, VPN, HTTPS) and install Jarvis there with this Mac's settings
#   bin/server.sh phone      show the phone's VPN profile as a QR code on this screen, to scan in the WireGuard app
#   bin/server.sh vpn        once this Mac's WireGuard is on: reach the server through the VPN from now on
#   bin/server.sh move       the switch: stop Jarvis here, copy everything to the server and start it there
#   bin/server.sh back       undo the switch: stop Jarvis on the server and start it on this Mac again
#   bin/server.sh update     after a push to GitHub: update the server (bin/update.sh there)
#   bin/server.sh status     what runs on the server
#
# move and back ask before they change anything (--yes to skip the question).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
HOST=jarvis-server                          # the ~/.ssh/config entry this script keeps
KEY="$HOME/.ssh/jarvis_server"
VPN_IP=10.8.0.1
REMOTE=jarvis-system                        # the repo's folder on the server, in the server user's home
MAC_SERVICES=(ai.hermes.gateway com.jarvis.web)   # what runs Jarvis on this Mac (LaunchAgents)
CA_DIR="$(brew --prefix 2>/dev/null || echo /opt/homebrew)/var/lib/caddy/pki/authorities/local"   # the phone trusts it

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[31mStopped: %s\033[0m\n' "$*" >&2; exit 1; }
on_server() { ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" "$@"; }
confirm() {  # confirm "question": yes with --yes, else asks
  [ "${YES:-}" = 1 ] && return 0
  [ -t 0 ] || fail "add --yes to go ahead without the question."
  read -rp "$1 [y/N] " answer
  [[ $answer =~ ^[Yy] ]] || fail "nothing changed."
}
env_get() { grep "^$2=" "$1" 2>/dev/null | head -1 | cut -d= -f2- || true; }
mac_python() { (cd "$REPO" && .venv/bin/python -c "$1"); }

ssh_entry() {  # ssh_entry ADDRESS: point the jarvis-server entry in ~/.ssh/config at ADDRESS
  local config="$HOME/.ssh/config"
  mkdir -p "$HOME/.ssh" && touch "$config" && chmod 600 "$config"
  sed -i '' '/^# >>> jarvis-server/,/^# <<< jarvis-server/d' "$config"
  printf '# >>> jarvis-server (bin/server.sh)\nHost %s\n  HostName %s\n  User ubuntu\n  IdentityFile %s\n  IdentitiesOnly yes\n  StrictHostKeyChecking accept-new\n  ServerAliveInterval 30\n# <<< jarvis-server\n' \
    "$HOST" "$1" "$KEY" >> "$config"
}

key() {
  [ -f "$KEY" ] || ssh-keygen -q -t ed25519 -N "" -C "jarvis-server" -f "$KEY"
  echo "Paste this public key where the server asks for an SSH key (Oracle: 'Paste public keys'):"
  echo
  cat "$KEY.pub"
}

setup() {
  local ip="${1:-}"
  [[ $ip =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "give the server's public IP: bin/server.sh setup 1.2.3.4"
  [ -f "$KEY" ] || fail "make the SSH key first: bin/server.sh key"
  ssh_entry "$ip"
  say "Connecting to $ip"
  on_server true || fail "can't log in to ubuntu@$ip with $KEY (is the key added and TCP 22 open?)."

  say "Jarvis's code on the server"
  on_server "[ -d $REMOTE/.git ] || git clone -q $(git -C "$REPO" remote get-url origin) $REMOTE; cd $REMOTE && git pull -q --ff-only"

  say "Preparing the server: updates, swap, SSH, firewall, VPN, HTTPS (a few minutes)"
  if [ -f "$CA_DIR/root.key" ]; then  # this Mac's certificate authority, so the phone needs no new certificate
    on_server 'rm -rf /tmp/jarvis-ca && mkdir -m 700 /tmp/jarvis-ca'
    scp -q "$CA_DIR/root.crt" "$CA_DIR/root.key" "$HOST:/tmp/jarvis-ca/"
  fi
  on_server "CADDY_CA_DIR=/tmp/jarvis-ca $REMOTE/deploy/server/prepare.sh $ip; rm -rf /tmp/jarvis-ca"

  say "Your settings, from this Mac"
  if ! on_server "[ -f $REMOTE/.env ]"; then
    {
      for key in JARVIS_OWNER_NAME JARVIS_LOCALE JARVIS_CURRENCY JARVIS_LANGUAGES JARVIS_CONTACT_EMAIL JARVIS_MONEY_AI \
                 JARVIS_VOICE_WORDS JARVIS_VOICE_KEEP JARVIS_CHAT_MODEL JARVIS_EMBED_MODEL; do
        value="$(env_get "$REPO/.env" "$key")"
        [ -z "$value" ] || echo "$key=$value"
      done
      echo "JARVIS_TIMEZONE=$(mac_python 'from jarvis import config; print(config.TIMEZONE)')"
      echo "JARVIS_HOSTS=$VPN_IP"
    } | on_server "umask 077 && cat > $REMOTE/.env"
  fi

  say "Installing Jarvis on the server (15-30 minutes, mostly downloads; log: ~/$REMOTE/logs/install.log there)"
  # Started apart from this connection, so a dropped connection doesn't stop it; this window follows the log.
  on_server "cd $REMOTE && mkdir -p logs && (JARVIS_INSTALL_YES=1 setsid nohup ./install.sh > logs/install.log 2>&1; echo \"install exit \$?\" >> logs/install.log) > /dev/null 2>&1 &"
  sleep 3
  on_server "tail -n +1 -f $REMOTE/logs/install.log & t=\$!; while ! grep -q '^install exit' $REMOTE/logs/install.log; do sleep 5; done; sleep 1; kill \$t"
  on_server "grep -q '^install exit 0' $REMOTE/logs/install.log" || fail "the install stopped; see the log above."

  say "This Mac's VPN profile"
  scp -q "$HOST:jarvis-vpn/computer.conf" "$REPO/secrets/wireguard-jarvis.conf" && chmod 600 "$REPO/secrets/wireguard-jarvis.conf"
  cat <<EOF

  Jarvis is installed on the server; this Mac still runs your Jarvis until 'bin/server.sh move'.
  Next:
    1. Oracle: allow UDP 51820 in the network's security list (docs/server.md).
    2. This Mac: WireGuard app (Mac App Store) -> Import tunnel from file -> $REPO/secrets/wireguard-jarvis.conf
       -> Activate. Then: bin/server.sh vpn
    3. Phone: WireGuard app -> + -> Create from QR code, with: bin/server.sh phone
EOF
}

phone() {
  local png
  png="$(mktemp -t jarvis-phone-vpn).png"
  on_server "qrencode -t png -s 8 -o - < jarvis-vpn/phone.conf" > "$png"
  chmod 600 "$png"
  open "$png"
  echo "Scan the QR code in the WireGuard app on your phone (+ -> Create from QR code), then switch the tunnel on."
  if [ -t 0 ]; then read -rp "Press Enter when it's scanned (the picture is then deleted). "; else sleep 180; fi
  rm -f "$png"
}

vpn() {
  ssh -o BatchMode=yes -o ConnectTimeout=10 -o HostName="$VPN_IP" "$HOST" true \
    || fail "can't reach $VPN_IP: is this Mac's WireGuard tunnel switched on?"
  ssh_entry "$VPN_IP"
  echo "The server is now reached through the VPN ($VPN_IP)."
  echo "Last step: in Oracle's security list, delete the TCP 22 rule. Then only WireGuard answers from the internet."
}

hermes_list() {  # the Hermes state that moves; the Hermes program itself is installed on the server
  printf '%s\n' .env auth.json memories sessions skills pairing platforms shared kanban channel_directory.json \
    'telegram_update_receipts_*.json' 'state.db*' 'response_store.db*' 'kanban.db*' 'projects.db*' 'runs_idempotency.db*'
}

move() {
  on_server "curl -sf http://127.0.0.1:8791/api/health >/dev/null" \
    || fail "Jarvis isn't installed and running on the server yet (bin/server.sh setup)."
  local data_root
  data_root="$(mac_python 'from jarvis import config; print(config.DATA_ROOT)')"
  cat <<EOF
The switch moves Jarvis to the server:
  - stops Jarvis and its Telegram bot on this Mac (the code, the models and the database stay here, untouched)
  - copies the database, $data_root, the sign-ins in secrets/ and Hermes's chats and memory to the server
  - starts Jarvis there, with the same scheduled jobs; 'bin/server.sh back' undoes it
EOF
  confirm "Move Jarvis to the server now?"

  say "Stopping Jarvis on this Mac"
  for label in "${MAC_SERVICES[@]}"; do
    launchctl disable "gui/$(id -u)/$label" 2>/dev/null || true
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  done
  on_server "sudo systemctl stop jarvis-web jarvis-hermes"

  say "Copying the database"
  docker exec jarvis-db pg_dump -U jarvis -d jarvis --no-owner --no-privileges | gzip | on_server "cat > /tmp/jarvis-move.sql.gz"
  on_server "$REMOTE/deploy/server/restore-db.sh /tmp/jarvis-move.sql.gz '$data_root' && rm /tmp/jarvis-move.sql.gz"

  say "Copying your files, sign-ins and Hermes's chats and memory"
  rsync -a --exclude .DS_Store "$data_root/" "$HOST:Jarvis/"
  rsync -a --exclude backup.env --exclude 'wireguard-*' "$REPO/secrets/" "$HOST:$REMOTE/secrets/"
  rsync -a --include learn-queue.jsonl --include memory-review.json --exclude '*' "$REPO/state/" "$HOST:$REMOTE/state/"
  local filters=()
  while read -r item; do filters+=(--include "/$item" --include "/$item/***"); done < <(hermes_list)
  rsync -a "${filters[@]}" --exclude '*' "$HOME/.hermes/" "$HOST:.hermes/"

  say "Starting Jarvis on the server"
  on_server "cd $REMOTE && bin/apply-settings.sh >/dev/null && bin/add-jobs.sh && sudo systemctl enable --now jarvis-hermes jarvis-web >/dev/null 2>&1 \
    && sudo systemctl restart jarvis-hermes && for i in \$(seq 300); do curl -sf http://127.0.0.1:8642/health >/dev/null && break; sleep 1; done \
    && sudo systemctl restart jarvis-web && sleep 5 && curl -sf http://127.0.0.1:8791/api/health >/dev/null \
    && (.venv/bin/jarvis-warm-chat >/dev/null 2>&1 &)" || fail "Jarvis didn't come up on the server: bin/server.sh back puts it back on this Mac."
  cat <<EOF

  Jarvis now runs on the server. On your phone, with the VPN on:
    1. open https://$VPN_IP in Safari, Share -> Add to Home Screen (a new app: the address changed)
    2. in the new app: More -> Notifications -> turn them on; then delete the old Jarvis from the Home Screen
  Telegram keeps working as before. 'bin/server.sh back' undoes the switch.
EOF
}

back() {
  cat <<EOF
Undo the switch: Jarvis stops on the server and starts on this Mac again. Anything new on the server since the
switch (chats, payments read, files added there) stays on the server and is not copied back.
EOF
  confirm "Go back to the Mac?"
  on_server "sudo systemctl disable --now jarvis-web jarvis-hermes" || echo "  (couldn't reach the server; stop it there yourself)"
  for label in "${MAC_SERVICES[@]}"; do
    launchctl enable "gui/$(id -u)/$label"
    launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/$label.plist" 2>/dev/null || launchctl kickstart -k "gui/$(id -u)/$label"
  done
  echo "Jarvis runs on this Mac again."
}

update() { on_server "cd $REMOTE && bin/update.sh"; }

status() {
  on_server "systemctl is-active jarvis-hermes jarvis-web ollama caddy wg-quick@wg0 | paste -sd ' ' -; cd $REMOTE && git log -1 --format='%h %s'; curl -s http://127.0.0.1:8791/api/health; echo; free -h | head -2; df -h / | tail -1"
}

args=()
for arg in "$@"; do [ "$arg" = --yes ] && YES=1 || args+=("$arg"); done
set -- "${args[@]:-}"
case "${1:-}" in
  key) key ;;
  setup) setup "${2:-}" ;;
  phone) phone ;;
  vpn) vpn ;;
  move) move ;;
  back) back ;;
  update) update ;;
  status) status ;;
  *) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
