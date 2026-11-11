"""Build the project page and the online demo into one folder for GitHub Pages (site/README.md).

  python3 site/build.py [OUT]      default OUT: _site

The page is site/index.html. The demo is the real phone app from web/app, unchanged except for paths that work
under a sub-folder, with site/demo/mock.js answering in place of the server (from site/demo/data.json).
Nothing here needs Jarvis to be installed; the GitHub Pages workflow runs it on every change.
"""
import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE, APP = ROOT / "site", ROOT / "web" / "app"
# The demo person's settings, as the real server puts them in the page (jarvis/web/server.py _profile).
PROFILE = {"name": "Priya", "locale": "en-IN", "currency": "INR", "host": "other", "voice": False, "photos": True,
           "signin": False}


def build(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # The project page and its pictures.
    shutil.copy(SITE / "index.html", out / "index.html")
    (out / "img").mkdir()
    for picture in (ROOT / "docs" / "screenshots").glob("*.png"):
        shutil.copy(picture, out / "img" / picture.name)
    shutil.copy(APP / "icons" / "icon-192.png", out / "img" / "icon-192.png")
    (out / ".nojekyll").write_text("")  # serve the files as they are

    # The demo: the real app, with root paths made relative, and the stand-in server loaded first.
    demo = out / "demo"
    shutil.copytree(APP, demo / "static", ignore=shutil.ignore_patterns("index.html", "sw.js", "manifest.webmanifest"))
    app_js = demo / "static" / "app.js"
    app_js.write_text(app_js.read_text().replace('"/static/', '"static/'))
    page = (APP / "index.html").read_text()
    page = re.sub(r'\s*<link rel="manifest"[^>]*>', "", page)
    page = page.replace('"/static/', '"static/').replace("<title>Jarvis</title>", "<title>Jarvis demo</title>")
    meta = f'<meta name="jarvis-profile" content="{html.escape(json.dumps(PROFILE))}">\n<script src="mock.js"></script>'
    if "<!-- jarvis-profile -->" not in page:
        sys.exit("web/app/index.html no longer has the <!-- jarvis-profile --> marker")
    (demo / "index.html").write_text(page.replace("<!-- jarvis-profile -->", meta, 1))
    shutil.copy(SITE / "demo" / "mock.js", demo / "mock.js")
    shutil.copy(SITE / "demo" / "data.json", demo / "data.json")
    print(f"built {out}: the page, {len(list((out / 'img').glob('*.png')))} pictures and the demo")


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "_site")
