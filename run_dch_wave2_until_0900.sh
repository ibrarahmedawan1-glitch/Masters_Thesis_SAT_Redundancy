#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

stamp="$(date +%Y%m%d_%H%M%S)"
out="${1:-results_optimized/dch_focused_wave2_until_0900_${stamp}}"
baseline_root="${BASELINE_ROOT:-results_optimized/abc_then_tfo_whole_suite_20260622_000534/abc_cec_pass_outputs}"
circuits="${CIRCUITS:-square,sin,div,bar,i2c}"
workers="${WORKERS:-12}"
budgets="${BUDGETS:-10000,50000}"
max_budget="${MAX_GENERATED_BUDGET:-50000}"
solver="${SOLVER:-cadical153}"
run_until="${RUN_UNTIL:-09:00}"
worker_cache_entries="${WORKER_CACHE_ENTRIES:-2}"
persistent_retry_tiers="${PERSISTENT_RETRY_TIERS:-2}"

if [[ -z "${RUN_SECONDS:-}" ]]; then
  now_epoch="$(date +%s)"
  target_epoch="$(date -d "today ${run_until}" +%s)"
  if (( target_epoch <= now_epoch )); then
    target_epoch="$(date -d "tomorrow ${run_until}" +%s)"
  fi
  RUN_SECONDS="$(( target_epoch - now_epoch - 180 ))"
  if (( RUN_SECONDS < 300 )); then
    RUN_SECONDS=300
  fi
fi

mkdir -p "$out"
echo "$$" > "$out/launcher.pid"
exec > >(tee -a "$out/launcher.log") 2>&1

echo "output_root=$out"
echo "baseline_root=$baseline_root"
echo "flow=dch"
echo "circuits=$circuits"
echo "run_until=$run_until"
echo "seconds=$RUN_SECONDS"
echo "workers=$workers"
echo "budgets=$budgets"
echo "max_generated_budget=$max_budget"
echo "solver=$solver"
echo "worker_cache_entries=$worker_cache_entries"
echo "persistent_retry_tiers=$persistent_retry_tiers"
echo "started=$(date '+%Y-%m-%d %H:%M:%S %Z')"

export ALG10_ALLOW_WORKER_MEMORY_OVERSUBSCRIBE=1

venv/bin/python post_abc_residual_tfo_experiment.py \
  --baseline-root "$baseline_root" \
  --flows dch \
  --circuits "$circuits" \
  --output-dir "$out" \
  --seconds-per-flow "$RUN_SECONDS" \
  --jobs "$workers" \
  --budgets "$budgets" \
  --max-generated-budget "$max_budget" \
  --microbatch-size 4 \
  --retry-microbatch-size 1 \
  --persistent-retry-tiers "$persistent_retry_tiers" \
  --worker-cache-entries "$worker_cache_entries" \
  --deadline-reserve-seconds 120 \
  --unknown-task-guard-seconds 240 \
  --checkpoint-interval 60 \
  --solver "$solver" \
  --order proof_reverse_portfolio \
  --cec-timeout 300

echo "finished=$(date '+%Y-%m-%d %H:%M:%S %Z')"
