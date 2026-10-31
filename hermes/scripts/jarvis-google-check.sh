#!/bin/bash
# Hermes cron (daily 09:00): warn on Telegram before the Google sign-in expires. Silent when fine.
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
# Output goes through jarvis-notify: stored in the app's Activity, pushed to the phone if that kind is
# switched on, and echoed for Telegram while "Also send to Telegram" is on.
"$HOME/jarvis-system/.venv/bin/jarvis-google-check" | "$HOME/jarvis-system/.venv/bin/jarvis-notify" problems --one
