"""Files the user adds in the app (docs/files.md), in two separate ways:

- attached to one chat (the 📎 in Chat): read into text for that conversation only. It is kept a week in
  state/attachments/ and is never added to the user's files, searched or learned from.
- added to their files (More → Your files): saved into ~/Jarvis/<folder>/ and indexed at once, so any chat can find
  and quote it, like the files Jarvis already reads from that folder.
"""
import contextlib
import io
import json
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

from .. import config, ingest, ocr
from ..parse import parse_file

ATTACH_DIR = config.SYSTEM_DIR / "state" / "attachments"
KEEP_ATTACHMENTS_DAYS = 7
MAX_BYTES = 20_000_000
MAX_CHARS = 60_000  # about 15,000 words: what the chat model can read with room left for the conversation
FOLDERS = ("documents", "finance", "health", "notes")
READABLE = sorted(config.SUPPORTED_SUFFIXES)
VIEW_CHARS = 200_000  # the quick view shows this much of what Jarvis read
PICTURE_WIDTH = 1400  # PDF pages and HEIC photos are shown as JPEGs this wide

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
        photos = sorted(s.lstrip(".").upper() for s in config.IMAGE_SUFFIXES if s != ".jpeg")
        raise ValueError("Jarvis can read PDF, Word, text, Markdown, CSV, JSON and web page files"
                         + (f", and photos ({', '.join(photos)})." if photos else
                            ". Photos need text recognition (Tesseract, docs/files.md)."))


def _no_text() -> str:
    """Why a file came out empty."""
    if ocr.available():
        return "no words were found in it"
    return "a scanned PDF needs text recognition (Tesseract, docs/files.md)"


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
        raise ValueError(f"{name} has no text Jarvis can read: {_no_text()}.")
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
                "note": f"Saved, but it has no text Jarvis can read: {_no_text()}."}
    return {"path": str(target.relative_to(config.DATA_ROOT)), "name": target.name, "searchable": True,
            "note": f"Saved and ready: Jarvis can answer from {target.name} in any chat."}


def _mine(relative: str) -> Path:
    """One of the user's files in ~/Jarvis, by its path there; nothing outside it, nothing hidden."""
    target = (config.DATA_ROOT / (relative or "")).resolve()
    root = config.DATA_ROOT.resolve()
    if not target.is_file() or not target.is_relative_to(root) or any(
            p.startswith(".") for p in target.relative_to(root).parts):
        raise LookupError("no such file")
    return target


def _kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif"}:
        return "photo"
    return "text" if suffix in config.SUPPORTED_SUFFIXES else "other"


def view(relative: str) -> dict:
    """What the quick view in Your files shows: the file's details and the text Jarvis reads in it."""
    target = _mine(relative)
    relative = target.relative_to(config.DATA_ROOT.resolve())
    kind, stat, pages, sections, error = _kind(target), target.stat(), None, [], None
    try:
        if kind == "pdf":
            import pypdfium2

            with contextlib.closing(pypdfium2.PdfDocument(str(target))) as pdf:
                pages = len(pdf)
        if target.suffix.lower() in config.SUPPORTED_SUFFIXES:
            sections = [{"heading": s.heading, "page": s.page, "text": s.text.strip()} for s in parse_file(target)
                        if s.text and s.text.strip()]
    except Exception:
        kind, error = "other", "Jarvis couldn't read this file: it may be damaged or password-protected."
    shown, cut = [], False
    for section in sections:
        room = VIEW_CHARS - sum(len(s["text"]) for s in shown)
        if room <= 0:
            cut = True
            break
        cut = cut or len(section["text"]) > room
        shown.append({**section, "text": section["text"][:room]})
    with _db() as conn:
        searchable = conn.execute("SELECT 1 FROM documents WHERE path IN (%s, %s)",
                                  (str(target), str(config.DATA_ROOT / relative))).fetchone()
    return {"path": str(relative), "name": target.name, "folder": relative.parts[0], "kind": kind,
            "size": stat.st_size, "added": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "pages": pages, "sections": shown, "cut": cut, "error": error, "searchable": bool(searchable),
            "readable": target.suffix.lower() in config.SUPPORTED_SUFFIXES,
            "picture": kind == "pdf" or target.suffix.lower() == ".heic"}


def raw(relative: str) -> Path:
    """The file itself, for the quick view and the Open button."""
    return _mine(relative)


def picture(relative: str, page: int = 1) -> bytes:
    """A JPEG of a PDF page, or of a HEIC photo (browsers other than Safari can't show HEIC)."""
    from PIL import Image, ImageOps

    target = _mine(relative)
    if target.suffix.lower() == ".pdf":
        import pypdfium2

        with contextlib.closing(pypdfium2.PdfDocument(str(target))) as pdf:
            if not 1 <= page <= len(pdf):
                raise LookupError("no such page")
            width = pdf[page - 1].get_width() or 612
            image = pdf[page - 1].render(scale=min(4.0, PICTURE_WIDTH / width)).to_pil()
    elif target.suffix.lower() == ".heic" and config.HEIC_CONVERTER:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp, "photo.jpg")
            ocr.convert_heic(target, out)
            with Image.open(out) as converted:
                image = ImageOps.exif_transpose(converted).copy()
        image.thumbnail((PICTURE_WIDTH * 2, PICTURE_WIDTH * 2))
    else:
        raise LookupError("no picture for this file")
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "JPEG", quality=82)
    return buffer.getvalue()


def remove_file(relative: str) -> None:
    """Delete a file from ~/Jarvis and from the index."""
    target = _mine(relative)
    target.unlink()
    with _db() as conn:
        conn.execute("DELETE FROM documents WHERE path IN (%s, %s)", (str(target), str(config.DATA_ROOT / relative)))
