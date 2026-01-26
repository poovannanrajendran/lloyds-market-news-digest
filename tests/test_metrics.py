from __future__ import annotations

from datetime import date, datetime, timezone

from lloyds_digest.models import RunMetrics
from lloyds_digest.reporting.metrics import compute_run_summary


def test_compute_run_summary() -> None:
    run = RunMetrics(
        run_id="run",
        run_date=date(2026, 1, 26),
        started_at=datetime.now(timezone.utc),
        total_candidates=10,
        extracted=5,
        fetched=8,
        errors=1,
    )
    summary = compute_run_summary(run)
    assert summary.coverage == 0.5
    assert summary.total_candidates == 10
