#!/bin/bash
# Hermes cron (Sundays 20:00): suggest memory facts to archive; nothing changes until the user replies "clean up".
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
exec "$HOME/jarvis-system/.venv/bin/jarvis-memory-review"
