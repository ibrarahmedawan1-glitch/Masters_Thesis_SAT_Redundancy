#!/usr/bin/env bash
set -euo pipefail

tag="${RUN_TAG:-sin_tfo_4h_$(date +%Y%m%d_%H%M%S)}"
source_aag="results_optimized/datasets/dataset_2026-06-13_13-27-11-814736_finishline_parallel_safe_20260613_132711_sin/custom_epfl_arithmetic_sin.aag"
source_checkpoint="results_optimized/alg10_checkpoints_parallel_tfo_sin_20260614/custom_epfl_arithmetic_sin_b17da687e8a4.json"
output_dir="results_optimized/parallel_tfo_${tag}"
checkpoint_dir="results_optimized/alg10_checkpoints_parallel_tfo_${tag}"

mkdir -p "$output_dir" "$checkpoint_dir"

exec venv/bin/python -u alg10_parallel_commit_coordinator.py \
  "$source_aag" \
  "$output_dir/custom_epfl_arithmetic_sin.aag" \
  --checkpoint-dir "$checkpoint_dir" \
  --checkpoint-json "$source_checkpoint" \
  --worker-engine tfo \
  --recheck-engine tfo \
  --jobs 4 \
  --budgets 10000,50000,250000,1000000,5000000 \
  --batch-size 16 \
  --seconds 14400 \
  --max-generations 100000 \
  --solver cadical153 \
  --order proof_reverse_portfolio \
  --recheck-budget 0 \
  --cec-timeout 120 \
  --report "$output_dir/summary.json" \
  --jsonl "$output_dir/generations.jsonl"
