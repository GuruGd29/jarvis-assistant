#!/bin/bash
# Hermes cron (nightly at 02:30): turn queued chat messages into lasting facts in Jarvis's memory. Prints nothing on success.
unset PYTHONPATH PYTHONHOME
~/jarvis-system/.venv/bin/jarvis-learn 2>>~/jarvis-system/logs/learn.log || echo "Jarvis learning failed; see ~/jarvis-system/logs/learn.log"
