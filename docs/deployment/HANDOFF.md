# Handoff - Lloyd's Market News Digest

## Current AI and credit controls — v1.1.0

As of 8 October 2026, GPT-6 Luna handles summaries, digest composition and LinkedIn text; GPT-5 Nano handles relevance/classification. Flex uses ordinary-tier fallback when capacity is unavailable. Luna uses no reasoning and an 8,192-token completion cap. The banner is template-rendered.

An independent organisation Costs API check runs before the pipeline and on exit. It sends Slack/Discord warnings when estimated remaining credit is **$1 or less**, or accounting is unavailable. Reconcile the balance/cost baseline after top-ups; billing data can lag. This is an estimate rather than a live credit-balance endpoint.

- [Detailed optimisation release](../releases/v1.1.0.md)
- [Model configuration and rollback](gpt6-luna-rollout.md)
- [Credit monitoring and safe dry-run](openai-balance-alerts.md)


Last updated: 2026-10-08

## Scope
This handoff captures the current production-like setup for daily digest automation, n8n LinkedIn monitoring, and alerting.

## Environment
- Host: `automation-runner-01`
- Path: `/opt/automation/lloyds-market-news-digest`
- Timezone: `Europe/London`
- Python env: conda `314`
- n8n URL: `http://192.168.1.30:5678/`

## Active schedules (cron)
- Daily pipeline run:
  - `0 8 * * *` -> `./scripts/run_daily.sh`
- Missed-run heartbeat check:
  - `15,45 * * * *` -> `./scripts/check_run_freshness.sh`
- n8n workflow monitor window:
  - `45,55 8 * * *`, `5,15,25 9 * * *`, and `5,15 10 * * *` -> `./scripts/check_n8n_workflow_alerts.sh`
- 24h consolidated summary:
  - `0 9 * * *` -> `./scripts/send_24h_summary.sh`
- System maintenance (runner-level):
  - user `labadmin`, `CRON_TZ=Europe/London`
  - `0 12 */2 * *` -> `/opt/automation/n8n/update_system_stack.sh`
  - includes: OS package updates, Python deps refresh, n8n update, safe Docker Compose refresh

## Alerting architecture
Transport:
- `scripts/notify_webhooks.sh`
- Uses Slack/Discord webhooks from `.env`

Immediate alerts:
- `run_daily.sh`: immediate failure (`trap ERR`), configurable success (`ALERT_NOTIFY_ON_SUCCESS`)
- `check_run_freshness.sh`: stale/missing daily heartbeat detection
- `check_n8n_workflow_alerts.sh`: n8n execution status monitor for a single workflow, optional success alerts, and stop-after-terminal-status for the day
  - waits until after the 10:00 fallback schedule before treating a failed run as final

Consolidated alert:
- `send_24h_summary.sh` (daily 09:00)
- Includes:
  - Lloyds run health/totals (24h)
  - latest n8n status
  - YouTube V5 metrics (new videos, transcript coverage, missing category/tags)

## Key scripts
- `scripts/run_daily.sh`
- `scripts/check_run_freshness.sh`
- `scripts/check_n8n_workflow_alerts.sh`
- `scripts/send_24h_summary.sh`
- `scripts/notify_webhooks.sh`

## n8n monitored workflow
- Name: `LloydsNewsDigest-PosttoLinkedin`
- ID: `p3vKHAd612unzVWP`

## n8n runtime notes
- n8n images now use stable channel:
  - `N8N_IMAGE=n8nio/n8n:stable`
  - `N8N_RUNNERS_IMAGE=n8nio/runners:stable`
- Current runtime observed on runner: `n8n 2.16.1`
- LinkedIn node compatibility patch is applied in maintenance script:
  - replaces deprecated `LinkedIn-Version: 202504` with `202604`
  - patch runs after n8n/docker refresh to avoid regression until upstream image includes the fix

## State/log files
- `logs/run_YYYY-MM-DD.log`
- `logs/cron.log`
- `logs/last_daily_success_epoch.txt`
- `logs/last_daily_missed.alerted`
- `logs/n8n_last_seen_execution_id.txt`
- `logs/n8n_alert_done_date.txt`

## Manual operator commands
Run daily pipeline now:
```bash
cd /opt/automation/lloyds-market-news-digest
/bin/bash -lc 'export PATH="$HOME/miniconda3/bin:$PATH"; export PYTHONPATH=$PWD/src; ./scripts/run_daily.sh'
```

`run_daily.sh` handles Conda activation/fallback, required Python import validation, low-disk refusal, stale `.git/index.lock` cleanup, and Git alignment internally.

Test notification transport:
```bash
cd /opt/automation/lloyds-market-news-digest
/bin/bash -lc 'set -a; source .env; set +a; ./scripts/notify_webhooks.sh "ops test message" info'
```

Run n8n monitor once:
```bash
cd /opt/automation/lloyds-market-news-digest
/bin/bash -lc 'set -a; source .env; set +a; ./scripts/check_n8n_workflow_alerts.sh'
```

Run 24h summary once:
```bash
cd /opt/automation/lloyds-market-news-digest
/bin/bash -lc 'set -a; source .env; set +a; ./scripts/send_24h_summary.sh --dry-run'
/bin/bash -lc 'set -a; source .env; set +a; ./scripts/send_24h_summary.sh'
```

## Security notes
- Keep live secrets only in runtime `.env` on runner.
- Do not commit webhook URLs/API keys/tokens.
- If exposure suspected, rotate keys and update runner `.env`.

## Related docs
- `docs/deployment/automation-runner-01-deployment.md`
- `docs/deployment/alert-notifications.md`
- `docs/deployment/alerting-mechanism-consolidated.md`
- `docs/deployment/notion-handoff.md`
- `docs/deployment/HANDOFF.md`
- `DAY2_OPS_RUNBOOK.md`
