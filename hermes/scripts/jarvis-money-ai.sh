#!/bin/bash
# Nightly: bank alert emails from banks without a built-in reader, read by the local AI (JARVIS_MONEY_AI).
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
"$HOME/jarvis-system/.venv/bin/jarvis-money-sync" --ai --days 3 | "$HOME/jarvis-system/.venv/bin/jarvis-notify" problems --one
