# The project page and the online demo

Published by `.github/workflows/pages.yml` to **https://gurugd29.github.io/jarvis-assistant/** on every change to
`site/`, `web/app/` or the screenshots.

| File | What it is |
|---|---|
| `index.html` | the project page: one self-contained file, light and dark |
| `build.py` | puts the page, the screenshots and the demo into one folder: `python3 site/build.py _site` |
| `demo/mock.js` | stands in for the Jarvis server in the browser: answers the app from `data.json`, moves dates to today, and streams a few written chat replies |
| `demo/data.json` | every screen's data, recorded from a real Jarvis filled with made-up data |
| `demo/make_data.py` | makes `data.json` again (see below) |

The demo is the real phone app from `web/app`, so it changes with the app. Only paths are adjusted for the
sub-folder. Nothing in it is saved or sent anywhere.

**Try it locally:**

```bash
python3 site/build.py /tmp/pages/jarvis-assistant && python3 -m http.server 8000 --directory /tmp/pages
# then open http://127.0.0.1:8000/jarvis-assistant/
```

**Record the data again** when the app's screens change. This needs Postgres with pgvector and Ollama with bge-m3.
The script refuses to run against Jarvis's own database or folders. Every name, number and place in it is made up:

```bash
createdb jarvis_demo
JARVIS_DEMO=1 JARVIS_DB_NAME=jarvis_demo JARVIS_DATA_ROOT=$(mktemp -d) JARVIS_SECRETS_DIR=$(mktemp -d) \
  JARVIS_OWNER_NAME=Priya JARVIS_LOCALE=en_IN JARVIS_CURRENCY=INR JARVIS_TIMEZONE=Asia/Kolkata \
  .venv/bin/python site/demo/make_data.py
dropdb jarvis_demo
```
