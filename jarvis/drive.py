"""Copy the Google Drive folder "Jarvis" into ~/Jarvis so it is searched like any other file. Read-only:
Jarvis never changes Drive. Runs only when asked ("sync drive" in chat, or jarvis-drive-sync).

Files land in ~/Jarvis/documents/Drive/..., except a top-level Drive subfolder named finance, health or
notes, which lands in ~/Jarvis/<that>/Drive/... Google Docs are saved as .docx, Sheets as .csv (first
sheet) and Slides as .pdf. A file deleted from the Drive folder is deleted here too; files Jarvis did not
copy from Drive are never touched.

  jarvis-drive-sync          sync now, print a one-line summary
  jarvis-drive-sync --quiet  print only on failure
"""
import argparse
import fcntl
import io
import json
import sys
from pathlib import Path

from . import calendars, config

FOLDER_NAME = "Jarvis"
SCOPE = "https://www.googleapis.com/auth/drive.readonly"
MANIFEST = config.DATA_ROOT / ".drive-sync.json"   # hidden, so it is not indexed
LOCK = config.DATA_ROOT / ".drive-sync.lock"
MAX_BYTES = 50 * 1024 * 1024
FOLDER = "application/vnd.google-apps.folder"
EXPORTS = {
    "application/vnd.google-apps.document": (".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "application/vnd.google-apps.spreadsheet": (".csv", "text/csv"),
    "application/vnd.google-apps.presentation": (".pdf", "application/pdf"),
}
DOMAIN_FOLDERS = {"finance", "health", "notes"}


class NotSignedIn(RuntimeError):
    pass


def _service():
    from googleapiclient.discovery import build

    creds = calendars.google_credentials()
    if SCOPE not in (creds.scopes or []):
        raise NotSignedIn("Drive access isn't granted yet: run  ~/jarvis-system/.venv/bin/jarvis-auth google  on your Mac.")
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _list(service, query: str) -> list[dict]:
    items, token = [], None
    while True:
        page = service.files().list(q=query, pageToken=token, pageSize=1000, spaces="drive",
                                    fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)").execute()
        items += page.get("files", [])
        token = page.get("nextPageToken")
        if not token:
            return items


def _walk(service, folder_id: str, parts: tuple[str, ...] = ()) -> list[tuple[dict, tuple[str, ...]]]:
    out = []
    for item in _list(service, f"'{folder_id}' in parents and trashed = false"):
        if item["mimeType"] == FOLDER:
            out += _walk(service, item["id"], parts + (item["name"],))
        else:
            out.append((item, parts))
    return out


def _safe(name: str) -> str:
    return name.replace("/", "-").replace("\0", "").strip() or "untitled"


def _local_path(item: dict, parts: tuple[str, ...]) -> Path | None:
    name = _safe(item["name"])
    if item["mimeType"] in EXPORTS:
        suffix = EXPORTS[item["mimeType"]][0]
        name = name if name.lower().endswith(suffix) else name + suffix
    elif Path(name).suffix.lower() not in config.SUPPORTED_SUFFIXES:
        return None  # photos, zips and the like: nothing Jarvis can read
    parts = tuple(_safe(p) for p in parts)
    if parts and parts[0].lower() in DOMAIN_FOLDERS:
        return config.DATA_ROOT / parts[0].lower() / "Drive" / Path(*parts[1:], name)
    return config.DATA_ROOT / "documents" / "Drive" / Path(*parts, name)


def _download(service, item: dict, path: Path) -> None:
    from googleapiclient.http import MediaIoBaseDownload

    if item["mimeType"] in EXPORTS:
        request = service.files().export_media(fileId=item["id"], mimeType=EXPORTS[item["mimeType"]][1])
    else:
        request = service.files().get_media(fileId=item["id"])
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.part")
    tmp.write_bytes(buffer.getvalue())
    tmp.replace(path)


def sync() -> dict:
    """Mirror the Drive folder into ~/Jarvis, then index the changes. Returns the counts."""
    config.DATA_ROOT.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # one sync at a time
        service = _service()
        folders = _list(service, f"name = '{FOLDER_NAME}' and mimeType = '{FOLDER}' and 'root' in parents and trashed = false")
        if not folders:
            raise FileNotFoundError(f"No folder named \"{FOLDER_NAME}\" at the top of your Google Drive.")
        manifest: dict = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
        counts = {"added": 0, "updated": 0, "removed": 0, "unchanged": 0, "skipped": 0, "failed": 0}
        seen = {}
        for item, parts in _walk(service, folders[0]["id"]):
            path = _local_path(item, parts)
            if path is None or int(item.get("size") or 0) > MAX_BYTES:
                counts["skipped"] += 1
                continue
            seen[item["id"]] = {"path": str(path), "modified": item["modifiedTime"]}
            old = manifest.get(item["id"])
            if old and old["modified"] == item["modifiedTime"] and old["path"] == str(path) and path.exists():
                counts["unchanged"] += 1
                continue
            try:
                _download(service, item, path)
            except Exception as error:
                print(f"failed {item['name']}: {error}", file=sys.stderr)
                counts["failed"] += 1
                seen.pop(item["id"])
                if old:
                    seen[item["id"]] = old  # keep the earlier copy
                continue
            if old and old["path"] != str(path):
                Path(old["path"]).unlink(missing_ok=True)  # renamed or moved in Drive
            counts["updated" if old else "added"] += 1
        for file_id, old in manifest.items():
            if file_id not in seen:
                Path(old["path"]).unlink(missing_ok=True)
                counts["removed"] += 1
        MANIFEST.write_text(json.dumps(seen, indent=1))
    if counts["added"] or counts["updated"] or counts["removed"]:
        _index()
    return counts


def _index() -> None:
    import contextlib

    import psycopg
    from pgvector.psycopg import register_vector

    from . import ingest

    with psycopg.connect(config.DB_DSN) as conn, contextlib.redirect_stdout(io.StringIO()):
        register_vector(conn)
        ingest.full_pass(conn)


def summary(counts: dict) -> str:
    changed = [f"{counts[k]} {k}" for k in ("added", "updated", "removed", "failed") if counts[k]]
    if not changed:
        return f"Drive folder \"{FOLDER_NAME}\" is already up to date ({counts["unchanged"]} file{"" if counts["unchanged"] == 1 else "s"})."
    return f"Drive folder \"{FOLDER_NAME}\" synced: {', '.join(changed)}. Changed files are searchable now."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    try:
        counts = sync()
    except Exception as error:
        print(f"⚠️ Jarvis couldn't sync your Drive folder: {error}")
        sys.exit(1)
    if not args.quiet or counts["failed"]:
        print(summary(counts))


if __name__ == "__main__":
    main()
