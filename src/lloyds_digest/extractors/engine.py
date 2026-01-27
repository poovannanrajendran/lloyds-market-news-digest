from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from lloyds_digest.models import ArticleRecord, Candidate, ExtractionResult
from lloyds_digest.scoring.heuristics import evaluate_text
from lloyds_digest.scoring.method_prefs import MethodPrefs
from lloyds_digest.storage.mongo_repo import MongoRepo
from lloyds_digest.storage.postgres_repo import PostgresRepo


class Extractor(Protocol):
    name: str

    def extract(self, html: str) -> ExtractionResult:
        ...


@dataclass
class ExtractionEngine:
    extractors: list[Extractor]

    def run(
        self,
        candidate: Candidate,
        html: str,
        postgres: PostgresRepo | None = None,
        mongo: MongoRepo | None = None,
    ) -> ArticleRecord | None:
        domain = _extract_domain(candidate.source_id)
        extractors = (
            _order_extractors(self.extractors, postgres, domain)
            if postgres is not None and domain
            else self.extractors
        )
        for extractor in extractors:
            started_at = _utc_now()
            result = extractor.extract(html)
            cleaned_text = (result.text or "").replace("\x00", "")
            decision, score = evaluate_text(cleaned_text)
            ended_at = _utc_now()
            duration_ms = int((ended_at - started_at).total_seconds() * 1000)

            attempt_payload = {
                "candidate_id": candidate.candidate_id,
                "method": extractor.name,
                "decision": decision,
                "score": score,
                "success": result.success,
                "error": result.error,
            }
            if mongo is not None:
                mongo.insert_attempt_raw(
                    {
                        **attempt_payload,
                        "extracted_at": result.extracted_at,
                        "title": result.title,
                        "text": result.text,
                        "html": result.html,
                        "metadata": result.metadata,
                        "duration_ms": duration_ms,
                    }
                )
            if postgres is not None:
                postgres.insert_attempt(
                    candidate_id=candidate.candidate_id,
                    kind="extract",
                    method=extractor.name,
                    status=decision,
                    started_at=started_at,
                    ended_at=ended_at,
                    error=result.error,
                    metadata={"score": score, "duration_ms": duration_ms},
                )
                if domain:
                    postgres.record_method_attempt(
                        domain=domain,
                        method=extractor.name,
                        success=decision == "ACCEPT",
                        duration_ms=duration_ms,
                    )

            if decision != "ACCEPT":
                continue

            article = ArticleRecord(
                article_id=candidate.candidate_id,
                source_id=candidate.source_id,
                url=candidate.url,
                title=result.title or candidate.title,
                published_at=candidate.published_at,
                body_text=cleaned_text,
                extraction_method=extractor.name,
                metadata={"score": score},
            )
            if postgres is not None:
                postgres.upsert_article(article)
            if mongo is not None:
                mongo.upsert_winner(
                    candidate.candidate_id,
                    {
                        "candidate_id": candidate.candidate_id,
                        "source_id": candidate.source_id,
                        "url": candidate.url,
                        "method": extractor.name,
                        "title": article.title,
                        "text": article.body_text,
                        "score": score,
                    },
                )
            if postgres is not None and domain:
                postgres.update_domain_prefs(domain)
            return article

        if postgres is not None and domain:
            postgres.update_domain_prefs(domain)
        return None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _extract_domain(source_id: str) -> str | None:
    if ":" not in source_id:
        return None
    return source_id.split(":", 1)[1]


def _order_extractors(
    extractors: list[Extractor],
    postgres: PostgresRepo,
    domain: str,
) -> list[Extractor]:
    prefs = postgres.get_domain_prefs(domain)
    if prefs is None:
        return extractors

    by_name = {extractor.name: extractor for extractor in extractors}
    ordered: list[Extractor] = []
    if prefs.primary_method in by_name:
        ordered.append(by_name[prefs.primary_method])
    for name in prefs.fallback_methods:
        if name in by_name and by_name[name] not in ordered:
            ordered.append(by_name[name])
    for extractor in extractors:
        if extractor not in ordered:
            ordered.append(extractor)
    return ordered
