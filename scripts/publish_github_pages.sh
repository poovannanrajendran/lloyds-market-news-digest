#!/usr/bin/env bash
set -euo pipefail
STARTED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="$ROOT_DIR/output"
DRY_RUN="${DRY_RUN:-0}"
export PYTHONPATH="$ROOT_DIR/src:${PYTHONPATH:-}"

if command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo "Python interpreter not found (python/python3)."
  exit 1
fi

publish_from_clean_worktree() {
  local run_date="$1"
  local latest_file="$2"
  local latest_basename="$3"
  local dry_run="$4"
  local commit_msg="$5"
  local worktree_dir
  local post_rel=""
  local image_rel=""
  local image_source=""
  local logo_source
  local status=0

  logo_source="$ROOT_DIR/src/images/London_Lloyds_Market_News_Digest.png"
  worktree_dir="$(mktemp -d /tmp/lloyds-publish-XXXXXX)"

  git -C "$ROOT_DIR" fetch origin main
  git -C "$ROOT_DIR" worktree add --detach "$worktree_dir" origin/main

  (
    set -euo pipefail

    cd "$worktree_dir"
    mkdir -p docs/digests docs/assets

    cp "$latest_file" "docs/digests/$latest_basename"

    if [[ -f "$logo_source" ]]; then
      cp "$logo_source" "docs/digests/London_Lloyds_Market_News_Digest.png"
    fi

    if [[ -n "$run_date" ]]; then
      image_source="$OUTPUT_DIR/linkedin_images/linkedin_image_${run_date}.png"
      if [[ -f "$image_source" ]]; then
        cp "$image_source" "docs/assets/linkedin_image_${run_date}.png"
        echo "Published LinkedIn image: docs/assets/linkedin_image_${run_date}.png"
      else
        echo "LinkedIn image not found for ${run_date}: $image_source"
      fi
    fi

    "$PYTHON_BIN" scripts/update_github_pages_index.py \
      --site-dir "docs" \
      --archive-limit 30 \
      --allow-index-fallback

    git add docs

    if [[ -n "$run_date" ]]; then
      post_rel="output/linkedin/linkedin_post_${run_date}.txt"
      image_rel="output/linkedin_images/linkedin_image_${run_date}.png"

      if [[ -f "$ROOT_DIR/$post_rel" ]]; then
        mkdir -p "$(dirname "$post_rel")"
        cp "$ROOT_DIR/$post_rel" "$post_rel"
        git add "$post_rel"
      fi

      if [[ -f "$ROOT_DIR/$image_rel" ]]; then
        mkdir -p "$(dirname "$image_rel")"
        cp "$ROOT_DIR/$image_rel" "$image_rel"
        git add "$image_rel"
      fi
    fi

    if git diff --cached --quiet; then
      echo "No publish changes to commit against origin/main."
      exit 0
    fi

    if [[ "$dry_run" == "1" ]]; then
      echo "DRY_RUN=1: skipping git commit/push in publish_github_pages.sh"
      exit 0
    fi

    git commit -m "$commit_msg"

    for attempt in 1 2 3; do
      if git push origin HEAD:main; then
        echo "Publish push succeeded (attempt ${attempt})."
        exit 0
      fi

      if [[ "$attempt" -eq 3 ]]; then
        echo "Publish push failed after ${attempt} attempts."
        exit 1
      fi

      echo "Push rejected; fetching/rebasing and retrying (attempt ${attempt})."
      git fetch origin main
      git rebase origin/main
      sleep 2
    done
  ) || status=$?

  git -C "$ROOT_DIR" worktree remove --force "$worktree_dir" || true
  rm -rf "$worktree_dir" || true

  return "$status"
}

cd "$ROOT_DIR"
export OUTPUT_DIR

LATEST_FILE="$("$PYTHON_BIN" - <<'PY'
import os
import re
from pathlib import Path

output_dir = Path(os.environ["OUTPUT_DIR"])
pattern = re.compile(r"^digest_\d{4}-\d{2}-\d{2}\.html$")
files = [p for p in output_dir.glob("digest_*.html") if pattern.match(p.name)]
files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
if not files:
    raise SystemExit(1)
print(files[0])
PY
)"

if [[ -z "$LATEST_FILE" ]]; then
  echo "No digest found in output/ (digest_YYYY-MM-DD.html)."
  exit 1
fi

LATEST_BASENAME="$(basename "$LATEST_FILE")"
RUN_DATE=""
if [[ "$LATEST_BASENAME" =~ ^digest_([0-9]{4}-[0-9]{2}-[0-9]{2})\.html$ ]]; then
  RUN_DATE="${BASH_REMATCH[1]}"
fi

publish_from_clean_worktree \
  "$RUN_DATE" \
  "$LATEST_FILE" \
  "$LATEST_BASENAME" \
  "$DRY_RUN" \
  "publish: $(date +%Y-%m-%d)"

ENDED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
"$PYTHON_BIN" scripts/log_phase_timing.py --phase publish_pages --started-at "$STARTED_AT" --ended-at "$ENDED_AT" || true
