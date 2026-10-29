"""Index ~/Jarvis into Postgres. Only new or changed files are re-embedded; deleted files are removed.

Usage:
  jarvis-ingest            one pass over the whole folder
  jarvis-ingest --watch    one pass, then re-index on every file change
"""
import argparse
import hashlib
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

from . import config
from .embed import embed
from .parse import Section, parse_file


def chunk_sections(sections: list[Section]) -> list[Section]:
    """Split long sections on paragraph boundaries into ~CHUNK_CHARS pieces with overlap."""
    chunks: list[Section] = []
    for section in sections:
        paragraphs = [p.strip() for p in section.text.split("\n\n") if p.strip()]
        current = ""
        for paragraph in paragraphs:
            # A single paragraph longer than a chunk is cut by characters.
            while len(paragraph) > config.CHUNK_CHARS:
                head, paragraph = paragraph[:config.CHUNK_CHARS], paragraph[config.CHUNK_CHARS - config.CHUNK_OVERLAP:]
                if current:
                    chunks.append(Section(section.heading, section.page, current))
                    current = ""
                chunks.append(Section(section.heading, section.page, head))
            if current and len(current) + len(paragraph) + 2 > config.CHUNK_CHARS:
                chunks.append(Section(section.heading, section.page, current))
                current = current[-config.CHUNK_OVERLAP:] + "\n\n" + paragraph
            else:
                current = f"{current}\n\n{paragraph}" if current else paragraph
        if current.strip():
            chunks.append(Section(section.heading, section.page, current))
    return chunks


def domain_of(path: Path) -> str:
    first = path.relative_to(config.DATA_ROOT).parts[0]
    return first if first in config.DOMAINS else "documents"


def is_indexable(path: Path) -> bool:
    relative = path.relative_to(config.DATA_ROOT)
    hidden = any(part.startswith(".") for part in relative.parts)
    return path.is_file() and not hidden and path.suffix.lower() in config.SUPPORTED_SUFFIXES


def index_file(conn: psycopg.Connection, path: Path) -> str:
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    row = conn.execute("SELECT id, content_hash FROM documents WHERE path = %s", (str(path),)).fetchone()
    if row and row[1] == content_hash:
        return "unchanged"

    chunks = chunk_sections(parse_file(path))
    if not chunks:
        return "empty"
    title = path.stem.replace("_", " ").replace("-", " ")
    # Title and heading are embedded with the text so "my car insurance" finds a chunk that only says "policy".
    vectors = embed([f"{title}\n{c.heading or ''}\n{c.text}" for c in chunks])

    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    with conn.transaction():
        if row:
            conn.execute("DELETE FROM documents WHERE id = %s", (row[0],))
        document_id = conn.execute(
            "INSERT INTO documents (path, domain, title, content_hash, modified_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (str(path), domain_of(path), title, content_hash, modified),
        ).fetchone()[0]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (document_id, ord, heading, page, content, embedding) VALUES (%s, %s, %s, %s, %s, %s)",
                [(document_id, i, c.heading, c.page, c.text, v) for i, (c, v) in enumerate(zip(chunks, vectors))],
            )
    return f"{'updated' if row else 'added'} ({len(chunks)} chunks)"


def remove_missing(conn: psycopg.Connection) -> int:
    removed = 0
    for document_id, path in conn.execute("SELECT id, path FROM documents").fetchall():
        candidate = Path(path)
        if not candidate.exists() or not candidate.is_relative_to(config.DATA_ROOT):
            conn.execute("DELETE FROM documents WHERE id = %s", (document_id,))
            print(f"removed   {path}")
            removed += 1
    conn.commit()
    return removed


def full_pass(conn: psycopg.Connection) -> None:
    started = time.time()
    counts: dict[str, int] = {}
    for path in sorted(config.DATA_ROOT.rglob("*")):
        if not is_indexable(path):
            continue
        try:
            status = index_file(conn, path)
        except Exception as error:  # one bad file must not stop the pass
            conn.rollback()
            status = f"failed: {error}"
        conn.commit()
        counts[status.split()[0]] = counts.get(status.split()[0], 0) + 1
        if status != "unchanged":
            print(f"{status:<24} {path.relative_to(config.DATA_ROOT)}")
    counts["removed"] = remove_missing(conn)
    try:
        from .health import import_lab_reports

        counts["lab_results"] = import_lab_reports()["results_saved"]
    except Exception as error:  # lab import must never block document indexing
        counts["lab_results"] = f"failed: {error}"
    print(f"pass done in {time.time() - started:.1f}s: {counts}")


def watch(conn: psycopg.Connection) -> None:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    pending: set[Path] = set()

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event):
            pending.add(Path(event.src_path))

    observer = Observer()
    observer.schedule(Handler(), str(config.DATA_ROOT), recursive=True)
    observer.start()
    print(f"watching {config.DATA_ROOT}")
    try:
        while True:
            time.sleep(5)  # debounce: editors write files in several steps
            if pending:
                pending.clear()
                full_pass(conn)
    finally:
        observer.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    if not config.DATA_ROOT.is_dir():
        sys.exit(f"{config.DATA_ROOT} does not exist")
    with psycopg.connect(config.DB_DSN) as conn:
        register_vector(conn)
        full_pass(conn)
        if args.watch:
            watch(conn)


if __name__ == "__main__":
    main()
