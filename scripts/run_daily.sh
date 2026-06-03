#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs"
LOG_FILE="$LOG_DIR/run_$(date +%Y-%m-%d).log"
NOTIFY_SCRIPT="$ROOT_DIR/scripts/notify_webhooks.sh"
CURRENT_STEP="bootstrap"
CURRENT_BRANCH="main"

mkdir -p "$LOG_DIR"

iso_now() {
  date -Is 2>/dev/null || date "+%Y-%m-%dT%H:%M:%S%z"
}

notify() {
  local message="$1"
  local level="${2:-info}"
  if [[ -x "$NOTIFY_SCRIPT" ]]; then
    "$NOTIFY_SCRIPT" "$message" "$level" || true
  fi
}

file_mtime_epoch() {
  local path="$1"
  stat -c %Y "$path" 2>/dev/null || stat -f %m "$path" 2>/dev/null
}

preflight_disk_space() {
  local path="${1:-$ROOT_DIR}"
  local min_free_mb="${RUN_DAILY_MIN_FREE_MB:-2048}"
  local free_mb

  free_mb="$(df -Pm "$path" | awk 'NR == 2 {print $4}')"
  if [[ -z "$free_mb" ]]; then
    notify "Unable to determine free disk space for ${path}; continuing run." "warning"
    return 0
  fi

  if (( free_mb < min_free_mb )); then
    notify "Daily run blocked: only ${free_mb}MB free at ${path}; minimum is ${min_free_mb}MB." "error"
    return 1
  fi
}

git_cleanup_stale_locks() {
  local lock_path=".git/index.lock"
  local max_age_seconds="${RUN_DAILY_GIT_LOCK_MAX_AGE_SECONDS:-900}"
  local now_epoch lock_epoch lock_age

  [[ -f "$lock_path" ]] || return 0

  if pgrep -u "$(id -u)" -x git >/dev/null 2>&1; then
    notify "Found ${lock_path}, but a git process is active; leaving lock in place." "warning"
    return 0
  fi

  now_epoch="$(date +%s)"
  lock_epoch="$(file_mtime_epoch "$lock_path" || true)"
  if [[ -z "$lock_epoch" ]]; then
    notify "Found ${lock_path}, but could not read lock age; leaving lock in place." "warning"
    return 0
  fi

  lock_age=$((now_epoch - lock_epoch))
  if (( lock_age >= max_age_seconds )); then
    rm -f "$lock_path"
    notify "Removed stale ${lock_path} (${lock_age}s old) before run." "warning"
  else
    notify "Found fresh ${lock_path} (${lock_age}s old); leaving lock in place." "warning"
  fi
}

activate_python_environment() {
  local env_name="${CONDA_ENV_NAME:-314}"
  local conda_base=""

  export CONDA_NO_PLUGINS="${CONDA_NO_PLUGINS:-true}"

  if command -v conda >/dev/null 2>&1; then
    if conda_base="$(CONDA_NO_PLUGINS=true conda info --base 2>/dev/null)" && [[ -n "$conda_base" && -f "$conda_base/etc/profile.d/conda.sh" ]]; then
      # shellcheck disable=SC1090
      source "$conda_base/etc/profile.d/conda.sh"
      if conda activate "$env_name"; then
        return 0
      fi
      notify "Conda activation failed for env '${env_name}'; falling back to Python path." "warning"
    else
      notify "Conda profile unavailable; falling back to Python path." "warning"
    fi
  fi

  if [[ -x "$HOME/miniconda3/envs/$env_name/bin/python" ]]; then
    export PATH="$HOME/miniconda3/envs/$env_name/bin:$PATH"
  elif [[ -x "$HOME/miniconda3/bin/python" ]]; then
    export PATH="$HOME/miniconda3/bin:$PATH"
  else
    notify "No Conda Python found under $HOME/miniconda3; using current PATH." "warning"
  fi
}

validate_python_runtime() {
  if ! command -v python >/dev/null 2>&1; then
    notify "Daily run blocked: python is not available on PATH." "error"
    return 1
  fi

  python - <<'PY'
import lloyds_digest
import requests
import bs4
import feedparser
import trafilatura
import readability
import psycopg
import pymongo
from PIL import Image
PY
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
    local commit_msg="automation: ${phase_label} snapshot $(iso_now)"
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
  notify "Run failed at step='$CURRENT_STEP' (exit=$exit_code) on $(iso_now). See $LOG_FILE" "error"
}

trap on_error ERR

CURRENT_STEP="disk_preflight"
preflight_disk_space "$ROOT_DIR"

CURRENT_STEP="python_environment"
activate_python_environment

cd "$ROOT_DIR"

export PYTHONPATH="$ROOT_DIR/src:${PYTHONPATH:-}"

CURRENT_STEP="python_preflight"
validate_python_runtime

# Keep runner aligned with upstream to avoid non-fast-forward push failures.
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  CURRENT_STEP="git_lock_cleanup"
  git_cleanup_stale_locks
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

# Keep the published site files from origin/main in the working tree so the
# final snapshot does not accidentally record them as deletions while still
# preserving generated outputs under output/.
git checkout -- docs >/dev/null 2>&1 || true

CURRENT_STEP="git_post_commit_push"
git_commit_and_push_if_dirty "post-run"

if [[ "${ALERT_NOTIFY_ON_SUCCESS:-1}" == "1" ]]; then
  AUDIT_SUMMARY="$(build_audit_summary)"
  notify "Run completed successfully on $(iso_now). ${AUDIT_SUMMARY}. Log: $LOG_FILE" "success"
fi
