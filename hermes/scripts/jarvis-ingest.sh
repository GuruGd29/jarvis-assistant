#!/bin/bash
# Hermes cron (every 15 min): index new or changed files in ~/Jarvis (unchanged files are skipped by hash).
# Output goes to the log; Telegram hears about it only when indexing fails.
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
# Failure messages go through jarvis-notify as "Important problems" (see the other jarvis scripts).
{
  log="$HOME/jarvis-system/logs/ingest.log"
  "$HOME/jarvis-system/.venv/bin/jarvis-ingest" >> "$log" 2>&1 || echo "⚠️ Jarvis couldn't index new files in ~/Jarvis (see $log)."
} | "$HOME/jarvis-system/.venv/bin/jarvis-notify" problems --one
