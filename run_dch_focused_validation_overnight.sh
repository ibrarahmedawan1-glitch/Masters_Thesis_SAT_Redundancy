#!/usr/bin/env bash
set -euo pipefail

stamp="$(date +%Y%m%d_%H%M%S)"
out="${1:-results_optimized/dch_focused_validation_${stamp}}"
baseline_root="results_optimized/abc_then_tfo_whole_suite_20260622_000534/abc_cec_pass_outputs"

mkdir -p "$out"
echo "output_root=$out"
echo "baseline_root=$baseline_root"
echo "started=$(date '+%Y-%m-%d %H:%M:%S %Z')"

run_phase() {
  local label="$1"
  local seconds="$2"
  local circuits="$3"
  local phase_out="$out/$label"

  echo
  echo "phase=$label"
  echo "seconds=$seconds"
  echo "circuits=$circuits"
  echo "phase_started=$(date '+%Y-%m-%d %H:%M:%S %Z')"

  venv/bin/python post_abc_residual_tfo_experiment.py \
    --baseline-root "$baseline_root" \
    --flows dch \
    --circuits "$circuits" \
    --output-dir "$phase_out" \
    --seconds-per-flow "$seconds" \
    --jobs 12 \
    --budgets 10000,50000 \
    --max-generated-budget 50000 \
    --microbatch-size 4 \
    --retry-microbatch-size 1 \
    --deadline-reserve-seconds 30 \
    --unknown-task-guard-seconds 90 \
    --checkpoint-interval 60 \
    --solver cadical153 \
    --order proof_reverse_portfolio \
    --cec-timeout 300

  echo "phase_finished=$(date '+%Y-%m-%d %H:%M:%S %Z')"
}

# Biggest residual producers from the 90s whole-suite dch screen.
run_phase \
  "phase1_top5_6h" \
  21600 \
  "mem_ctrl,log2,multiplier,sqrt,voter"

# Second tier, still thesis-useful, but kept shorter so the full run finishes
# before morning inspection.
run_phase \
  "phase2_next5_2h30m" \
  9000 \
  "square,sin,div,bar,i2c"

echo
echo "finished=$(date '+%Y-%m-%d %H:%M:%S %Z')"
