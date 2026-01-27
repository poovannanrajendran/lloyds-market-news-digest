from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

import yaml


@dataclass(frozen=True)
class BoilerplateRules:
    rules: dict[str, list[str]]
    ignore_paths: list[str]

    def for_url(self, url: str) -> list[str]:
        if _is_ignored(url, self.ignore_paths):
            return []
        key = template_key(url)
        return self.rules.get(key, [])


def template_key(url: str) -> str:
    parsed = urlsplit(url)
    domain = parsed.netloc.lower()
    path = parsed.path.strip("/")
    if not path:
        group = "root"
    else:
        parts = path.split("/")
        group = "/".join(parts[:2]).lower()
    return f"{domain}|{group}"


def load_rules(path: Path | str) -> BoilerplateRules:
    rules_path = Path(path)
    if not rules_path.exists():
        return BoilerplateRules(rules={}, ignore_paths=[])
    raw = rules_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError("boilerplate.yaml must define a mapping at the top level")
    normalized: dict[str, list[str]] = {}
    ignore_paths = []
    for key, value in data.items():
        if not isinstance(key, str):
            continue
        if key == "__ignore_paths__" and isinstance(value, list):
            ignore_paths = [str(item) for item in value if str(item).strip()]
            continue
        if isinstance(value, list):
            normalized[key] = [str(item) for item in value if str(item).strip()]
    return BoilerplateRules(rules=normalized, ignore_paths=ignore_paths)


def strip_boilerplate(text: str, blocks: Iterable[str]) -> str:
    cleaned = text
    for block in blocks:
        cleaned = cleaned.replace(block, "")
    return _collapse_whitespace(cleaned)


def _collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def _is_ignored(url: str, prefixes: list[str]) -> bool:
    if not prefixes:
        return False
    path = urlsplit(url).path.lower()
    for prefix in prefixes:
        if path.startswith(prefix.lower()):
            return True
    return False
