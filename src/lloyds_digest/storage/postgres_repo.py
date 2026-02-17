from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping

from lloyds_digest.models import ArticleRecord, Candidate, RunMetrics, Source
from lloyds_digest.scoring.method_prefs import MethodPrefs, MethodStats, select_method_prefs


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

    def get_latest_run_id(self) -> str | None:
        sql = "SELECT run_id FROM runs ORDER BY started_at DESC LIMIT 1"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
                if not row:
                    return None
                return row[0]

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
        metrics_json = json.dumps(metrics_payload)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        run.run_id,
                        run.run_date,
                        run.started_at,
                        run.ended_at,
                        metrics_json,
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
        metadata_json = json.dumps(candidate.metadata)
        url = _sanitize_text(candidate.url)
        title = _sanitize_text(candidate.title)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        candidate.candidate_id,
                        candidate.source_id,
                        url,
                        title,
                        candidate.published_at,
                        candidate.discovered_at,
                        metadata_json,
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
        metadata_json = json.dumps(dict(metadata or {}))
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
                        metadata_json,
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
        metadata_json = json.dumps(article.metadata)
        url = _sanitize_text(article.url)
        title = _sanitize_text(article.title)
        body_text = _sanitize_text(article.body_text)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        article.article_id,
                        article.source_id,
                        url,
                        title,
                        article.published_at,
                        body_text,
                        article.created_at,
                        article.extraction_method,
                        metadata_json,
                    ),
                )
                conn.commit()

    def has_article(self, article_id: str) -> bool:
        sql = "SELECT 1 FROM articles WHERE article_id = %s"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (article_id,))
                return cur.fetchone() is not None

    def record_method_attempt(
        self,
        domain: str,
        method: str,
        success: bool,
        duration_ms: int | None,
    ) -> None:
        sql = """
            INSERT INTO domain_method_stats (
                domain, method, attempts, successes, last_attempt_at, last_success_at,
                duration_history, median_duration_ms, updated_at
            )
            VALUES (%s, %s, 1, %s, NOW(), %s, %s, %s, NOW())
            ON CONFLICT (domain, method) DO UPDATE SET
                attempts = domain_method_stats.attempts + 1,
                successes = domain_method_stats.successes + EXCLUDED.successes,
                last_attempt_at = NOW(),
                last_success_at = COALESCE(EXCLUDED.last_success_at, domain_method_stats.last_success_at),
                duration_history = EXCLUDED.duration_history,
                median_duration_ms = EXCLUDED.median_duration_ms,
                updated_at = NOW()
        """
        history = [duration_ms] if duration_ms is not None else []
        median_value = duration_ms if duration_ms is not None else None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT duration_history FROM domain_method_stats WHERE domain = %s AND method = %s",
                    (domain, method),
                )
                row = cur.fetchone()
                if row and row[0]:
                    history = list(row[0])
                    if duration_ms is not None:
                        history.append(duration_ms)
                if history:
                    history = history[-25:]
                    median_value = _median(history)
                cur.execute(
                    sql,
                    (
                        domain,
                        method,
                        1 if success else 0,
                        _utc_now() if success else None,
                        json.dumps(history),
                        median_value,
                    ),
                )
                conn.commit()

    def get_method_stats(self, domain: str) -> list[MethodStats]:
        sql = """
            SELECT method, attempts, successes, median_duration_ms, last_success_at, last_attempt_at
            FROM domain_method_stats
            WHERE domain = %s
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (domain,))
                rows = cur.fetchall()
        return [
            MethodStats(
                method=row[0],
                attempts=row[1],
                successes=row[2],
                median_duration_ms=row[3],
                last_success_at=row[4],
                last_attempt_at=row[5],
            )
            for row in rows
        ]

    def get_domain_prefs(self, domain: str) -> MethodPrefs | None:
        sql = """
            SELECT primary_method, fallback_methods, confidence, last_changed_at,
                   locked_until, drift_flag, drift_notes
            FROM domain_method_prefs
            WHERE domain = %s
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (domain,))
                row = cur.fetchone()
        if not row:
            return None
        return MethodPrefs(
            domain=domain,
            primary_method=row[0],
            fallback_methods=list(row[1] or []),
            confidence=float(row[2] or 0.0),
            last_changed_at=row[3],
            locked_until=row[4],
            drift_flag=bool(row[5]),
            drift_notes=row[6],
        )

    def upsert_domain_prefs(self, prefs: MethodPrefs) -> None:
        sql = """
            INSERT INTO domain_method_prefs (
                domain, primary_method, fallback_methods, confidence,
                last_changed_at, locked_until, drift_flag, drift_notes, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (domain) DO UPDATE SET
                primary_method = EXCLUDED.primary_method,
                fallback_methods = EXCLUDED.fallback_methods,
                confidence = EXCLUDED.confidence,
                last_changed_at = EXCLUDED.last_changed_at,
                locked_until = EXCLUDED.locked_until,
                drift_flag = EXCLUDED.drift_flag,
                drift_notes = EXCLUDED.drift_notes,
                updated_at = NOW()
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        prefs.domain,
                        prefs.primary_method,
                        prefs.fallback_methods,
                        prefs.confidence,
                        prefs.last_changed_at,
                        prefs.locked_until,
                        prefs.drift_flag,
                        prefs.drift_notes,
                    ),
                )
                conn.commit()

    def update_domain_prefs(self, domain: str) -> MethodPrefs | None:
        stats = self.get_method_stats(domain)
        if not stats:
            return None
        current = self.get_domain_prefs(domain)
        prefs = select_method_prefs(domain, stats, current, _utc_now())
        if prefs is None:
            return None
        self.upsert_domain_prefs(prefs)
        return prefs

    def insert_llm_usage(
        self,
        run_id: str | None,
        candidate_id: str | None,
        stage: str,
        model: str,
        prompt_version: str,
        cached: bool,
        started_at: datetime,
        ended_at: datetime | None,
        latency_ms: int | None,
        tokens_prompt: int | None = None,
        tokens_completion: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        sql = """
            INSERT INTO llm_usage (
                run_id, candidate_id, stage, model, prompt_version, cached,
                started_at, ended_at, latency_ms, tokens_prompt, tokens_completion, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        metadata_json = json.dumps(dict(metadata or {}))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        run_id,
                        candidate_id,
                        stage,
                        model,
                        prompt_version,
                        cached,
                        started_at,
                        ended_at,
                        latency_ms,
                        tokens_prompt,
                        tokens_completion,
                        metadata_json,
                    ),
                )
            conn.commit()

    def insert_llm_cost_call(
        self,
        run_id: str | None,
        candidate_id: str | None,
        stage: str,
        provider: str,
        model: str,
        service_tier: str | None,
        tokens_prompt: int,
        tokens_completion: int,
        cost_input_usd: float,
        cost_output_usd: float,
        cost_total_usd: float,
        metadata: dict | None = None,
    ) -> None:
        sql = """
            INSERT INTO llm_cost_calls (
                run_id, candidate_id, stage, provider, model, service_tier,
                tokens_prompt, tokens_completion, cost_input_usd, cost_output_usd, cost_total_usd, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        metadata_json = json.dumps(metadata or {})
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        run_id,
                        candidate_id,
                        stage,
                        provider,
                        model,
                        service_tier,
                        tokens_prompt,
                        tokens_completion,
                        cost_input_usd,
                        cost_output_usd,
                        cost_total_usd,
                        metadata_json,
                    ),
                )
            conn.commit()

    def upsert_llm_cost_stage_daily(
        self,
        usage_date: str,
        stage: str,
        provider: str,
        model: str,
        service_tier: str | None,
        calls: int,
        tokens_prompt: int,
        tokens_completion: int,
        cost_total_usd: float,
    ) -> None:
        sql = """
            INSERT INTO llm_cost_stage_daily (
                usage_date, stage, provider, model, service_tier,
                calls, tokens_prompt, tokens_completion, cost_total_usd
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (usage_date, stage, provider, model, service_tier)
            DO UPDATE SET
                calls = llm_cost_stage_daily.calls + EXCLUDED.calls,
                tokens_prompt = llm_cost_stage_daily.tokens_prompt + EXCLUDED.tokens_prompt,
                tokens_completion = llm_cost_stage_daily.tokens_completion + EXCLUDED.tokens_completion,
                cost_total_usd = llm_cost_stage_daily.cost_total_usd + EXCLUDED.cost_total_usd
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        usage_date,
                        stage,
                        provider,
                        model,
                        service_tier,
                        calls,
                        tokens_prompt,
                        tokens_completion,
                        cost_total_usd,
                    ),
                )
            conn.commit()

    def insert_run_phase_timing(
        self,
        run_id: str,
        phase: str,
        duration_ms: int,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> None:
        sql = """
            INSERT INTO run_phase_timings (
                run_id, phase, started_at, ended_at, duration_ms, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        metadata_json = json.dumps(metadata or {})
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        run_id,
                        phase,
                        started_at,
                        ended_at,
                        duration_ms,
                        metadata_json,
                    ),
                )
            conn.commit()
    def insert_digest(
        self,
        run_date: date,
        output_path: str,
        item_count: int,
        status: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        sql = """
            INSERT INTO digests (run_date, output_path, item_count, status, metadata)
            VALUES (%s, %s, %s, %s, %s)
        """
        metadata_json = json.dumps(dict(metadata or {}))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (run_date, output_path, item_count, status, metadata_json),
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


def _median(values: list[int]) -> int:
    sorted_values = sorted(values)
    mid = len(sorted_values) // 2
    if len(sorted_values) % 2 == 1:
        return sorted_values[mid]
    return int((sorted_values[mid - 1] + sorted_values[mid]) / 2)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sanitize_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.replace("\x00", "")
