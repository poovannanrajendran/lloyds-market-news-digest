from __future__ import annotations

import argparse
import html
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg

from lloyds_digest.config import load_config
from lloyds_digest.storage.mongo_repo import MongoRepo, MongoConfigError
from lloyds_digest.utils import load_env_file


def main() -> None:
    load_env_file(Path(".env"))
    config = load_config(Path("config.yaml"))
    args = _parse_args()

    runs = _fetch_runs(limit=args.limit_runs)
    if not runs:
        print("No runs found.")
        return

    output_dir = Path("output") / "dashboard"
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.run_id:
        run = next((r for r in runs if r["run_id"] == args.run_id), None)
        if not run:
            print(f"Run not found: {args.run_id}")
            return
        html = _render_run_page(run, runs, config)
        out_path = output_dir / f"run_{run['run_id']}.html"
        out_path.write_text(html, encoding="utf-8")
        print(f"Wrote {out_path}")
        return

    for run in runs:
        html = _render_run_page(run, runs, config)
        out_path = output_dir / f"run_{run['run_id']}.html"
        out_path.write_text(html, encoding="utf-8")
        print(f"Wrote {out_path}")

    index_html = _render_index_page(runs)
    index_path = output_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    print(f"Wrote {index_path}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render an HTML dashboard for recent runs.")
    parser.add_argument("--run-id", default="", help="Render only a single run ID.")
    parser.add_argument("--limit-runs", type=int, default=20, help="Number of recent runs to include.")
    return parser.parse_args()


def _dsn_from_env() -> str:
    required = ["POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"]
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise RuntimeError(f"Missing Postgres env vars: {', '.join(missing)}")
    return (
        f"host={os.environ['POSTGRES_HOST']} "
        f"port={os.environ['POSTGRES_PORT']} "
        f"dbname={os.environ['POSTGRES_DB']} "
        f"user={os.environ['POSTGRES_USER']} "
        f"password={os.environ['POSTGRES_PASSWORD']}"
    )


def _fetch_runs(limit: int) -> list[dict[str, Any]]:
    sql = """
        SELECT run_id, run_date, started_at, ended_at, metrics
        FROM runs
        ORDER BY started_at DESC
        LIMIT %s
    """
    runs: list[dict[str, Any]] = []
    with psycopg.connect(_dsn_from_env()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            for row in cur.fetchall():
                run_id, run_date, started_at, ended_at, metrics = row
                runs.append(
                    {
                        "run_id": run_id,
                        "run_date": run_date,
                        "started_at": started_at,
                        "ended_at": ended_at,
                        "metrics": metrics or {},
                    }
                )
    return runs


def _run_counts(run: dict[str, Any], config) -> dict[str, Any]:
    run_id = run["run_id"]
    run_date = run["run_date"]
    started_at = run["started_at"]
    ended_at = run["ended_at"] or datetime.now(timezone.utc)
    max_age_days = getattr(config, "filters", None).max_age_days if getattr(config, "filters", None) else 7
    cutoff = datetime.combine(run_date, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=max_age_days)

    sql_candidates = """
        SELECT COUNT(*),
               COUNT(*) FILTER (WHERE published_at IS NOT NULL AND published_at < %s) AS filtered_by_age
        FROM candidates
        WHERE metadata->>'run_id' = %s
    """
    sql_articles = """
        SELECT COUNT(*) FROM articles
        WHERE created_at >= %s AND created_at <= %s
    """
    sql_llm = """
        SELECT stage, COUNT(*)
        FROM llm_usage
        WHERE run_id = %s
        GROUP BY stage
    """

    with psycopg.connect(_dsn_from_env()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql_candidates, (cutoff, run_id))
            total_candidates, filtered_by_age = cur.fetchone()

            cur.execute(sql_articles, (started_at, ended_at))
            total_articles = cur.fetchone()[0]

            cur.execute(sql_llm, (run_id,))
            llm_counts = {stage: count for stage, count in cur.fetchall()}

    return {
        "total_candidates": total_candidates,
        "filtered_by_age": filtered_by_age,
        "total_articles": total_articles,
        "llm_counts": llm_counts,
    }


def _fetch_rejections(run_id: str) -> dict[str, int] | None:
    try:
        mongo = MongoRepo.from_env()
    except MongoConfigError:
        return None
    try:
        collection = mongo._collection("rejections")
        pipeline = [
            {"$match": {"run_id": run_id}},
            {"$group": {"_id": "$stage", "count": {"$sum": 1}}},
        ]
        results = collection.aggregate(pipeline)
        return {item["_id"]: int(item["count"]) for item in results}
    except Exception:
        return None


def _fetch_render_stats(run_id: str, run_started_at: datetime, run_ended_at: datetime) -> dict[str, Any]:
    sql = """
        SELECT stage, model, COUNT(*), AVG(latency_ms), SUM(tokens_prompt), SUM(tokens_completion)
        FROM llm_usage
        WHERE (stage LIKE 'render_%%' OR stage LIKE 'render_digest:%%')
          AND run_id = %s
        GROUP BY stage, model
        ORDER BY MAX(started_at) DESC
    """
    rows = []
    with psycopg.connect(_dsn_from_env()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            for row in cur.fetchall():
                rows.append(row)
    if rows:
        return {"rows": rows}
    sql = """
        SELECT stage, model, COUNT(*), AVG(latency_ms), SUM(tokens_prompt), SUM(tokens_completion)
        FROM llm_usage
        WHERE (stage LIKE 'render_%%' OR stage LIKE 'render_digest:%%')
          AND started_at >= %s AND started_at <= %s
        GROUP BY stage, model
        ORDER BY MAX(started_at) DESC
    """
    with psycopg.connect(_dsn_from_env()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (run_started_at, run_ended_at))
            for row in cur.fetchall():
                rows.append(row)
    return {"rows": rows}


def _fetch_costs(run_date: datetime.date) -> list[tuple[Any, ...]]:
    sql = """
        SELECT usage_date, stage, provider, model, service_tier, calls, cost_total_usd
        FROM llm_cost_stage_daily
        WHERE usage_date = %s
        ORDER BY cost_total_usd DESC
    """
    with psycopg.connect(_dsn_from_env()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (run_date,))
            return cur.fetchall()


def _fetch_phase_timings(run_id: str) -> list[tuple[Any, ...]]:
    sql = """
        SELECT phase, started_at, ended_at, duration_ms
        FROM run_phase_timings
        WHERE run_id = %s
        ORDER BY started_at NULLS LAST, phase
    """
    with psycopg.connect(_dsn_from_env()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            return cur.fetchall()


def _fetch_attempt_errors(run_id: str, limit: int = 25) -> list[tuple[Any, ...]]:
    sql = """
        SELECT
            a.kind,
            a.method,
            a.status,
            a.error,
            c.url,
            c.source_id,
            a.started_at
        FROM attempts a
        JOIN candidates c ON c.candidate_id = a.candidate_id
        WHERE c.metadata->>'run_id' = %s
          AND (a.status = 'ERROR' OR a.error IS NOT NULL)
        ORDER BY a.started_at DESC
        LIMIT %s
    """
    with psycopg.connect(_dsn_from_env()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (run_id, limit))
            return cur.fetchall()


def _render_run_page(run: dict[str, Any], runs: list[dict[str, Any]], config) -> str:
    counts = _run_counts(run, config)
    rejections = _fetch_rejections(run["run_id"])
    started_at = run["started_at"]
    ended_at = run["ended_at"] or datetime.now(timezone.utc)
    render_stats = _fetch_render_stats(run["run_id"], started_at, ended_at)
    costs = _fetch_costs(run["run_date"])
    phase_rows = _fetch_phase_timings(run["run_id"])
    attempt_errors = _fetch_attempt_errors(run["run_id"])

    metrics = run.get("metrics") or {}
    llm_counts = counts["llm_counts"]
    good_selected = llm_counts.get("summarise", 0)

    rejection_rows = ""
    if rejections is None:
        rejection_rows = "<tr><td colspan='2'>Rejection stats not available (Mongo not configured).</td></tr>"
    else:
        for stage, count in sorted(rejections.items()):
            rejection_rows += f"<tr><td>{stage}</td><td>{count}</td></tr>"

    render_rows = ""
    for stage, model, calls, avg_latency, tokens_prompt, tokens_completion in render_stats["rows"]:
        render_rows += (
            "<tr>"
            f"<td>{stage}</td>"
            f"<td>{model}</td>"
            f"<td>{calls}</td>"
            f"<td>{int(avg_latency or 0)}</td>"
            f"<td>{int(tokens_prompt or 0)}</td>"
            f"<td>{int(tokens_completion or 0)}</td>"
            "</tr>"
        )

    error_rows = ""
    for kind, method, status, error, url, source_id, started_at_err in attempt_errors:
        error_rows += (
            "<tr>"
            f"<td>{html.escape(str(kind))}</td>"
            f"<td>{html.escape(str(method))}</td>"
            f"<td>{html.escape(str(status))}</td>"
            f"<td>{html.escape(str(error or ''))}</td>"
            f"<td>{html.escape(str(url or ''))}</td>"
            f"<td>{html.escape(str(source_id))}</td>"
            f"<td>{_format_dt(started_at_err) if started_at_err else ''}</td>"
            "</tr>"
        )

    cost_rows = ""
    if costs:
        for usage_date, stage, provider, model, service_tier, calls, total in costs:
            cost_rows += (
                "<tr>"
                f"<td>{usage_date}</td>"
                f"<td>{stage}</td>"
                f"<td>{provider}</td>"
                f"<td>{model}</td>"
                f"<td>{service_tier or ''}</td>"
                f"<td>{calls}</td>"
                f"<td>${float(total):.4f}</td>"
                "</tr>"
            )
    else:
        cost_rows = "<tr><td colspan='7'>No cost data for this run date.</td></tr>"

    phase_table_rows = ""
    if phase_rows:
        for phase, p_start, p_end, duration_ms in phase_rows:
            phase_table_rows += (
                "<tr>"
                f"<td>{phase}</td>"
                f"<td>{_format_dt(p_start) if p_start else ''}</td>"
                f"<td>{_format_dt(p_end) if p_end else ''}</td>"
                f"<td>{_format_duration_ms(duration_ms)}</td>"
                "</tr>"
            )
    else:
        phase_table_rows = "<tr><td colspan='4'>No phase timing data found.</td></tr>"

    run_list = "".join(
        f"<option value='run_{r['run_id']}.html'>{r['run_date']} · {r['started_at'].strftime('%H:%M:%S')}</option>"
        for r in runs
    )

    duration = ended_at - started_at
    duration_str = _format_duration(duration)
    started_str = _format_dt(started_at)
    ended_str = _format_dt(ended_at)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Digest Run Dashboard · {run['run_date']}</title>
  <style>
    :root {{
      --ink:#0b1f3b; --slate:#5b6b7a; --teal:#1f7a8c; --sand:#f6f4f0; --line:#d7dee6;
      --accent:#c9a227;
    }}
    body {{ margin:0; font-family:"Source Sans 3","Segoe UI",Arial,sans-serif; background:var(--sand); color:var(--ink); }}
    .wrap {{ max-width:1200px; margin:0 auto; padding:32px 24px 60px; }}
    header {{ background:linear-gradient(120deg,#0b1f3b 0%,#12345a 45%,#1f7a8c 100%); color:#fff; padding:24px 28px; border-radius:16px; }}
    header h1 {{ margin:0 0 6px; font-size:24px; }}
    header .meta {{ color:rgba(255,255,255,0.75); }}
    .controls {{ margin-top:14px; }}
    select {{ padding:8px 10px; border-radius:8px; border:1px solid var(--line); }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:16px; margin-top:20px; }}
    .card {{ background:#fff; border-radius:14px; padding:16px; border:1px solid var(--line); box-shadow:0 8px 16px rgba(11,31,59,0.05); }}
    .card h2 {{ margin-top:0; font-size:16px; color:var(--teal); }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); }}
    th {{ background:#f2f5f8; }}
    details.collapsible {{ background:#fff; border:1px solid var(--line); border-radius:12px; padding:8px 12px; box-shadow:0 8px 16px rgba(11,31,59,0.05); }}
    details.collapsible summary {{ cursor:pointer; font-weight:600; color:var(--teal); margin:4px 0 8px; }}
    details.collapsible[open] summary {{ margin-bottom:12px; }}
    .section {{ margin-top:24px; }}
    .section h2 {{ margin-bottom:10px; font-size:18px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>Lloyd’s Market Digest · Run Dashboard</h1>
      <div class="meta">Run date: {run['run_date']} · Started: {started_str} · Ended: {ended_str} · Duration: {duration_str}</div>
      <div class="controls">
        <label for="runSelect">Other runs:</label>
        <select id="runSelect" onchange="if(this.value) window.location.href=this.value;">
          {run_list}
        </select>
      </div>
    </header>

    <div class="grid">
      <div class="card">
        <h2>Sources & Candidates</h2>
        <p>Total sources: {metrics.get('total_sources', 'n/a')}</p>
        <p>Total candidates: {counts['total_candidates']}</p>
        <p>Filtered by age: {counts['filtered_by_age']}</p>
      </div>
      <div class="card">
        <h2>Fetch & Extract</h2>
        <p>Fetched: {metrics.get('fetched', 'n/a')}</p>
        <p>Extracted: {metrics.get('extracted', 'n/a')}</p>
        <p>Articles created: {counts['total_articles']}</p>
      </div>
      <div class="card">
        <h2>LLM Stages</h2>
        <p>Relevance calls: {llm_counts.get('relevance', 0)}</p>
        <p>Classify calls: {llm_counts.get('classify', 0)}</p>
        <p>Summarise calls: {llm_counts.get('summarise', 0)}</p>
        <p>Good articles selected: {good_selected}</p>
      </div>
      <div class="card">
        <h2>Errors</h2>
        <p>Total errors: {metrics.get('errors', 'n/a')}</p>
        <p>Notes: {json.dumps(metrics.get('notes', {}))}</p>
      </div>
    </div>

    <div class="section">
      <h2>Rejections by Stage</h2>
      <table>
        <tr><th>Stage</th><th>Count</th></tr>
        {rejection_rows}
      </table>
    </div>

    <div class="section">
      <h2>Render Stats (HTML + LinkedIn)</h2>
      <table>
        <tr><th>Stage</th><th>Model</th><th>Calls</th><th>Avg Latency (ms)</th><th>Prompt Tokens</th><th>Completion Tokens</th></tr>
        {render_rows or "<tr><td colspan='6'>No render stats found.</td></tr>"}
      </table>
    </div>

    <div class="section">
      <h2>Cost Summary</h2>
      <table>
        <tr><th>Date</th><th>Stage</th><th>Provider</th><th>Model</th><th>Tier</th><th>Calls</th><th>Total Cost</th></tr>
        {cost_rows}
      </table>
    </div>

    <div class="section">
      <h2>Run Phase Timings</h2>
      <table>
        <tr><th>Phase</th><th>Started</th><th>Ended</th><th>Duration</th></tr>
        {phase_table_rows}
      </table>
    </div>
    <div class="section">
      <details class="collapsible">
        <summary>Recent Errors</summary>
        <table>
          <tr><th>Kind</th><th>Method</th><th>Status</th><th>Error</th><th>URL</th><th>Source</th><th>Started</th></tr>
          {error_rows or "<tr><td colspan='7'>No error details found.</td></tr>"}
        </table>
      </details>
    </div>
  </div>
</body>
</html>
"""


def _render_index_page(runs: list[dict[str, Any]]) -> str:
    rows = ""
    for run in runs:
        run_id = run["run_id"]
        run_date = run["run_date"]
        started = run["started_at"]
        ended = run["ended_at"] or "-"
        rows += (
            "<tr>"
            f"<td>{run_date}</td>"
            f"<td>{started}</td>"
            f"<td>{ended}</td>"
            f"<td><a href='run_{run_id}.html'>View</a></td>"
            "</tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Digest Run Dashboard</title>
  <style>
    body {{ margin:0; font-family:"Source Sans 3","Segoe UI",Arial,sans-serif; background:#f6f4f0; color:#0b1f3b; }}
    .wrap {{ max-width:1000px; margin:0 auto; padding:32px 24px 60px; }}
    h1 {{ margin-top:0; }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; background:#fff; border-radius:12px; overflow:hidden; }}
    th, td {{ text-align:left; padding:10px 12px; border-bottom:1px solid #d7dee6; }}
    th {{ background:#f2f5f8; }}
    a {{ color:#1f7a8c; text-decoration:none; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Digest Run Dashboard</h1>
    <table>
      <tr><th>Date</th><th>Started</th><th>Ended</th><th>Dashboard</th></tr>
      {rows}
    </table>
  </div>
</body>
</html>
"""


def _format_dt(value: datetime) -> str:
    return value.strftime("%Y-%b-%d %H:%M:%S")


def _format_duration(delta: timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _format_duration_ms(duration_ms: int | None) -> str:
    if duration_ms is None:
        return ""
    total_seconds = int(duration_ms // 1000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


if __name__ == "__main__":
    main()
