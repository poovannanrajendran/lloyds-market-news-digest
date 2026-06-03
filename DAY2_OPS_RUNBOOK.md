# Day‑2 Ops Runbook — Lloyd’s Market News Digest

## Current scheduler (automation-runner-01)
- Timezone: `Europe/London`
- Main run: `08:00` daily via `scripts/run_daily.sh`
- Missed-run heartbeat checks: `15,45 * * * *` via `scripts/check_run_freshness.sh`
- n8n workflow alert checks: `08:45, 08:55, 09:05, 09:15, 09:25` via `scripts/check_n8n_workflow_alerts.sh`
- Consolidated 24h summary alert: `09:00` daily via `scripts/send_24h_summary.sh`

## Alerting overview
- Transport script: `scripts/notify_webhooks.sh`
- Channels: Slack incoming webhook + Discord webhook
- Daily pipeline:
  - Immediate failure alert from `run_daily.sh` trap
  - Configurable success alert (`ALERT_NOTIFY_ON_SUCCESS`)
  - Success message includes audit metrics from Postgres
- n8n workflow monitor:
  - Workflow ID driven (`N8N_ALERT_WORKFLOW_ID`)
  - Immediate failure alert when execution status is terminal error
  - Configurable success alert (`N8N_ALERT_NOTIFY_ON_SUCCESS`)
  - Stops polling for the day after success/failure
  - Writes one marker line to cron log when marked done for the day
- Consolidated 24h summary (`scripts/send_24h_summary.sh`):
  - additive daily ops summary (does not replace immediate alerts)
  - includes Lloyds 24h health/totals + latest n8n status + YouTube V5 metrics

## Daily checks
- Verify Postgres + Mongo connectivity
- Confirm `sources.csv` is up to date
- Confirm disk space for `output/` and `logs/`
- Verify cron entries are present: `crontab -l`
- Verify recent alerts arrived in Slack/Discord when expected

## Run now (manual)
```bash
cd /opt/automation/lloyds-market-news-digest
/bin/bash -lc 'export PATH="$HOME/miniconda3/bin:$PATH"; export PYTHONPATH=$PWD/src; ./scripts/run_daily.sh'
```

## Run n8n alert check now (manual)
```bash
set -a; source .env; set +a
./scripts/check_n8n_workflow_alerts.sh
```

## Send 24h consolidated summary now (manual)
```bash
set -a; source .env; set +a
./scripts/send_24h_summary.sh --dry-run
./scripts/send_24h_summary.sh
```

## Verify output
- `output/digest_YYYY-MM-DD.html` exists and opens
- `logs/run_YYYY-MM-DD.log` created
- Postgres `digests` row inserted
- `logs/last_daily_success_epoch.txt` updated
- `logs/cron.log` includes `n8n-alert: marked done...` once n8n terminal state is detected

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
- Check OpenAI quota/status if `429 insufficient_quota` appears

### Alerts not sending
- Confirm `.env` has `ALERT_WEBHOOK_SLACK` and/or `ALERT_WEBHOOK_DISCORD`
- Test transport:
  ```bash
  set -a; source .env; set +a
  ./scripts/notify_webhooks.sh "ops test message" info
  ```
- Check `logs/cron.log` for script execution errors

### Runner preflight/self-healing
- `scripts/run_daily.sh` owns Python activation; cron should not source `conda.sh` directly.
- The runner sets `CONDA_NO_PLUGINS=true` so broken Conda plugins, including `anaconda-anon-usage`, do not block `conda info --base`.
- If Conda activation fails, the runner falls back to `$HOME/miniconda3/envs/314/bin/python` and validates required imports before starting the pipeline.
- The runner blocks early when free disk space is below `RUN_DAILY_MIN_FREE_MB` (default `2048`) to avoid partial writes.
- A stale `.git/index.lock` older than `RUN_DAILY_GIT_LOCK_MAX_AGE_SECONDS` (default `900`) is removed only when no Git process is active for the runner user.

## Backfills / reruns
- Re-run pipeline for a specific date (future CLI/orchestrator)
- Clear `fetch_cache` by key if corrupted

## Cleanup
- Archive old logs and HTML files quarterly
- Optionally prune Mongo `attempts_raw` and `fetch_cache` by age

## Health indicators
- Coverage (extracted / total candidates) should be stable
- Method Health section: watch for drift flags
- n8n LinkedIn workflow should produce one terminal execution each day in scheduled window
