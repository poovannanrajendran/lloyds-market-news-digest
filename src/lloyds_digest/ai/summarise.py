from __future__ import annotations

import json
from typing import Any

from lloyds_digest.ai.base import (
    OpenAIClient,
    PromptSpec,
    build_cache_key,
    cached_call,
    estimate_tokens,
    extract_openai_usage,
)
from lloyds_digest.storage.mongo_repo import MongoRepo

PROMPT = PromptSpec(name="summarise", version="v1", filename="summarise_v1.txt")


def summarise(
    text: str,
    model: str,
    mongo: MongoRepo | None = None,
    host: str | None = None,
) -> dict[str, Any]:
    prompt = f"{PROMPT.prompt_text}\n\nCONTENT:\n{text}"
    key = build_cache_key(model, PROMPT.version, text)

    def _call() -> dict[str, Any]:
        client = OpenAIClient(model=model, base_url=host)
        response = client.generate(prompt)
        response_text = response.get("response", "")
        raw = response.get("raw", {}) if isinstance(response.get("raw"), dict) else {}
        prompt_tokens, completion_tokens, cached_prompt_tokens = extract_openai_usage(raw)
        return {
            "response": response_text,
            "model": model,
            "prompt_version": PROMPT.version,
            "tokens_prompt": prompt_tokens if prompt_tokens is not None else estimate_tokens(prompt),
            "tokens_completion": completion_tokens
            if completion_tokens is not None
            else estimate_tokens(response_text),
            "tokens_cached_prompt": cached_prompt_tokens,
        }

    result = cached_call(mongo, key, _call)
    raw = result["payload"].get("response", "")
    parsed = _safe_json(raw)
    payload = result["payload"]
    return {
        "cached": result["cached"],
        "raw": raw,
        "parsed": parsed,
        "tokens_prompt": payload.get("tokens_prompt"),
        "tokens_completion": payload.get("tokens_completion"),
    }


def _safe_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        return {}
