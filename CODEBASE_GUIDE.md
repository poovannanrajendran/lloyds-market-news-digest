# Codebase Guide — Lloyd’s Market News Digest

## End-to-end pipeline (current wiring)
1) **Ingest sources** from `sources.csv` (root). Each row defines `source_type`, `domain`, `url`, `topics`, `page_type`.
2) **Discovery**
   - RSS/Atom feeds: parse entries into `Candidate` records.
   - Listing pages: fetch HTML, extract links, canonicalize, and emit candidates.
   - De-duplication is done by canonical URL hash (candidate_id).
3) **Fetch** candidate URLs over HTTP with retries/backoff and optional cache.
4) **Extract** content with a multi-method chain (trafilatura → readability → bs4 heuristic → crawl4ai stub). Each attempt is audited.
5) **AI processing** (local-first Ollama): relevance / classify / summarise with Mongo cache and Postgres usage tracking.
6) **Digest** renders HTML by source_type then topic; optional SMTP delivery.
7) **Observability**: JSONL logging + run metrics + Method Health section in digest.

> Note: There is no single orchestrator yet. The verification runs used scripted steps to drive discovery → fetch → extract. The CLI is a skeleton in Phase 01.

## Module responsibilities

### Core
- `src/lloyds_digest/models.py`
  - Data models: Source, Candidate, FetchResult, ExtractionResult, ArticleRecord, RunMetrics.
- `src/lloyds_digest/config.py`
  - Loads `config.yaml` + env overrides (`LLOYDS_DIGEST__`).
- `src/lloyds_digest/registry.py`
  - Component registries for fetchers/extractors/ai/sinks.

### Discovery
- `src/lloyds_digest/discovery/csv_loader.py`
  - Parses `sources.csv` and validates enums. Adds `regulatory` source_type support.
- `src/lloyds_digest/discovery/rss.py`
  - RSS/Atom parsing via feedparser. Emits candidates, snapshots to Mongo.
- `src/lloyds_digest/discovery/listing.py`
  - Listing HTML fetch + link extraction + same-domain filtering + candidate emission.
- `src/lloyds_digest/discovery/url_utils.py`
  - Canonicalization + candidate_id hash.

### Fetching
- `src/lloyds_digest/fetchers/http.py`
  - HTTP fetcher with retries and Mongo cache. Cache key uses canonical URL + fetcher name.

### Extraction
- `src/lloyds_digest/extractors/engine.py`
  - Orchestrates extractors; logs attempts to Postgres + Mongo; selects winner.
  - Orders extractors by domain preferences when available.
- `src/lloyds_digest/extractors/trafilatura.py`, `readability.py`, `bs4_heuristic.py`, `crawl4ai.py`
  - Extractor implementations (crawl4ai is a stub adapter).

### Scoring / Method Learning
- `src/lloyds_digest/scoring/heuristics.py`
  - Accept/too-short thresholds.
- `src/lloyds_digest/scoring/method_prefs.py`
  - Computes primary + fallback methods from stats, cooldown rules, drift flag.

### AI
- `src/lloyds_digest/ai/base.py`
  - Ollama client + prompt loader + cache key + cached call wrapper.
- `src/lloyds_digest/ai/relevance.py`, `classify.py`, `summarise.py`
  - AI stages with prompt files in `src/lloyds_digest/ai/prompts/`.

### Reporting / Observability
- `src/lloyds_digest/reporting/digest_renderer.py`
  - HTML digest renderer + Method Health section.
- `src/lloyds_digest/reporting/email_sender.py`
  - Optional SMTP delivery.
- `src/lloyds_digest/reporting/metrics.py`
  - Run summary metrics.
- `src/lloyds_digest/reporting/logging.py`
  - JSONL log emitter.
- `src/lloyds_digest/reporting/method_health.py`
  - Builds Method Health list from stats.

### Storage
- `src/lloyds_digest/storage/postgres_repo.py`
  - Processed/relational persistence (sources, candidates, attempts, articles, method prefs/stats, digests, llm usage).
- `src/lloyds_digest/storage/mongo_repo.py`
  - Raw/unstructured persistence (discovery snapshots, fetch cache, raw attempts, winners, ai cache).
- `migrations/*.sql`
  - Postgres schema (run all in order).

## Config-driven behavior
- `config.yaml` provides defaults for cache/output dirs and topics.
- Env overrides use `LLOYDS_DIGEST__` prefix (double-underscore for nesting).
- DB and infra configuration is in `.env` (Postgres + Mongo + SMTP + Ollama).

## Storage split (raw vs processed)
- **Mongo (raw/unstructured)**
  - `discovery_snapshots`: RSS/listing raw discovery
  - `fetch_cache`: HTTP response cache (keyed by canonical URL + fetcher)
  - `attempts_raw`: raw extraction attempts
  - `winners`: winning extraction results
  - `ai_cache`: AI stage output cache

- **Postgres (processed/relational)**
  - `sources`, `candidates`, `attempts`, `articles`
  - `domain_method_stats`, `domain_method_prefs`
  - `llm_usage`, `digests`

## Method learning (prefs + stats)
- Each extraction attempt updates **domain_method_stats** with attempts, successes, duration history.
- `select_method_prefs()` computes primary + fallbacks with a cooldown to avoid flapping.
- Drift flag is set when primary success rate drops below threshold.
- Extractor chain is ordered using prefs (primary → fallbacks → remaining).

## How to add a new source
1) Add a row to `sources.csv` with `source_type`, `domain`, `url`, `topics`, `page_type`.
2) If it’s a new `source_type`, add it to `SOURCE_TYPES` in `csv_loader.py`.
3) Run discovery to see candidates; check snapshots in Mongo.

## How to add an extractor
1) Implement `extract(html) -> ExtractionResult` in `src/lloyds_digest/extractors/`.
2) Add it to the extractor chain in your orchestrator or test harness.
3) Ensure method name is stable (used for prefs/stats).

## How to add an AI provider
1) Add a client in `src/lloyds_digest/ai/` (similar to `OllamaClient`).
2) Add a new wrapper module (e.g., `ai/relevance_openai.py`).
3) Use cache keys that include provider + model + prompt version.

## How to add an output sink
1) Implement a renderer or sink in `src/lloyds_digest/reporting/` or new `sinks/` package.
2) Add it to a pipeline or CLI command.

## Debugging failures
- **Logs**: JSONL entries (if using `reporting.logging.log_event`).
- **Postgres**:
  - `attempts` shows extraction failures
  - `domain_method_stats` shows method performance
  - `llm_usage` tracks AI calls
- **Mongo**:
  - `attempts_raw` keeps full extraction output
  - `fetch_cache` shows cached HTML
  - `ai_cache` shows cached AI responses
- **Common issues**:
  - HTTP 301/403 → ensure redirects allowed, user-agent set
  - Postgres JSONB errors → ensure dicts are JSON serialized
  - Mongo cache conflicts → ensure `key` is not in `$set`
