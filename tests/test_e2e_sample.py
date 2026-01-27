from __future__ import annotations

import csv
import random
from pathlib import Path
from datetime import date

import pytest

from lloyds_digest.config import load_config
from lloyds_digest.pipeline import run_pipeline


pytestmark = pytest.mark.network


def _require_deps() -> None:
    pytest.importorskip("httpx")
    pytest.importorskip("feedparser")
    pytest.importorskip("bs4")


def _pick_random_source(seed: int = 314) -> dict[str, str]:
    rows = []
    with Path("sources.csv").open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(row)
    if not rows:
        pytest.skip("sources.csv has no rows")
    random.Random(seed).shuffle(rows)
    return rows[0]


def _write_single_source(tmp_path: Path, row: dict[str, str]) -> Path:
    path = tmp_path / "sources_single.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)
    return path


def test_e2e_one_relevant_article(tmp_path, monkeypatch):
    pytest.skip("Live E2E test disabled by default; enable when needed.")
    _require_deps()

    row = _pick_random_source()
    sources_path = _write_single_source(tmp_path, row)

    # Use live network, LLM, and real DB connections for full end-to-end coverage.
    monkeypatch.setenv("LLOYDS_DIGEST_LLM_MODE", "on")
    monkeypatch.setenv("LLOYDS_DIGEST_KEYWORDS_FILE", "relevant_keywords.yaml")
    monkeypatch.setenv("LLOYDS_DIGEST_KEYWORDS_MIN_SCORE", "1.0")
    monkeypatch.setenv("LLOYDS_DIGEST__FILTERS__MAX_AGE_DAYS", "365")

    config = load_config(Path("config.yaml"))
    result = run_pipeline(
        run_date=date.today(),
        config=config,
        sources_path=sources_path,
        max_candidates=30,
        max_sources=1,
        skip_seen=False,
        log=lambda _msg: None,
        log_detail=lambda _msg: None,
    )

    assert result.digest_items, "Expected at least one relevant article from a single source."
