# Lloyd’s Market News Digest

Local-first news discovery + extraction + AI scoring + HTML/email digest for London Lloyd’s Market.

## Phase 01 — Quickstart
- Conda env: `314` (Python 3.14)
- Copy `.env.example` -> `.env` and set DB + SMTP + Ollama values
- Ensure `config.yaml` exists in the repo root (a minimal sample is included)

### Run the CLI (Phase 01)
```bash
conda activate 314
python -m lloyds_digest --help
python -m lloyds_digest run --now
python -m lloyds_digest run --run-date 2026-01-26
python -m lloyds_digest run --now --max-candidates 20
python -m lloyds_digest run --now --limit-articles 20
python -m lloyds_digest run --now --force-refresh --max-candidates 50
python -m lloyds_digest run --now --max-urls 10
python -m lloyds_digest run --now --max-urls 10 --max-candidates 50
```

### Boilerplate filtering (optional)
Generate per-domain/path boilerplate rules (15 URLs per template):
```bash
python scripts/analyze_boilerplate.py --samples 15 --output boilerplate.yaml
```
Ignore certain path prefixes:
```bash
python scripts/analyze_boilerplate.py --samples 15 --ignore-path-prefix /newsroom --ignore-path-prefix /careers
```

### Relevance keyword gating (optional)
Provide a YAML keyword list and set a minimum score:
```bash
export LLOYDS_DIGEST_KEYWORDS_FILE=relevant_keywords.yaml
export LLOYDS_DIGEST_KEYWORDS_MIN_SCORE=2.5
```

### Recency filter
Configure the max age in `config.yaml`:
```yaml
filters:
  max_age_days: 7
  keyword_min_score: 3.0
  require_core_lloyds: true
  require_core_combo: true
  exclude_paths:
    - /privacy
    - /cookie
    - /terms
```

### Verbose logging
```bash
python -m lloyds_digest run --now --verbose
```

### LLM digest comparison (24h, render-only)
Generate HTML outputs (ChatGPT + DeepSeek via Ollama) using the last 24 hours of already-extracted articles:
```bash
python scripts/render_digest_llm_compare.py
```
Outputs land in `output/` as:
`digest_YYYY-MM-DD_chatgpt.html`, `digest_YYYY-MM-DD_<deepseek-model>.html`

Prompt text for each provider is configured in `config.yaml` under `llm_prompts`.
```

#### Provider options
```bash
python scripts/render_digest_llm_compare.py --provider local
python scripts/render_digest_llm_compare.py --provider chatgpt
python scripts/render_digest_llm_compare.py --provider deepseek
```
Default `all` runs ChatGPT + DeepSeek (local is opt-in).

#### Chunking + retries (render-only)
```bash
python scripts/render_digest_llm_compare.py --chunk-by domain --chunk-size 15
python scripts/render_digest_llm_compare.py --max-chunks 2
```
Env overrides:
```bash
export DIGEST_CHUNK_SIZE=15
export DIGEST_CHUNK_RETRIES=2
export DIGEST_MAX_PER_DOMAIN=5
export EXEC_SUMMARY_MAX_CHARS=500
```

#### DeepSeek via Ollama
Set the DeepSeek model separately if desired:
```bash
export OLLAMA_DEEPSEEK_MODEL=deepseek-v3.2:cloud
```

#### Highlight ordering + hygiene
The render-only digest applies content hygiene and ordering before HTML output:
- Filters common non-article URLs (subscribe, careers, tag/topic pages).
- Scores likely articles using URL/date/title/excerpt signals.
- Orders highlights: primary (Lloyd's) → secondary → regulatory → compliance → PRA → insurance → financial → other.
- Caps highlights per domain (default 5).
- Dedupe across sources by canonical URL or highly similar titles; keeps highest-scoring item.

#### LinkedIn artifact (ChatGPT)
Generate a LinkedIn-ready HTML (external footer, top 12 highlights by default, min 3 London Market items):
```bash
python scripts/render_digest_llm_compare.py --provider chatgpt --linkedin
python scripts/render_digest_chatgpt_linkedin.py
```
Env overrides:
```bash
export LINKEDIN_MAX_ITEMS=12
export LINKEDIN_MIN_LONDON=3
```

#### GitHub Pages publish (public digest)
The render step now writes:
- `output/digest_YYYY-MM-DD.html` (internal)
- `output/digest_YYYY-MM-DD_public.html` (external)

Publish the external digest to GitHub Pages:
```bash
python scripts/render_digest_llm_compare.py --provider chatgpt
scripts/publish_github_pages.sh
```
Pages source: `main` branch, `/docs` folder.

### Config overrides via env
Use `LLOYDS_DIGEST__` with double underscores for nesting:
```bash
export LLOYDS_DIGEST__CACHE__ENABLED=true
export LLOYDS_DIGEST__OUTPUT__DIRECTORY=output
```

## Phase 02 — Storage Layer
### Dependencies
```bash
conda activate 314
python -m pip install psycopg pymongo
```

### Postgres migrations
```bash
conda activate 314
source .env
scripts/db_init_postgres.sh
```

### Mongo indexes (Atlas or local)
```bash
conda activate 314
source .env
mongosh "$MONGODB_URI" scripts/db_init_mongo.js
```

### Smoke test connections
```bash
conda activate 314
source .env
python scripts/smoke_test_connections.py
```

## Phase 03 — CSV + RSS Discovery
### Dependencies
```bash
conda activate 314
python -m pip install feedparser httpx
```

### sources.csv format
```
source_type,domain,url,topics,page_type
primary,insurancejournal.com,https://example.com/feed,Lloyd's;Marine,rss
secondary,bloomberg.com,https://example.com/listing,Market Analysis,listing
```

## Phase 05 — Fetchers + Cache
### Dependencies
```bash
conda activate 314
python -m pip install tenacity
```

## Phase 06 — Extraction Engine
### Dependencies (optional)
```bash
conda activate 314
python -m pip install trafilatura readability-lxml beautifulsoup4
```

## Phase 07 — crawl4ai + Method Preferences
### Dependencies (optional)
```bash
conda activate 314
python -m pip install crawl4ai
```

## Phase 08 — AI Processing + Caching
### Dependencies (optional)
```bash
conda activate 314
python -m pip install ollama
```

## Phase 09 — Digest Renderer + Email
SMTP uses the standard library `smtplib`; no extra dependencies required.

## Phase 10 — Observability + Drift Reporting
Outputs JSONL logs and includes Method Health section when failures exist.

## Phase 11 — Ops Packaging + Scheduling
### Quickstart
```bash
conda activate 314
scripts/run_daily.sh
```

### Daily Ops (launchd)
```bash
cp scripts/lloyds_digest.plist ~/Library/LaunchAgents/com.lloyds.digest.daily.plist
launchctl load ~/Library/LaunchAgents/com.lloyds.digest.daily.plist
launchctl start com.lloyds.digest.daily
```
