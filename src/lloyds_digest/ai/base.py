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


@dataclass
class OpenAIClient:
    model: str
    api_key: str | None = None
    base_url: str | None = None
    service_tier: str | None = None

    def _endpoint(self) -> str:
        base = self.base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com")
        return f"{base.rstrip('/')}/v1/chat/completions"

    def _resolve_api_key(self) -> str:
        key = self.api_key or os.environ.get("OPENAI_API_KEY", "")
        if not key:
            raise ValueError("OPENAI_API_KEY is required when LLM mode is enabled.")
        return key

    def generate(self, prompt: str) -> dict[str, Any]:
        primary_tier = self.service_tier or os.environ.get("OPENAI_SERVICE_TIER", "flex")
        result = self._generate_with_tier(prompt, primary_tier)
        if result is not None:
            return result
        fallback_tier = os.environ.get("OPENAI_FALLBACK_SERVICE_TIER", "standard")
        return self._generate_with_tier(prompt, fallback_tier)

    def _generate_with_tier(self, prompt: str, service_tier: str | None) -> dict[str, Any] | None:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Return JSON only, no markdown."},
                {"role": "user", "content": prompt},
            ],
        }
        # Keep responses stable by default for non-reasoning models.
        if not self.model.startswith("gpt-5"):
            payload["temperature"] = 0.2

        tier = (service_tier or os.environ.get("OPENAI_SERVICE_TIER", "flex")).strip()
        payload["service_tier"] = tier or "flex"

        max_completion_tokens = os.environ.get("OPENAI_MAX_COMPLETION_TOKENS", "").strip()
        if max_completion_tokens:
            payload["max_completion_tokens"] = int(max_completion_tokens)

        timeout = float(os.environ.get("OPENAI_TIMEOUT", "120"))
        headers = {
            "Authorization": f"Bearer {self._resolve_api_key()}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=timeout) as client:
            response = client.post(self._endpoint(), json=payload, headers=headers)
            if response.status_code >= 400:
                if self._should_fallback(response, payload["service_tier"]):
                    return None  # caller will retry using the fallback tier
                response.raise_for_status()
            data = response.json()
        return {
            "response": _extract_openai_text(data),
            "raw": data,
            "service_tier": payload["service_tier"],
        }

    def _should_fallback(self, response: httpx.Response, service_tier: str) -> bool:
        if response.status_code != 429:
            return False
        body_text = response.text.lower()
        if "resource_unavailable" not in body_text and "insufficient resources" not in body_text:
            return False
        if service_tier.lower() != "flex":
            return False
        fallback_tier = os.environ.get("OPENAI_FALLBACK_SERVICE_TIER", "standard").strip() or "standard"
        return fallback_tier.lower() != "flex"


def build_cache_key(model: str, prompt_version: str, content: str) -> str:
    payload = json.dumps(
        {
            "model": model,
            "prompt_version": prompt_version,
            "content": normalize_cache_content(content),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_cache_content(content: str) -> str:
    if not content:
        return ""
    return " ".join(content.split()).strip()


def post_openai_chat_completion(
    prompt: str,
    *,
    model: str,
    api_key: str,
    service_tier: str,
    fallback_tier: str,
    timeout: float,
    system_prompt: str,
    temperature: float | None = None,
    max_attempts: int = 1,
) -> dict[str, Any]:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "service_tier": service_tier,
    }
    if temperature is not None:
        body["temperature"] = temperature
    for attempt in range(1, max_attempts + 1):
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, headers=headers, json=body)
            actual_tier = body["service_tier"]
            if (
                response.status_code == 429
                and actual_tier.lower() == "flex"
                and fallback_tier.lower() != "flex"
                and _is_flex_capacity_429(response)
            ):
                print(f"OpenAI flex exhausted; retrying on tier={fallback_tier}", flush=True)
                body["service_tier"] = fallback_tier
                actual_tier = fallback_tier
                response = client.post(url, headers=headers, json=body)
            if response.status_code >= 400:
                if attempt == max_attempts:
                    raise httpx.HTTPStatusError(
                        f"OpenAI error {response.status_code}: {response.text}",
                        request=response.request,
                        response=response,
                    )
                continue
            data = response.json()
            return {
                "data": data,
                "service_tier": actual_tier,
            }
    raise RuntimeError("OpenAI request failed after retries.")


def _is_flex_capacity_429(response: httpx.Response) -> bool:
    body_text = response.text.lower()
    return "resource_unavailable" in body_text or "insufficient resources" in body_text


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


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def extract_openai_usage(raw: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
    prompt_tokens = _as_int(usage.get("prompt_tokens"))
    completion_tokens = _as_int(usage.get("completion_tokens"))
    details = usage.get("prompt_tokens_details", {}) if isinstance(usage, dict) else {}
    cached_prompt_tokens = _as_int(details.get("cached_tokens")) if isinstance(details, dict) else None
    return prompt_tokens, completion_tokens, cached_prompt_tokens


def _extract_openai_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] or {}
    message = first.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts)
    return ""


def _as_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None
