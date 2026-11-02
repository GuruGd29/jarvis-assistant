"""Files the user adds in the app (docs/files.md), in two separate ways:

- attached to one chat (the 📎 in Chat): read into text for that conversation only. It is kept a week in
  state/attachments/ and is never added to the user's files, searched or learned from.
- added to their files (More → Your files): saved into ~/Jarvis/<folder>/ and indexed at once, so any chat can find
  and quote it, like the files Jarvis already reads from that folder.
"""
import json
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

from .. import config, ingest
from ..parse import parse_file

ATTACH_DIR = config.SYSTEM_DIR / "state" / "attachments"
KEEP_ATTACHMENTS_DAYS = 7
MAX_BYTES = 20_000_000
MAX_CHARS = 60_000  # about 15,000 words: what the chat model can read with room left for the conversation
FOLDERS = ("documents", "finance", "health", "notes")
READABLE = sorted(config.SUPPORTED_SUFFIXES)

# How an attached file travels inside the user's message to Hermes. The Jarvis plugin strips this block before it
# searches, learns or looks for commands; the app shows it as a file chip.
# " · " never appears in a safe file name, so it separates the name from its size.
_HEADER = "[Attached to this chat only (not saved to the user's files): {name} · {info}. Answer from it.]"
CHAT_FILE = re.compile(r"\[Attached to this chat only \(not saved to the user's files\): (?P<name>.+?) · (?P<info>[^\]]*?)"
                       r"\. Answer from it\.\]\n<<<FILE\n(?P<text>[\s\S]*?)\nFILE>>>\n?")


def safe_name(name: str) -> str:
    """A file name that is safe on disk: no folders, no odd characters, never empty."""
    name = Path((name or "").replace("\\", "/")).name
    # only what is unsafe in a file name goes; Tamil and other scripts (with their vowel signs) stay.
    # "·" too: it separates the name from its size in a chat message.
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*\u00b7]', "_", name).strip(" .")
    return name[:120] or "file"


def _readable(name: str) -> None:
    if Path(name).suffix.lower() not in config.SUPPORTED_SUFFIXES:
        raise ValueError(f"Jarvis can read {', '.join(s.lstrip('.') for s in READABLE if s not in ('.htm', '.markdown'))}"
                         " files. Photos and other files aren't readable yet.")


def _text(path: Path) -> tuple[str, int | None]:
    sections = parse_file(path)
    text = "\n\n".join(s.text.strip() for s in sections if s.text and s.text.strip())
    pages = max((s.page or 0 for s in sections), default=0) or None
    return text, pages


def _info(pages: int | None, words: int) -> str:
    return f"{pages} page{'' if pages == 1 else 's'}" if pages else f"{words:,} words"


# --- attached to one chat ---------------------------------------------------------------------------------------

def attach(name: str, data: bytes) -> dict:
    """Read a file attached in Chat; returns what the app shows on its chip."""
    name = safe_name(name)
    _readable(name)
    if len(data) > MAX_BYTES:
        raise ValueError("That file is over 20 MB.")
    _cleanup()
    folder = ATTACH_DIR / uuid.uuid4().hex
    folder.mkdir(parents=True)
    path = folder / name
    path.write_bytes(data)
    try:
        text, pages = _text(path)
    except Exception as error:
        shutil.rmtree(folder, ignore_errors=True)
        raise ValueError(f"Couldn't read {name}: it may be damaged or password-protected.") from error
    if not text.strip():
        shutil.rmtree(folder, ignore_errors=True)
        raise ValueError(f"{name} has no text Jarvis can read (a scanned PDF or a photo needs text recognition).")
    words, info = len(text.split()), _info(pages, len(text.split()))
    (folder / "text.txt").write_text(text[:MAX_CHARS])
    (folder / "about.json").write_text(json.dumps({"name": name, "info": info}))
    return {"id": folder.name, "name": name, "info": info, "words": words, "cut": len(text) > MAX_CHARS}


def message_with(attachment_id: str, text: str) -> tuple[str, str]:
    """The message for Hermes with the attached file's text in front, and the name for the chat's title."""
    if not re.fullmatch(r"[0-9a-f]{32}", attachment_id or ""):
        raise ValueError("That attachment is no longer there. Attach the file again.")
    folder = ATTACH_DIR / attachment_id
    if not (folder / "text.txt").is_file() or not (folder / "about.json").is_file():
        raise ValueError("That attachment is no longer there. Attach the file again.")
    about = json.loads((folder / "about.json").read_text())
    body = (folder / "text.txt").read_text()
    return f"{_HEADER.format(**about)}\n<<<FILE\n{body}\nFILE>>>\n{text}", about["name"]


def split_message(content: str) -> tuple[dict | None, str]:
    """A stored user message as the app shows it: the attached file (if any) and the user's own words."""
    match = CHAT_FILE.search(content or "")
    if not match:
        return None, content
    own = (content[:match.start()] + content[match.end():]).strip()
    return {"name": match.group("name"), "info": match.group("info")}, own


def _cleanup() -> None:
    """Attachments are kept a week, for re-reading a chat; then they go."""
    if not ATTACH_DIR.is_dir():
        return
    cutoff = time.time() - KEEP_ATTACHMENTS_DAYS * 86400
    for folder in ATTACH_DIR.iterdir():
        if folder.is_dir() and folder.stat().st_mtime < cutoff:
            shutil.rmtree(folder, ignore_errors=True)


# --- the user's own files (~/Jarvis) ----------------------------------------------------------------------------

def _db() -> psycopg.Connection:
    conn = psycopg.connect(config.DB_DSN)
    register_vector(conn)
    return conn


def my_files() -> dict:
    """Every file in ~/Jarvis by folder, with whether Jarvis can search it."""
    with _db() as conn:
        indexed = {path: chunks for path, chunks in conn.execute(
            "SELECT d.path, count(c.id) FROM documents d LEFT JOIN chunks c ON c.document_id = d.id GROUP BY d.path")}
    folders = []
    for folder in config.DOMAINS:
        base = config.DATA_ROOT / folder
        files = []
        for path in sorted(base.rglob("*")) if base.is_dir() else []:
            if not path.is_file() or any(p.startswith(".") for p in path.relative_to(config.DATA_ROOT).parts):
                continue
            stat = path.stat()
            files.append({"path": str(path.relative_to(config.DATA_ROOT)), "name": path.name,
                          "size": stat.st_size, "added": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                          "searchable": str(path) in indexed, "readable": path.suffix.lower() in config.SUPPORTED_SUFFIXES})
        files.sort(key=lambda f: f["added"], reverse=True)
        folders.append({"folder": folder, "files": files})
    return {"folders": folders, "upload_to": list(FOLDERS), "readable": READABLE}


def add_file(folder: str, name: str, data: bytes) -> dict:
    """Save a file into ~/Jarvis/<folder>/ and index it now (a name already there gets " (2)")."""
    if folder not in FOLDERS:
        raise ValueError("Pick Documents, Finance, Health or Notes.")
    name = safe_name(name)
    _readable(name)
    if len(data) > MAX_BYTES:
        raise ValueError("That file is over 20 MB.")
    target = config.DATA_ROOT / folder / name
    stem, suffix, n = target.stem, target.suffix, 2
    while target.exists():
        target = target.with_name(f"{stem} ({n}){suffix}")
        n += 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    try:
        with _db() as conn:
            status = ingest.index_file(conn, target)
    except Exception as error:
        target.unlink(missing_ok=True)
        raise ValueError(f"Couldn't read {name}: it may be damaged or password-protected.") from error
    if status == "empty":
        return {"path": str(target.relative_to(config.DATA_ROOT)), "name": target.name, "searchable": False,
                "note": "Saved, but it has no text Jarvis can read (a scanned PDF needs text recognition)."}
    return {"path": str(target.relative_to(config.DATA_ROOT)), "name": target.name, "searchable": True,
            "note": f"Saved and ready: Jarvis can answer from {target.name} in any chat."}


def remove_file(relative: str) -> None:
    """Delete a file from ~/Jarvis and from the index."""
    target = (config.DATA_ROOT / (relative or "")).resolve()
    if not target.is_file() or not target.is_relative_to(config.DATA_ROOT.resolve()):
        raise LookupError("no such file")
    target.unlink()
    with _db() as conn:
        conn.execute("DELETE FROM documents WHERE path IN (%s, %s)", (str(target), str(config.DATA_ROOT / relative)))
