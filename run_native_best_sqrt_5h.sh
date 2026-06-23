#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || "${1:-}" == -* ]]; then
  cat <<'USAGE'
Usage: ./run_native_best_sqrt_5h.sh [output_dir]

Environment overrides:
  RUN_SECONDS=18000
  WORKERS=12
  SOLVER=cadical153
  DRY_RUN=1
USAGE
  exit 0
fi

RUN_DIR="${1:-results_optimized/native_tfo_continue_best_sqrt_5h_20260622}"
SEED_CHECKPOINT="${SEED_CHECKPOINT:-results_optimized/native_tfo_continue_best_sqrt_smoke_20260622/epfl_arithmetic_sqrt/checkpoints/epfl_epfl_arithmetic_sqrt_02dcd1dab783.json}"
RUN_SECONDS="${RUN_SECONDS:-18000}"
WORKERS="${WORKERS:-12}"
WORKER_CACHE_ENTRIES="${WORKER_CACHE_ENTRIES:-2}"
PERSISTENT_RETRY_TIERS="${PERSISTENT_RETRY_TIERS:-3}"
SOLVER="${SOLVER:-cadical153}"
DRY_RUN="${DRY_RUN:-0}"

mkdir -p "$RUN_DIR"
echo "$$" > "$RUN_DIR/native_campaign.pid"
exec > >(tee -a "$RUN_DIR/run.log") 2>&1

echo "run_dir=$RUN_DIR"
echo "seed_checkpoint=$SEED_CHECKPOINT"
echo "seconds=$RUN_SECONDS workers=$WORKERS solver=$SOLVER"
echo "dry_run=$DRY_RUN"

cmd=(
  venv/bin/python alg10_native_tfo_7h_campaign.py
  --checkpoint-json "$SEED_CHECKPOINT" \
  --output-dir "$RUN_DIR" \
  --seconds "$RUN_SECONDS" \
  --workers "$WORKERS" \
  --worker-cache-entries "$WORKER_CACHE_ENTRIES" \
  --persistent-retry-tiers "$PERSISTENT_RETRY_TIERS" \
  --solver "$SOLVER"
)
if [[ "$DRY_RUN" != "0" ]]; then
  cmd+=(--dry-run)
fi

exec "${cmd[@]}"
