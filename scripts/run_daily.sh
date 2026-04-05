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

if [[ "${ALERT_NOTIFY_ON_SUCCESS:-1}" == "1" ]]; then
  notify "Run completed successfully on $(date -Is). Log: $LOG_FILE" "success"
fi
