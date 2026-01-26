from __future__ import annotations

import pytest

from lloyds_digest.storage.mongo_repo import MongoConfigError, MongoRepo
from lloyds_digest.storage.postgres_repo import PostgresConfigError, build_postgres_dsn


def test_build_postgres_dsn() -> None:
    env = {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "lloyds",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "postgres",
    }
    dsn = build_postgres_dsn(env)
    assert "host=localhost" in dsn
    assert "port=5432" in dsn
    assert "dbname=lloyds" in dsn


def test_build_postgres_dsn_missing() -> None:
    with pytest.raises(PostgresConfigError):
        build_postgres_dsn({})


def test_mongo_repo_from_env_missing() -> None:
    with pytest.raises(MongoConfigError):
        MongoRepo.from_env({})
