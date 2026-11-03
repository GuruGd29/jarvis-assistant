#!/bin/bash
# Update Jarvis on a server to the newest version on GitHub (docs/server.md): the new code, new Python packages when
# there are any, database changes, Hermes settings when they changed, then a restart of what changed. If Jarvis isn't
# healthy afterwards, it goes back to the version before by itself. Run on the server, where the services are
# systemd's; from the Mac, `bin/server.sh update` runs it. Database changes stay when it goes back (they only add).
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '==> %s\n' "$*"; }
fail() { printf 'Stopped: %s\n' "$*" >&2; exit 1; }
wait_for() {  # wait_for URL SECONDS
  for _ in $(seq "$2"); do curl -sf "$1" >/dev/null && return 0; sleep 1; done
  return 1
}
[ "$(uname -s)" = Linux ] || fail "this is for the server. On a Mac: git pull, then restart the app (docs/install-mac.md)."
[ -z "$(git status --porcelain --untracked-files=no)" ] || fail "the server's copy has local changes (git status)."

before="$(git rev-parse HEAD)"
git fetch -q origin main
after="$(git rev-parse origin/main)"
if [ "$before" = "$after" ]; then
  echo "Jarvis is up to date: $(git log -1 --format='%h %s')"
  exit 0
fi
changed="$(git diff --name-only "$before" "$after")"

apply() {  # make the checked-out version run; the parts restarted follow the files that changed
  if grep -qE '^(install\.sh|deploy/)' <<< "$changed"; then
    say "The installer changed: running it again (a few minutes; log: logs/update-install.log)"
    JARVIS_INSTALL_YES=1 ./install.sh > logs/update-install.log 2>&1 || return 1
  elif grep -qE '^(requirements\.lock|pyproject\.toml)$' <<< "$changed"; then
    say "New Python packages"
    .venv/bin/pip install -q -r requirements.lock && .venv/bin/pip install -q --no-deps -e . || return 1
  fi
  .venv/bin/jarvis-migrate >/dev/null || return 1
  if grep -q '^hermes/' <<< "$changed"; then
    say "Hermes settings changed: restarting Hermes (the next reply is slower once)"
    bin/apply-settings.sh >/dev/null && sudo systemctl restart jarvis-hermes || return 1
    wait_for http://127.0.0.1:8642/health 300 || return 1
  fi
  sudo systemctl restart jarvis-web
  wait_for http://127.0.0.1:8791/api/health 90
}

say "Updating $(git rev-parse --short "$before") -> $(git rev-parse --short "$after"): $(git log -1 --format=%s "$after")"
git merge -q --ff-only "$after"
if apply; then
  (.venv/bin/jarvis-warm-chat >/dev/null 2>&1 &)  # the first reply after a restart is quick again
  echo "Updated: $(git log -1 --format='%h %s')"
  exit 0
fi

say "The new version isn't healthy: going back to $(git rev-parse --short "$before")"
git reset -q --hard "$before"
apply || fail "going back didn't help either: see journalctl -u jarvis-web -u jarvis-hermes"
fail "the update was undone and Jarvis runs the version before. See journalctl -u jarvis-web -u jarvis-hermes."
