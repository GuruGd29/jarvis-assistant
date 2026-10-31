#!/bin/bash
# Hermes cron: Jarvis weekly summary (Sundays 19:00). Hermes sets PYTHONPATH for itself; the Jarvis venv must not inherit it.
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
exec "$HOME/jarvis-system/.venv/bin/jarvis-weekly"
