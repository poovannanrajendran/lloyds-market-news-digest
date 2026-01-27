# Day‑2 Ops Runbook — Lloyd’s Market News Digest

## Daily checks
- Verify Postgres + Mongo connectivity
- Confirm `sources.csv` is up to date
- Confirm disk space for `output/` and `logs/`

## Run now (manual)
```bash
conda activate 314
scripts/run_daily.sh
```

## Verify output
- `output/digest_YYYY-MM-DD.html` exists and opens
- `logs/run_YYYY-MM-DD.log` created
- Postgres `digests` row inserted

## Troubleshooting
### Discovery failures
- Check `sources.csv` rows for invalid `source_type` or `page_type`
- Check Mongo `discovery_snapshots`

### Fetch failures
- Check HTTP status in `fetch_cache` (Mongo)
- Retry with cache disabled if needed

### Extraction failures
- Check Postgres `attempts` for failure counts
- Check Mongo `attempts_raw` for full content

### AI failures
- Check `OLLAMA_HOST` + model names
- Check Mongo `ai_cache` and Postgres `llm_usage`

## Backfills / reruns
- Re-run pipeline for a specific date (future CLI/orchestrator)
- Clear `fetch_cache` by key if corrupted

## Cleanup
- Archive old logs and HTML files quarterly
- Optionally prune Mongo `attempts_raw` and `fetch_cache` by age

## Health indicators
- Coverage (extracted / total candidates) should be stable
- Method Health section: watch for drift flags
