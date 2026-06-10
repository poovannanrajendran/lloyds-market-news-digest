#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NOTIFY_SCRIPT="$ROOT_DIR/scripts/notify_webhooks.sh"
STATE_FILE="$ROOT_DIR/logs/n8n_last_seen_execution_id.txt"
DONE_FILE="$ROOT_DIR/logs/n8n_alert_done_date.txt"

# Required:
# - N8N_PUBLIC_API_KEY
# - N8N_ALERT_WORKFLOW_ID
# Optional:
# - N8N_API_BASE_URL (default: http://127.0.0.1:5678/api/v1)
# - N8N_ALERT_NOTIFY_ON_SUCCESS (default: 0)
# - N8N_ALERT_WORKFLOW_NAME (display only)
# - N8N_ALERT_FINAL_CUTOFF_LOCAL (default: 10:05; do not finalize errors before fallback schedule)

N8N_API_BASE_URL="${N8N_API_BASE_URL:-http://127.0.0.1:5678/api/v1}"
WORKFLOW_ID="${N8N_ALERT_WORKFLOW_ID:-}"
WORKFLOW_NAME="${N8N_ALERT_WORKFLOW_NAME:-}"
NOTIFY_SUCCESS="${N8N_ALERT_NOTIFY_ON_SUCCESS:-0}"
ALERT_FINAL_CUTOFF_LOCAL="${N8N_ALERT_FINAL_CUTOFF_LOCAL:-10:05}"

if [[ ! -x "$NOTIFY_SCRIPT" ]]; then
  exit 0
fi

if [[ -z "${N8N_PUBLIC_API_KEY:-}" || -z "$WORKFLOW_ID" ]]; then
  exit 0
fi

mkdir -p "$ROOT_DIR/logs"

today="$(date +%F)"
if [[ -f "$DONE_FILE" ]]; then
  done_date="$(tr -d '[:space:]' < "$DONE_FILE" || true)"
  if [[ "$done_date" == "$today" ]]; then
    exit 0
  fi
fi

mark_done_today() {
  local final_status="$1"
  echo "$today" > "$DONE_FILE"
  echo "n8n-alert: marked done for $today (status=$final_status)"
}

RAW="$(python3 - "$N8N_API_BASE_URL" "$N8N_PUBLIC_API_KEY" "$WORKFLOW_ID" <<'PY'
import json
import sys
import urllib.parse
import urllib.request

base_url, api_key, workflow_id = sys.argv[1:4]
params = urllib.parse.urlencode({"limit": 25, "workflowId": workflow_id})
url = f"{base_url.rstrip('/')}/executions?{params}"
req = urllib.request.Request(url, headers={"X-N8N-API-KEY": api_key})

with urllib.request.urlopen(req, timeout=15) as resp:
    data = json.loads(resp.read().decode("utf-8"))

items = data.get("data", [])
if not items:
    print("{}")
    raise SystemExit(0)

# API returns newest first.
latest = items[0]
print(json.dumps(latest))
PY
)"

if [[ -z "$RAW" || "$RAW" == "{}" ]]; then
  exit 0
fi

latest_id="$(python3 - "$RAW" <<'PY'
import json
import sys
obj = json.loads(sys.argv[1])
print(obj.get("id", ""))
PY
)"

if [[ -z "$latest_id" ]]; then
  exit 0
fi

previous_id=""
if [[ -f "$STATE_FILE" ]]; then
  previous_id="$(tr -d '[:space:]' < "$STATE_FILE" || true)"
fi

# First run seeds state without alert storm.
if [[ -z "$previous_id" ]]; then
  echo "$latest_id" > "$STATE_FILE"
  exit 0
fi

if [[ "$latest_id" == "$previous_id" ]]; then
  exit 0
fi

echo "$latest_id" > "$STATE_FILE"

readarray -t parsed < <(python3 - "$RAW" <<'PY'
import json
import sys
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

obj = json.loads(sys.argv[1])

def parse_dt(s):
    if not s:
        return None
    # n8n API gives ISO timestamps with Z.
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

eid = str(obj.get("id", ""))
status = str(obj.get("status", "unknown"))
mode = str(obj.get("mode", "unknown"))
wf_id = str(obj.get("workflowId", ""))
wf_name = str(obj.get("workflowName", ""))
retry_of = obj.get("retryOf")
started_at = obj.get("startedAt")
stopped_at = obj.get("stoppedAt")

start_dt = parse_dt(started_at)
stop_dt = parse_dt(stopped_at)
duration_ms = ""
if start_dt and stop_dt:
    duration_ms = str(int((stop_dt - start_dt).total_seconds() * 1000))

run_data = obj.get("data", {}).get("resultData", {}).get("runData", {}) if isinstance(obj.get("data"), dict) else {}
nodes_executed = len(run_data.keys()) if isinstance(run_data, dict) else 0

print(eid)
print(status)
print(mode)
print(wf_id)
print(wf_name)
print("" if retry_of is None else str(retry_of))
print("" if started_at is None else str(started_at))
print("" if stopped_at is None else str(stopped_at))
print(duration_ms)
print(str(nodes_executed))
started_local_date = ""
if start_dt:
    if ZoneInfo is not None:
        started_local_date = start_dt.astimezone(ZoneInfo("Europe/London")).date().isoformat()
    else:
        started_local_date = start_dt.date().isoformat()
print(started_local_date)
PY
)

eid="${parsed[0]:-}"
status="${parsed[1]:-unknown}"
mode="${parsed[2]:-unknown}"
wf_id="${parsed[3]:-$WORKFLOW_ID}"
wf_name_from_api="${parsed[4]:-}"
retry_of="${parsed[5]:-}"
started_at="${parsed[6]:-}"
stopped_at="${parsed[7]:-}"
duration_ms="${parsed[8]:-}"
nodes_executed="${parsed[9]:-0}"
started_local_date="${parsed[10]:-}"

if [[ "$started_local_date" != "$today" ]]; then
# Keep polling until we see today's execution, do not finalize day on stale executions.
  exit 0
fi

wf_display="$WORKFLOW_NAME"
if [[ -z "$wf_display" ]]; then
  wf_display="$wf_name_from_api"
fi
if [[ -z "$wf_display" ]]; then
  wf_display="$wf_id"
fi

message="n8n workflow='${wf_display}' execution_id=${eid} status=${status} mode=${mode}"
message="${message} started=${started_at:-na} stopped=${stopped_at:-na} duration_ms=${duration_ms:-na} nodes_executed=${nodes_executed}"
if [[ -n "$retry_of" ]]; then
  message="${message} retry_of=${retry_of}"
fi

if [[ "$status" == "error" || "$status" == "failed" || "$status" == "crashed" ]]; then
  current_local_time="$(date +%H:%M)"
  if [[ "$current_local_time" < "$ALERT_FINAL_CUTOFF_LOCAL" ]]; then
    echo "n8n-alert: observed status=$status for execution_id=$eid before fallback cutoff=$ALERT_FINAL_CUTOFF_LOCAL; waiting for retry"
    exit 0
  fi
  "$NOTIFY_SCRIPT" "$message" "error" || true
  mark_done_today "$status"
elif [[ "$status" == "success" && "$NOTIFY_SUCCESS" == "1" ]]; then
  "$NOTIFY_SCRIPT" "$message" "success" || true
  mark_done_today "$status"
elif [[ "$status" == "success" && "$NOTIFY_SUCCESS" != "1" ]]; then
  mark_done_today "$status"
fi
