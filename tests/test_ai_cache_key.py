from __future__ import annotations

from lloyds_digest.ai.base import build_cache_key, normalize_cache_content


def test_ai_cache_key_changes_with_version() -> None:
    key1 = build_cache_key("model", "v1", "content")
    key2 = build_cache_key("model", "v2", "content")
    assert key1 != key2


def test_ai_cache_key_ignores_whitespace_noise() -> None:
    key1 = build_cache_key("model", "v1", "a   b\nc")
    key2 = build_cache_key("model", "v1", "a b c")
    assert key1 == key2


def test_normalize_cache_content_collapses_whitespace() -> None:
    assert normalize_cache_content("  a\tb\nc  ") == "a b c"
