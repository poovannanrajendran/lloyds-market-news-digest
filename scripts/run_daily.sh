#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs"
LOG_FILE="$LOG_DIR/run_$(date +%Y-%m-%d).log"
NOTIFY_SCRIPT="$ROOT_DIR/scripts/notify_webhooks.sh"
CURRENT_STEP="bootstrap"
CURRENT_BRANCH="main"

mkdir -p "$LOG_DIR"

notify() {
  local message="$1"
  local level="${2:-info}"
  if [[ -x "$NOTIFY_SCRIPT" ]]; then
    "$NOTIFY_SCRIPT" "$message" "$level" || true
  fi
}

git_push_with_retries() {
  local phase_label="$1"
  local max_attempts="${2:-3}"
  local attempt=1

  while (( attempt <= max_attempts )); do
    if git push origin "$CURRENT_BRANCH"; then
      return 0
    fi

    notify "Git push attempt ${attempt}/${max_attempts} failed during ${phase_label}; retrying without rebase." "warning"
    git fetch origin "$CURRENT_BRANCH" >/dev/null 2>&1 || true
    attempt=$((attempt + 1))
  done

  notify "Git push still failed after ${max_attempts} attempts during ${phase_label}; continuing run." "warning"
  return 1
}

git_abort_stale_rebase() {
  if [[ -d .git/rebase-merge || -d .git/rebase-apply ]]; then
    git rebase --abort >/dev/null 2>&1 || true
    notify "Detected stale git rebase state; aborted before run." "warning"
  fi
}

git_force_align_to_origin() {
  local phase_label="$1"
  if ! git fetch origin "$CURRENT_BRANCH"; then
    notify "Git fetch failed during ${phase_label}; continuing run." "warning"
    return 1
  fi
  if ! git reset --hard "origin/$CURRENT_BRANCH"; then
    notify "Git hard align failed during ${phase_label}; continuing run." "warning"
    return 1
  fi
  return 0
}

git_align_to_origin_preserve_worktree() {
  local phase_label="$1"
  if ! git fetch origin "$CURRENT_BRANCH"; then
    notify "Git fetch failed during ${phase_label}; continuing run." "warning"
    return 1
  fi
  # Move HEAD/index to origin while preserving working tree changes for post-run snapshot.
  if ! git reset --mixed "origin/$CURRENT_BRANCH"; then
    notify "Git mixed reset failed during ${phase_label}; continuing run." "warning"
    return 1
  fi
  return 0
}

git_sync_with_remote() {
  local phase_label="$1"
  local max_attempts="${2:-3}"
  local attempt=1

  while (( attempt <= max_attempts )); do
    if git pull --ff-only origin "$CURRENT_BRANCH"; then
      return 0
    fi
    notify "Git ff-only pull failed during ${phase_label} (attempt ${attempt}/${max_attempts}); trying rebase pull." "warning"
    if git pull --rebase --autostash origin "$CURRENT_BRANCH"; then
      return 0
    fi
    git rebase --abort >/dev/null 2>&1 || true
    attempt=$((attempt + 1))
  done

  notify "Git sync failed after ${max_attempts} attempts during ${phase_label}; continuing run." "warning"
  return 1
}

git_commit_and_push_if_dirty() {
  local phase_label="$1"
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    return 0
  fi

  # Include all tracked/untracked changes.
  if ! git add -A; then
    notify "Git add failed during ${phase_label} snapshot; continuing run." "warning"
    return 0
  fi

  if ! git diff --cached --quiet 2>/dev/null; then
    local commit_msg="automation: ${phase_label} snapshot $(date -Iseconds)"
    if ! git commit -m "$commit_msg"; then
      notify "Git commit failed during ${phase_label} snapshot; continuing run." "warning"
      return 0
    fi
    git_push_with_retries "${phase_label} snapshot" 4 || true
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
  CURRENT_STEP="git_rebase_cleanup"
  git_abort_stale_rebase
  CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
  CURRENT_STEP="git_pre_run_align"
  git_force_align_to_origin "pre-run align" || true
  CURRENT_STEP="git_pre_commit_push"
  git_commit_and_push_if_dirty "pre-run"
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

CURRENT_STEP="git_post_publish_align"
git_align_to_origin_preserve_worktree "post-publish align" || true

CURRENT_STEP="git_post_commit_push"
git_commit_and_push_if_dirty "post-run"

if [[ "${ALERT_NOTIFY_ON_SUCCESS:-1}" == "1" ]]; then
  AUDIT_SUMMARY="$(build_audit_summary)"
  notify "Run completed successfully on $(date -Is). ${AUDIT_SUMMARY}. Log: $LOG_FILE" "success"
fi
