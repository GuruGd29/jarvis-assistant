#!/bin/bash
# Hermes cron (every 30 min): read new HDFC/ICICI alert emails into the transactions table. Silent.
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
exec "$HOME/jarvis-system/.venv/bin/jarvis-money-sync" --days 2
