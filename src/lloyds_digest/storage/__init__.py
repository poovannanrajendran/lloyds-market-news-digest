"""Storage backends for Lloyd's Digest."""

from __future__ import annotations

__all__ = ["PostgresRepo", "MongoRepo"]

from lloyds_digest.storage.mongo_repo import MongoRepo
from lloyds_digest.storage.postgres_repo import PostgresRepo
