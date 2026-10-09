"""Isolated, three-day Nano/Luna relevance shadow audit helpers."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

AUDIT_START = date(2026, 10, 10)
AUDIT_END = date(2026, 10, 12)
AUDIT_ROOT = Path("logs/model_shadow")


def audit_enabled(run_date: date) -> bool:
    """Return true only for the three explicitly authorised London run dates."""
    return AUDIT_START <= run_date <= AUDIT_END


def input_path(run_date: date, run_id: str) -> Path:
    return AUDIT_ROOT / run_date.isoformat() / f"inputs_{run_id}.jsonl"


def result_path(run_date: date, run_id: str) -> Path:
    return AUDIT_ROOT / run_date.isoformat() / f"results_{run_id}.jsonl"


class ShadowAuditSession:
    """Capture inputs for the independent worker; Nano remains authoritative."""

    def __init__(self, run_date: date, run_id: str) -> None:
        self.run_date = run_date
        self.run_id = run_id
        self.enabled = audit_enabled(run_date)
        if self.enabled:
            path = input_path(run_date, run_id)
            try:
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.chmod(path.parent, 0o700)
                for target in (path, jobs_path(run_date, run_id)):
                    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                    os.close(fd)
                    os.chmod(target, 0o600)
            except Exception:
                # Capture is observational only; the pipeline continues normally.
                pass

    def submit_luna(self, candidate_id: str, title: str, url: str, prompt: str) -> bool:
        if not self.enabled:
            return True
        try:
            path = jobs_path(self.run_date, self.run_id)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {
                            "run_date": self.run_date.isoformat(),
                            "run_id": self.run_id,
                            "candidate_id": candidate_id,
                            "title": title,
                            "url": url,
                            "prompt": prompt,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(path, 0o600)
            return True
        except Exception:
            return False


def jobs_path(run_date: date, run_id: str) -> Path:
    return AUDIT_ROOT / run_date.isoformat() / f"jobs_{run_id}.jsonl"


def capture_nano_relevance(
    *,
    run_date: date,
    run_id: str,
    candidate_id: str,
    title: str,
    url: str,
    model: str,
    prompt_version: str,
    prompt: str,
    nano_result: dict[str, Any] | None,
    production_relevant: bool,
) -> bool:
    """Persist exact prompt and Nano response without affecting filtering."""
    if not audit_enabled(run_date):
        return True

    result = nano_result or {}
    record = {
        "schema_version": 1,
        "run_date": run_date.isoformat(),
        "run_id": run_id,
        "candidate_id": candidate_id,
        "title": title,
        "url": url,
        "nano": {
            "model": model,
            "prompt_version": prompt_version,
            "prompt": prompt,
            "raw_output": result.get("raw"),
            "parsed_output": result.get("parsed"),
            "error": None if nano_result is not None else "Nano relevance call failed",
            "cached": bool(result.get("cached")),
            "latency_ms": result.get("latency_ms"),
            "tokens_prompt": result.get("tokens_prompt"),
            "tokens_completion": result.get("tokens_completion"),
            "tokens_cached_prompt": result.get("tokens_cached_prompt"),
            "tokens_cache_write": result.get("tokens_cache_write"),
            "service_tier": result.get("service_tier"),
            "production_relevant": production_relevant,
        },
    }
    try:
        path = input_path(run_date, run_id)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(path, 0o600)
        return True
    except Exception:
        # This is observational only. Capture failure must never change the digest.
        return False
