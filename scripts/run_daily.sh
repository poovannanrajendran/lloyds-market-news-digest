#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs"
LOG_FILE="$LOG_DIR/run_$(date +%Y-%m-%d).log"
NOTIFY_SCRIPT="$ROOT_DIR/scripts/notify_webhooks.sh"
CURRENT_STEP="bootstrap"

mkdir -p "$LOG_DIR"

notify() {
  local message="$1"
  local level="${2:-info}"
  if [[ -x "$NOTIFY_SCRIPT" ]]; then
    "$NOTIFY_SCRIPT" "$message" "$level" || true
  fi
}

git_commit_and_push_if_dirty() {
  local phase_label="$1"
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    return 0
  fi

  # Include all tracked/untracked changes.
  git add -A

  if ! git diff --cached --quiet; then
    local commit_msg="automation: ${phase_label} snapshot $(date -Iseconds)"
    git commit -m "$commit_msg"
    git push origin "$CURRENT_BRANCH"
  fi
}

build_audit_summary() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "audit=unavailable"
    return 0
  fi

  python3 - <<'PY' 2>/dev/null || echo "audit=unavailable"
import os
from datetime import date

try:
    import psycopg
except Exception:
    print("audit=unavailable")
    raise SystemExit(0)

host = os.environ.get("POSTGRES_HOST")
port = os.environ.get("POSTGRES_PORT")
db = os.environ.get("POSTGRES_DB")
user = os.environ.get("POSTGRES_USER")
pwd = os.environ.get("POSTGRES_PASSWORD")
if not all([host, port, db, user, pwd]):
    print("audit=unavailable")
    raise SystemExit(0)

conn_str = f"host={host} port={port} dbname={db} user={user} password={pwd}"
today = date.today().isoformat()

with psycopg.connect(conn_str) as conn:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT run_id,
                   COALESCE(metrics->>'candidates','0'),
                   COALESCE(metrics->>'fetched','0'),
                   COALESCE(metrics->>'extracted','0'),
                   COALESCE(metrics->>'errors','0')
            FROM runs
            WHERE run_date = %s
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (today,),
        )
        run_row = cur.fetchone()

        cur.execute(
            """
            SELECT COALESCE(item_count,0)
            FROM digests
            WHERE run_date = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (today,),
        )
        dig_row = cur.fetchone()

if not run_row:
    print(f"date={today} run=missing")
else:
    run_id, candidates, fetched, extracted, errors = run_row
    items = dig_row[0] if dig_row else 0
    print(
        f"date={today} run_id={run_id} candidates={candidates} fetched={fetched} "
        f"extracted={extracted} errors={errors} digest_items={items}"
    )
PY
}

on_error() {
  local exit_code="$?"
  notify "Run failed at step='$CURRENT_STEP' (exit=$exit_code) on $(date -Is). See $LOG_FILE" "error"
}

trap on_error ERR

if command -v conda >/dev/null 2>&1; then
  CURRENT_STEP="conda_activate"
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate 314
fi

cd "$ROOT_DIR"

export PYTHONPATH="$ROOT_DIR/src:${PYTHONPATH:-}"

# Keep runner aligned with upstream to avoid non-fast-forward push failures.
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  CURRENT_STEP="git_pull"
  CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
  CURRENT_STEP="git_pre_commit_push"
  git_commit_and_push_if_dirty "pre-run"
  CURRENT_STEP="git_pull"
  git pull --ff-only origin "$CURRENT_BRANCH"
fi

CURRENT_STEP="pipeline_run"
python -m lloyds_digest run --now --verbose | tee -a "$LOG_FILE"
CURRENT_STEP="render_digest"
python scripts/render_digest_llm_compare.py | tee -a "$LOG_FILE"
CURRENT_STEP="render_linkedin_post"
python scripts/render_linkedin_post.py | tee -a "$LOG_FILE"
CURRENT_STEP="render_linkedin_image"
python scripts/render_linkedin_image_from_template.py | tee -a "$LOG_FILE"
CURRENT_STEP="publish_pages"
scripts/publish_github_pages.sh | tee -a "$LOG_FILE"
CURRENT_STEP="render_dashboard"
python scripts/render_run_dashboard.py | tee -a "$LOG_FILE"

# Heartbeat for missed-run watchdog.
date +%s > "$LOG_DIR/last_daily_success_epoch.txt"

CURRENT_STEP="git_post_commit_push"
git_commit_and_push_if_dirty "post-run"

if [[ "${ALERT_NOTIFY_ON_SUCCESS:-1}" == "1" ]]; then
  AUDIT_SUMMARY="$(build_audit_summary)"
  notify "Run completed successfully on $(date -Is). ${AUDIT_SUMMARY}. Log: $LOG_FILE" "success"
fi
