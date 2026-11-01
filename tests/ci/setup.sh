#!/bin/bash
# Build a throwaway Jarvis on a GitHub runner with the real installer (install.sh, no questions) on a machine set up
# like the Oracle server (ARM64 Ubuntu, the model on 2 CPU cores), then add the fake data. Run from the repo root
# by .github/workflows/weekly-tests.yml; the settings come from the workflow's environment.
set -euo pipefail

JARVIS_INSTALL_YES=1 JARVIS_MODEL_THREADS=2 ./install.sh   # 2 threads: the server's 2 OCPU

# The installer's scheduled jobs exist (13 without backups) but are paused here: the run starts at 2:00, next to
# the nightly jobs, which would compete with the timed chats. SRV-01/02 run the job scripts directly.
jobs="$(hermes cron list < /dev/null | grep -oE '^  [0-9a-f]{12}' || true)"
echo "scheduled jobs created: $(wc -w <<< "$jobs")"
[ "$(wc -w <<< "$jobs")" -ge 13 ] || { hermes cron list < /dev/null; exit 1; }
for id in $jobs; do hermes cron pause "$id" < /dev/null >/dev/null; done

# Fake data, then the search index.
.venv/bin/python tests/ci/seed.py
.venv/bin/jarvis-ingest | tail -1
curl -s http://127.0.0.1:8791/api/health; echo

# The same warm-up the server's keep-warm job runs, so the first test case is not charged for the cold start
# (loading the model and reading Jarvis's long prompt from scratch); its time is the server's cold start.
.venv/bin/jarvis-warm-chat || true
echo "setup done"
