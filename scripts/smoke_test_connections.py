from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone

from lloyds_digest.models import RunMetrics
from lloyds_digest.storage.mongo_repo import MongoRepo
from lloyds_digest.storage.postgres_repo import PostgresRepo


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def smoke_postgres() -> None:
    repo = PostgresRepo.from_env()
    if not repo.ping():
        raise RuntimeError("Postgres ping failed")

    run_id = f"smoke-{uuid.uuid4()}"
    run = RunMetrics(run_id=run_id, run_date=date.today(), started_at=_utc_now())
    repo.create_run(run)

    with repo._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT run_id FROM runs WHERE run_id = %s", (run_id,))
            row = cur.fetchone()
            if not row or row[0] != run_id:
                raise RuntimeError("Postgres round-trip failed")


def smoke_mongo() -> None:
    repo = MongoRepo.from_env()
    if not repo.ping():
        raise RuntimeError("Mongo ping failed")

    key = f"smoke-{uuid.uuid4()}"
    payload = {"key": key, "value": "ok", "created_at": _utc_now()}
    repo.upsert_ai_cache(key, payload)

    collection = repo._collection("ai_cache")
    doc = collection.find_one({"key": key})
    if not doc:
        raise RuntimeError("Mongo round-trip failed")


if __name__ == "__main__":
    print("Running Postgres smoke test...")
    smoke_postgres()
    print("Postgres OK")

    print("Running Mongo smoke test...")
    smoke_mongo()
    print("Mongo OK")
