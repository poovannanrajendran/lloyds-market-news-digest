#!/usr/bin/env python3
"""Consume the run's prompt queue and evaluate GPT-6 Luna in shadow mode."""

from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

from lloyds_digest.ai.base import OpenAIClient, extract_openai_usage
from lloyds_digest.ai.relevance import _safe_json
from lloyds_digest.reporting.model_shadow_audit import (
    audit_enabled,
    jobs_path,
    result_path,
)
from lloyds_digest.utils import load_env_file


def evaluate(prompt: str) -> dict[str, Any]:
    started = time.monotonic()
    result: dict[str, Any] = {
        "model": "gpt-6-luna",
        "attempts": 0,
        "raw_output": None,
        "parsed_output": None,
        "error": None,
        "tokens_prompt": None,
        "tokens_completion": None,
        "tokens_cached_prompt": None,
        "tokens_cache_write": None,
        "service_tier": None,
        "latency_ms": None,
    }
    for attempt in range(1, 4):
        result["attempts"] = attempt
        try:
            response = OpenAIClient(model="gpt-6-luna").generate(prompt)
            raw = response.get("raw", {})
            text = response.get("response", "")
            parsed = _safe_json(text)
            tokens_prompt, tokens_completion, cached = extract_openai_usage(raw)
            usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
            prompt_details = (
                usage.get("prompt_tokens_details", {}) if isinstance(usage, dict) else {}
            )
            result.update(
                {
                    "raw_output": text,
                    "tokens_prompt": tokens_prompt,
                    "tokens_completion": tokens_completion,
                    "tokens_cached_prompt": cached,
                    "tokens_cache_write": prompt_details.get("cache_write_tokens")
                    if isinstance(prompt_details, dict)
                    else None,
                    "service_tier": response.get("service_tier"),
                }
            )
            if not parsed:
                raise ValueError("GPT-6 Luna returned invalid or empty relevance JSON")
            result.update({"parsed_output": parsed, "error": None})
            break
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
            if attempt < 3:
                time.sleep(attempt)
    result["latency_ms"] = round((time.monotonic() - started) * 1000)
    return result


def run_worker(run_date: date, run_id: str, done_file: Path) -> int:
    if not audit_enabled(run_date):
        raise ValueError("Shadow worker is outside the fixed 10–12 October 2026 window")
    queue = jobs_path(run_date, run_id)
    queue.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(queue.parent, 0o700)
    started = time.monotonic()
    futures = {}
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="luna-shadow") as pool:
        while not queue.is_file() and not done_file.exists():
            if time.monotonic() - started > 3600:
                raise TimeoutError("Shadow worker exceeded its one-hour safety window")
            time.sleep(0.25)
        if queue.is_file():
            with queue.open("r", encoding="utf-8") as stream:
                while True:
                    position = stream.tell()
                    line = stream.readline()
                    if line and line.endswith("\n"):
                        job = json.loads(line)
                        futures[pool.submit(evaluate, job["prompt"])] = job
                        continue
                    if line:
                        stream.seek(position)
                    if done_file.exists():
                        break
                    if time.monotonic() - started > 3600:
                        raise TimeoutError("Shadow worker exceeded its one-hour safety window")
                    time.sleep(0.25)

        results: list[dict[str, Any]] = []
        for future in as_completed(futures):
            job = futures[future]
            try:
                luna = future.result()
            except Exception as exc:
                luna = {"model": "gpt-6-luna", "error": f"{type(exc).__name__}: {exc}"}
            results.append(
                {
                    "run_date": run_date.isoformat(),
                    "run_id": run_id,
                    "candidate_id": job.get("candidate_id"),
                    "title": job.get("title"),
                    "url": job.get("url"),
                    "luna": luna,
                }
            )

    output = result_path(run_date, run_id)
    with output.open("w", encoding="utf-8") as stream:
        for row in results:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(output, 0o600)
    print(f"Luna shadow worker finished: prompts={len(results)} results={output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-date", required=True, type=date.fromisoformat)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--done-file", required=True, type=Path)
    args = parser.parse_args()
    load_env_file(Path(".env"))
    return run_worker(args.run_date, args.run_id, args.done_file)


if __name__ == "__main__":
    raise SystemExit(main())
