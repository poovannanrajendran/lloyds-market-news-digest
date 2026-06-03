# Consolidated Alert Mechanism (Lloyds + n8n + YouTube V5)

This document is the single reference for the alert architecture used by `lloyds-market-news-digest` on `automation-runner-01`.

## 1) Objectives

- Keep operators informed of failures as soon as they happen.
- Provide a daily operational snapshot across Lloyds pipeline and YouTube V5.
- Use one transport layer for all channels (Slack + Discord).
- Keep runtime behavior simple (shell scripts + cron + `.env`).

## 2) Alert Components

### 2.1 Transport

- Script: `scripts/notify_webhooks.sh`
- Channels:
  - Slack incoming webhook (`ALERT_WEBHOOK_SLACK`)
  - Discord webhook (`ALERT_WEBHOOK_DISCORD`)
- Message envelope:
  - `[level] [project] [host] message`

### 2.2 Immediate alerts (event-driven)

1. Daily run pipeline (`scripts/run_daily.sh`)
- Failure alert: immediate (`trap ERR`)
- Success alert: optional (`ALERT_NOTIFY_ON_SUCCESS=1`)

2. Missed-run freshness monitor (`scripts/check_run_freshness.sh`)
- Periodic checks from cron
- Alerts when heartbeat is stale/missing

3. n8n workflow monitor (`scripts/check_n8n_workflow_alerts.sh`)
- Polls n8n executions API
- Sends error alerts for failed/crashed/error states
- Optional success alerts (`N8N_ALERT_NOTIFY_ON_SUCCESS=1`)
- Uses state files under `logs/` to avoid duplicate day alerts

### 2.3 Daily consolidated summary (time-driven)

- Script: `scripts/send_24h_summary.sh`
- Schedule: `0 9 * * *` (with `CRON_TZ=Europe/London`)
- Purpose: 24-hour operational summary in one message

Summary sections:
- Lloyds digest (runs, latest run, totals, freshness, n8n latest status)
- YouTube V5 (totals, new videos, transcript coverage, enrichment gaps)

## 3) Data Sources Used by Alerts

### 3.1 Lloyds Postgres (`lloyds_digest`)

- Table `runs`: run counts + latest run + metrics (`candidates/fetched/extracted/errors`)
- Table `digests`: `item_count` totals in 24h

### 3.2 Freshness heartbeat

- File: `logs/last_daily_success_epoch.txt`
- Used to infer stale/ok freshness state

### 3.3 n8n API

- Endpoint: `${N8N_API_BASE_URL}/executions`
- Filtered by `N8N_ALERT_WORKFLOW_ID`

### 3.4 YouTube V5 Postgres

- URI default: `postgresql://dbuser:dbuser@192.168.1.20:5432/youtube_liked_videos`
- Table default: `youtube_videos`
- Uses `added_at`, `transcript`, `categories`, `tags` for metrics

## 4) Severity Rules (Consolidated 24h Script)

- `error`:
  - any Lloyds failed run in last 24h
  - stale freshness state
  - n8n latest status in `error|failed|crashed`
- `warning`:
  - no Lloyds runs in last 24h
  - no new YouTube videos in last 24h
- `info`:
  - none of the above

## 5) Scheduler Baseline on automation-runner-01

```cron
CRON_TZ=Europe/London
0 8 * * * cd /opt/automation/lloyds-market-news-digest && /bin/bash -lc 'export PATH="$HOME/miniconda3/bin:$PATH"; export PYTHONPATH=$PWD/src; ./scripts/run_daily.sh' >> /opt/automation/lloyds-market-news-digest/logs/cron.log 2>&1
15,45 * * * * cd /opt/automation/lloyds-market-news-digest && /bin/bash -lc 'set -a; source .env; set +a; ./scripts/check_run_freshness.sh' >> /opt/automation/lloyds-market-news-digest/logs/cron.log 2>&1
45,55 8 * * * cd /opt/automation/lloyds-market-news-digest && /bin/bash -lc 'set -a; source .env; set +a; ./scripts/check_n8n_workflow_alerts.sh' >> /opt/automation/lloyds-market-news-digest/logs/cron.log 2>&1
5,15,25 9 * * * cd /opt/automation/lloyds-market-news-digest && /bin/bash -lc 'set -a; source .env; set +a; ./scripts/check_n8n_workflow_alerts.sh' >> /opt/automation/lloyds-market-news-digest/logs/cron.log 2>&1
0 9 * * * cd /opt/automation/lloyds-market-news-digest && /bin/bash -lc 'set -a; source .env; set +a; ./scripts/send_24h_summary.sh' >> /opt/automation/lloyds-market-news-digest/logs/cron.log 2>&1
```

The daily runner performs its own Conda activation/fallback and self-healing preflight; do not source `conda.sh` directly in cron.

## 6) Required / Optional Env Keys

Required:
- `ALERT_WEBHOOK_SLACK` and/or `ALERT_WEBHOOK_DISCORD`
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- `N8N_PUBLIC_API_KEY`, `N8N_ALERT_WORKFLOW_ID`

Optional:
- `ALERT_PROJECT_NAME`
- `ALERT_NOTIFY_ON_SUCCESS`
- `N8N_API_BASE_URL`, `N8N_ALERT_WORKFLOW_NAME`, `N8N_ALERT_NOTIFY_ON_SUCCESS`
- `YOUTUBE_POSTGRES_URI`
- `YOUTUBE_SUMMARY_TABLE`

## 7) Test / Troubleshooting

Dry-run consolidated summary:

```bash
set -a; source .env; set +a
./scripts/send_24h_summary.sh --dry-run
```

Live summary send:

```bash
set -a; source .env; set +a
./scripts/send_24h_summary.sh
```

Check cron evidence:

```bash
tail -n 200 logs/cron.log
```

## 8) Short Summary of New Addition (24h Summary)

Added `scripts/send_24h_summary.sh` and scheduled it at **09:00 Europe/London** on `automation-runner-01`.

The new alert sends one daily consolidated message containing:
- Lloyds 24h run health and totals
- latest n8n status
- YouTube V5 24h ingestion/transcript/enrichment metrics

This does not replace existing immediate alerts; it complements them with a daily operational snapshot.

## 9) Security Notes

- Keep secrets only in runtime `.env` on runner host.
- Do not commit webhook/API keys.
- Rotate keys if leaked.
