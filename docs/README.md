# Documentation index

Current as of 8 October 2026, release **v1.1.0**. The daily path uses GPT-5 Nano for relevance/classification and GPT-6 Luna for summaries, digest composition and LinkedIn text. The banner is template-rendered. The daily runner checks estimated organisation credit before processing and on exit and alerts at $1 or less.

## Start here

| Document | Purpose |
|---|---|
| [Project README](../README.md) | Setup and everyday commands |
| [v1.1.0 release](releases/v1.1.0.md) | Detailed optimisation, cost evidence, validation and limitations |
| [Codebase guide](../CODEBASE_GUIDE.md) | Active orchestration, modules and cost accounting |
| [Changelog](../CHANGELOG.md) | Versioned change summary |
| [Day-2 runbook](../DAY2_OPS_RUNBOOK.md) | Checks, troubleshooting and operator commands |
| [Codex brief](CODEX_BRIEF.md) | Current maintenance conventions and historical design references |

## Deployment and operations

| Document | Purpose |
|---|---|
| [Runner deployment](deployment/automation-runner-01-deployment.md) | Host/environment setup and scheduler |
| [Production handoff](deployment/HANDOFF.md) | Deployment, schedules and operational ownership |
| [Model rollout](deployment/gpt6-luna-rollout.md) | Private model settings, validation and focused rollback |
| [OpenAI credit monitor](deployment/openai-balance-alerts.md) | Costs API baseline, inclusive threshold and reconciliation |
| [Temporary Nano/Luna shadow audit](operations/model-shadow-audit.md) | Isolated three-run relevance comparison (10–12 October 2026) |
| [Alert notifications](deployment/alert-notifications.md) | Slack/Discord transport and alert commands |
| [Consolidated alert architecture](deployment/alerting-mechanism-consolidated.md) | Shared pipeline/n8n/YouTube alerts |
| [24-hour summary handoff](deployment/handoff-alerting-24h-summary.md) | Earlier summary implementation plus current credit-check addendum |
| [Notion handoff copy](deployment/notion-handoff.md) | Local copy of operational handoff; no external Notion update implied |

## Historical material and local evidence

[Phase notebook](../phases.md) retains implementation history with its active renderer commands corrected. The [April homeserver/YouTube session](deployment/homeserver-optimations-and-v5-youtube.md) remains a dated historical record. Original PRD/plan documents retain their historical requirements; use the current release and rollout for production model decisions.

Published HTML digests are historical publication artifacts and are not rewritten by documentation maintenance. Private supplied usage exports and live-trial source/output files remain local evidence, not GitHub release attachments. Local reports under `output/model_evaluation_2026-10-08/` and `output/openai_cost_analysis_2026-10-08/` provide the original evaluation context. Their historical forecasts are not live balance measurements.

## Documentation maintenance

Change model settings through the rollout guide and keep credentials/private baselines out of Git. Record the implementation, measured checks and limits in release notes. Update active instructions without rewriting historical observations as current facts. Before describing a speed or quality improvement, obtain representative measurements; current small trials establish compatibility and promising cost behaviour only.
