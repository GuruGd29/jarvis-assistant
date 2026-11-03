#!/bin/bash
# The server scripts on a fresh Ubuntu 24.04 ARM runner, after install.sh (docs/server.md): prepare.sh (VPN, HTTPS,
# firewall), the app's server checks behind HTTPS, restore-db.sh (a database copy back in), and bin/update.sh,
# including going back by itself when a new version is broken. Run from the repo root by weekly-tests.yml.
set -euo pipefail

check() { printf '  %-58s' "$1"; shift; if "$@" >/dev/null 2>&1; then echo ok; else echo FAILED; exit 1; fi; }
wait_for() { for _ in $(seq "$2"); do curl -sf "$1" >/dev/null && return 0; sleep 1; done; return 1; }
status() { curl -s -o /dev/null -w '%{http_code}' --cacert /tmp/jarvis-ca.crt "$@"; }

echo "== deploy/server/prepare.sh"
PREPARE_SKIP_UPGRADE=1 deploy/server/prepare.sh 203.0.113.10 > logs/prepare.log 2>&1 || { tail -30 logs/prepare.log; exit 1; }
check "WireGuard is up on 10.8.0.1" ip -4 addr show wg0
check "phone and computer VPN profiles made" test -s ~/jarvis-vpn/phone.conf -a -s ~/jarvis-vpn/computer.conf
[ ! -x /usr/sbin/sshd ] || check "SSH takes keys only" sudo grep -q "PasswordAuthentication no" /etc/ssh/sshd_config.d/60-jarvis.conf
grep -q '^JARVIS_HOSTS=' .env || echo "JARVIS_HOSTS=10.8.0.1" >> .env
sudo systemctl restart jarvis-web && wait_for http://127.0.0.1:8791/api/health 60
for _ in $(seq 30); do sudo test -f /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt && break; sleep 1; done
sudo cat /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt > /tmp/jarvis-ca.crt
check "the app over HTTPS on the VPN address" test "$(status https://10.8.0.1/api/health)" = 200
check "another host name is refused (421)" test "$(status -H 'Host: evil.example' http://127.0.0.1:8791/api/health)" = 421
check "a change from another website is refused (403)" \
  test "$(status -X POST -H 'Origin: https://evil.example' https://10.8.0.1/api/push/unsubscribe -d '{}')" = 403
check "the server itself still reaches the app" test "$(status http://127.0.0.1:8791/api/health)" = 200

echo "== deploy/server/restore-db.sh"
count() { PGPASSWORD="$(grep '^JARVIS_DB_PASSWORD=' .env | cut -d= -f2-)" psql -X -tA -h 127.0.0.1 -U jarvis -d jarvis -c "$1"; }
before="$(count 'SELECT count(*) FROM documents'):$(count 'SELECT count(*) FROM chunks')"
PGPASSWORD="$(grep '^JARVIS_DB_PASSWORD=' .env | cut -d= -f2-)" pg_dump -h 127.0.0.1 -U jarvis -d jarvis --no-owner --no-privileges \
  | gzip > /tmp/jarvis-copy.sql.gz
sudo systemctl stop jarvis-web jarvis-hermes
deploy/server/restore-db.sh /tmp/jarvis-copy.sql.gz /old/home/Jarvis
sudo systemctl start jarvis-hermes jarvis-web
wait_for http://127.0.0.1:8642/health 300 && wait_for http://127.0.0.1:8791/api/health 90
check "the same files and chunks after the copy ($before)" \
  test "$(count 'SELECT count(*) FROM documents'):$(count 'SELECT count(*) FROM chunks')" = "$before"

echo "== bin/update.sh"
# A stand-in for GitHub: a local copy of this version as "main", which gets a good and then a broken new version.
git config --global user.email ci@example.com && git config --global user.name CI
git clone -q --bare . /tmp/origin.git
git -C /tmp/origin.git branch -f main HEAD
git remote set-url origin /tmp/origin.git && git fetch -q origin && git checkout -q -B main
git clone -q /tmp/origin.git /tmp/work && git -C /tmp/work checkout -q main
echo "# a new version" >> /tmp/work/jarvis/web/__init__.py
git -C /tmp/work commit -qam "A good change" && git -C /tmp/work push -q origin main
check "a good version is installed" bin/update.sh
check "and runs" test "$(git log -1 --format=%s)" = "A good change"
good="$(git rev-parse HEAD)"
echo "this is not python (" >> /tmp/work/jarvis/web/server.py
git -C /tmp/work commit -qam "A broken change" && git -C /tmp/work push -q origin main
check "a broken version is refused" bash -c '! bin/update.sh'
check "and Jarvis is back on the good one, healthy" test "$(git rev-parse HEAD)" = "$good"
check "the app answers" curl -sf http://127.0.0.1:8791/api/health
echo "server checks passed"
