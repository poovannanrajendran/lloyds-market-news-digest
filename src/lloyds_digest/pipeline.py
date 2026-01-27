from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
import importlib
import os
from pathlib import Path
from typing import Callable, Iterable, Optional
from uuid import uuid4

from lloyds_digest.boilerplate import BoilerplateRules, load_rules, strip_boilerplate
from lloyds_digest.config import AppConfig
from lloyds_digest.discovery.csv_loader import load_sources_csv, upsert_sources
from lloyds_digest.extractors.bs4_heuristic import Bs4HeuristicExtractor
from lloyds_digest.extractors.crawl4ai import Crawl4AIExtractor
from lloyds_digest.extractors.engine import ExtractionEngine
from lloyds_digest.extractors.readability import ReadabilityExtractor
from lloyds_digest.extractors.trafilatura import TrafilaturaExtractor
from lloyds_digest.fetchers.http import FetchCache, HttpFetcher
from lloyds_digest.keywords import KeywordRules, compact_text, load_keywords
from lloyds_digest.models import Candidate, RunMetrics
from lloyds_digest.reporting.digest_renderer import DigestConfig, DigestItem, render_digest
from lloyds_digest.reporting.metrics import compute_run_summary, summarize_failures
from lloyds_digest.storage.mongo_repo import MongoConfigError, MongoRepo
from lloyds_digest.storage.postgres_repo import PostgresConfigError, PostgresRepo

classify_mod = importlib.import_module("lloyds_digest.ai.classify")
relevance_mod = importlib.import_module("lloyds_digest.ai.relevance")
summarise_mod = importlib.import_module("lloyds_digest.ai.summarise")


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    run_date: date
    total_sources: int
    total_candidates: int
    fetched: int
    extracted: int
    errors: int
    output_path: Optional[Path]
    digest_items: list[DigestItem]
    warnings: list[str]


def run_pipeline(
    run_date: date,
    config: AppConfig,
    sources_path: Path,
    output_dir_override: Optional[Path] = None,
    cache_override: Optional[bool] = None,
    max_candidates: Optional[int] = None,
    max_sources: Optional[int] = None,
    skip_seen: bool = True,
    log: Optional[Callable[[str], None]] = None,
    log_detail: Optional[Callable[[str], None]] = None,
) -> PipelineResult:
    logger = log or (lambda message: None)
    detail = log_detail or (lambda message: None)
    warnings: list[str] = []

    run_id = uuid4().hex
    started_at = _utc_now()

    postgres = _try_postgres(logger, warnings)
    mongo = _try_mongo(logger, warnings)
    boilerplate_rules = load_rules(Path("boilerplate.yaml"))
    if boilerplate_rules.rules:
        logger(f"Loaded boilerplate rules: {len(boilerplate_rules.rules)} templates")
    keyword_rules = load_keywords(Path(os.environ.get("LLOYDS_DIGEST_KEYWORDS_FILE", "relevant_keywords.yaml")))
    if keyword_rules.terms:
        logger(f"Loaded relevance keywords: {len(keyword_rules.terms)} terms")

    try:
        sources = load_sources_csv(sources_path)
    except Exception as exc:
        raise RuntimeError(f"Failed to load sources CSV: {exc}") from exc
    if max_sources is not None and max_sources > 0:
        if len(sources) > max_sources:
            warnings.append(f"Limiting sources to {max_sources} of {len(sources)} loaded.")
            sources = sources[:max_sources]

    if postgres is not None:
        try:
            upsert_sources(postgres, sources)
        except Exception as exc:
            warnings.append(f"Postgres upsert_sources failed; continuing without DB. ({exc})")
            postgres = None

    metrics = RunMetrics(
        run_id=run_id,
        run_date=run_date,
        started_at=started_at,
        total_sources=len(sources),
    )

    candidates = _discover_candidates(sources, postgres, mongo, run_id, detail, warnings)
    if max_candidates is not None and max_candidates > 0:
        if len(candidates) > max_candidates:
            warnings.append(
                f"Limiting candidates to {max_candidates} of {len(candidates)} discovered."
            )
            candidates = candidates[:max_candidates]
    candidates = _filter_recent_candidates(
        candidates,
        run_date,
        days=config.filters.max_age_days,
        log=detail,
    )
    metrics.total_candidates = len(candidates)

    fetcher = HttpFetcher()
    cache_enabled = cache_override if cache_override is not None else config.cache.enabled
    cache_backend = None
    if cache_enabled and mongo is not None:
        cache_backend = FetchCache(mongo)
    elif cache_enabled and mongo is None:
        warnings.append("Cache enabled but Mongo is unavailable; continuing without cache.")

    extraction_engine = ExtractionEngine(
        extractors=[
            TrafilaturaExtractor(),
            ReadabilityExtractor(),
            Bs4HeuristicExtractor(),
            Crawl4AIExtractor(),
        ]
    )

    digest_items: list[DigestItem] = []
    fetch_results = []
    total_candidates = len(candidates)
    for idx, candidate in enumerate(candidates, start=1):
        if skip_seen:
            if postgres is not None and postgres.has_article(candidate.candidate_id):
                detail(f"[{idx}/{total_candidates}] Skip existing article {candidate.url}")
                continue
            if postgres is None and mongo is not None:
                if mongo.get_winner(candidate.candidate_id):
                    detail(f"[{idx}/{total_candidates}] Skip existing article {candidate.url}")
                    continue
        detail(f"[{idx}/{total_candidates}] Fetching {candidate.url}")
        result = fetcher.fetch(candidate.url, cache_backend)
        fetch_results.append(result)
        if result.error or not result.content:
            metrics.errors += 1
            detail(f"[{idx}/{total_candidates}] Fetch failed {candidate.url}")
            continue
        # PDFs aren't supported yet; skip now and revisit with a PDF extractor (pypdf/pdfplumber)
        # when we decide how to handle binary documents in the digest.
        if _looks_like_pdf(result.url, result.content):
            metrics.errors += 1
            warnings.append(f"Skipped PDF content: {candidate.url}")
            detail(f"[{idx}/{total_candidates}] Skipped PDF {candidate.url}")
            continue
        metrics.fetched += 1
        html = result.content.decode("utf-8", errors="ignore") if isinstance(result.content, bytes) else result.content
        detail(f"[{idx}/{total_candidates}] Extracting {candidate.url}")
        article = extraction_engine.run(candidate, html, postgres=postgres, mongo=mongo)
        if article is None:
            detail(f"[{idx}/{total_candidates}] No extractable content {candidate.url}")
            continue
        metrics.extracted += 1
        digest_items.extend(
            _article_to_items(
                candidate,
                article,
                run_id=run_id,
                postgres=postgres,
                mongo=mongo,
                warnings=warnings,
                log=detail,
                boilerplate_rules=boilerplate_rules,
                keyword_rules=keyword_rules,
            )
        )

    metrics.ended_at = _utc_now()

    if postgres is not None:
        try:
            postgres.create_run(metrics)
        except Exception as exc:
            warnings.append(f"Postgres create_run failed. ({exc})")

    output_path: Optional[Path] = None
    if config.output.enabled:
        output_dir = output_dir_override or config.output.directory
        try:
            output_path = render_digest(
                digest_items,
                run_date=run_date,
                output_dir=output_dir,
                config=DigestConfig(),
                postgres=postgres,
            )
        except Exception as exc:
            warnings.append(f"Failed to render digest. ({exc})")

    if fetch_results:
        failures = summarize_failures(fetch_results)
        if failures:
            for reason, count in failures.items():
                warnings.append(f"{count} fetch failures: {reason}")

    summary = compute_run_summary(metrics)
    logger(
        "Run summary: "
        f"candidates={summary.total_candidates}, fetched={summary.fetched}, "
        f"extracted={summary.extracted}, errors={summary.errors}"
    )

    return PipelineResult(
        run_id=run_id,
        run_date=run_date,
        total_sources=metrics.total_sources,
        total_candidates=metrics.total_candidates,
        fetched=metrics.fetched,
        extracted=metrics.extracted,
        errors=metrics.errors,
        output_path=output_path,
        digest_items=digest_items,
        warnings=warnings,
    )


def _discover_candidates(
    sources: Iterable,
    postgres: Optional[PostgresRepo],
    mongo: Optional[MongoRepo],
    run_id: str,
    logger: Callable[[str], None],
    warnings: list[str],
) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[str] = set()

    rss_discoverer = _load_rss_discoverer(warnings)
    if rss_discoverer is not None:
        try:
            candidates.extend(
                rss_discoverer.discover(
                    sources,
                    postgres=postgres,
                    mongo=mongo,
                    run_id=run_id,
                    seen=seen,
                    log=logger,
                )
            )
        except Exception as exc:
            warnings.append(f"RSS discovery failed: {exc}")

    listing_discoverer = _load_listing_discoverer(warnings)
    if listing_discoverer is not None:
        try:
            candidates.extend(
                listing_discoverer.discover(
                    sources,
                    postgres=postgres,
                    mongo=mongo,
                    run_id=run_id,
                    seen=seen,
                    log=logger,
                )
            )
        except Exception as exc:
            warnings.append(f"Listing discovery failed: {exc}")

    logger(f"Discovered {len(candidates)} candidates")
    return candidates


def _filter_recent_candidates(
    candidates: list[Candidate],
    run_date: date,
    days: int,
    log: Callable[[str], None],
) -> list[Candidate]:
    cutoff = datetime.combine(run_date, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=days)
    filtered: list[Candidate] = []
    for candidate in candidates:
        published_at = candidate.published_at
        if published_at is None:
            filtered.append(candidate)
            continue
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        if published_at >= cutoff:
            filtered.append(candidate)
        else:
            log(f"[gate] skip old article ({published_at.date().isoformat()}): {candidate.url}")
    return filtered


def _load_rss_discoverer(warnings: list[str]):
    try:
        from lloyds_digest.discovery.rss import RSSDiscoverer
    except Exception as exc:  # pragma: no cover - dependency guard
        warnings.append(f"RSS discovery disabled: {exc}")
        return None
    return RSSDiscoverer()


def _load_listing_discoverer(warnings: list[str]):
    try:
        from lloyds_digest.discovery.listing import ListingDiscoverer
    except Exception as exc:  # pragma: no cover - dependency guard
        warnings.append(f"Listing discovery disabled: {exc}")
        return None
    return ListingDiscoverer()


def _article_to_items(
    candidate: Candidate,
    article,
    run_id: str,
    postgres: Optional[PostgresRepo],
    mongo: Optional[MongoRepo],
    warnings: list[str],
    log: Callable[[str], None],
    boilerplate_rules: BoilerplateRules,
    keyword_rules: KeywordRules,
) -> list[DigestItem]:
    topics = candidate.metadata.get("topics") if candidate.metadata else None
    topic = ", ".join(topics) if isinstance(topics, list) and topics else "General"
    source_type = candidate.metadata.get("source_type") if candidate.metadata else None
    score = None
    if isinstance(article.metadata, dict):
        score = article.metadata.get("score")

    raw_text = article.body_text or ""
    blocks = boilerplate_rules.for_url(candidate.url)
    if blocks:
        cleaned = strip_boilerplate(raw_text, blocks)
        if cleaned != raw_text:
            log(f"[clean] stripped boilerplate for {candidate.url}")
        raw_text = cleaned

    summary = None
    why_it_matters = None
    if keyword_rules.terms:
        gate_text = compact_text(article.title or candidate.title, raw_text)
        min_score = float(os.environ.get("LLOYDS_DIGEST_KEYWORDS_MIN_SCORE", "2.5"))
        score_hint, matches = keyword_rules.score(gate_text.lower())
        if score_hint < min_score:
            log(f"[gate] keyword score {score_hint:.2f} below {min_score:.2f}: {candidate.url}")
            _record_rejection(
                mongo=mongo,
                candidate=candidate,
                run_id=run_id,
                stage="keyword",
                reason=f"score {score_hint:.2f} below {min_score:.2f}",
                score=score_hint,
                matches=matches,
                text=raw_text,
            )
            return []
        log(f"[gate] keyword score {score_hint:.2f} matched {len(matches)} terms")
    if _llm_enabled():
        text = _trim_text(raw_text)
        log(f"[llm] relevance {candidate.url}")
        relevance_model = _llm_model("LLOYDS_DIGEST_LLM_RELEVANCE_MODEL", "qwen3:14b")
        classify_model = _llm_model("LLOYDS_DIGEST_LLM_CLASSIFY_MODEL", "qwen2.5-coder")
        summarise_model = _llm_model("LLOYDS_DIGEST_LLM_SUMMARISE_MODEL", "qwen2.5-coder")
        relevance_result = _run_llm_stage(
            stage="relevance",
            model=relevance_model,
            prompt_version=relevance_mod.PROMPT.version,
            call_fn=lambda: relevance_mod.relevance(text, model=relevance_model, mongo=mongo),
            postgres=postgres,
            run_id=run_id,
            candidate_id=candidate.candidate_id,
            warnings=warnings,
        )
        if relevance_result:
            parsed = relevance_result.get("parsed") or {}
            why_it_matters = parsed.get("reason")
            confidence = parsed.get("confidence")
            relevant_flag = parsed.get("relevant")
            if relevant_flag is False:
                log(f"[gate] LLM marked not relevant: {candidate.url}")
                _record_rejection(
                    mongo=mongo,
                    candidate=candidate,
                    run_id=run_id,
                    stage="llm_relevance",
                    reason="llm marked not relevant",
                    score=score,
                    matches=None,
                    text=raw_text,
                    llm_response=relevance_result.get("parsed"),
                )
                return []
            if isinstance(confidence, (int, float)):
                score = float(confidence)

        log(f"[llm] classify {candidate.url}")
        classify_result = _run_llm_stage(
            stage="classify",
            model=classify_model,
            prompt_version=classify_mod.PROMPT.version,
            call_fn=lambda: classify_mod.classify(
                text,
                model=classify_model,
                mongo=mongo,
            ),
            postgres=postgres,
            run_id=run_id,
            candidate_id=candidate.candidate_id,
            warnings=warnings,
        )
        if classify_result:
            parsed = classify_result.get("parsed") or {}
            label = parsed.get("label")
            if isinstance(label, str) and label.strip():
                topic = label.strip()

        log(f"[llm] summarise {candidate.url}")
        summarise_result = _run_llm_stage(
            stage="summarise",
            model=summarise_model,
            prompt_version=summarise_mod.PROMPT.version,
            call_fn=lambda: summarise_mod.summarise(
                text,
                model=summarise_model,
                mongo=mongo,
            ),
            postgres=postgres,
            run_id=run_id,
            candidate_id=candidate.candidate_id,
            warnings=warnings,
        )
        if summarise_result:
            parsed = summarise_result.get("parsed") or {}
            bullets = parsed.get("bullets")
            if isinstance(bullets, list) and bullets:
                summary = [str(item).strip() for item in bullets if str(item).strip()]

    if summary is None:
        summary = _summarize_text(raw_text)
    title = article.title or candidate.title or article.url

    return [
        DigestItem(
            title=title,
            url=article.url,
            summary=summary,
            score=score,
            source_type=source_type or "unknown",
            topic=topic,
            why_it_matters=why_it_matters,
        )
    ]


def _summarize_text(text: str, max_sentences: int = 3) -> Optional[list[str]]:
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    sentences = _split_sentences(cleaned)
    bullets = [sentence.strip() for sentence in sentences if sentence.strip()]
    if not bullets:
        return None
    return bullets[:max_sentences]


def _split_sentences(text: str) -> list[str]:
    separators = {".", "!", "?"}
    current: list[str] = []
    sentences: list[str] = []
    for char in text:
        current.append(char)
        if char in separators:
            sentence = "".join(current).strip()
            if sentence:
                sentences.append(sentence)
            current = []
    if current:
        sentence = "".join(current).strip()
        if sentence:
            sentences.append(sentence)
    return sentences


def _run_llm_stage(
    stage: str,
    model: str,
    prompt_version: str,
    call_fn,
    postgres: Optional[PostgresRepo],
    run_id: str,
    candidate_id: str,
    warnings: list[str],
) -> Optional[dict]:
    started_at = _utc_now()
    try:
        result = call_fn()
    except Exception as exc:
        warnings.append(f"LLM {stage} failed: {exc}")
        return None
    ended_at = _utc_now()
    latency_ms = int((ended_at - started_at).total_seconds() * 1000)

    if postgres is not None:
        try:
            postgres.insert_llm_usage(
                run_id=run_id,
                candidate_id=candidate_id,
                stage=stage,
                model=model,
                prompt_version=prompt_version,
                cached=bool(result.get("cached")),
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=latency_ms,
                tokens_prompt=None,
                tokens_completion=None,
                metadata={"parsed": result.get("parsed")},
            )
        except Exception as exc:
            warnings.append(f"Failed to record llm_usage for {stage}: {exc}")

    return result


def _llm_enabled() -> bool:
    mode = os.environ.get("LLOYDS_DIGEST_LLM_MODE", "on").strip().lower()
    return mode not in {"off", "false", "0", "no"}


def _llm_model(env_key: str, default: str) -> str:
    return os.environ.get(env_key, default)


def _trim_text(text: str, max_chars: int = 6000) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars]


def _record_rejection(
    mongo: Optional[MongoRepo],
    candidate: Candidate,
    run_id: str,
    stage: str,
    reason: str,
    score: float | None,
    matches: list[str] | None,
    text: str,
    llm_response: dict | None = None,
) -> None:
    if mongo is None:
        return
    payload = {
        "candidate_id": candidate.candidate_id,
        "source_id": candidate.source_id,
        "url": candidate.url,
        "title": candidate.title,
        "published_at": candidate.published_at,
        "metadata": candidate.metadata,
        "run_id": run_id,
        "stage": stage,
        "reason": reason,
        "score": score,
        "matches": matches,
        "text": text,
        "llm_response": llm_response,
    }
    try:
        mongo.insert_rejection(payload)
    except Exception:
        return


def _looks_like_pdf(url: str, content: str | bytes) -> bool:
    # Lightweight detection only; prefer a real PDF extraction path in a future phase.
    if url.lower().endswith(".pdf"):
        return True
    if isinstance(content, bytes):
        snippet = content.lstrip()[:1024]
        return snippet.startswith(b"%PDF")
    snippet = content.lstrip()[:1024]
    return snippet.startswith("%PDF")


def _try_postgres(logger: Callable[[str], None], warnings: list[str]) -> Optional[PostgresRepo]:
    try:
        repo = PostgresRepo.from_env()
    except PostgresConfigError:
        return None
    try:
        repo.ping()
        logger("Postgres connected")
        return repo
    except Exception as exc:
        warnings.append(f"Postgres unavailable: {exc}")
        return None


def _try_mongo(logger: Callable[[str], None], warnings: list[str]) -> Optional[MongoRepo]:
    try:
        repo = MongoRepo.from_env()
    except MongoConfigError:
        return None
    try:
        repo.ping()
        logger("Mongo connected")
        return repo
    except Exception as exc:
        warnings.append(f"Mongo unavailable: {exc}")
        return None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
