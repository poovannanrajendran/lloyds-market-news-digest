from __future__ import annotations

from pathlib import Path
from typing import Iterable

import os


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


def load_env_file(path: Path | str, override: bool = False) -> dict[str, str]:
    """Load a .env file into os.environ, returning the keys set."""
    env_path = Path(path)
    if not env_path.exists():
        return {}

    loaded: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if not key:
            continue
        if not override and key in os.environ:
            continue
        os.environ[key] = value
        loaded[key] = value
    return loaded
