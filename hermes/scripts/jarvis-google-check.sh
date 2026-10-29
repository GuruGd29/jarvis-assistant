#!/bin/bash
# Hermes cron (daily 09:00): warn on Telegram before the Google sign-in expires. Silent when fine.
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
exec "$HOME/jarvis-system/.venv/bin/jarvis-google-check"
