from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


class MongoConfigError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class MongoRepo:
    uri: str
    database: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "MongoRepo":
        data = env or os.environ
        uri = data.get("MONGODB_URI")
        db_name = data.get("MONGO_DB_NAME")
        if not uri or not db_name:
            missing = [
                name
                for name, value in (
                    ("MONGODB_URI", uri),
                    ("MONGO_DB_NAME", db_name),
                )
                if not value
            ]
            raise MongoConfigError("Missing Mongo env vars: " + ", ".join(missing))
        return cls(uri=uri, database=db_name)

    def _client(self):
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise RuntimeError("pymongo is required for MongoRepo") from exc
        return MongoClient(self.uri)

    def _collection(self, name: str):
        client = self._client()
        return client[self.database][name]

    def ping(self) -> bool:
        client = self._client()
        return bool(client.admin.command("ping"))

    def insert_discovery_snapshot(self, payload: Mapping[str, Any]) -> str:
        collection = self._collection("discovery_snapshots")
        data = dict(payload)
        data.setdefault("created_at", _utc_now())
        result = collection.insert_one(data)
        return str(result.inserted_id)

    def upsert_fetch_cache(self, key: str, payload: Mapping[str, Any]) -> None:
        collection = self._collection("fetch_cache")
        data = dict(payload)
        data["updated_at"] = _utc_now()
        collection.update_one({"key": key}, {"$set": data, "$setOnInsert": {"key": key}}, upsert=True)

    def get_fetch_cache(self, key: str) -> dict[str, Any] | None:
        collection = self._collection("fetch_cache")
        doc = collection.find_one({"key": key})
        if not doc:
            return None
        doc.pop("_id", None)
        return doc

    def insert_attempt_raw(self, payload: Mapping[str, Any]) -> str:
        collection = self._collection("attempts_raw")
        data = dict(payload)
        data.setdefault("created_at", _utc_now())
        result = collection.insert_one(data)
        return str(result.inserted_id)

    def upsert_winner(self, key: str, payload: Mapping[str, Any]) -> None:
        collection = self._collection("winners")
        data = dict(payload)
        data["updated_at"] = _utc_now()
        collection.update_one({"key": key}, {"$set": data, "$setOnInsert": {"key": key}}, upsert=True)

    def upsert_ai_cache(self, key: str, payload: Mapping[str, Any]) -> None:
        collection = self._collection("ai_cache")
        data = dict(payload)
        data["updated_at"] = _utc_now()
        collection.update_one({"key": key}, {"$set": data, "$setOnInsert": {"key": key}}, upsert=True)

    def get_ai_cache(self, key: str) -> dict[str, Any] | None:
        collection = self._collection("ai_cache")
        doc = collection.find_one({"key": key})
        if not doc:
            return None
        doc.pop("_id", None)
        return doc
