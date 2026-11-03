"""Text recognition for photos and scanned PDF pages, with Tesseract (free and open source; docs/files.md).

Without Tesseract a photo isn't readable and a scanned page stays empty, as before. What it reads is kept in
state/ocr/ by the file's content, so indexing again or opening the file in Your files doesn't read it twice.
"""
import hashlib
import json
import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from functools import cache
from pathlib import Path

from . import config

CACHE_DIR = config.SYSTEM_DIR / "state" / "ocr"
MAX_PAGES = 30   # a longer scan is read up to here
MAX_SIDE = 4000  # a bigger photo is scaled down first: it reads no better, only slower
PAGE_DPI = 300   # what Tesseract reads best
TIMEOUT = 120

# The user's languages (JARVIS_LANGUAGES, in words) as Tesseract's names; English is always read.
_TESSERACT_NAMES = {"tamil": "tam", "hindi": "hin", "telugu": "tel", "kannada": "kan", "malayalam": "mal",
                    "marathi": "mar", "bengali": "ben", "gujarati": "guj", "punjabi": "pan", "urdu": "urd",
                    "french": "fra", "german": "deu", "spanish": "spa", "portuguese": "por", "italian": "ita",
                    "dutch": "nld", "arabic": "ara", "chinese": "chi_sim", "japanese": "jpn", "korean": "kor"}


def available() -> bool:
    return bool(config.TESSERACT)


def wanted() -> list[str]:
    """Tesseract's names for the languages to read: JARVIS_OCR_LANGS ("eng+tam"), else English and the user's."""
    chosen = [code.strip() for code in os.environ.get("JARVIS_OCR_LANGS", "").replace(",", "+").split("+")
              if code.strip()]
    if not chosen:
        words = config.LANGUAGES.lower()
        chosen = ["eng"] + [code for name, code in _TESSERACT_NAMES.items() if name in words]
    return chosen


@cache
def languages() -> str:
    """The wanted languages that Tesseract has installed: 'eng+tam'."""
    listed = subprocess.run([config.TESSERACT, "--list-langs"], capture_output=True, text=True, timeout=30).stdout
    installed = set(listed.split()[1:]) if listed else set()
    return "+".join(code for code in wanted() if code in installed) or "eng"


def read_image(path: Path) -> str:
    """The text in a photo or screenshot ("" when there is none)."""
    return _cached(path.read_bytes(), "photo", lambda: _recognise_photo(path))


def read_pages(path: Path, numbers: list[int]) -> dict[int, str]:
    """The text on these pages of a PDF (1-based), read as pictures: for scanned pages with no text in them."""
    numbers = sorted(numbers)[:MAX_PAGES]
    found = _cached(path.read_bytes(), f"pages {numbers}", lambda: json.dumps(_recognise_pages(path, numbers)))
    return {int(n): text for n, text in json.loads(found).items()}


def _cached(data: bytes, what: str, read) -> str:
    key = hashlib.sha256(data + f"\n{what}\n{languages()}".encode()).hexdigest()
    saved = CACHE_DIR / f"{key}.txt"
    if saved.is_file():
        saved.touch()
        return saved.read_text()
    text = read()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    saved.write_text(text)
    return text


def _recognise_photo(path: Path) -> str:
    from PIL import Image, ImageOps

    with tempfile.TemporaryDirectory() as tmp:
        source = path
        if path.suffix.lower() == ".heic":
            source = Path(tmp, "photo.png")
            convert_heic(path, source)
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image).convert("L")  # phone photos are often stored sideways
            image.thumbnail((MAX_SIDE, MAX_SIDE))
            image.save(Path(tmp, "page.png"))
        return _tesseract(Path(tmp, "page.png"))


def convert_heic(path: Path, out: Path) -> None:
    """An iPhone photo (HEIC) as a PNG or JPEG, by the name of `out`: with sips on a Mac, heif-convert on Linux."""
    if config.HEIC_CONVERTER.endswith("sips"):
        kind = "jpeg" if out.suffix == ".jpg" else "png"
        command = [config.HEIC_CONVERTER, "-s", "format", kind, str(path), "--out", str(out)]
    else:
        command = [config.HEIC_CONVERTER, str(path), str(out)]
    subprocess.run(command, capture_output=True, check=True, timeout=TIMEOUT)


def _recognise_pages(path: Path, numbers: list[int]) -> dict[int, str]:
    import pypdfium2

    pdf = pypdfium2.PdfDocument(str(path))
    with tempfile.TemporaryDirectory() as tmp:
        pictures = {}
        for number in numbers:
            if number <= len(pdf):
                pictures[number] = Path(tmp, f"{number}.png")
                pdf[number - 1].render(scale=PAGE_DPI / 72, grayscale=True).to_pil().save(pictures[number])
        pdf.close()
        # Pages are read side by side; each Tesseract keeps to one core so they don't fight over them.
        with ThreadPoolExecutor(max(1, (os.cpu_count() or 2) // 2)) as pool:
            texts = pool.map(_tesseract, pictures.values())
        return dict(zip(pictures, texts))


def _tesseract(picture: Path) -> str:
    result = subprocess.run([config.TESSERACT, str(picture), "stdout", "-l", languages()], capture_output=True,
                            text=True, timeout=TIMEOUT, env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[-300:] or "text recognition failed")
    return clean(result.stdout)


# Tesseract puts an invisible joiner-breaker (U+200C) after a virama (Tamil's pulli ், Hindi's halant ्, ...), so
# "ராஜேஷ் குமார்" wouldn't match what it read. Real text almost never has one there.
_AFTER_VIRAMA = re.compile("(?<=[\u094d\u09cd\u0a4d\u0acd\u0b4d\u0bcd\u0c4d\u0ccd\u0d4d])\u200c")


def clean(text: str) -> str:
    return _AFTER_VIRAMA.sub("", text.replace("\f", "")).strip()
