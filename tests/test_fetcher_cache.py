from __future__ import annotations

from lloyds_digest.fetchers.http import HttpFetcher, build_cache_key


def test_build_cache_key_strips_utm() -> None:
    key1 = build_cache_key("httpx", "https://example.com/a?utm_source=x&keep=1")
    key2 = build_cache_key("httpx", "https://example.com/a?keep=1")
    assert key1 == key2


def test_fetcher_uses_cache() -> None:
    class StubCache:
        def __init__(self) -> None:
            self.hits = 0

        def get(self, url: str):
            self.hits += 1
            return {
                "status_code": 200,
                "content": "cached",
                "final_url": url,
                "fetched_at": None,
            }

        def set(self, url: str, payload: dict, final_url: str) -> None:  # pragma: no cover
            raise AssertionError("set should not be called on cache hit")

    fetcher = HttpFetcher()
    cache = StubCache()
    result = fetcher.fetch("https://example.com", cache=cache)

    assert result.from_cache is True
    assert result.content == "cached"
    assert cache.hits == 1
