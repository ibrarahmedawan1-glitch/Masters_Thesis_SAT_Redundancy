#!/usr/bin/env bash
set -eu

tag="${RUN_TAG:-sqrt_30m_$(date +%Y%m%d_%H%M%S)}"
source_aag="results_optimized/datasets/dataset_2026-06-13_13-27-11-816457_finishline_parallel_safe_20260613_132711_sqrt/custom_epfl_arithmetic_sqrt.aag"
source_checkpoint="results_optimized/alg10_checkpoints_parallel_finishline_parallel_safe_20260613_132711_sqrt/custom_epfl_arithmetic_sqrt_02dcd1dab783.json"
output_dir="results_optimized/parallel_commit_${tag}"
checkpoint_dir="results_optimized/alg10_checkpoints_parallel_commit_${tag}"

mkdir -p "$output_dir" "$checkpoint_dir"

exec venv/bin/python -u alg10_parallel_commit_coordinator.py \
  "$source_aag" \
  "$output_dir/custom_epfl_arithmetic_sqrt.aag" \
  --checkpoint-dir "$checkpoint_dir" \
  --checkpoint-json "$source_checkpoint" \
  --jobs 3 \
  --budgets 500000 \
  --batch-size 12 \
  --seconds 1800 \
  --max-generations 1 \
  --solver cadical153 \
  --order untried_first \
  --cec-timeout 60 \
  --report "$output_dir/summary.json" \
  --jsonl "$output_dir/generations.jsonl"
