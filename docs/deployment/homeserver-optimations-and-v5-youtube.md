# homeserver-optimations-and-v5-youtube

Date: 2026-04-05

## Session Summary

This session finalized deployment and operations work across home server automation, YouTube V5 enrichment, and alerting.

## Key Outcomes

1. YouTube V5 enrichment runtime moved off Mac
- Deployed enrichment on `ai-node-01`.
- Configured hourly schedule there.
- Confirmed direct updates to Postgres (`youtube_liked_videos`).
- Ensured enrichment only fills missing `categories`/`tags`.
- Confirmed timestamp-preserving behavior (`youtube_added_at` trigger protection).

2. Lloyds + YouTube daily consolidated alert
- Added `scripts/send_24h_summary.sh` on `automation-runner-01`.
- Added daily cron schedule at `09:00` (`Europe/London`).
- Alert now includes:
  - Lloyds 24h run health/totals/freshness/n8n latest status
  - YouTube V5 24h totals/new videos/transcript coverage/missing categories-tags
- Performed dry-run and live send validation.

3. Documentation updates
- Updated deployment alert docs with 24h summary section and schedule.
- Added consolidated alert mechanism reference.
- Added handoff document for future operators.

## Files Added/Updated During This Work

- `docs/deployment/alert-notifications.md`
- `docs/deployment/alerting-mechanism-consolidated.md`
- `docs/deployment/handoff-alerting-24h-summary.md`
- `docs/deployment/homeserver-optimations-and-v5-youtube.md`

## Operational Notes

- 24h summary is additive and does not replace immediate failure alerts.
- Scheduler host for summary is `automation-runner-01`.
- Scheduler host for YouTube enrichment is `ai-node-01`.
- Keep secrets in runtime `.env`, not in git.
