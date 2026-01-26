from __future__ import annotations

from typing import Iterable


def parse_topics_csv(value: str | None) -> list[str]:
    """Parse a comma-separated topics string into a de-duplicated list."""
    if not value:
        return []

    topics: list[str] = []
    seen: set[str] = set()
    for raw in value.split(","):
        topic = raw.strip()
        if not topic:
            continue
        if topic.lower() in seen:
            continue
        seen.add(topic.lower())
        topics.append(topic)
    return topics


def unique_ordered(values: Iterable[str]) -> list[str]:
    """Return de-duplicated values while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
