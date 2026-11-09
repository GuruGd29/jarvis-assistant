#!/bin/bash
# Get a fresh Ubuntu 24.04 server ready for Jarvis, before install.sh (docs/server.md): security updates, a swap
# file, SSH with keys only, the WireGuard VPN with one profile for your phone and one for your computer, and HTTPS
# for the app on the VPN address only. Nothing of Jarvis is reachable from the internet; only WireGuard answers.
#
#   deploy/server/prepare.sh PUBLIC_IP
#
# Run it as the server's normal user (ubuntu on Oracle) from the cloned repo; it uses sudo. Safe to run again:
# keys, profiles and settings already there are kept. bin/server.sh setup runs it for you from the Mac.
# CADDY_CA_DIR=<folder with root.crt and root.key>: use that certificate authority for HTTPS (your Mac's), so a phone
# that already trusts it needs no new certificate.
# JARVIS_HTTPS_PORT=<port>: the app's HTTPS port on the VPN address. Normally 443; 8443 when another program already
# uses 443 (Coolify's proxy, for one), so the app is then https://10.8.0.1:8443.
set -euo pipefail

PUBLIC_IP="${1:-}"
VPN_DIR="$HOME/jarvis-vpn"        # the phone's and the computer's VPN profiles (private keys: keep them private)
SERVER_VPN_IP="10.8.0.1"
PORT=51820
CADDY_PKI="/var/lib/caddy/.local/share/caddy/pki/authorities/local"

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
say "Firewall: WireGuard (UDP $PORT) from the internet, Jarvis only on the VPN"
if ! dpkg -s iptables-persistent >/dev/null 2>&1 && command -v ufw >/dev/null; then
  sudo ufw allow "$PORT/udp" >/dev/null && sudo ufw allow in on wg0 >/dev/null
else
  echo "iptables-persistent iptables-persistent/autosave_v4 boolean true" | sudo debconf-set-selections
  echo "iptables-persistent iptables-persistent/autosave_v6 boolean true" | sudo debconf-set-selections
  sudo apt-get install -y -q iptables-persistent >/dev/null
  sudo iptables -C INPUT -p udp --dport "$PORT" -j ACCEPT 2>/dev/null || sudo iptables -I INPUT -p udp --dport "$PORT" -j ACCEPT
  sudo iptables -C INPUT -i wg0 -j ACCEPT 2>/dev/null || sudo iptables -I INPUT -i wg0 -j ACCEPT
  # Kept for the next boot: only these two rules go into the saved set, ahead of its "refuse everything else" rule.
  # Saving all the live rules would also store Docker's and ufw's (Coolify runs in Docker), which they make again
  # themselves at boot.
  rules=/etc/iptables/rules.v4
  if sudo grep -q '^-A INPUT -j REJECT' "$rules" 2>/dev/null; then
    for rule in "-A INPUT -p udp -m udp --dport $PORT -j ACCEPT" "-A INPUT -i wg0 -j ACCEPT"; do
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

# ---------- 6. HTTPS for the app, on the VPN address only ----------
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
say "HTTPS for the app at $APP_URL (Caddy)"
if [ -n "${CADDY_CA_DIR:-}" ] && [ -f "$CADDY_CA_DIR/root.key" ]; then
  # Your Mac's certificate authority: a phone that trusts it already trusts this server too. Certificates Caddy
  # made from another authority before are dropped, so it makes new ones from this one.
  sudo systemctl stop caddy
  sudo install -d -m 700 -o caddy -g caddy "$CADDY_PKI"
  sudo install -m 600 -o caddy -g caddy "$CADDY_CA_DIR/root.crt" "$CADDY_CA_DIR/root.key" "$CADDY_PKI/"
  sudo rm -f "$CADDY_PKI/intermediate.crt" "$CADDY_PKI/intermediate.key"
  sudo rm -rf /var/lib/caddy/.local/share/caddy/certificates/local
fi
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
# Jarvis (deploy/server/prepare.sh): the app over HTTPS on the VPN address only. Replies stream, so they are passed
# on straight away. No port 80 redirect: the app is only ever opened by its https:// address, and port 80 may belong
# to another program.
{
	local_certs
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
EOF
# Caddy listens on the VPN address, so it starts after WireGuard.
sudo mkdir -p /etc/systemd/system/caddy.service.d
printf '[Unit]\nAfter=wg-quick@wg0.service\nRequires=wg-quick@wg0.service\n' \
  | sudo tee /etc/systemd/system/caddy.service.d/wireguard.conf >/dev/null
sudo systemctl daemon-reload && sudo systemctl enable caddy >/dev/null 2>&1 && sudo systemctl restart caddy

say "The server is ready for install.sh"
[ ! -f /var/run/reboot-required ] || echo "  The updates need a restart: sudo reboot (the VPN and HTTPS come back by themselves)."
cat <<EOF
  VPN profiles:  $VPN_DIR/phone.conf and $VPN_DIR/computer.conf (private keys: keep them private)
  Phone:         qrencode -t ansiutf8 < $VPN_DIR/phone.conf    then scan it in the WireGuard app
  The app:       $APP_URL with the VPN on, once Jarvis is installed
  Oracle:        allow UDP $PORT in the network's security list (docs/server.md); once the VPN works, remove TCP 22
EOF
