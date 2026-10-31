#!/bin/bash
# Hermes cron (every 15 min): copy dated Jarvis tasks to the iCloud calendar "Jarvis Tasks". Prints only on failure.
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
# Output goes through jarvis-notify: stored in the app's Activity, pushed to the phone if that kind is
# switched on, and echoed for Telegram while "Also send to Telegram" is on.
"$HOME/jarvis-system/.venv/bin/jarvis-task-sync" | "$HOME/jarvis-system/.venv/bin/jarvis-notify" problems --one
