from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from lloyds_digest.storage.postgres_repo import PostgresRepo
from lloyds_digest.utils import load_env_file


def main() -> None:
    load_env_file(Path(".env"))
    args = _parse_args()
    run_id = args.run_id or _latest_run_id()
    if not run_id:
        print("No run_id found.")
        return

    started_at = _parse_dt(args.started_at) if args.started_at else None
    ended_at = _parse_dt(args.ended_at) if args.ended_at else None
    duration_ms = args.duration_ms
    if duration_ms is None and started_at and ended_at:
        duration_ms = int((ended_at - started_at).total_seconds() * 1000)
    if duration_ms is None:
        print("Duration unavailable.")
        return

    postgres = PostgresRepo(_dsn_from_env())
    postgres.insert_run_phase_timing(
        run_id=run_id,
        phase=args.phase,
        duration_ms=duration_ms,
        started_at=started_at,
        ended_at=ended_at,
        metadata={},
    )
    print(f"Logged phase {args.phase} for run {run_id}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Log a run phase timing entry.")
    parser.add_argument("--phase", required=True, help="Phase name")
    parser.add_argument("--run-id", default="", help="Run ID (defaults to latest)")
    parser.add_argument("--started-at", default="", help="UTC ISO timestamp")
    parser.add_argument("--ended-at", default="", help="UTC ISO timestamp")
    parser.add_argument("--duration-ms", type=int, default=None, help="Duration in ms")
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


def _latest_run_id() -> str | None:
    sql = "SELECT run_id FROM runs ORDER BY started_at DESC LIMIT 1"
    with psycopg.connect(_dsn_from_env()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            if not row:
                return None
            return row[0]


def _parse_dt(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(timezone.utc)


if __name__ == "__main__":
    main()
