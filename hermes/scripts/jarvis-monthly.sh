#!/bin/bash
# Hermes cron (1st of the month, 09:00): last month's money report.
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
exec "$HOME/jarvis-system/.venv/bin/jarvis-monthly"
