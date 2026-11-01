#!/bin/bash
# Add Jarvis's scheduled jobs to Hermes, once each: jobs that already exist are left alone, so it is safe to run
# again (install.sh runs it; on a Mac run it yourself). Results go to the app's notifications, and also to Telegram
# when TELEGRAM_ALLOWED_USERS is set in ~/.hermes/.env. List them with `hermes cron list`; change a time with
# `hermes cron edit <id>`. Times are this computer's local time.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
hermes="${HERMES_BIN:-$HOME/.hermes/hermes-agent/.hermes/bin/hermes}"
telegram="$(grep '^TELEGRAM_ALLOWED_USERS=' "$HOME/.hermes/.env" 2>/dev/null | cut -d= -f2- | cut -d, -f1 || true)"
deliver="local"
[ -z "$telegram" ] || deliver="telegram:$telegram"
existing="$("$hermes" cron list 2>/dev/null < /dev/null || true)"

job() {  # job NAME "SCHEDULE" SCRIPT
  grep -qE "Name: +$1\$" <<< "$existing" && return 0
  "$hermes" cron create --name "$1" --script "$3" --no-agent --deliver "$deliver" "$2" < /dev/null >/dev/null
  echo "  + $1 ($2)"
}
job jarvis-reminders         "*/5 * * * *"  jarvis-reminders.sh        # task and medicine reminders
job jarvis-morning-briefing  "30 7 * * *"   jarvis-briefing.sh         # the morning brief
job jarvis-keepwarm          "*/20 * * * *" jarvis-keepwarm.sh         # keep the models loaded
job jarvis-google-check      "0 9 * * *"    jarvis-google-check.sh     # says so if Google sign-in stops working
job jarvis-money-sync        "*/30 * * * *" jarvis-money-sync.sh       # new bank alert emails
job jarvis-money-ai          "15 2 * * *"   jarvis-money-ai.sh         # other banks' emails, read by the AI
job jarvis-learn             "30 2 * * *"   jarvis-learn.sh            # remember facts from the day's chats
job jarvis-weekly-summary    "0 19 * * 0"   jarvis-weekly.sh           # Sunday evening: the week
job jarvis-task-sync         "*/15 * * * *" jarvis-task-sync.sh        # tasks to the iPhone calendar (iCloud only)
job jarvis-renewal-alerts    "0 9 * * *"    jarvis-renewal-alerts.sh   # renewals and expiry dates from your files
job jarvis-monthly-money     "0 9 1 * *"    jarvis-monthly.sh          # the 1st: last month's money report
job jarvis-memory-review     "0 20 * * 0"   jarvis-memory-review.sh    # Sunday: memories to check
job jarvis-ingest            "*/15 * * * *" jarvis-ingest.sh           # index new and changed files
# Backups only once they are set up (docs/backups.md), so a fresh install does not report failures every night.
[ ! -f "$repo/secrets/backup.env" ] || job jarvis-backup "0 3 * * *" jarvis-backup.sh
