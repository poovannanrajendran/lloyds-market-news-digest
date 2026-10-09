#!/usr/bin/env python3
"""Run a post-publication, read-only Nano versus GPT-6 Luna relevance audit."""

from __future__ import annotations

import argparse
import json
import os
import statistics
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from lloyds_digest.reporting.model_shadow_audit import (
    AUDIT_ROOT,
    audit_enabled,
    input_path,
    jobs_path,
    result_path,
)


def _report_path(run_date: date, run_id: str) -> Path:
    return AUDIT_ROOT / "reports" / f"model_comparison_{run_date.isoformat()}_{run_id}.md"


def _decision(parsed: Any) -> str:
    if not isinstance(parsed, dict) or not isinstance(parsed.get("relevant"), bool):
        return "unknown"
    return "accept" if parsed["relevant"] else "reject"


def _money_estimate(records: list[dict[str, Any]], key: str) -> float:
    # Same Flex/default tier rule as the application cost ledger. The estimate is
    # for comparison only; the organisation Costs API remains authoritative.
    total = 0.0
    for item in records:
        if key == "nano" and item.get("cached"):
            continue
        tokens_in = int(item.get("tokens_prompt") or 0)
        tokens_out = int(item.get("tokens_completion") or 0)
        cached_in = min(tokens_in, int(item.get("tokens_cached_prompt") or 0))
        uncached_in = tokens_in - cached_in
        tier = str(item.get("service_tier") or "flex").lower()
        divisor = 2 if tier == "flex" else 1
        if key == "nano":
            total += (
                (uncached_in * 0.05 + cached_in * 0.005 + tokens_out * 0.40) / 1_000_000 / divisor
            )
        else:
            total += (
                (uncached_in * 0.10 + cached_in * 0.01 + tokens_out * 0.50) / 1_000_000 / divisor
            )
    return total


def _write_report(
    run_date: date,
    run_id: str,
    paired: list[dict[str, Any]],
    luna_errors: int,
) -> Path:
    report = _report_path(run_date, run_id)
    report.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    decisions = [
        (
            row,
            _decision(row["nano"].get("parsed_output")),
            _decision(row["luna"].get("parsed_output")),
        )
        for row in paired
    ]
    counts = {
        "both_accept": sum(nano == "accept" and luna == "accept" for _, nano, luna in decisions),
        "both_reject": sum(nano == "reject" and luna == "reject" for _, nano, luna in decisions),
        "nano_only": sum(nano == "accept" and luna == "reject" for _, nano, luna in decisions),
        "luna_only": sum(nano == "reject" and luna == "accept" for _, nano, luna in decisions),
        "unknown": sum(nano == "unknown" or luna == "unknown" for _, nano, luna in decisions),
    }
    comparable = len(paired) - counts["unknown"]
    agreements = counts["both_accept"] + counts["both_reject"]
    nano_latencies = [
        int(row["nano"].get("latency_ms"))
        for row in paired
        if row["nano"].get("latency_ms") is not None and not row["nano"].get("cached")
    ]
    luna_latencies = [
        int(row["luna"].get("latency_ms"))
        for row in paired
        if row["luna"].get("latency_ms") is not None
    ]
    nano_cost = _money_estimate([row["nano"] for row in paired], "nano")
    luna_cost = _money_estimate([row["luna"] for row in paired], "luna")
    agreement_summary = (
        f"| Decision agreement among known pairs | {agreements}/{comparable} "
        f"({(agreements / comparable * 100):.1f}%) |"
        if comparable
        else "| Decision agreement among known pairs | n/a |"
    )
    mean_latency_summary = (
        f"- Mean request latency: Nano {statistics.mean(nano_latencies):.0f} ms; "
        f"Luna {statistics.mean(luna_latencies):.0f} ms."
        if nano_latencies and luna_latencies
        else "- Mean request latency: unavailable for one or both models."
    )

    lines = [
        f"# Nano / GPT-6 Luna shadow comparison — {run_date.isoformat()}",
        "",
        f"- Run ID: `{run_id}`",
        f"- Generated after digest publication: {datetime.now(UTC).isoformat()}",
        "- Production decision-maker: GPT-5 Nano. "
        "Luna results were shadow-only and did not change the published digest.",
        f"- Paired relevance prompts: {len(paired)}; Luna call errors: {luna_errors}.",
        f"- Nano cache hits (captured without a new Nano API charge): "
        f"{sum(bool(row['nano'].get('cached')) for row in paired)}.",
        "",
        "## Decision comparison",
        "",
        "| Outcome | Articles |",
        "|---|---:|",
        f"| Both accept | {counts['both_accept']} |",
        f"| Both reject | {counts['both_reject']} |",
        f"| Nano accepts, Luna rejects | {counts['nano_only']} |",
        f"| Luna accepts, Nano rejects | {counts['luna_only']} |",
        f"| At least one decision unknown | {counts['unknown']} |",
        agreement_summary,
        "",
        "Agreement is not accuracy: no independent human-labelled relevance set is available. "
        "Review both disagreement groups to assess whether Luna would improve the digest.",
        "",
        "## Runtime and cost indicators",
        "",
        mean_latency_summary,
        f"- Estimated per-run model cost: Nano ${nano_cost:.6f}; Luna ${luna_cost:.6f}; "
        f"difference ${luna_cost - nano_cost:+.6f}.",
        "- Cost uses published Standard rates with a 50% Flex adjustment for `flex` responses. "
        "Nano cache hits are excluded; cache writes or billing adjustments may be omitted, "
        "so this estimate is not reconciled billing.",
        "",
        "## Per-article review",
        "",
        "| Article | Nano | Luna | Nano confidence | Luna confidence | Nano reason | Luna reason |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for row, nano_decision, luna_decision in decisions:
        nano = row["nano"].get("parsed_output") or {}
        luna = row["luna"].get("parsed_output") or {}
        title = (
            str(row.get("title") or row.get("url") or "Untitled")
            .replace("|", "\\|")
            .replace("\n", " ")
        )
        url = str(row.get("url") or "")
        article = f"[{title}]({url})" if url.startswith(("http://", "https://")) else title
        nreason = (
            str(nano.get("reason") or row["nano"].get("error") or "—")
            .replace("|", "\\|")
            .replace("\n", " ")
        )
        lreason = (
            str(luna.get("reason") or row["luna"].get("error") or "—")
            .replace("|", "\\|")
            .replace("\n", " ")
        )
        nconfidence = nano.get("confidence", "—")
        lconfidence = luna.get("confidence", "—")
        lines.append(
            f"| {article} | {nano_decision} | {luna_decision} | {nconfidence} | "
            f"{lconfidence} | {nreason} | {lreason} |"
        )
    lines.extend(
        [
            "",
            "## Raw evidence",
            "",
            f"- Exact prompts, article inputs, Nano raw/parsed outputs, and production decisions: "
            f"`{input_path(run_date, run_id)}`",
            f"- Luna request queue with the same prompts: `{jobs_path(run_date, run_id)}`",
            f"- Luna raw/parsed outputs, usage, latency, service tier, and errors: "
            f"`{result_path(run_date, run_id)}`",
            "- Evidence remains under ignored `logs/`; it is not published or committed to Git.",
            "",
        ]
    )
    report.write_text("\n".join(lines), encoding="utf-8")
    os.chmod(report, 0o600)
    return report


def run_audit(run_date: date, run_id: str) -> Path:
    if not audit_enabled(run_date):
        raise ValueError(
            f"Shadow audit is disabled for {run_date}; "
            "the fixed window is 2026-10-10 through 2026-10-12 only"
        )
    source = input_path(run_date, run_id)
    if not source.is_file():
        raise FileNotFoundError(f"No captured Nano evidence found for run {run_id}: {source}")
    output = result_path(run_date, run_id)
    if not output.is_file():
        raise FileNotFoundError(f"No Luna shadow results found for run {run_id}: {output}")
    nano_records = [
        json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    luna_records = [
        json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    luna_by_candidate = {str(row.get("candidate_id")): row for row in luna_records}
    paired = []
    for nano_row in nano_records:
        candidate_id = str(nano_row.get("candidate_id") or "")
        luna_row = luna_by_candidate.get(candidate_id)
        paired.append(
            {
                "candidate_id": candidate_id,
                "title": nano_row.get("title"),
                "url": nano_row.get("url"),
                "nano": nano_row.get("nano") or {},
                "luna": (luna_row or {}).get("luna")
                or {"error": "No Luna result was recorded for this article"},
            }
        )
    errors = sum(bool(row["luna"].get("error")) for row in paired)
    return _write_report(run_date, run_id, paired, errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-date", required=True, type=date.fromisoformat)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    report = run_audit(args.run_date, args.run_id)
    print(f"Nano/Luna shadow report: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
