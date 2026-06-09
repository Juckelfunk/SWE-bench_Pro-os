#!/usr/bin/env bash
set -euo pipefail

RUN="${1:-}"
DEST="${2:-traj_s3/${RUN:-all}}"
PART="${3:-}"
SRC="s3://scaleapi-results/swe-bench-pro/${RUN:+$RUN/}${PART:+$PART/}"

if [[ "$RUN" == "--eval-only" ]]; then
  DEST="${2:-traj_s3/eval_only}"
  aws s3 sync "s3://scaleapi-results/swe-bench-pro/" "$DEST" \
    --exclude "*" \
    --include "*/eval/*" \
    --include "*/output/eval_results.json"
else
  aws s3 sync "$SRC" "$DEST"
fi
