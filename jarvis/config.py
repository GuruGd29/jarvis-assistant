"""Settings, read from environment variables with ~/jarvis-system/.env as fallback."""
import os
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent.parent


def _load_env_file() -> None:
    env_file = SYSTEM_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_env_file()

DATA_ROOT = Path(os.environ.get("JARVIS_DATA_ROOT", Path.home() / "Jarvis")).expanduser()
DOMAINS = ("documents", "finance", "health", "notes", "email-export")

DB_DSN = (
    f"host={os.environ.get('JARVIS_DB_HOST', '127.0.0.1')} "
    f"port={os.environ.get('JARVIS_DB_PORT', '5433')} "
    f"dbname={os.environ.get('JARVIS_DB_NAME', 'jarvis')} "
    f"user={os.environ.get('JARVIS_DB_USER', 'jarvis')} "
    f"password={os.environ['JARVIS_DB_PASSWORD']}"
)

OLLAMA_URL = os.environ.get("JARVIS_OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL = os.environ.get("JARVIS_EMBED_MODEL", "bge-m3")
# Multilingual, so Tamil questions rank as well as English ones (bge-reranker-base was weak on Tamil).
RERANK_MODEL = os.environ.get("JARVIS_RERANK_MODEL", "BAAI/bge-reranker-v2-m3-int8")
MODELS_DIR = SYSTEM_DIR / "models"

# ~600 tokens per chunk; overlap keeps a sentence that straddles a boundary findable.
CHUNK_CHARS = int(os.environ.get("JARVIS_CHUNK_CHARS", "2400"))
CHUNK_OVERLAP = int(os.environ.get("JARVIS_CHUNK_OVERLAP", "300"))

SECRETS_DIR = SYSTEM_DIR / "secrets"


def _system_timezone() -> str:
    try:
        return str(Path("/etc/localtime").resolve()).split("zoneinfo/", 1)[1]
    except (OSError, IndexError):
        return "UTC"


TIMEZONE = os.environ.get("JARVIS_TIMEZONE", _system_timezone())
# A calendar change proposed by Jarvis must be approved by the user within this window.
PENDING_APPROVAL_MINUTES = 10

SUPPORTED_SUFFIXES ={".pdf", ".docx", ".md", ".markdown", ".txt", ".csv", ".json", ".html", ".htm"}
