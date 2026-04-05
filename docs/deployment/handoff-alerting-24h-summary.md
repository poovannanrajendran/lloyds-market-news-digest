# Handoff: Alerting System + 24h Consolidated Summary

Date: 2026-04-05
Owner: Poovannan / Codex handoff
Environment: `automation-runner-01` (`Europe/London`)

## 1) What Was Added

A new daily consolidated alert was added:

- Script: `scripts/send_24h_summary.sh`
- Schedule: daily at `09:00` (`CRON_TZ=Europe/London`)
- Delivery path: existing `scripts/notify_webhooks.sh` (Slack + Discord)

This is additive. Existing immediate alerts remain active.

## 2) Existing Alert Flows (Current)

1. Immediate pipeline alerts
- `scripts/run_daily.sh`
- failure alert on `ERR`
- optional success alert

2. Missed-run freshness alerts
- `scripts/check_run_freshness.sh`

3. n8n workflow alerts
- `scripts/check_n8n_workflow_alerts.sh`

4. New 24h consolidated summary
- `scripts/send_24h_summary.sh`

## 3) What the 24h Summary Includes

### Lloyds section
- runs in last 24h (total/success/failed)
- latest run (id/status/start/duration)
- totals (candidates/fetched/extracted/errors)
- digest items total
- freshness state (from heartbeat file)
- latest n8n execution status

### YouTube V5 section
- total videos
- new videos in last 24h
- latest `added_at`
- transcript coverage (present/missing/added_24h)
- missing categories/tags count

## 4) Runtime + Schedule Details

Host:
- `automation-runner-01`

Cron (active):
```cron
CRON_TZ=Europe/London
0 9 * * * cd /opt/automation/lloyds-market-news-digest && /bin/bash -lc 'set -a; source .env; set +a; ./scripts/send_24h_summary.sh' >> /opt/automation/lloyds-market-news-digest/logs/cron.log 2>&1
```

## 5) Required Config

From `.env`:
- `ALERT_WEBHOOK_SLACK` and/or `ALERT_WEBHOOK_DISCORD`
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- `N8N_PUBLIC_API_KEY`, `N8N_ALERT_WORKFLOW_ID`

Optional:
- `YOUTUBE_POSTGRES_URI` (default points to `192.168.1.20:5432/youtube_liked_videos`)
- `YOUTUBE_SUMMARY_TABLE` (default `youtube_videos`)

## 6) Validation Done

- Dry-run tested successfully on runner.
- Live send executed successfully and logged in `logs/cron.log`.
- Cron entry verified present.

## 7) Operations Commands

Dry-run:
```bash
cd /opt/automation/lloyds-market-news-digest
/bin/bash -lc 'set -a; source .env; set +a; ./scripts/send_24h_summary.sh --dry-run'
```

Live send:
```bash
cd /opt/automation/lloyds-market-news-digest
/bin/bash -lc 'set -a; source .env; set +a; ./scripts/send_24h_summary.sh'
```

Check cron + recent logs:
```bash
crontab -l
cd /opt/automation/lloyds-market-news-digest
tail -n 200 logs/cron.log
```

## 8) Rollback

If needed, disable only the 24h summary without impacting other alerts:

1. Remove cron line containing `send_24h_summary.sh`
2. Keep all other cron entries unchanged
3. Optionally retain script for future use

## 9) Related Documentation

- `docs/deployment/alert-notifications.md`
- `docs/deployment/alerting-mechanism-consolidated.md`

## 10) Notes for Future Updates

- If Lloyds schema changes (`runs`/`digests`), update SQL in `send_24h_summary.sh`.
- If YouTube table schema changes, update YouTube summary SQL fields.
- Keep secrets out of git; only runtime `.env` on runner.
