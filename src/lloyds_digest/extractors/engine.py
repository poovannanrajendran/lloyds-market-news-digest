from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from lloyds_digest.models import ArticleRecord, Candidate, ExtractionResult
from lloyds_digest.scoring.heuristics import evaluate_text
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
        for extractor in self.extractors:
            started_at = _utc_now()
            result = extractor.extract(html)
            decision, score = evaluate_text(result.text or "")
            ended_at = _utc_now()

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
                    metadata={"score": score},
                )

            if decision != "ACCEPT":
                continue

            article = ArticleRecord(
                article_id=candidate.candidate_id,
                source_id=candidate.source_id,
                url=candidate.url,
                title=result.title or candidate.title,
                published_at=candidate.published_at,
                body_text=result.text,
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
            return article

        return None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
