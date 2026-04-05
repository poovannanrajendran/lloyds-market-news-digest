# Lloyd's Digest - Ops Handoff (Notion Copy)

## Environment
- Host: `automation-runner-01` (`192.168.1.30`)
- Repo path: `/opt/automation/lloyds-market-news-digest`
- Runtime: conda env `314`
- Scheduler timezone: `Europe/London`

## Daily automation
- Main job:
  - `0 8 * * *` -> `./scripts/run_daily.sh`
- Missed-run monitor:
  - `15,45 * * * *` -> `./scripts/check_run_freshness.sh`
- n8n workflow monitor window:
  - `45,55 8 * * *` and `5,15,25 9 * * *`
  - Script: `./scripts/check_n8n_workflow_alerts.sh`

## Notification design
- Delivery script: `scripts/notify_webhooks.sh`
- Channels:
  - Slack webhook (`ALERT_WEBHOOK_SLACK`)
  - Discord webhook (`ALERT_WEBHOOK_DISCORD`)

### Daily pipeline alerts
- Failure: immediate (trap in `run_daily.sh`)
- Success: configurable (`ALERT_NOTIFY_ON_SUCCESS`)
- Success includes audit stats:
  - `run_id`
  - `candidates`, `fetched`, `extracted`, `errors`
  - `digest_items`

### n8n workflow alerts
- Workflow targeted by:
  - `N8N_ALERT_WORKFLOW_ID`
  - Optional display name: `N8N_ALERT_WORKFLOW_NAME`
- Source API:
  - `N8N_API_BASE_URL` (default local `http://127.0.0.1:5678/api/v1`)
  - `N8N_PUBLIC_API_KEY`
- Failure: immediate when a new terminal error execution appears
- Success: configurable (`N8N_ALERT_NOTIFY_ON_SUCCESS`)
- Includes execution stats:
  - workflow name/id
  - execution id
  - mode/status
  - started/stopped timestamps
  - duration ms
  - nodes executed
  - retry source (if applicable)
- Poll stop behavior:
  - After today’s first terminal success/failure, monitor stops for the day
  - Marker written once: `n8n-alert: marked done for YYYY-MM-DD (status=...)`

## State files
- Daily heartbeat:
  - `logs/last_daily_success_epoch.txt`
- Missed-run flag:
  - `logs/last_daily_missed.alerted`
- n8n monitor state:
  - `logs/n8n_last_seen_execution_id.txt`
  - `logs/n8n_alert_done_date.txt`

## Manual operations
### Run full daily pipeline now
```bash
cd /opt/automation/lloyds-market-news-digest
/bin/bash -lc 'source "$HOME/miniconda3/etc/profile.d/conda.sh" && conda activate 314 && export PYTHONPATH=$PWD/src && ./scripts/run_daily.sh'
```

### Test webhook transport
```bash
cd /opt/automation/lloyds-market-news-digest
/bin/bash -lc 'set -a; source .env; set +a; ./scripts/notify_webhooks.sh "n8n ops test message" info'
```

### Run n8n alert checker once
```bash
cd /opt/automation/lloyds-market-news-digest
/bin/bash -lc 'set -a; source .env; set +a; ./scripts/check_n8n_workflow_alerts.sh'
```

## n8n details
- URL: `http://192.168.1.30:5678/`
- Current monitored workflow:
  - Name: `LloydsNewsDigest-PosttoLinkedin`
  - ID: `p3vKHAd612unzVWP`

## Security notes
- Live secrets are stored only in runner `.env`
- Do not commit webhook URLs/API keys to git
- Use key names in docs, not key values
- Rotate secrets if exposed in logs or chat

## Reference docs
- `docs/deployment/automation-runner-01-deployment.md`
- `docs/deployment/alert-notifications.md`
- `DAY2_OPS_RUNBOOK.md`
