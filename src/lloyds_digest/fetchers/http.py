from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from lloyds_digest.discovery.url_utils import canonicalise_url
from lloyds_digest.models import FetchResult
from lloyds_digest.storage.mongo_repo import MongoRepo


class CacheBackend(Protocol):
    def get(self, url: str) -> dict[str, Any] | None:
        ...

    def set(
        self,
        url: str,
        payload: dict[str, Any],
        final_url: str,
    ) -> None:
        ...


@dataclass
class FetchCache:
    mongo: MongoRepo
    fetcher_name: str = "httpx"

    def get(self, url: str) -> dict[str, Any] | None:
        key = build_cache_key(self.fetcher_name, url)
        return self.mongo.get_fetch_cache(key)

    def set(self, url: str, payload: dict[str, Any], final_url: str) -> None:
        key = build_cache_key(self.fetcher_name, final_url)
        record = dict(payload)
        record.update(
            {
                "key": key,
                "fetcher": self.fetcher_name,
                "url": url,
                "final_url": final_url,
                "updated_at": _utc_now(),
            }
        )
        self.mongo.upsert_fetch_cache(key, record)


@dataclass
class HttpFetcher:
    timeout: float = 20.0
    max_attempts: int = 3
    fetcher_name: str = "httpx"

    def fetch(self, url: str, cache: CacheBackend | None = None) -> FetchResult:
        cached = cache.get(url) if cache is not None else None
        if cached:
            return FetchResult(
                candidate_id=cached.get("candidate_id", ""),
                url=cached.get("final_url", url),
                status_code=cached.get("status_code"),
                fetched_at=cached.get("fetched_at", _utc_now()),
                content=cached.get("content"),
                from_cache=True,
            )

        started = _utc_now()
        try:
            response = self._fetch(url)
            elapsed_ms = int(response.elapsed.total_seconds() * 1000)
            result = FetchResult(
                candidate_id="",
                url=str(response.url),
                status_code=response.status_code,
                fetched_at=started,
                content=response.text,
                elapsed_ms=elapsed_ms,
                from_cache=False,
            )
            if cache is not None:
                cache.set(
                    url,
                    {
                        "status_code": response.status_code,
                        "content": response.text,
                        "fetched_at": started,
                    },
                    final_url=str(response.url),
                )
            return result
        except Exception as exc:  # pragma: no cover - defensive
            return FetchResult(
                candidate_id="",
                url=url,
                status_code=None,
                fetched_at=started,
                content=None,
                error=str(exc),
            )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _fetch(self, url: str) -> httpx.Response:
        with httpx.Client(
            timeout=self.timeout,
            headers={"User-Agent": "lloyds-digest/0.1"},
            follow_redirects=True,
        ) as client:
            response = client.get(url)
            if response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"Server error: {response.status_code}",
                    request=response.request,
                    response=response,
                )
            return response


def build_cache_key(fetcher_name: str, url: str) -> str:
    canonical = canonicalise_url(url)
    payload = f"{fetcher_name}|{canonical}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
