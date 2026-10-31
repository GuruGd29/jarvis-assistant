#!/bin/bash
# Hermes cron (1st of the month, 09:00): last month's money report.
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
# Output goes through jarvis-notify: stored in the app's Activity, pushed to the phone if that kind is
# switched on, and echoed for Telegram while "Also send to Telegram" is on.
"$HOME/jarvis-system/.venv/bin/jarvis-monthly" | "$HOME/jarvis-system/.venv/bin/jarvis-notify" reports --one
