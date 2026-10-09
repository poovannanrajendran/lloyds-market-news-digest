from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

from lloyds_digest.reporting import model_shadow_audit as audit

_SPEC = importlib.util.spec_from_file_location(
    "run_model_shadow_audit", Path(__file__).parents[1] / "scripts" / "run_model_shadow_audit.py"
)
assert _SPEC and _SPEC.loader
runner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(runner)
_WORKER_SPEC = importlib.util.spec_from_file_location(
    "model_shadow_worker", Path(__file__).parents[1] / "scripts" / "model_shadow_worker.py"
)
assert _WORKER_SPEC and _WORKER_SPEC.loader
worker = importlib.util.module_from_spec(_WORKER_SPEC)
_WORKER_SPEC.loader.exec_module(worker)


def test_shadow_window_is_exactly_three_dates() -> None:
    assert not audit.audit_enabled(date(2026, 10, 9))
    assert all(audit.audit_enabled(date(2026, 10, day)) for day in (10, 11, 12))
    assert not audit.audit_enabled(date(2026, 10, 13))


def test_capture_records_exact_prompt_and_nano_io_only_inside_window(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(audit, "AUDIT_ROOT", tmp_path)
    kwargs = dict(
        run_id="run-1",
        candidate_id="article-1",
        title="Market story",
        url="https://example.test/story",
        model="gpt-5-nano",
        prompt_version="v1",
        prompt="exact input prompt",
        nano_result={"raw": '{"relevant":true}', "parsed": {"relevant": True}, "latency_ms": 123},
        production_relevant=True,
    )
    assert audit.capture_nano_relevance(run_date=date(2026, 10, 9), **kwargs)
    assert not list(tmp_path.rglob("*.jsonl"))

    assert audit.capture_nano_relevance(run_date=date(2026, 10, 10), **kwargs)
    path = audit.input_path(date(2026, 10, 10), "run-1")
    row = json.loads(path.read_text().strip())
    assert row["nano"]["prompt"] == "exact input prompt"
    assert row["nano"]["raw_output"] == '{"relevant":true}'
    assert row["nano"]["production_relevant"] is True


def test_luna_shadow_runs_concurrently_and_persists_separate_output(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(audit, "AUDIT_ROOT", tmp_path)
    monkeypatch.setattr(
        worker,
        "evaluate",
        lambda prompt: {
            "model": "gpt-6-luna",
            "raw_output": prompt,
            "parsed_output": {"relevant": True},
        },
    )
    run_date = date(2026, 10, 11)
    session = audit.ShadowAuditSession(run_date, "run-async")
    assert session.submit_luna("article-1", "Title", "https://example.test/a", "same prompt")
    assert audit.capture_nano_relevance(
        run_date=run_date,
        run_id="run-async",
        candidate_id="article-1",
        title="Title",
        url="https://example.test/a",
        model="gpt-5-nano",
        prompt_version="v1",
        prompt="same prompt",
        nano_result={"raw": '{"relevant":true}', "parsed": {"relevant": True}},
        production_relevant=True,
    )
    done_file = tmp_path / "done"
    done_file.touch()
    assert worker.run_worker(run_date, "run-async", done_file) == 0
    luna_row = json.loads(audit.result_path(run_date, "run-async").read_text().strip())
    nano_row = json.loads(audit.input_path(run_date, "run-async").read_text().strip())
    assert nano_row["nano"]["prompt"] == luna_row["luna"]["raw_output"] == "same prompt"


def test_run_audit_writes_separate_comparison_report(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(audit, "AUDIT_ROOT", tmp_path)
    run_date = date(2026, 10, 10)
    run_id = "run-2"
    input_file = audit.input_path(run_date, run_id)
    input_file.parent.mkdir(parents=True)
    records = [
        {
            "candidate_id": "1",
            "title": "Shared story",
            "url": "https://example.test/shared",
            "nano": {
                "prompt": "prompt 1",
                "parsed_output": {"relevant": True, "reason": "Nano yes"},
                "production_relevant": True,
                "latency_ms": 100,
                "tokens_prompt": 100,
                "tokens_completion": 10,
                "service_tier": "flex",
            },
        },
        {
            "candidate_id": "2",
            "title": "Disagreement story",
            "url": "https://example.test/different",
            "nano": {
                "prompt": "prompt 2",
                "parsed_output": {"relevant": False, "reason": "Nano no"},
                "production_relevant": False,
                "latency_ms": 200,
                "tokens_prompt": 100,
                "tokens_completion": 10,
                "service_tier": "flex",
            },
        },
    ]
    input_file.write_text("".join(json.dumps(row) + "\n" for row in records))

    monkeypatch.setattr(runner, "AUDIT_ROOT", tmp_path)
    result_file = audit.result_path(run_date, run_id)
    result_file.write_text(
        "".join(
            json.dumps(
                {
                    "candidate_id": row["candidate_id"],
                    "title": row["title"],
                    "url": row["url"],
                    "luna": {
                        "parsed_output": {
                            "relevant": row["candidate_id"] == "2",
                            "reason": "Luna decision",
                        },
                        "raw_output": "{}",
                        "error": None,
                        "tokens_prompt": 100,
                        "tokens_completion": 8,
                        "service_tier": "flex",
                        "latency_ms": 150,
                    },
                }
            )
            + "\n"
            for row in records
        )
    )
    report = runner.run_audit(run_date, run_id)
    content = report.read_text()
    assert "Nano accepts, Luna rejects | 1" in content
    assert "Luna accepts, Nano rejects | 1" in content
    assert "Exact prompts, article inputs, Nano raw/parsed outputs" in content
    assert audit.result_path(run_date, run_id).is_file()
