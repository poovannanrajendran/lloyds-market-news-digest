from __future__ import annotations

import json
from typing import Any

from lloyds_digest.ai.base import PromptSpec, OllamaClient, build_cache_key, cached_call
from lloyds_digest.storage.mongo_repo import MongoRepo

PROMPT = PromptSpec(name="classify", version="v1", filename="classify_v1.txt")


def classify(
    text: str,
    model: str,
    mongo: MongoRepo | None = None,
    host: str | None = None,
) -> dict[str, Any]:
    prompt = f"{PROMPT.prompt_text}\n\nCONTENT:\n{text}"
    key = build_cache_key(model, PROMPT.version, text)

    def _call() -> dict[str, Any]:
        client = OllamaClient(model=model, host=host)
        response = client.generate(prompt)
        return {
            "response": response.get("response", ""),
            "model": model,
            "prompt_version": PROMPT.version,
        }

    result = cached_call(mongo, key, _call)
    raw = result["payload"].get("response", "")
    parsed = _safe_json(raw)
    return {"cached": result["cached"], "raw": raw, "parsed": parsed}


def _safe_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        return {}
