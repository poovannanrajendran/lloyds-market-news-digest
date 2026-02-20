"""AI processing modules."""

from __future__ import annotations

__all__ = [
    "PromptSpec",
    "OpenAIClient",
    "OllamaClient",
    "build_cache_key",
    "relevance",
    "classify",
    "summarise",
]

from lloyds_digest.ai.base import OpenAIClient, OllamaClient, PromptSpec, build_cache_key
from lloyds_digest.ai.classify import classify
from lloyds_digest.ai.relevance import relevance
from lloyds_digest.ai.summarise import summarise
