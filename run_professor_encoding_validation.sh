#!/usr/bin/env bash
set -euo pipefail

mode="${1:-full}"
stamp="$(date +%Y%m%d_%H%M%S)"
out="${2:-results_optimized/professor_encoding_validation_${stamp}}"

case "$mode" in
  quick|full|extended) ;;
  *)
    echo "usage: $0 [quick|full|extended] [output_dir]" >&2
    exit 2
    ;;
esac

mkdir -p "$out/logs"

echo "output_root=$out"
echo "mode=$mode"
echo "started=$(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "step_timeout_seconds=${VALIDATION_STEP_TIMEOUT_SECONDS:-none}"

run_step() {
  local name="$1"
  shift
  local log="$out/logs/${name}.log"
  echo
  echo "=== $name ==="
  echo "command=$*" | tee "$log"
  if [[ -n "${VALIDATION_STEP_TIMEOUT_SECONDS:-}" ]]; then
    timeout "${VALIDATION_STEP_TIMEOUT_SECONDS}" "$@" 2>&1 | tee -a "$log"
  else
    "$@" 2>&1 | tee -a "$log"
  fi
}

run_step professor_controls \
  venv/bin/python test_professor_encoding_controls.py

run_step exact_tfo_miter \
  venv/bin/python test_alg10_tfo_miter.py

run_step frontier_shard_probe \
  venv/bin/python test_alg10_frontier_shard_probe.py

run_step parallel_commit_coordinator \
  venv/bin/python test_alg10_parallel_commit_coordinator.py

run_step bounded_encoding_2x2 \
  venv/bin/python test_encoding_soundness_bounded.py \
    --max-inputs 2 \
    --max-gates 2 \
    --progress-interval 0

if [[ "$mode" == "quick" ]]; then
  echo
  echo "finished=$(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "Quick validation complete."
  exit 0
fi

run_step bounded_encoding_depth3 \
  venv/bin/python test_encoding_soundness_bounded.py \
    --max-inputs 2 \
    --max-gates 2 \
    --include-depth3 \
    --progress-interval 10000

run_step thesis_correctness_stress \
  venv/bin/python thesis_correctness_stress.py \
    --seconds 20 \
    --budgets 1000,5000,20000 \
    --include-c7552 \
    --include-epfl \
    --output-dir "$out/thesis_correctness_stress"

if [[ "$mode" == "extended" ]]; then
  run_step bounded_encoding_3x2 \
    venv/bin/python test_encoding_soundness_bounded.py \
      --max-inputs 3 \
      --max-gates 2 \
      --progress-interval 10000

  run_step thesis_correctness_stress_40s \
    venv/bin/python thesis_correctness_stress.py \
      --seconds 40 \
      --budgets 1000,5000,20000,100000 \
      --include-c7552 \
      --include-epfl \
      --output-dir "$out/thesis_correctness_stress_40s"
fi

echo
echo "finished=$(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "Validation complete."
