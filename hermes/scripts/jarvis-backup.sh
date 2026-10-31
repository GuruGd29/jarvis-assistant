#!/bin/bash
# Hermes cron (nightly 03:00): encrypted restic backup (see ~/jarvis-system/bin/backup.sh). Prints only on failure,
# which goes to the app as an "Important problems" notification.
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin"
"$HOME/jarvis-system/bin/backup.sh" 2>>"$HOME/jarvis-system/logs/backup.log" | "$HOME/jarvis-system/.venv/bin/jarvis-notify" problems --one
