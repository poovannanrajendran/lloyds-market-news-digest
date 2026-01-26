from __future__ import annotations

from lloyds_digest.ai.base import build_cache_key


def test_ai_cache_key_changes_with_version() -> None:
    key1 = build_cache_key("model", "v1", "content")
    key2 = build_cache_key("model", "v2", "content")
    assert key1 != key2
