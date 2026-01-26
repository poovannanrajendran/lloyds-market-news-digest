from __future__ import annotations

from lloyds_digest.utils import parse_topics_csv


def test_parse_topics_csv() -> None:
    raw = "  Lloyds, insurance, reinsurance, lloyds, , marine "
    assert parse_topics_csv(raw) == ["Lloyds", "insurance", "reinsurance", "marine"]


def test_parse_topics_csv_empty() -> None:
    assert parse_topics_csv("") == []
    assert parse_topics_csv(None) == []
