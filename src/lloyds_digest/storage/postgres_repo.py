from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from lloyds_digest.models import ArticleRecord, Candidate, RunMetrics, Source


class PostgresConfigError(RuntimeError):
    pass


@dataclass
class PostgresRepo:
    dsn: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "PostgresRepo":
        return cls(dsn=build_postgres_dsn(env or os.environ))

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("psycopg is required for PostgresRepo") from exc
        return psycopg.connect(self.dsn)

    def ping(self) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return cur.fetchone() == (1,)

    def upsert_source(self, source: Source) -> None:
        sql = """
            INSERT INTO sources (source_id, name, kind, url, enabled, tags, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (source_id) DO UPDATE SET
                name = EXCLUDED.name,
                kind = EXCLUDED.kind,
                url = EXCLUDED.url,
                enabled = EXCLUDED.enabled,
                tags = EXCLUDED.tags,
                updated_at = NOW()
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        source.source_id,
                        source.name,
                        source.kind,
                        source.url,
                        source.enabled,
                        source.tags,
                    ),
                )
                conn.commit()

    def create_run(self, run: RunMetrics) -> None:
        sql = """
            INSERT INTO runs (run_id, run_date, started_at, ended_at, metrics)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (run_id) DO UPDATE SET
                run_date = EXCLUDED.run_date,
                started_at = EXCLUDED.started_at,
                ended_at = EXCLUDED.ended_at,
                metrics = EXCLUDED.metrics
        """
        metrics_payload = {
            "total_sources": run.total_sources,
            "total_candidates": run.total_candidates,
            "fetched": run.fetched,
            "extracted": run.extracted,
            "errors": run.errors,
            "notes": run.notes,
        }
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        run.run_id,
                        run.run_date,
                        run.started_at,
                        run.ended_at,
                        metrics_payload,
                    ),
                )
                conn.commit()

    def insert_candidate(self, candidate: Candidate) -> None:
        sql = """
            INSERT INTO candidates (
                candidate_id, source_id, url, title, published_at, discovered_at, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (candidate_id) DO UPDATE SET
                title = EXCLUDED.title,
                published_at = EXCLUDED.published_at,
                metadata = EXCLUDED.metadata
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        candidate.candidate_id,
                        candidate.source_id,
                        candidate.url,
                        candidate.title,
                        candidate.published_at,
                        candidate.discovered_at,
                        candidate.metadata,
                    ),
                )
                conn.commit()

    def insert_attempt(
        self,
        candidate_id: str,
        kind: str,
        method: str,
        status: str,
        started_at: datetime,
        ended_at: datetime | None,
        error: str | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        sql = """
            INSERT INTO attempts (
                candidate_id, kind, method, status, started_at, ended_at, error, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        candidate_id,
                        kind,
                        method,
                        status,
                        started_at,
                        ended_at,
                        error,
                        dict(metadata or {}),
                    ),
                )
                conn.commit()

    def upsert_article(self, article: ArticleRecord) -> None:
        sql = """
            INSERT INTO articles (
                article_id, source_id, url, title, published_at, body_text, created_at,
                extraction_method, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (article_id) DO UPDATE SET
                title = EXCLUDED.title,
                published_at = EXCLUDED.published_at,
                body_text = EXCLUDED.body_text,
                extraction_method = EXCLUDED.extraction_method,
                metadata = EXCLUDED.metadata
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        article.article_id,
                        article.source_id,
                        article.url,
                        article.title,
                        article.published_at,
                        article.body_text,
                        article.created_at,
                        article.extraction_method,
                        article.metadata,
                    ),
                )
                conn.commit()


def build_postgres_dsn(env: Mapping[str, str]) -> str:
    host = env.get("POSTGRES_HOST")
    port = env.get("POSTGRES_PORT")
    database = env.get("POSTGRES_DB")
    user = env.get("POSTGRES_USER")
    password = env.get("POSTGRES_PASSWORD")

    missing = [
        name
        for name, value in (
            ("POSTGRES_HOST", host),
            ("POSTGRES_PORT", port),
            ("POSTGRES_DB", database),
            ("POSTGRES_USER", user),
            ("POSTGRES_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        raise PostgresConfigError(
            "Missing Postgres env vars: " + ", ".join(missing)
        )

    return (
        f"host={host} port={port} dbname={database} user={user} password={password}"
    )
