"""Embeddings through Ollama (bge-m3, 1024 dimensions)."""
import httpx

from . import config


def embed(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    with httpx.Client(timeout=300) as client:
        for start in range(0, len(texts), 16):
            payload = {"model": config.EMBED_MODEL, "input": texts[start:start + 16], "keep_alive": "30m"}
            response = client.post(f"{config.OLLAMA_URL}/api/embed", json=payload)
            if response.status_code == 500:
                # A cold model load can time out under memory pressure; the second attempt usually loads fast.
                response = client.post(f"{config.OLLAMA_URL}/api/embed", json=payload)
            response.raise_for_status()
            vectors.extend(response.json()["embeddings"])
    return vectors
