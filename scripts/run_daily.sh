#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs"
LOG_FILE="$LOG_DIR/run_$(date +%Y-%m-%d).log"

mkdir -p "$LOG_DIR"

if command -v conda >/dev/null 2>&1; then
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate 314
fi

cd "$ROOT_DIR"

python -m lloyds_digest run --now --verbose | tee -a "$LOG_FILE"
python scripts/render_digest_llm_compare.py --provider chatgpt --linkedin | tee -a "$LOG_FILE"
