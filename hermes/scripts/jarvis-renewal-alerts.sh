#!/bin/bash
# Hermes cron (daily 09:00): bills and renewals due in 2 days, from the user's files. Prints nothing when none are due.
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
# Output goes through jarvis-notify: stored in the app's Activity, pushed to the phone if that kind is
# switched on, and echoed for Telegram while "Also send to Telegram" is on.
"$HOME/jarvis-system/.venv/bin/jarvis-renewal-alerts" | "$HOME/jarvis-system/.venv/bin/jarvis-notify" renewals
