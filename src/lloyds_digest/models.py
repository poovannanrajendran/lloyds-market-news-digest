from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Source:
    source_id: str
    name: str
    kind: str
    url: str | None = None
    enabled: bool = True
    tags: list[str] = field(default_factory=list)


@dataclass
class Candidate:
    candidate_id: str
    source_id: str
    url: str
    title: str | None = None
    published_at: datetime | None = None
    discovered_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    candidate_id: str
    url: str
    status_code: int | None = None
    fetched_at: datetime = field(default_factory=_utc_now)
    content: str | bytes | None = None
    error: str | None = None
    elapsed_ms: int | None = None
    from_cache: bool = False


@dataclass
class ExtractionResult:
    candidate_id: str
    method: str
    extracted_at: datetime = field(default_factory=_utc_now)
    title: str | None = None
    text: str | None = None
    html: str | None = None
    success: bool = True
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ArticleRecord:
    article_id: str
    source_id: str
    url: str
    title: str | None = None
    published_at: datetime | None = None
    body_text: str | None = None
    created_at: datetime = field(default_factory=_utc_now)
    extraction_method: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunMetrics:
    run_id: str
    run_date: date
    started_at: datetime
    ended_at: datetime | None = None
    total_sources: int = 0
    total_candidates: int = 0
    fetched: int = 0
    extracted: int = 0
    errors: int = 0
    notes: dict[str, Any] = field(default_factory=dict)
