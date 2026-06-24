#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DATASET="${DATASET:-helper_code/sweap_eval_full_v2.jsonl}"
S3_DEST="${S3_DEST:-traj_s3/all}"
REPOS_ROOT="${REPOS_ROOT:-analysis/repos}"
REPO_MANIFEST="${REPO_MANIFEST:-analysis/output/repo_availability.json}"
DERIVED_RESULTS_ROOT="${DERIVED_RESULTS_ROOT:-analysis/output/derived_eval_results}"

if [[ -z "${OFFICIAL_RESULTS_ROOT:-}" ]]; then
  if [[ -d "traj" ]]; then
    OFFICIAL_RESULTS_ROOT="traj"
  else
    OFFICIAL_RESULTS_ROOT="$S3_DEST"
  fi
fi

echo "==> Downloading SWE-Bench Pro artifacts from S3"
scripts/download_s3_results.sh "" "$S3_DEST"

echo "==> Preparing repository cache"
python3 scripts/prepare_failure_analysis_repos.py \
  --dataset "$DATASET" \
  --repos-root "$REPOS_ROOT" \
  --manifest "$REPO_MANIFEST"

echo "==> Building eval_results.json files"
python3 scripts/build_derived_eval_results.py \
  --dataset "$DATASET" \
  --eval-root "$S3_DEST" \
  --official-results-root "$OFFICIAL_RESULTS_ROOT" \
  --out-root "$DERIVED_RESULTS_ROOT"

echo "==> Init complete"
echo "Artifacts: $S3_DEST"
echo "Repos: $REPOS_ROOT"
echo "Repo manifest: $REPO_MANIFEST"
echo "Eval results: $DERIVED_RESULTS_ROOT"
