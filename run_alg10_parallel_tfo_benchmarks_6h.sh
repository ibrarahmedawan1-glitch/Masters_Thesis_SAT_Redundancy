#!/usr/bin/env bash
set -euo pipefail

tag="${RUN_TAG:-benchmarks_tfo_6h_$(date +%Y%m%d_%H%M%S)}"
output_dir="results_optimized/parallel_tfo_${tag}"

mkdir -p "$output_dir"

exec venv/bin/python -u alg10_dynamic_tfo_pool_campaign.py \
  --output-dir "$output_dir" \
  --seconds 21600 \
  --jobs 8 \
  --budgets 10000,50000,250000,1000000,5000000 \
  --budget-growth 2 \
  --max-generated-budget 40000000 \
  --microbatch-size 16 \
  --retry-microbatch-size 1 \
  --deadline-reserve-seconds 300 \
  --unknown-task-guard-seconds 900 \
  --checkpoint-interval 60 \
  --max-targets 6 \
  --target-filter sin,sqrt,hyp,div,log2,mem_ctrl \
  --solver cadical153 \
  --order proof_reverse_portfolio \
  --cec-timeout 180
