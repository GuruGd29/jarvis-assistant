"""Voice messages to text on this computer: whisper.cpp's server, started by the app and kept running so the
model stays loaded (about 1 GB; a 20-second message takes under 2 seconds on an M1's graphics chip).

The phone sends 16 kHz mono WAV made in the browser, so no audio converter is needed here."""
import asyncio
import logging
import os
import re
import shutil
import subprocess

import httpx

from .. import config

log = logging.getLogger("jarvis.voice")
URL = f"http://127.0.0.1:{config.WHISPER_PORT}"
MAX_BYTES = 5_000_000  # about 2.5 minutes of 16 kHz WAV
_starting = asyncio.Lock()
# Whisper's notes for silence and sounds ("[BLANK_AUDIO]", "(music)"), not words the user said.
_NOT_SPEECH = re.compile(r"\[[^\]]*\]|\([^)]*\)")


def available() -> bool:
    return bool(shutil.which("whisper-server")) and config.WHISPER_MODEL.is_file()


def clean(text: str) -> str:
    return " ".join(_NOT_SPEECH.sub(" ", text).split())


async def _ready(client: httpx.AsyncClient) -> bool:
    try:
        return (await client.get(f"{URL}/health", timeout=2)).status_code == 200
    except httpx.HTTPError:
        return False


async def start(wait: float = 0) -> bool:
    """Start the server unless it is already running (it outlives app restarts); with `wait`, wait until the model
    is loaded. True when it is ready."""
    if not available():
        return False
    async with _starting, httpx.AsyncClient() as client:
        if await _ready(client):
            return True
        threads = str(min(os.cpu_count() or 4, 8))
        with open(config.SYSTEM_DIR / "logs" / "whisper.log", "ab") as out:
            subprocess.Popen(
                [shutil.which("whisper-server"), "-m", str(config.WHISPER_MODEL), "-l", "auto", "-t", threads,
                 "--host", "127.0.0.1", "--port", str(config.WHISPER_PORT)],
                stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True)
        log.info("started whisper-server with %s", config.WHISPER_MODEL.name)
        for _ in range(int(wait * 2)):
            await asyncio.sleep(0.5)
            if await _ready(client):
                return True
    return False


async def transcribe(wav: bytes) -> str:
    if not await start(wait=60):
        raise RuntimeError("The voice model didn't start; see logs/whisper.log.")
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(f"{URL}/inference", data={"response_format": "json"},
                                     files={"file": ("voice.wav", wav, "audio/wav")})
    response.raise_for_status()
    return clean(response.json().get("text", ""))
