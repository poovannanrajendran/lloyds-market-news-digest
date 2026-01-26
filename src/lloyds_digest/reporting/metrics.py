from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from lloyds_digest.models import Candidate, FetchResult, RunMetrics


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    run_date: str
    coverage: float
    total_candidates: int
    fetched: int
    extracted: int
    errors: int
    started_at: datetime
    ended_at: datetime | None


def compute_run_summary(run: RunMetrics) -> RunSummary:
    coverage = 0.0
    if run.total_candidates:
        coverage = run.extracted / run.total_candidates
    return RunSummary(
        run_id=run.run_id,
        run_date=str(run.run_date),
        coverage=coverage,
        total_candidates=run.total_candidates,
        fetched=run.fetched,
        extracted=run.extracted,
        errors=run.errors,
        started_at=run.started_at,
        ended_at=run.ended_at,
    )


def summarize_failures(fetch_results: Iterable[FetchResult]) -> dict[str, int]:
    failures: dict[str, int] = {}
    for result in fetch_results:
        if result.error:
            failures[result.error] = failures.get(result.error, 0) + 1
    return failures
