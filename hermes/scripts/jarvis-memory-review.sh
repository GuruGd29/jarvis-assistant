#!/bin/bash
# Hermes cron (Sundays 20:00): suggest memory facts to archive; nothing changes until the user replies "clean up".
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
# Output goes through jarvis-notify: stored in the app's Activity, pushed to the phone if that kind is
# switched on, and echoed for Telegram while "Also send to Telegram" is on.
"$HOME/jarvis-system/.venv/bin/jarvis-memory-review" | "$HOME/jarvis-system/.venv/bin/jarvis-notify" reports --one
