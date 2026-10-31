#!/bin/bash
# Hermes cron (every 30 min): read new HDFC/ICICI alert emails into the transactions table. Silent.
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
# Output goes through jarvis-notify: stored in the app's Activity, pushed to the phone if that kind is
# switched on, and echoed for Telegram while "Also send to Telegram" is on.
"$HOME/jarvis-system/.venv/bin/jarvis-money-sync" --days 2 | "$HOME/jarvis-system/.venv/bin/jarvis-notify" problems --one
