from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from lloyds_digest.storage.mongo_repo import MongoRepo


PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class PromptSpec:
    name: str
    version: str
    filename: str

    @property
    def prompt_text(self) -> str:
        return (PROMPTS_DIR / self.filename).read_text(encoding="utf-8")


@dataclass
class OllamaClient:
    model: str
    host: str | None = None

    def _endpoint(self) -> str:
        base = self.host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        return f"{base.rstrip('/')}/api/generate"

    def generate(self, prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        timeout = float(os.environ.get("OLLAMA_TIMEOUT", "120"))
        with httpx.Client(timeout=timeout) as client:
            response = client.post(self._endpoint(), json=payload)
            response.raise_for_status()
            return response.json()


def build_cache_key(model: str, prompt_version: str, content: str) -> str:
    payload = json.dumps(
        {"model": model, "prompt_version": prompt_version, "content": content},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cached_call(
    mongo: MongoRepo | None,
    key: str,
    call_fn,
) -> dict[str, Any]:
    if mongo is not None:
        cached = mongo.get_ai_cache(key)
        if cached:
            return {"cached": True, "payload": cached}
    result = call_fn()
    if mongo is not None:
        mongo.upsert_ai_cache(key, result)
    return {"cached": False, "payload": result}
