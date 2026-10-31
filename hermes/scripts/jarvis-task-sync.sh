#!/bin/bash
# Hermes cron (every 15 min): copy dated Jarvis tasks to the iCloud calendar "Jarvis Tasks". Prints only on failure.
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
exec "$HOME/jarvis-system/.venv/bin/jarvis-task-sync"
