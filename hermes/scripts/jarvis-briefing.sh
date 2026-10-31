#!/bin/bash
# Hermes cron: Jarvis briefing. Hermes sets PYTHONPATH for itself; the Jarvis venv must not inherit it.
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
# Output goes through jarvis-notify: stored in the app's Activity, pushed to the phone if that kind is
# switched on, and echoed for Telegram while "Also send to Telegram" is on.
"$HOME/jarvis-system/.venv/bin/jarvis-briefing" | "$HOME/jarvis-system/.venv/bin/jarvis-notify" reports --one
