from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


WEIGHTS = {
    "core_lloyds_market_structure": 3.0,
    "digital_placement_platforms_modernisation": 2.5,
    "company_market_global_specialty_keywords": 2.0,
    "brokers_distribution": 2.0,
    "lloyds_governance_regulation_signals": 1.5,
    "data_tech_ops_signals": 1.0,
    "entities": 1.5,
}


@dataclass(frozen=True)
class KeywordRules:
    terms: list[tuple[str, float]]

    def score(self, text: str) -> tuple[float, list[str]]:
        haystack = text.lower()
        score = 0.0
        matches: list[str] = []
        for term, weight in self.terms:
            if _contains(haystack, term):
                score += weight
                matches.append(term)
        return score, matches


def load_keywords(path: Path | str) -> KeywordRules:
    keywords_path = Path(path)
    if not keywords_path.exists():
        return KeywordRules(terms=[])
    raw = keywords_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError("relevant_keywords.yaml must define a mapping at the top level")
    terms: list[tuple[str, float]] = []
    for key, value in data.items():
        weight = WEIGHTS.get(key, 1.0)
        terms.extend(_flatten_terms(value, weight))
    return KeywordRules(terms=terms)


def _flatten_terms(value: object, weight: float) -> list[tuple[str, float]]:
    if isinstance(value, list):
        return [(str(item).lower(), weight) for item in value if str(item).strip()]
    if isinstance(value, dict):
        terms: list[tuple[str, float]] = []
        for item in value.values():
            terms.extend(_flatten_terms(item, weight))
        return terms
    return []


def _contains(haystack: str, term: str) -> bool:
    if len(term) <= 3:
        return re.search(rf"\\b{re.escape(term)}\\b", haystack) is not None
    return term in haystack


def compact_text(title: str | None, body: str, max_chars: int = 4000) -> str:
    base = []
    if title:
        base.append(title)
    if body:
        base.append(body[:max_chars])
    return " ".join(base)
