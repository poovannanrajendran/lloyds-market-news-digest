"""AI processing modules (local-first)."""

from __future__ import annotations

__all__ = [
    "PromptSpec",
    "OllamaClient",
    "build_cache_key",
    "relevance",
    "classify",
    "summarise",
]

from lloyds_digest.ai.base import OllamaClient, PromptSpec, build_cache_key
from lloyds_digest.ai.classify import classify
from lloyds_digest.ai.relevance import relevance
from lloyds_digest.ai.summarise import summarise
