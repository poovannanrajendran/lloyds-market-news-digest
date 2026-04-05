#!/usr/bin/env bash
set -euo pipefail

# Sends a plain text alert to Slack and/or Discord via incoming webhooks.
# Configure one or both environment variables:
# - ALERT_WEBHOOK_SLACK
# - ALERT_WEBHOOK_DISCORD

MESSAGE="${1:-Automation alert}"
LEVEL="${2:-info}"
HOST_NAME="${HOSTNAME:-$(hostname 2>/dev/null || echo unknown-host)}"
PROJECT_NAME="${ALERT_PROJECT_NAME:-lloyds-market-news-digest}"

if [[ -z "${ALERT_WEBHOOK_SLACK:-}" && -z "${ALERT_WEBHOOK_DISCORD:-}" ]]; then
  exit 0
fi

TEXT="[$LEVEL] [$PROJECT_NAME] [$HOST_NAME] $MESSAGE"
PAYLOAD="$(python - "$TEXT" <<'PY'
import json
import sys
text = sys.argv[1]
print(json.dumps({"text": text}))
PY
)"
DISCORD_PAYLOAD="$(python - "$TEXT" <<'PY'
import json
import sys
text = sys.argv[1]
print(json.dumps({"content": text}))
PY
)"

if [[ -n "${ALERT_WEBHOOK_SLACK:-}" ]]; then
  curl -fsS -X POST "$ALERT_WEBHOOK_SLACK" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" >/dev/null || true
fi

if [[ -n "${ALERT_WEBHOOK_DISCORD:-}" ]]; then
  curl -fsS -X POST "$ALERT_WEBHOOK_DISCORD" \
    -H "Content-Type: application/json" \
    -d "$DISCORD_PAYLOAD" >/dev/null || true
fi

