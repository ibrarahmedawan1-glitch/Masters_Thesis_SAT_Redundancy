#!/usr/bin/env bash
set -euo pipefail

stamp="$(date +%Y%m%d_%H%M%S)"
out="${1:-results_optimized/abc_then_tfo_whole_suite_${stamp}}"
mkdir -p "$out"
echo "output_root=$out"

venv/bin/python abc_then_tfo_whole_suite_experiment.py \
  --output-root "$out" \
  --flows strash,balance,rewrite,refactor,dc2,dch,fraig,resyn2,resyn2x2,dc2_fraig,dch_resyn2 \
  --abc-timeout 300 \
  --cec-timeout 180 \
  --seconds-per-flow 90 \
  --jobs 12 \
  --budgets 10000 \
  --max-generated-budget 10000 \
  --deadline-reserve-seconds 5 \
  --unknown-task-guard-seconds 10 \
  2>&1 | tee "$out/run.log"
