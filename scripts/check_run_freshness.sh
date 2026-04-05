#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP_FILE="$ROOT_DIR/logs/last_daily_success_epoch.txt"
ALERT_FLAG_FILE="$ROOT_DIR/logs/last_daily_missed.alerted"
NOTIFY_SCRIPT="$ROOT_DIR/scripts/notify_webhooks.sh"

# Alert if no successful run happened in the last 30 hours.
MAX_AGE_SECONDS="${DAILY_RUN_MAX_AGE_SECONDS:-108000}"

if [[ ! -x "$NOTIFY_SCRIPT" ]]; then
  exit 0
fi

if [[ ! -f "$STAMP_FILE" ]]; then
  if [[ ! -f "$ALERT_FLAG_FILE" ]]; then
    "$NOTIFY_SCRIPT" "No successful daily run heartbeat found (missing $STAMP_FILE)." "error" || true
    touch "$ALERT_FLAG_FILE"
  fi
  exit 0
fi

last_success_epoch="$(tr -d '[:space:]' < "$STAMP_FILE" || true)"
if [[ -z "$last_success_epoch" || ! "$last_success_epoch" =~ ^[0-9]+$ ]]; then
  if [[ ! -f "$ALERT_FLAG_FILE" ]]; then
    "$NOTIFY_SCRIPT" "Invalid heartbeat timestamp in $STAMP_FILE." "error" || true
    touch "$ALERT_FLAG_FILE"
  fi
  exit 0
fi

now_epoch="$(date +%s)"
age="$(( now_epoch - last_success_epoch ))"

if (( age > MAX_AGE_SECONDS )); then
  if [[ ! -f "$ALERT_FLAG_FILE" ]]; then
    "$NOTIFY_SCRIPT" "Daily run heartbeat is stale: last success was ${age}s ago (> ${MAX_AGE_SECONDS}s)." "error" || true
    touch "$ALERT_FLAG_FILE"
  fi
else
  if [[ -f "$ALERT_FLAG_FILE" ]]; then
    "$NOTIFY_SCRIPT" "Daily run heartbeat recovered. Last success age=${age}s." "info" || true
    rm -f "$ALERT_FLAG_FILE"
  fi
fi

