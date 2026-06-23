#!/usr/bin/env bash
set -euo pipefail

tag="${RUN_TAG:-native_tfo_7h_$(date +%Y%m%d_%H%M%S)}"
output_dir="results_optimized/parallel_tfo_${tag}"

exec venv/bin/python -u alg10_native_tfo_7h_campaign.py \
  --output-dir "$output_dir" \
  --seconds 25200 \
  "$@"
