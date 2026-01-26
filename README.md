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
```

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
