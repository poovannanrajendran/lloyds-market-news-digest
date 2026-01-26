from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from lloyds_digest.models import Source
from lloyds_digest.storage.postgres_repo import PostgresRepo
from lloyds_digest.utils import unique_ordered

SOURCE_TYPES = {"primary", "secondary", "additional", "regulatory"}
PAGE_TYPES = {"rss", "listing"}


@dataclass(frozen=True)
class CsvSourceRow:
    source_type: str
    domain: str
    url: str
    topics: list[str]
    page_type: str

    def to_source(self) -> Source:
        source_id = f"{self.source_type}:{self.domain}"
        tags = unique_ordered(
            [
                *self.topics,
                f"source_type:{self.source_type}",
                f"page_type:{self.page_type}",
                f"domain:{self.domain}",
            ]
        )
        return Source(
            source_id=source_id,
            name=self.domain,
            kind=self.source_type,
            url=self.url,
            tags=tags,
        )


def parse_topics_field(value: str) -> list[str]:
    if not value:
        return []
    raw = [topic.strip() for topic in value.replace(",", ";").split(";")]
    return unique_ordered([topic for topic in raw if topic])


def load_sources_csv(path: Path | str) -> list[CsvSourceRow]:
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    rows: list[CsvSourceRow] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV must include a header row")
        required = {"source_type", "domain", "url", "topics", "page_type"}
        missing = required - {name.strip() for name in reader.fieldnames}
        if missing:
            raise ValueError(f"CSV missing required columns: {sorted(missing)}")

        for idx, row in enumerate(reader, start=2):
            source_type = (row.get("source_type") or "").strip().lower()
            domain = (row.get("domain") or "").strip()
            url = (row.get("url") or "").strip()
            topics_value = (row.get("topics") or "").strip()
            page_type = (row.get("page_type") or "").strip().lower()

            if not source_type or not domain or not url or not page_type:
                raise ValueError(f"Row {idx}: missing required fields")
            if source_type not in SOURCE_TYPES:
                raise ValueError(f"Row {idx}: invalid source_type '{source_type}'")
            if page_type not in PAGE_TYPES:
                raise ValueError(f"Row {idx}: invalid page_type '{page_type}'")

            rows.append(
                CsvSourceRow(
                    source_type=source_type,
                    domain=domain,
                    url=url,
                    topics=parse_topics_field(topics_value),
                    page_type=page_type,
                )
            )

    return rows


def iter_sources(rows: Iterable[CsvSourceRow]) -> Iterable[Source]:
    for row in rows:
        yield row.to_source()


def upsert_sources(postgres: PostgresRepo, rows: Iterable[CsvSourceRow]) -> int:
    count = 0
    for source in iter_sources(rows):
        postgres.upsert_source(source)
        count += 1
    return count
