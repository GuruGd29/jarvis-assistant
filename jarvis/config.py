"""Settings, read from environment variables with ~/jarvis-system/.env as fallback."""
import copy
import os
import re
from pathlib import Path

from babel import Locale
from babel.dates import get_date_format
from babel.numbers import format_currency, get_currency_symbol, get_territory_currencies

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

SECRETS_DIR = Path(os.environ.get("JARVIS_SECRETS_DIR", SYSTEM_DIR / "secrets")).expanduser()


def _system_timezone() -> str:
    try:
        return str(Path("/etc/localtime").resolve()).split("zoneinfo/", 1)[1]
    except (OSError, IndexError):
        return "UTC"


TIMEZONE = os.environ.get("JARVIS_TIMEZONE", _system_timezone())


# ---- Where the user lives: name, number and date style, currency, languages (all set in .env) ----
def _system_locale() -> str:
    lang = (os.environ.get("LC_ALL") or os.environ.get("LC_MONETARY") or os.environ.get("LANG") or "").split(".")[0]
    return lang if re.fullmatch(r"[a-z]{2,3}_[A-Z]{2}", lang) else "en_US"


OWNER_NAME = os.environ.get("JARVIS_OWNER_NAME", "").strip()  # used in greetings; empty = no name
LOCALE = (os.environ.get("JARVIS_LOCALE") or _system_locale()).replace("-", "_")  # e.g. en_IN, en_US, de_DE
_babel_locale = Locale.parse(LOCALE)
CURRENCY = (os.environ.get("JARVIS_CURRENCY") or (get_territory_currencies(_babel_locale.territory) or ["USD"])[0]).upper()
LANGUAGES = os.environ.get("JARVIS_LANGUAGES", _babel_locale.get_language_name("en"))  # e.g. "Tamil and English"
# Web push needs a contact address for the push services (Apple, Google, Mozilla); never shown to anyone else.
CONTACT_EMAIL = os.environ.get("JARVIS_CONTACT_EMAIL", "").strip()
# The local chat model: answers chats and reads bank emails the built-in readers don't know.
CHAT_MODEL = os.environ.get("JARVIS_CHAT_MODEL", "qwen3-4b-instruct-64k")
# Bank emails from banks without a built-in reader: "nightly" reads them once a night (an AI read pushes the chat
# out of the model's memory, which costs minutes on a CPU server), "always" on every money sync, "off" never.
MONEY_AI = os.environ.get("JARVIS_MONEY_AI", "nightly").lower()
# Day/month order of numeric dates like 05/12/2026, from the locale: "dmy", "mdy" or "ymd".
_short = get_date_format("short", locale=_babel_locale).pattern.lower()
DATE_ORDER = "".join(sorted("dmy", key=lambda c: _short.find(c)))
CURRENCY_SYMBOL = get_currency_symbol(CURRENCY, locale=_babel_locale)


def money(amount: float, decimals: bool = True) -> str:
    """An amount in the user's currency and style: ₹1,50,000.50 (en_IN), $150,000.50 (en_US), 150.000,50 € (de_DE)."""
    if decimals:
        return format_currency(amount, CURRENCY, locale=_babel_locale)
    pattern = copy.copy(_babel_locale.currency_formats["standard"])  # the cached one is shared
    pattern.frac_prec = (0, 0)
    return format_currency(round(amount), CURRENCY, locale=_babel_locale, format=pattern, currency_digits=False)
# A calendar change proposed by Jarvis must be approved by the user within this window.
PENDING_APPROVAL_MINUTES = 10

SUPPORTED_SUFFIXES ={".pdf", ".docx", ".md", ".markdown", ".txt", ".csv", ".json", ".html", ".htm"}
