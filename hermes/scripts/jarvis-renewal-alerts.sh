#!/bin/bash
# Hermes cron (daily 09:00): bills and renewals due in 2 days, from the user's files. Prints nothing when none are due.
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
exec "$HOME/jarvis-system/.venv/bin/jarvis-renewal-alerts"
