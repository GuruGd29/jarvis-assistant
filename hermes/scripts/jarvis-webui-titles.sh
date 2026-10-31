#!/bin/bash
# Hermes cron (nightly 02:45, after jarvis-learn): title Open WebUI chats that have been quiet 30+ minutes. Prints nothing on success.
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
# Failure messages go through jarvis-notify as "Important problems" (see the other jarvis scripts).
{
  /opt/homebrew/bin/docker exec -i open-webui python3 - < ~/jarvis-system/bin/webui_titles.py 2>>~/jarvis-system/logs/webui-titles.log \
    || echo "Jarvis could not title Open WebUI chats; see ~/jarvis-system/logs/webui-titles.log"
} | "$HOME/jarvis-system/.venv/bin/jarvis-notify" problems --one
