# Alert Notifications (Slack + Discord + n8n)

This project supports two alert streams:

1. Daily pipeline alerts from `scripts/run_daily.sh` and `scripts/check_run_freshness.sh`
2. n8n workflow alerts from `scripts/check_n8n_workflow_alerts.sh`

## 1) Notification transport

All alerts are sent through:

- `scripts/notify_webhooks.sh`

Supported channels:

- Slack incoming webhook
- Discord webhook

Required env vars (one or both):

- `ALERT_WEBHOOK_SLACK`
- `ALERT_WEBHOOK_DISCORD`

Optional:

- `ALERT_PROJECT_NAME` (default: `lloyds-market-news-digest`)

## 2) Daily pipeline alerts

Configured in `scripts/run_daily.sh`:

- Failure alert: immediate via `trap ERR`
- Success alert: controlled by `ALERT_NOTIFY_ON_SUCCESS`
- Success payload includes Postgres audit summary:
  - run date/id
  - candidates/fetched/extracted/errors
  - digest item count

Relevant env var:

- `ALERT_NOTIFY_ON_SUCCESS=1` (or `0`)

Missed-run detector:

- `scripts/check_run_freshness.sh`
- Alerts when no successful heartbeat is found within threshold.

## 3) n8n workflow alerts

Script:

- `scripts/check_n8n_workflow_alerts.sh`

What it does:

- Calls n8n public API executions endpoint for one workflow ID
- Detects new executions
- Sends:
  - immediate error alert on failed/crashed/error run
  - success alert only if enabled
- Stops polling for the day after terminal status (success/failure)
- Writes a one-line marker to cron log:
  - `n8n-alert: marked done for YYYY-MM-DD (status=...)`

State files (under `logs/`):

- `n8n_last_seen_execution_id.txt`
- `n8n_alert_done_date.txt`

Required env vars:

- `N8N_API_BASE_URL` (example: `http://127.0.0.1:5678/api/v1`)
- `N8N_PUBLIC_API_KEY`
- `N8N_ALERT_WORKFLOW_ID`

Optional env vars:

- `N8N_ALERT_WORKFLOW_NAME`
- `N8N_ALERT_NOTIFY_ON_SUCCESS` (`1`/`0`)

## 4) Scheduler configuration (runner)

Current recommended cron:

```cron
CRON_TZ=Europe/London
0 8 * * * cd /opt/automation/lloyds-market-news-digest && /bin/bash -lc 'source "$HOME/miniconda3/etc/profile.d/conda.sh" && conda activate 314 && export PYTHONPATH=$PWD/src && ./scripts/run_daily.sh' >> /opt/automation/lloyds-market-news-digest/logs/cron.log 2>&1
15,45 * * * * cd /opt/automation/lloyds-market-news-digest && /bin/bash -lc 'set -a; source .env; set +a; ./scripts/check_run_freshness.sh' >> /opt/automation/lloyds-market-news-digest/logs/cron.log 2>&1
45,55 8 * * * cd /opt/automation/lloyds-market-news-digest && /bin/bash -lc 'set -a; source .env; set +a; ./scripts/check_n8n_workflow_alerts.sh' >> /opt/automation/lloyds-market-news-digest/logs/cron.log 2>&1
5,15,25 9 * * * cd /opt/automation/lloyds-market-news-digest && /bin/bash -lc 'set -a; source .env; set +a; ./scripts/check_n8n_workflow_alerts.sh' >> /opt/automation/lloyds-market-news-digest/logs/cron.log 2>&1
```

This gives 10-minute polling between 08:45 and 09:30, then stops for the day after terminal run state is seen.

## 5) Test commands

Channel test:

```bash
set -a; source .env; set +a
./scripts/notify_webhooks.sh "n8n test alert: webhook integration active" info
```

n8n monitor test (single pass):

```bash
set -a; source .env; set +a
./scripts/check_n8n_workflow_alerts.sh
```

## 6) Reuse in other projects

1. Copy scripts:
   - `scripts/notify_webhooks.sh`
   - `scripts/check_n8n_workflow_alerts.sh`
2. Add env keys listed above.
3. Add cron lines matching your schedule window and timezone.
4. Use project-specific values:
   - `ALERT_PROJECT_NAME`
   - `N8N_ALERT_WORKFLOW_ID`
   - `N8N_ALERT_WORKFLOW_NAME`

## 7) Secret handling policy

Do not commit live secrets to git.

Keep secrets only in runtime `.env` on the runner. For handover, use a secure secret manager or encrypted vault and store only key names/owners in documentation.

## 8) 24-hour consolidated summary (Lloyds + YouTube V5)

Script:

- `scripts/send_24h_summary.sh`

What it does (rolling last 24 hours):

- Lloyds digest summary:
  - run counts (total/success/failed) from `runs`
  - latest run id/status/start/duration
  - totals: candidates/fetched/extracted/errors
  - digest item total from `digests`
  - freshness state from `logs/last_daily_success_epoch.txt`
  - latest n8n execution id/status via n8n public API
- YouTube V5 summary (remote Postgres):
  - total videos
  - new videos in last 24h
  - transcript coverage + present/missing + transcript-added-24h
  - rows missing category or tags

Default YouTube source:

- `postgresql://dbuser:dbuser@192.168.1.20:5432/youtube_liked_videos`
- table: `youtube_videos`

Optional env vars:

- `YOUTUBE_POSTGRES_URI`
- `YOUTUBE_SUMMARY_TABLE` (default: `youtube_videos`)

Severity logic:

- `error`: any Lloyds failed run in 24h, stale freshness heartbeat, or n8n error/failed/crashed
- `warning`: no Lloyds runs in 24h or no new YouTube videos in 24h
- `info`: otherwise

## 9) Scheduler update (runner, 9:00 AM)

Recommended daily summary cron entry:

```cron
0 9 * * * cd /opt/automation/lloyds-market-news-digest && /bin/bash -lc 'set -a; source .env; set +a; ./scripts/send_24h_summary.sh' >> /opt/automation/lloyds-market-news-digest/logs/cron.log 2>&1
```

Current runner schedule includes this 9:00 AM job in `CRON_TZ=Europe/London`.

## 10) Test commands for consolidated summary

Dry-run (no webhook send):

```bash
set -a; source .env; set +a
./scripts/send_24h_summary.sh --dry-run
```

Live send:

```bash
set -a; source .env; set +a
./scripts/send_24h_summary.sh
```
