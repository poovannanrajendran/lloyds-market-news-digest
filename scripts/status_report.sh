#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs"
RUN_LOG="$LOG_DIR/run_$(date +%F).log"
HEARTBEAT_FILE="$LOG_DIR/last_daily_success_epoch.txt"
N8N_STATE_FILE="$LOG_DIR/n8n_last_seen_execution_id.txt"
N8N_DONE_FILE="$LOG_DIR/n8n_alert_done_date.txt"
ENV_FILE="$ROOT_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

fmt_epoch() {
  local epoch="${1:-}"
  if [[ -z "$epoch" || ! "$epoch" =~ ^[0-9]+$ ]]; then
    echo "na"
    return 0
  fi
  date -r "$epoch" '+%Y-%m-%d %H:%M:%S %Z'
}

run_state="missing"
if [[ -f "$RUN_LOG" ]]; then
  run_state="present"
fi

heartbeat_epoch="na"
heartbeat_age="na"
if [[ -f "$HEARTBEAT_FILE" ]]; then
  heartbeat_epoch="$(tr -d '[:space:]' < "$HEARTBEAT_FILE" || true)"
  if [[ "$heartbeat_epoch" =~ ^[0-9]+$ ]]; then
    heartbeat_age="$(( $(date +%s) - heartbeat_epoch ))s"
  fi
fi

n8n_exec="na"
if [[ -f "$N8N_STATE_FILE" ]]; then
  n8n_exec="$(tr -d '[:space:]' < "$N8N_STATE_FILE" || true)"
fi

n8n_done="na"
if [[ -f "$N8N_DONE_FILE" ]]; then
  n8n_done="$(tr -d '[:space:]' < "$N8N_DONE_FILE" || true)"
fi

latest_run_id="na"
latest_status="na"
latest_started="na"
latest_duration="na"
if command -v psql >/dev/null 2>&1 && [[ -n "${POSTGRES_HOST:-}" && -n "${POSTGRES_DB:-}" && -n "${POSTGRES_USER:-}" && -n "${POSTGRES_PASSWORD:-}" ]]; then
  latest_query="$(PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -AtX -F $'\t' -c "
SELECT
  COALESCE(r.run_id::text,'na'),
  CASE
    WHEN r.ended_at IS NULL THEN 'failed'
    WHEN EXISTS (
      SELECT 1
      FROM run_phase_timings p
      WHERE p.run_id = r.run_id
        AND p.phase = 'publish_pages'
        AND p.ended_at IS NOT NULL
    ) THEN 'success'
    ELSE 'failed'
  END AS run_status,
  TO_CHAR(r.started_at AT TIME ZONE 'Europe/London', 'YYYY-MM-DD HH24:MI:SS'),
  COALESCE(EXTRACT(EPOCH FROM (COALESCE(r.ended_at, NOW()) - r.started_at))::int,0)::int
FROM runs r
ORDER BY r.started_at DESC
LIMIT 1;
")"
  IFS=$'\t' read -r latest_run_id latest_status latest_started latest_duration <<<"${latest_query:-na\tna\tna\tna}"
fi

n8n_live_id="na"
n8n_live_status="na"
if [[ -n "${N8N_PUBLIC_API_KEY:-}" && -n "${N8N_ALERT_WORKFLOW_ID:-}" ]]; then
  n8n_line="$(python3 - "${N8N_API_BASE_URL:-http://127.0.0.1:5678/api/v1}" "${N8N_PUBLIC_API_KEY}" "${N8N_ALERT_WORKFLOW_ID}" <<'PY'
import json
import sys
import urllib.parse
import urllib.request

base, key, wf = sys.argv[1:4]
url = f"{base.rstrip('/')}/executions?" + urllib.parse.urlencode({"limit": 5, "workflowId": wf})
try:
    req = urllib.request.Request(url, headers={"X-N8N-API-KEY": key})
    data = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
    items = data.get("data", [])
    if items:
        first = items[0]
        print(f"{first.get('id','na')}\t{first.get('status','na')}")
    else:
        print("na\tna")
except Exception:
    print("na\terror")
PY
)"
  IFS=$'\t' read -r n8n_live_id n8n_live_status <<<"${n8n_line:-na\tna}"
fi

echo "daily_digest: run_log=${run_state} heartbeat_epoch=${heartbeat_epoch} heartbeat_age=${heartbeat_age}"
echo "daily_digest: latest_run=${latest_run_id} status=${latest_status} started=${latest_started} duration_sec=${latest_duration}"
echo "n8n: state_execution_id=${n8n_exec} alert_done_date=${n8n_done} live_execution_id=${n8n_live_id} live_status=${n8n_live_status}"
if [[ -f "$RUN_LOG" ]]; then
  echo "run_tail:"
  tail -n 20 "$RUN_LOG"
fi
