from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

import feedparser
import httpx

from lloyds_digest.discovery.csv_loader import CsvSourceRow
from lloyds_digest.models import Candidate
from lloyds_digest.storage.mongo_repo import MongoRepo
from lloyds_digest.storage.postgres_repo import PostgresRepo


@dataclass
class RSSDiscoverer:
    timeout: float = 20.0

    def discover(
        self,
        sources: Iterable[CsvSourceRow],
        postgres: PostgresRepo | None = None,
        mongo: MongoRepo | None = None,
        run_id: str | None = None,
    ) -> list[Candidate]:
        candidates: list[Candidate] = []
        seen: set[str] = set()
        for source in sources:
            if source.page_type != "rss":
                continue
            feed_content = self._fetch_feed(source.url)
            parsed = feedparser.parse(feed_content)
            snapshot_id = None
            if mongo is not None:
                snapshot_id = mongo.insert_discovery_snapshot(
                    {
                        "source_id": source.to_source().source_id,
                        "url": source.url,
                        "fetched_at": _utc_now(),
                        "entry_count": len(parsed.entries),
                        "feed": _safe_feed_summary(parsed),
                        "run_id": run_id,
                    }
                )

            parsed_candidates = parse_feed_entries(parsed, source, snapshot_id, run_id)
            for candidate in parsed_candidates:
                if candidate.candidate_id in seen:
                    continue
                seen.add(candidate.candidate_id)
                candidates.append(candidate)
                if postgres is not None:
                    postgres.insert_candidate(candidate)
        return candidates

    def _fetch_feed(self, url: str) -> bytes:
        with httpx.Client(timeout=self.timeout, headers={"User-Agent": "lloyds-digest/0.1"}) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.content


def parse_feed_entries(
    parsed: Any, source: CsvSourceRow, snapshot_id: str | None, run_id: str | None = None
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for entry in getattr(parsed, "entries", []):
        candidate = _candidate_from_entry(source, entry, snapshot_id, run_id)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _safe_feed_summary(parsed: Any) -> dict[str, Any]:
    feed = getattr(parsed, "feed", {})
    return {
        "title": getattr(feed, "title", None),
        "link": getattr(feed, "link", None),
        "updated": getattr(feed, "updated", None),
    }


def _candidate_from_entry(
    source: CsvSourceRow, entry: Any, snapshot_id: str | None, run_id: str | None
) -> Candidate | None:
    link = getattr(entry, "link", None)
    if not link:
        return None

    canonical = canonical_url(link)
    candidate_id = _candidate_id(canonical)
    title = getattr(entry, "title", None)
    published_at = _entry_datetime(entry)
    metadata = {
        "entry_id": getattr(entry, "id", None),
        "author": getattr(entry, "author", None),
        "summary": getattr(entry, "summary", None),
        "topics": source.topics,
        "source_type": source.source_type,
        "page_type": source.page_type,
        "snapshot_id": snapshot_id,
        "run_id": run_id,
        "canonical_url": canonical,
    }

    return Candidate(
        candidate_id=candidate_id,
        source_id=source.to_source().source_id,
        url=canonical,
        title=title,
        published_at=published_at,
        metadata=metadata,
    )


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    normalized = parts._replace(fragment="")
    return urlunsplit(normalized)


def _candidate_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _entry_datetime(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = getattr(entry, key, None)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)
    for key in ("published", "updated"):
        raw = getattr(entry, key, None)
        if raw:
            try:
                return datetime.fromisoformat(raw)
            except ValueError:
                continue
    return None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
