from __future__ import annotations

from pathlib import Path

import pytest

from lloyds_digest.discovery.csv_loader import load_sources_csv, upsert_sources


def test_load_sources_csv_valid(tmp_path: Path) -> None:
    csv_path = tmp_path / "sources.csv"
    csv_path.write_text(
        "\n".join(
            [
                "source_type,domain,url,topics,page_type",
                "primary,example.com,https://example.com/feed,Catastrophe;ILS,rss",
            ]
        ),
        encoding="utf-8",
    )

    rows = load_sources_csv(csv_path)

    assert len(rows) == 1
    row = rows[0]
    assert row.source_type == "primary"
    assert row.page_type == "rss"
    assert row.topics == ["Catastrophe", "ILS"]


def test_load_sources_csv_invalid_enum(tmp_path: Path) -> None:
    csv_path = tmp_path / "sources.csv"
    csv_path.write_text(
        "\n".join(
            [
                "source_type,domain,url,topics,page_type",
                "bad,example.com,https://example.com/feed,Catastrophe,rss",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid source_type"):
        load_sources_csv(csv_path)


def test_upsert_sources_calls_repo() -> None:
    class StubRepo:
        def __init__(self) -> None:
            self.items: list[str] = []

        def upsert_source(self, source) -> None:
            self.items.append(source.source_id)

    # Use real CsvSourceRow for clarity.
    from lloyds_digest.discovery.csv_loader import CsvSourceRow

    rows = [
        CsvSourceRow(
            source_type="primary",
            domain="example.com",
            url="https://example.com/feed",
            topics=["Catastrophe"],
            page_type="rss",
        )
    ]
    repo = StubRepo()
    count = upsert_sources(repo, rows)

    assert count == 1
    assert repo.items == ["primary:example.com"]
