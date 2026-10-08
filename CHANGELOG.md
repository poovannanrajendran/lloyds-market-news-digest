# Changelog

## v1.1.0 — 2026-10-08

- GPT-6 Luna replaces Mini for summaries, digest composition and LinkedIn text; GPT-5 Nano remains for relevance/classification.
- Shared request settings, no reasoning for Luna, completion cap, JSON object mode, and empty/truncated-output rejection.
- Source-grounded summary prompt v2 and digest/LinkedIn instructions.
- API-supported ordinary-tier fallback, returned-tier costing, cache-write accounting and no new spend for application cache hits.
- Independent organisation Costs API monitor alerts at estimated credit ≤ $1 through existing Slack/Discord channels.
- 63 tests passed, one disabled live test skipped; small live comparisons completed without publishing.
- Historical fixed-token simulation suggests 67.3% lower cost; a speed improvement is not established.
- Refreshed project, deployment and operator documentation.
- [Detailed release notes](docs/releases/v1.1.0.md).

## Earlier development notes (historical)
- Render-only digest generator with chunked prompts and progressive HTML output.
- Added DeepSeek (Ollama) provider alongside local and ChatGPT for digest rendering.
- Executive summary re-write with stricter length controls.
- Chunk retries for empty model output; raw response capture for debugging.
- Boilerplate stripping rules, keyword gating, and recency filtering are configurable in `config.yaml`.
- Highlight hygiene + ordering: filter non-article URLs, score likely articles, order by source category, and cap items per domain.
- Cross-source dedupe by canonical URL or highly similar titles; keep highest-quality item.
- LinkedIn artifact generation (ChatGPT) with external footer and top 6 highlights.
- Public digest artifact + GitHub Pages publish script.

## v1.0.0 — 2026-01-26
- Phase 11: ops packaging, scheduling templates, and release hygiene.

## v0.10.0
- Phase 10: observability metrics, structured logging, and drift reporting.

## v0.9.0
- Phase 09: HTML digest renderer and optional SMTP email delivery.

## v0.8.0
- Phase 08: AI processing, caching, and usage tracking.

## v0.7.0
- Phase 07: crawl4ai integration and domain method preferences.

## v0.6.0
- Phase 06: multi-method extraction engine with audit logging.

## v0.5.0
- Phase 05: HTTP fetcher and caching primitives.

## v0.4.0
- Phase 04: listing discovery and candidate de-duplication.

## v0.3.0
- Phase 03: CSV ingestion and RSS discovery.

## v0.2.0
- Phase 02: storage layer and migrations.

## v0.1.0
- Phase 01: CLI, config loader, and core models.
