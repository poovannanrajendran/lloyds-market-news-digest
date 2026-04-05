#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NOTIFY_SCRIPT="$ROOT_DIR/scripts/notify_webhooks.sh"
ENV_FILE="$ROOT_DIR/.env"
LOG_DIR="$ROOT_DIR/logs"
mkdir -p "$LOG_DIR"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

if [[ ! -x "$NOTIFY_SCRIPT" ]]; then
  echo "notify script missing: $NOTIFY_SCRIPT" >&2
  exit 1
fi

PGHOST_LOCAL="${POSTGRES_HOST:-localhost}"
PGPORT_LOCAL="${POSTGRES_PORT:-5432}"
PGDATABASE_LOCAL="${POSTGRES_DB:-lloyds_digest}"
PGUSER_LOCAL="${POSTGRES_USER:-dbuser}"
PGPASSWORD_LOCAL="${POSTGRES_PASSWORD:-dbuser}"

YOUTUBE_POSTGRES_URI="${YOUTUBE_POSTGRES_URI:-postgresql://dbuser:dbuser@192.168.1.20:5432/youtube_liked_videos}"
YOUTUBE_TABLE="${YOUTUBE_SUMMARY_TABLE:-youtube_videos}"

psql_local() {
  PGPASSWORD="$PGPASSWORD_LOCAL" psql -h "$PGHOST_LOCAL" -p "$PGPORT_LOCAL" -U "$PGUSER_LOCAL" -d "$PGDATABASE_LOCAL" -AtX -F $'\t' -c "$1"
}

psql_yt() {
  psql "$YOUTUBE_POSTGRES_URI" -AtX -F $'\t' -c "$1"
}

now_local="$(TZ=Europe/London date '+%Y-%m-%d %H:%M:%S %Z')"
window_start_local="$(TZ=Europe/London date -d '24 hours ago' '+%Y-%m-%d %H:%M:%S %Z')"

lloyds_metrics="$(psql_local "
SELECT
  COUNT(*)::int,
  COALESCE(SUM(CASE WHEN COALESCE((metrics->>'errors')::int,0)=0 THEN 1 ELSE 0 END),0)::int,
  COALESCE(SUM(CASE WHEN COALESCE((metrics->>'errors')::int,0)>0 THEN 1 ELSE 0 END),0)::int,
  COALESCE(SUM(COALESCE((metrics->>'candidates')::int,0)),0)::int,
  COALESCE(SUM(COALESCE((metrics->>'fetched')::int,0)),0)::int,
  COALESCE(SUM(COALESCE((metrics->>'extracted')::int,0)),0)::int,
  COALESCE(SUM(COALESCE((metrics->>'errors')::int,0)),0)::int
FROM runs
WHERE started_at >= (NOW() - INTERVAL '24 hours');
")"
IFS=$'\t' read -r l_runs l_success l_failed l_candidates l_fetched l_extracted l_errors <<<"${lloyds_metrics:-0\t0\t0\t0\t0\t0\t0}"

lloyds_latest="$(psql_local "
SELECT
  COALESCE(run_id::text,'na'),
  CASE WHEN COALESCE((metrics->>'errors')::int,0)>0 THEN 'failed' ELSE 'success' END,
  TO_CHAR(started_at AT TIME ZONE 'Europe/London', 'YYYY-MM-DD HH24:MI:SS'),
  COALESCE(EXTRACT(EPOCH FROM (COALESCE(ended_at, NOW()) - started_at))::int,0)::int
FROM runs
ORDER BY started_at DESC
LIMIT 1;
")"
IFS=$'\t' read -r l_latest_id l_latest_status l_latest_started l_latest_dur <<<"${lloyds_latest:-na\tunknown\tna\t0}"

l_digest_items="$(psql_local "SELECT COALESCE(SUM(COALESCE(item_count,0)),0)::int FROM digests WHERE created_at >= (NOW() - INTERVAL '24 hours');")"
l_digest_items="${l_digest_items:-0}"

freshness_status="unknown"
if [[ -f "$LOG_DIR/last_daily_success_epoch.txt" ]]; then
  last_epoch="$(tr -d '[:space:]' < "$LOG_DIR/last_daily_success_epoch.txt" || true)"
  if [[ "$last_epoch" =~ ^[0-9]+$ ]]; then
    age_sec="$(( $(date +%s) - last_epoch ))"
    if (( age_sec <= 93600 )); then
      freshness_status="ok"
    else
      freshness_status="stale"
    fi
  fi
fi

n8n_status="unknown"
n8n_exec_id="na"
if [[ -n "${N8N_PUBLIC_API_KEY:-}" && -n "${N8N_ALERT_WORKFLOW_ID:-}" ]]; then
  n8n_line="$(python3 - "${N8N_API_BASE_URL:-http://127.0.0.1:5678/api/v1}" "$N8N_PUBLIC_API_KEY" "$N8N_ALERT_WORKFLOW_ID" <<'PY'
import json,sys,urllib.parse,urllib.request
base=sys.argv[1]
key=sys.argv[2]
wf=sys.argv[3]
url=f"{base.rstrip('/')}/executions?"+urllib.parse.urlencode({'limit':1,'workflowId':wf})
try:
    req=urllib.request.Request(url, headers={'X-N8N-API-KEY':key})
    with urllib.request.urlopen(req, timeout=12) as r:
        data=json.loads(r.read().decode('utf-8'))
    items=data.get('data') or []
    if not items:
        print('na\tunknown')
    else:
        it=items[0]
        print(f"{it.get('id','na')}\t{it.get('status','unknown')}")
except Exception:
    print('na\terror')
PY
)"
  IFS=$'\t' read -r n8n_exec_id n8n_status <<<"${n8n_line:-na\tunknown}"
fi

yt_metrics="$(psql_yt "
SELECT
  COUNT(*)::int,
  COALESCE(SUM(CASE WHEN NULLIF(BTRIM(added_at),'')::timestamptz >= (NOW() - INTERVAL '24 hours') THEN 1 ELSE 0 END),0)::int,
  COALESCE(SUM(CASE WHEN transcript IS NOT NULL AND BTRIM(transcript) <> '' THEN 1 ELSE 0 END),0)::int,
  COALESCE(SUM(CASE WHEN transcript IS NULL OR BTRIM(transcript) = '' THEN 1 ELSE 0 END),0)::int,
  COALESCE(SUM(CASE WHEN NULLIF(BTRIM(added_at),'')::timestamptz >= (NOW() - INTERVAL '24 hours') AND transcript IS NOT NULL AND BTRIM(transcript) <> '' THEN 1 ELSE 0 END),0)::int,
  COALESCE(SUM(CASE WHEN categories IS NULL OR BTRIM(categories) = '' OR tags IS NULL OR BTRIM(tags) = '' THEN 1 ELSE 0 END),0)::int
FROM ${YOUTUBE_TABLE};
")"
IFS=$'\t' read -r yt_total yt_new24 yt_t_present yt_t_missing yt_t_added24 yt_missing_cat_tags <<<"${yt_metrics:-0\t0\t0\t0\t0\t0}"

yt_coverage="0"
if [[ "${yt_total:-0}" -gt 0 ]]; then
  yt_coverage="$(( 100 * yt_t_present / yt_total ))"
fi

yt_latest_added="$(psql_yt "SELECT COALESCE(TO_CHAR((MAX(NULLIF(BTRIM(added_at),'')::timestamptz) AT TIME ZONE 'Europe/London'), 'YYYY-MM-DD HH24:MI:SS'),'na') FROM ${YOUTUBE_TABLE};")"
yt_latest_added="${yt_latest_added:-na}"

level="info"
if [[ "${l_failed:-0}" -gt 0 || "$freshness_status" == "stale" || "$n8n_status" == "error" || "$n8n_status" == "failed" || "$n8n_status" == "crashed" ]]; then
  level="error"
elif [[ "${l_runs:-0}" -eq 0 || "${yt_new24:-0}" -eq 0 ]]; then
  level="warning"
fi

message=$(cat <<MSG
24h Summary (${window_start_local} -> ${now_local})

Lloyds digest:
- runs=${l_runs} success=${l_success} failed=${l_failed}
- latest_run=${l_latest_id} status=${l_latest_status} started=${l_latest_started} duration_sec=${l_latest_dur}
- totals_24h: candidates=${l_candidates} fetched=${l_fetched} extracted=${l_extracted} errors=${l_errors} digest_items=${l_digest_items}
- freshness=${freshness_status}
- n8n latest: execution_id=${n8n_exec_id} status=${n8n_status}

YouTube V5:
- total_videos=${yt_total} new_videos_24h=${yt_new24} latest_added_at=${yt_latest_added}
- transcript: coverage_pct=${yt_coverage} present=${yt_t_present} missing=${yt_t_missing} added_24h=${yt_t_added24}
- enrichment: missing_categories_or_tags=${yt_missing_cat_tags}
MSG
)

if [[ "$DRY_RUN" == "1" ]]; then
  echo "[dry-run] level=$level"
  echo "$message"
  exit 0
fi

"$NOTIFY_SCRIPT" "$message" "$level"
echo "24h-summary: sent at $(date -Is) level=${level}" >> "$LOG_DIR/cron.log"
