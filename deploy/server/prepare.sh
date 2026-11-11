#!/bin/bash
# Get a fresh Ubuntu 24.04 server ready for Jarvis, before install.sh (docs/install-server.md): security updates, a swap
# file, SSH with keys only, the WireGuard VPN with one profile for your phone and one for your computer, and HTTPS
# for the app on the VPN address. Nothing of Jarvis is reachable from the internet; only WireGuard answers, unless
# you give it a public name (JARVIS_DOMAIN below).
#
#   deploy/server/prepare.sh PUBLIC_IP
#
# Run it as the server's normal user (ubuntu on Oracle) from the cloned repo; it uses sudo. Safe to run again:
# keys, profiles and settings already there are kept. bin/server.sh setup runs it for you from the Mac.
# CADDY_CA_DIR=<folder with root.crt and root.key>: use that certificate authority for HTTPS (your Mac's), so a phone
# that already trusts it needs no new certificate.
# JARVIS_HTTPS_PORT=<port>: the app's HTTPS port on the VPN address. Normally 443; 8443 when another program already
# uses 443 (Coolify's proxy, for one), so the app is then https://10.8.0.1:8443.
# JARVIS_DOMAIN=<name>: also serve the app on this public name, e.g. yourname.dynv6.net, with a free Let's Encrypt
# certificate, so the phone needs no VPN (docs/public-address.md). Set a sign-in first; the app refuses public
# names until then. Kept when this runs again without it.
set -euo pipefail

PUBLIC_IP="${1:-}"
VPN_DIR="$HOME/jarvis-vpn"        # the phone's and the computer's VPN profiles (private keys: keep them private)
SERVER_VPN_IP="10.8.0.1"
PORT=51820
CADDY_PKI="/var/lib/caddy/.local/share/caddy/pki/authorities/local"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
# The public name: given now, or the one this script set up before (a name in the Caddyfile, not an IP address).
DOMAIN="${JARVIS_DOMAIN:-$(grep -m1 -oE '^https://[a-z0-9.-]+\.[a-z]{2,} \{' /etc/caddy/Caddyfile 2>/dev/null \
  | sed -E 's#^https://##; s# \{$##' || true)}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[31mStopped: %s\033[0m\n' "$*" >&2; exit 1; }
[ -n "$PUBLIC_IP" ] || fail "give the server's public IP: deploy/server/prepare.sh PUBLIC_IP"
[ "$(id -u)" != 0 ] || fail "run this as the server's normal user (ubuntu), not root."
. /etc/os-release
[ "$ID" = ubuntu ] || fail "this is for Ubuntu (24.04); this server runs $PRETTY_NAME."
export DEBIAN_FRONTEND=noninteractive

# ---------- 1. Updates ----------
say "System updates, and security updates from now on by themselves"
sudo apt-get update -q
# PREPARE_SKIP_UPGRADE=1 (the weekly test run) leaves the system's packages as they are.
[ -n "${PREPARE_SKIP_UPGRADE:-}" ] || sudo apt-get -y -q -o Dpkg::Options::=--force-confold full-upgrade >/dev/null
sudo apt-get install -y -q unattended-upgrades fail2ban wireguard qrencode caddy rsync >/dev/null
printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' \
  | sudo tee /etc/apt/apt.conf.d/20auto-upgrades >/dev/null

# ---------- 2. Memory: a swap file as a safety margin ----------
if [ -z "$(swapon --show --noheadings)" ]; then
  say "A 4 GB swap file"
  sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

# ---------- 3. SSH: keys only, no root, and fail2ban for anyone guessing ----------
say "SSH: keys only, no root login"
if [ -x /usr/sbin/sshd ]; then
  printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\n' \
    | sudo tee /etc/ssh/sshd_config.d/60-jarvis.conf >/dev/null
  sudo sshd -t && sudo systemctl reload-or-restart ssh
fi
sudo systemctl enable --now fail2ban >/dev/null 2>&1 || echo "  Warning: fail2ban didn't start (journalctl -u fail2ban)."

# ---------- 4. Firewall: WireGuard in; everything on the VPN ----------
# Oracle's Ubuntu images refuse everything not allowed in iptables (iptables-persistent, rules in
# /etc/iptables/rules.v4), ahead of any ufw rules; other servers come with ufw only. Jarvis's own services listen on
# 127.0.0.1 or the VPN address only.
say "Firewall: WireGuard (UDP $PORT) from the internet$([ -n "$DOMAIN" ] && echo ", the web (TCP 80, 443) for $DOMAIN"), the rest only on the VPN"
WEB_PORTS=""
[ -z "$DOMAIN" ] || WEB_PORTS="80 443"  # 80 only answers Let's Encrypt and sends browsers to https
# "Installed" means installed: a package removed with its settings left behind (ufw takes iptables-persistent's
# place that way) doesn't count, and the firewall the server already uses is kept.
installed() { dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q " installed$"; }
if ! installed iptables-persistent && installed ufw; then
  sudo ufw allow "$PORT/udp" >/dev/null && sudo ufw allow in on wg0 >/dev/null
  for web in $WEB_PORTS; do sudo ufw allow "$web/tcp" comment "Jarvis web" >/dev/null; done
  sudo ufw status | grep -q "^Status: active" || echo "  Note: ufw is installed but off, so only Oracle's security list protects this server."
else
  # Not saving the live rules on install: they may hold Docker's and ufw's (see below).
  echo "iptables-persistent iptables-persistent/autosave_v4 boolean false" | sudo debconf-set-selections
  echo "iptables-persistent iptables-persistent/autosave_v6 boolean false" | sudo debconf-set-selections
  sudo apt-get install -y -q iptables-persistent >/dev/null
  sudo iptables -C INPUT -p udp --dport "$PORT" -j ACCEPT 2>/dev/null || sudo iptables -I INPUT -p udp --dport "$PORT" -j ACCEPT
  sudo iptables -C INPUT -i wg0 -j ACCEPT 2>/dev/null || sudo iptables -I INPUT -i wg0 -j ACCEPT
  for web in $WEB_PORTS; do
    sudo iptables -C INPUT -p tcp --dport "$web" -j ACCEPT 2>/dev/null || sudo iptables -I INPUT -p tcp --dport "$web" -j ACCEPT
  done
  # Kept for the next boot: only these rules go into the saved set, ahead of its "refuse everything else" rule.
  # Saving all the live rules would also store Docker's and ufw's (Coolify runs in Docker), which they make again
  # themselves at boot.
  rules=/etc/iptables/rules.v4
  if sudo grep -q '^-A INPUT -j REJECT' "$rules" 2>/dev/null; then
    saved=("-A INPUT -p udp -m udp --dport $PORT -j ACCEPT" "-A INPUT -i wg0 -j ACCEPT")
    for web in $WEB_PORTS; do saved+=("-A INPUT -p tcp -m tcp --dport $web -j ACCEPT"); done
    for rule in "${saved[@]}"; do
      sudo grep -qxF -- "$rule" "$rules" || sudo sed -i "/^-A INPUT -j REJECT/i $rule" "$rules"
    done
  else
    sudo netfilter-persistent save >/dev/null
  fi
fi

# ---------- 5. WireGuard: the private network, with a profile for the phone and one for the computer ----------
say "WireGuard VPN ($SERVER_VPN_IP), profiles in $VPN_DIR"
mkdir -p "$VPN_DIR" && chmod 700 "$VPN_DIR"
(
  umask 077
  cd "$VPN_DIR"
  [ -f server.key ] || wg genkey > server.key
  wg pubkey < server.key > server.pub
  for device in phone computer; do
    [ -f "$device.key" ] || wg genkey > "$device.key"
    wg pubkey < "$device.key" > "$device.pub"
  done
  # AllowedIPs = only the server: the rest of the phone's internet doesn't go through the VPN, so it can stay on.
  profile() {  # profile DEVICE ADDRESS
    printf '[Interface]\nAddress = %s/32\nPrivateKey = %s\n\n[Peer]\nPublicKey = %s\nEndpoint = %s:%s\nAllowedIPs = %s/32\nPersistentKeepalive = 25\n' \
      "$2" "$(cat "$1.key")" "$(cat server.pub)" "$PUBLIC_IP" "$PORT" "$SERVER_VPN_IP" > "$1.conf"
  }
  profile phone 10.8.0.2
  profile computer 10.8.0.3
  printf '[Interface]\nAddress = %s/24\nListenPort = %s\nPrivateKey = %s\n\n[Peer]\n# phone\nPublicKey = %s\nAllowedIPs = 10.8.0.2/32\n\n[Peer]\n# computer\nPublicKey = %s\nAllowedIPs = 10.8.0.3/32\n' \
    "$SERVER_VPN_IP" "$PORT" "$(cat server.key)" "$(cat phone.pub)" "$(cat computer.pub)" > wg0.conf
)
sudo install -m 600 -o root -g root "$VPN_DIR/wg0.conf" /etc/wireguard/wg0.conf && rm "$VPN_DIR/wg0.conf"
sudo systemctl enable wg-quick@wg0 >/dev/null 2>&1
sudo systemctl restart wg-quick@wg0

# ---------- 6. HTTPS for the app, on the VPN address (and the public name, if any) ----------
# 443 unless another program already listens on it (Caddy itself doesn't count, when this runs again).
HTTPS_PORT="${JARVIS_HTTPS_PORT:-}"
if [ -z "$HTTPS_PORT" ]; then
  HTTPS_PORT=443
  if sudo ss -Hltnp 'sport = :443' | grep -qv '"caddy"'; then
    HTTPS_PORT=8443
    echo "  Port 443 is taken by another program ($(sudo ss -Hltnp 'sport = :443' | grep -v '"caddy"' | grep -o '(("[^"]*"' | head -1 | tr -d '("')), so the app uses 8443."
  fi
fi
APP_URL="https://$SERVER_VPN_IP$([ "$HTTPS_PORT" = 443 ] || echo ":$HTTPS_PORT")"
PUBLIC_SITES=""
if [ -n "$DOMAIN" ]; then
  [ "$HTTPS_PORT" = 443 ] && ! sudo ss -Hltnp 'sport = :80' | grep -qv '"caddy"' \
    || fail "the public name needs ports 80 and 443, and another program uses one of them."
  # The server's own address on its network (Oracle passes its public IP on to it), so these don't clash with the
  # VPN address's port 443.
  LOCAL_IP="$(ip -4 route get 1.1.1.1 | sed -n 's/.* src \([0-9.]*\).*/\1/p')"
  PUBLIC_SITES="
# The public name (docs/public-address.md), with a free Let's Encrypt certificate. Port 80 only answers Let's Encrypt
# and sends browsers to https. The app asks for a sign-in (docs/sign-in.md).
http://$DOMAIN {
	bind $LOCAL_IP
	redir https://$DOMAIN{uri} permanent
}

https://$DOMAIN {
	bind $LOCAL_IP
	header Strict-Transport-Security \"max-age=31536000\"
	reverse_proxy 127.0.0.1:8791 {
		flush_interval -1
	}
}"
fi
say "HTTPS for the app at $APP_URL (Caddy)"
if [ -n "${CADDY_CA_DIR:-}" ] && [ -f "$CADDY_CA_DIR/root.key" ]; then
  # Your Mac's certificate authority: a phone that trusts it already trusts this server too. Certificates Caddy
  # made from another authority before are dropped, so it makes new ones from this one.
  sudo systemctl stop caddy
  sudo install -d -m 700 -o caddy -g caddy "$CADDY_PKI"
  sudo install -m 600 -o caddy -g caddy "$CADDY_CA_DIR/root.crt" "$CADDY_CA_DIR/root.key" "$CADDY_PKI/"
  sudo rm -f "$CADDY_PKI/intermediate.crt" "$CADDY_PKI/intermediate.key"
  sudo rm -rf /var/lib/caddy/.local/share/caddy/certificates/local
  # The folders above the authority were just made by root; Caddy has to write its certificates next to them.
  sudo chown -R caddy:caddy /var/lib/caddy/.local
fi
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
# Jarvis (deploy/server/prepare.sh): the app over HTTPS on the VPN address, with Caddy's own certificate. Replies
# stream, so they are passed on straight away. No port 80 redirect there: the app is only ever opened by its https://
# address, and port 80 may belong to another program.
{
	skip_install_trust
	auto_https disable_redirects
}

$APP_URL {
	bind $SERVER_VPN_IP
	tls internal
	reverse_proxy 127.0.0.1:8791 {
		flush_interval -1
	}
}
$PUBLIC_SITES
EOF
# Caddy listens on the VPN address, so it starts after WireGuard.
sudo mkdir -p /etc/systemd/system/caddy.service.d
printf '[Unit]\nAfter=wg-quick@wg0.service\nRequires=wg-quick@wg0.service\n' \
  | sudo tee /etc/systemd/system/caddy.service.d/wireguard.conf >/dev/null
sudo systemctl daemon-reload && sudo systemctl enable caddy >/dev/null 2>&1 && sudo systemctl restart caddy
# Jarvis answers only to its own names (JARVIS_HOSTS), so the public one is added once Jarvis is installed.
if [ -n "$DOMAIN" ] && [ -f "$REPO/.env" ]; then
  hosts="$(sed -n 's/^JARVIS_HOSTS=//p' "$REPO/.env" | tail -1)"
  case ",$hosts," in
    *",$DOMAIN,"*) ;;
    *) if [ -n "$hosts" ]; then sed -i "s|^JARVIS_HOSTS=.*|JARVIS_HOSTS=$hosts,$DOMAIN|" "$REPO/.env"
       else echo "JARVIS_HOSTS=$SERVER_VPN_IP,$DOMAIN" >> "$REPO/.env"; fi
       ! systemctl is-active -q jarvis-web || sudo systemctl restart jarvis-web ;;
  esac
fi

say "The server is ready for install.sh"
[ ! -f /var/run/reboot-required ] || echo "  The updates need a restart: sudo reboot (the VPN and HTTPS come back by themselves)."
cat <<EOF
  VPN profiles:  $VPN_DIR/phone.conf and $VPN_DIR/computer.conf (private keys: keep them private)
  Phone:         qrencode -t ansiutf8 < $VPN_DIR/phone.conf    then scan it in the WireGuard app
  The app:       $APP_URL with the VPN on, once Jarvis is installed$([ -z "$DOMAIN" ] || printf '\n  Public:        https://%s from anywhere, after you set a sign-in (docs/sign-in.md);\n                 Oracle: allow TCP 80 and 443 too' "$DOMAIN")
  Oracle:        allow UDP $PORT in the network's security list (docs/install-server.md); once the VPN works, remove TCP 22
EOF
