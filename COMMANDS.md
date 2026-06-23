# Commands

Common commands for working on the thesis project from the repository root.

## Environment

Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

Install Python dependencies:

```bash
pip install -r requirements.txt
```

## Main Experiment

Run the full interactive thesis pipeline:

```bash
python3 main.py
```

Recommended first algorithm choice for the current pipeline is `9`, the committed in-memory incremental SAT optimizer.
After selecting `9`, choose a runtime mode and dataset profile from the prompts.

Algorithm 9 runtime modes:

- `1`: fast filtered thesis mode.
- `2`: exhaustive stuck-at sweep capped at 50k gates per circuit.
- `3`: filtered large-circuit survey with very-large SAT enabled.
- `4`: full exhaustive stuck-at sweep with no dataset gate cap and no SAT wall-clock abort.

Algorithm 10 is the checkpointed budget-cycling SAT engine. It has two modes:

- `1`: fast save/checkpoint mode with bounded per-circuit runtime.
- `2`: deep resume mode with larger budgets and a longer per-circuit runtime.
- `4`: strict-audit unresolved-to-zero campaign; cycles unresolved circuits using the strict checkpoint directory.
- `5`: strict audit fast save with SAT assumption audits enabled.
- `6`: strict audit enhanced deep with SAT assumption audits, CEX pool, pre-sim rejection, and phase-local resume enabled.

Useful non-interactive Algorithm 10 knobs:

```bash
ALG10_MODE=fast_save ALG10_MAX_CIRCUIT_SECONDS=60 ALG10_BUDGETS=100,1000,5000 python3 main.py
ALG10_MODE=deep_resume ALG10_MAX_CIRCUIT_SECONDS=600 ALG10_BUDGETS=1000,5000,20000,100000 python3 main.py
ALG10_AUDIT_ASSUMPTIONS=1 ALG10_MODE=fast_save ALG10_MAX_CIRCUIT_SECONDS=60 ALG10_BUDGETS=100,1000,5000 python3 main.py
ALG10_TOTAL_SECONDS=43200 ALG10_RESET_CHECKPOINT=0 ALG10_CHECKPOINT_DIR=results_optimized/alg10_checkpoints_strict_audit python3 main.py
```

Checkpoints are written under `results_optimized/alg10_checkpoints/` by default. Set `ALG10_CHECKPOINT_DIR=/path/to/dir` to choose another directory, and `ALG10_RESET_CHECKPOINT=1` to ignore an existing checkpoint.
To seed a campaign from the best known checkpoints in other experiment
families, set `ALG10_EXTRA_CHECKPOINT_DIRS` to a comma-separated list. Matching
still requires the same source SHA, and imported checkpoints use only the safe
`.work.aag`; stale phase-frontier metadata from the other directory is ignored.
Use `ALG10_CHECKPOINT_SELECT=gates` for lowest-gate seeds, or
`ALG10_CHECKPOINT_SELECT=unresolved` for unresolved-to-zero campaigns.
`ALG10_PROTECT_BEST_CHECKPOINT=1` is enabled by default; it prevents a later
cycle from overwriting a better matching checkpoint under the selected policy.

Algorithm 10 also has sound middle tiers before the full global miter:

```bash
ALG10_TFI_CONSTANCY=1 ALG10_TFI_ENGINE=persistent ALG10_TFI_SOLVER=cadical153 ALG10_TFI_BUDGET=500 python3 main.py
ALG10_WINDOW_MITER=1 ALG10_WINDOW_AUDIT=1 ALG10_WINDOW_LEVELS=5 ALG10_WINDOW_BUDGET=500 python3 main.py
ALG10_CONE_MITER=1 ALG10_CONE_ENGINE=hybrid ALG10_CONE_SOLVER=cadical153 ALG10_CONE_GROUP_MIN_SIZE=8 ALG10_CONE_BUDGET=1000 ALG10_CONE_MAX_GATES=5000 python3 main.py
ALG10_CEX_PRUNING=1 python3 main.py
```

The normal Algorithm 10 path in `main.py` now defaults to the best tested profile: current ordering, TFI constancy, audited bounded TFO window, exact affected-output cone, global fallback, and CEX pruning. The variables above are still useful when running ablations or intentionally disabling a tier.
For thesis-critical validation runs, use Alg10 menu option `5` first, then option `6` for deep validation. These presets enable `ALG10_AUDIT_ASSUMPTIONS=1`, which checks global and grouped-cone control assumptions before each SAT call that can accept a candidate. The audit costs some runtime, so long final performance campaigns can use options `3` or `4` after the strict audit presets have passed.

TFI `UNSAT` can commit a stuck-at constant safely. The default persistent TFI engine encodes the current good circuit once and reuses one solver for all constancy queries in the phase; set `ALG10_TFI_ENGINE=local` for the old per-candidate cone encoder. TFI `SAT`, timeout, or skip still escalates to the global miter, so the tier does not remove candidates from coverage.
The bounded TFO window tier is an UNSAT-only over-observable proof: it compares complete fanin cones of nearby fanout boundary roots. With `ALG10_WINDOW_AUDIT=1`, the roots must form a complete observable cut; otherwise the tier skips and escalates. Window `UNSAT` can commit safely only under that complete-cut condition; window `SAT`, timeout, or skip still escalates.
The cone miter compares only the output/latch-next roots affected by a candidate, but it encodes their complete fanin cone. Cone `UNSAT` can commit safely; cone `SAT`, timeout, or skip still escalates to global SAT. The hybrid cone engine reuses one configurable cone solver for larger identical affected-root groups and falls back to the original single-candidate cone miter for small groups.
CEX pruning is rejection-only. TFI CEXs only skip future TFI constancy checks; window/cone/global CEXs prune a candidate only after full-circuit simulation proves that exact candidate creates a real observable mismatch.

Run SAT-side ablation experiments:

```bash
python3 sat_ablation_experiments.py --circuits benchmarks/c7552.aag benchmark_suites/epfl/epfl_arithmetic_sin.aag --seconds 30
```

The full run generates synthetic circuits, copies `.aag` files from `benchmarks/`, optimizes every dataset circuit, verifies each output, and writes a CSV report to:

```text
results_optimized/thesis_results_ALG<id>_<timestamp>.csv
```

Algorithm 9 and Algorithm 10 reports include the selected mode and profile in both the filename and CSV columns.
For Algorithm 10, `main.py` also creates a companion chart folder next to each completed CSV, for example:

```text
results_optimized/thesis_results_ALG10_..._charts/
```

The folder contains a compact dashboard, top unresolved circuits, tier proof/timeout charts, rejection-only pruning charts, resume-progress charts when checkpoint columns are present, and small summary CSVs. Disable this post-run step with `ALG10_AUTO_PLOTS=0` if you need a raw CSV-only run.

## ABC Baseline Comparison

Run ABC-only synthesis flows on the latest Algorithm 10 dataset and compare the
area/depth/runtime/CEC metrics against the latest Alg10 CSV:

```bash
python3 abc_baseline_runner.py
```

Default flows are `strash`, `dc2`, `dch`, `fraig`, `resyn2`, and `resyn2x2`.
The runner writes detailed, summary-by-flow, and best-by-circuit CSVs under:

```text
results_optimized/abc_baselines/<timestamp>/
```

Run a smaller smoke or focused comparison:

```bash
python3 abc_baseline_runner.py --input benchmarks/c432.aag --flows strash,dc2,dch,fraig,resyn2
python3 abc_baseline_runner.py --input results_optimized/datasets/dataset_2026-06-08_19-21-02 --flows dc2,resyn2
python3 abc_baseline_runner.py --max-circuits 3 --flows strash,dc2
```

This is an external context baseline, not a replacement for the SAT pipeline:
ABC flows can perform broader logic synthesis than stuck-at constant redundancy
removal. Still require `Verify=PASS` before using a row in thesis comparisons.

## Plotting

Generate thesis plots from available CSV results:

```bash
python3 thesis_plots.py
```

Check `thesis_plots/` for generated images.
Generate the automatic Algorithm 10 chart bundle for an existing CSV:

```bash
python3 alg10_report_plots.py results_optimized/thesis_results_ALG10_....csv
```

## Benchmark Preparation And Demos

Prepare benchmark files:

```bash
python3 prepare_benchmarks.py
```

Prepare reusable benchmark suites for the main pipeline:

```bash
python3 prepare_benchmark_suites.py --epfl-dir epfl_benchmarks
python3 prepare_benchmark_suites.py --iwls2005-dir benchmark_suites/IWLS_benchmarks_2005_V_1.0
```

The IWLS command reads the extracted IWLS 2005 `*/netlist/*.v` files plus the included `library/GSCLib_3.0.v`, converts successful designs to ASCII AIGER under `benchmark_suites/iwls2005/`, and writes conversion status to `benchmark_suites/manifest.csv`. `main.py` only loads prepared `.aag` files from `benchmark_suites/`, so raw IWLS folders can sit there safely, but they are not benchmark inputs until this preparation step creates `.aag` files.

Run demo experiments:

```bash
python3 run_demo_experiment.py
python3 run_bench_demo.py
python3 demos/run_normalization_demo.py
```

## Partitioned Exact Miter Experiment

Compare the current monolithic exact cone miter with affected-root partitions:

```bash
venv/bin/python partitioned_miter_experiment.py --circuits benchmarks/c7552.aag benchmark_suites/epfl/epfl_arithmetic_sin.aag --partition-sizes 1,2,4,8 --budget 5000 --max-candidates 200 --scan-limit 10000 --seconds 60 --min-affected-roots 2 --classify-tfi
```

Run the bounded multi-output soundness check:

```bash
venv/bin/python test_partitioned_miter_soundness.py --max-inputs 2 --max-gates 2 --output-count 2 --max-output-sets 24 --partition-sizes 1,2 --budget 0
```

Exercise the optional Algorithm 10 cone mode without changing the default:

```bash
ALG10_CONE_ENGINE=partitioned ALG10_CONE_PARTITION_SIZE=1 ALG10_CONE_PARTITION_MIN_ROOTS=2 venv/bin/python main.py
```

Use a separate checkpoint directory for partition experiments, and raise the
partition-only cone cap only when testing hard circuits:

```bash
ALG10_CHECKPOINT_DIR=results_optimized/alg10_checkpoints_partitioned_experiment \
ALG10_CONE_ENGINE=partitioned \
ALG10_CONE_PARTITION_SIZE=1 \
ALG10_CONE_PARTITION_MIN_ROOTS=2 \
ALG10_CONE_PARTITION_MAX_GATES=50000 \
ALG10_AUDIT_ASSUMPTIONS=1 \
venv/bin/python main.py
```

Use partitioned mode as an experiment first. It is exact only because every
affected observable root is audited into exactly one partition; any SAT rejects,
all-UNSAT accepts, and timeout remains unresolved.

## Exact TFO-Slice Miter Experiment

Compare the existing monolithic exact cone with a good-cone plus faulty-TFO
encoding on a saved frontier:

```bash
venv/bin/python tfo_miter_experiment.py \
  --checkpoint-json results_optimized/alg10_checkpoints_parallel_finishline_parallel_safe_20260613_132711_sin/custom_epfl_arithmetic_sin_b17da687e8a4.json \
  --candidate-order proof_reverse_portfolio \
  --solver cadical153 \
  --budget 10000 \
  --max-candidates 9 \
  --seconds 180
```

Exercise the optional production cone engine:

```bash
ALG10_CONE_ENGINE=tfo \
ALG10_CONE_SOLVER=cadical153 \
ALG10_CONE_TFO_MAX_GOOD_GATES=0 \
ALG10_CONE_TFO_MAX_FAULTY_GATES=20000 \
venv/bin/python main.py
```

The TFO engine is exact because it encodes the complete good fanin cone of all
affected real observables and duplicates every relevant gate from the target
through those observables. Its runtime audit recomputes that slice and rejects
missing or extra gates before SAT. Only UNSAT accepts; SAT rejects; timeout or
skip escalates.

Probe the same frozen frontier with serial and multi-process exact TFO workers:

```bash
venv/bin/python alg10_frontier_shard_probe.py \
  results_optimized/datasets/dataset_2026-06-13_13-27-11-814736_finishline_parallel_safe_20260613_132711_sin/custom_epfl_arithmetic_sin.aag \
  --checkpoint-json results_optimized/alg10_checkpoints_parallel_finishline_parallel_safe_20260613_132711_sin/custom_epfl_arithmetic_sin_b17da687e8a4.json \
  --engine tfo \
  --limit 9 \
  --budget 10000 \
  --jobs 4 \
  --solver cadical153 \
  --order proof_reverse_portfolio \
  --json-out results_optimized/tfo_parallel_probe_sin_20260614.json
```

Run the single-writer transactional coordinator with parallel TFO workers and
sequential TFO rechecks:

```bash
venv/bin/python alg10_parallel_commit_coordinator.py \
  results_optimized/datasets/dataset_2026-06-13_13-27-11-814736_finishline_parallel_safe_20260613_132711_sin/custom_epfl_arithmetic_sin.aag \
  results_optimized/parallel_tfo_sin_20260614/custom_epfl_arithmetic_sin_tfo.aag \
  --checkpoint-dir results_optimized/alg10_checkpoints_parallel_tfo_sin_20260614 \
  --checkpoint-json results_optimized/alg10_checkpoints_parallel_finishline_parallel_safe_20260613_132711_sin/custom_epfl_arithmetic_sin_b17da687e8a4.json \
  --worker-engine tfo \
  --recheck-engine tfo \
  --jobs 4 \
  --budgets 10000 \
  --batch-size 9 \
  --max-generations 1 \
  --recheck-budget 0 \
  --cec-timeout 120
```

TFO conflict-budget history is stored separately from global-miter history, so
an old global timeout cannot suppress a new TFO query. Workers only propose;
the coordinator rechecks proposals sequentially against the progressively
updated generation and requires full ABC CEC before replacing the work AAG.

Run the four-hour post-commit `sin` pilot with escalating TFO budgets:

```bash
RUN_TAG=sin_tfo_4h_$(date +%Y%m%d_%H%M%S) \
  bash run_alg10_parallel_tfo_sin_4h.sh
```

The worker ladder is `10k,50k,250k,1M,5M` conflicts. A timeout at an early
tier is not terminal: the candidate remains checkpointed and advances to the
next budget. Coordinator rechecks are unlimited and every committed generation
still requires full CEC.

Run the six-hour hard-benchmark campaign from the best corrected checkpoints:

```bash
RUN_TAG=benchmarks_tfo_6h_$(date +%Y%m%d_%H%M%S) \
  bash run_alg10_parallel_tfo_benchmarks_6h.sh
```

The launcher now uses one global dynamic pool across `sin`, `sqrt`, `hyp`,
`div`, `log2`, and `mem_ctrl`. A free worker pulls the next eligible TFO
microbatch from any circuit instead of waiting for a circuit-sized visit to
finish. Circuits with fewer active tasks receive workers first; within a
circuit, untried candidates precede timeout retries. After the fixed
`10k,50k,250k,1M,5M` ladder, timeout candidates return to the queue at generated
budgets `10M,20M,40M,...`.

Each circuit still has an independent work AAG and checkpoint directory. An
UNSAT proposal pauses new dispatches only for that circuit, waits for its
same-generation tasks, then enters an asynchronous sequential-recheck and ABC
CEC barrier. The barrier consumes one slot from the same global worker budget,
so unrelated circuits continue without CPU oversubscription. Every committed
generation regenerates only that circuit's frontier.

Worker count is hardware-aware: `--jobs 0` uses the visible physical-core count
while respecting logical-CPU and available-memory limits. A new campaign
searches both top-level and earlier nested campaign checkpoint directories,
then keeps the lowest-gate valid checkpoint for each circuit before considering
frontier size. It also recognizes prior campaign outputs with
`final_verify=PASS`; if a commit ended before a new exact frontier was
serialized, that verified output is independently CEC-checked again, becomes
the next seed, and has its frontier regenerated.

Resume/adaptation rules:

- unchanged work AAG: resume the exact saved candidate frontier and TFO conflict
  history;
- timeout: retain the candidate and retry it at the next larger budget;
- SAT: reject that stuck-at candidate and continue the saved frontier;
- CEC-passed commit: keep the lower-gate AAG and regenerate its frontier,
  because gate indices changed;
- CEC failure or coordinator error: stop that target for audit.

Workers share queue ownership, timeout history, classifications, and committed
checkpoints through the single coordinator. They do not share learned SAT
clauses: candidate-local TFO instances have different CNFs, so direct clause
exchange is not currently sound or implemented.

The final `summary.json` records `max_active_workers`, classification and
proposal-barrier busy seconds, dispatch reasons, and measured worker
utilization. In-flight SAT calls are drained safely after the nominal deadline,
so a single exact query can still finish slightly after the requested duration.

## Exact Hard-Candidate Strategy Order Experiment

Compare fresh solver restarts with learned-clause retention across increasing
budgets, while testing every order of exact TFO, output-partitioned TFO, and
the full affected-root cone:

```bash
venv/bin/python hard_candidate_strategy_experiment.py \
  --checkpoint-json results_optimized/alg10_checkpoints_parallel_tfo_sin_4h_20260614_202340/custom_epfl_arithmetic_sin_b17da687e8a4.json \
  --checkpoint-frontier all \
  --candidate-order proof_reverse_portfolio \
  --strategies tfo,partition_tfo,cone \
  --modes fresh,persistent \
  --orders all \
  --budgets 1000,5000,20000 \
  --partition-size 1 \
  --max-candidates 20 \
  --seconds 1800
```

The runner is read-only. It measures each exact encoding once per candidate
and solver-state mode, then replays all six stop-on-first-proof orders from the
same measurements. Persistent mode keeps one solver and learned clauses across
the cumulative conflict targets. Fresh mode creates a new solver at every
tier. `partition_tfo` exactly partitions affected observable roots, audits the
partition and every TFO slice, and returns UNSAT only when every group is
UNSAT. Any resolved SAT/UNSAT disagreement between encodings aborts the run.

Use `strategy_detail_*.csv` for encoding size, conflict, and persistence
analysis. Use `portfolio_summary_*.csv` to rank orders first by resolved
candidates and then by total time. Clause retention is local to one unchanged
candidate CNF; clauses are not exchanged between different encodings or
workers.

Available experimental global frontier orders:

```bash
ALG10_GLOBAL_FRONTIER_ORDER=proof_cost
ALG10_GLOBAL_FRONTIER_ORDER=proof_cost_untried
ALG10_GLOBAL_FRONTIER_ORDER=proof_reverse_portfolio
```

These modes only reorder candidates. They never filter the frontier or change
the fault-control assumptions.

## Pair Stuck-At Experiment

Run the bounded pair-miter soundness check before any benchmark experiment:

```bash
venv/bin/python test_pair_stuckat_soundness.py --max-inputs 2 --max-gates 2 --output-count 2 --max-output-sets 24 --budget 0
```

Run a small real-circuit pair search:

```bash
venv/bin/python pair_stuckat_experiment.py --circuits benchmarks/c17.aag benchmarks/c432.aag --budget 5000 --max-candidates 60 --max-pairs 500 --seconds 30 --min-affected-roots 1 --sim-patterns 32
```

Compare against SAT-only pair checking by disabling the rejection-only
simulation filter:

```bash
venv/bin/python pair_stuckat_experiment.py --circuits benchmarks/c880.aag --budget 5000 --max-candidates 120 --max-pairs 3000 --seconds 60 --min-affected-roots 1 --sim-patterns 0
```

Optional pair filters are `--pair-filter same_roots` and
`--pair-filter overlap_roots`. These are search-space filters only; they do not
change the proof obligation for any pair that reaches SAT.

Use `--solve-singles` when pair classification matters. Without it, the runner
solves singles only after a pair UNSAT so `Pair_Only_UNSAT` remains meaningful.

Run a tiny frontier smoke from an Alg10 checkpoint. If `--circuits` is omitted,
the script uses the checkpoint's matching `.work.aag`:

```bash
venv/bin/python pair_stuckat_experiment.py \
  --checkpoint-json results_optimized/alg10_checkpoints_partitioned_experiment/custom_epfl_arithmetic_log2_8bfd84a960b5.json \
  --checkpoint-frontier pending \
  --budget 100 \
  --max-candidates 20 \
  --max-pairs 30 \
  --seconds 30 \
  --sim-patterns 32
```

Pair checks are experiment-only. A pair UNSAT is sound only for atomic commit of
both replacements in the same accepted context; do not promote into `main.py`
unless pair-only UNSATs appear and bounded tests remain clean.

## Packed Pre-SAT Simulation Experiment

Run the bounded soundness check for packed rejection-only simulation:

```bash
venv/bin/python test_alg10_presim_packing.py --max-inputs 2 --max-gates 2 --output-count 2 --max-output-sets 24 --max-pack-bits 128
```

Compare packed pre-sim against the current scalar-pattern pre-sim:

```bash
venv/bin/python alg10_presim_packing_experiment.py \
  --circuits benchmarks/c432.aag benchmarks/c880.aag benchmarks/c1355.aag benchmarks/c1908.aag \
  --max-candidates 300 \
  --walk-patterns 16 \
  --random-patterns 64 \
  --max-pack-bits 4096 \
  --compare-scalar
```

Use the packed engine in Algorithm 10 only as an audited experiment:

```bash
ALG10_PRE_SIM_REJECTION=1 \
ALG10_PRE_SIM_ENGINE=packed \
ALG10_PRE_SIM_PACKED_MAX_BITS=4096 \
ALG10_AUDIT_ASSUMPTIONS=1 \
venv/bin/python main.py
```

Packed pre-sim is rejection-only. It can skip candidates that are visibly
non-equivalent under concrete input patterns; it cannot accept a redundancy.

## Global SAT Solver Experiment

Compare PySAT backends on the same Algorithm 10 global frontier without
rewriting or checkpoint changes:

```bash
venv/bin/python global_solver_experiment.py \
  --checkpoint-json results_optimized/alg10_checkpoints_packed_from_strict/custom_epfl_arithmetic_log2_8bfd84a960b5.json \
  --checkpoint-frontier candidates \
  --solvers glucose4,cadical153,cadical195,maplecm,minisat22 \
  --budgets 1000 \
  --max-candidates 60 \
  --seconds 60
```

Use a different global solver in Algorithm 10 only as an experiment:

```bash
ALG10_CHECKPOINT_DIR=results_optimized/alg10_checkpoints_packed_from_strict \
ALG10_GLOBAL_SOLVER=cadical153 \
ALG10_GLOBAL_MAX_CONSEC_TIMEOUTS=80 \
ALG10_PRE_SIM_REJECTION=1 \
ALG10_PRE_SIM_ENGINE=packed \
ALG10_PRE_SIM_PACKED_MAX_BITS=4096 \
ALG10_AUDIT_ASSUMPTIONS=1 \
venv/bin/python main.py
```

`ALG10_GLOBAL_MAX_CONSEC_TIMEOUTS` is a checkpointing safety valve. It does not
accept or reject candidates; it stops a global frontier run after repeated
timeouts so later work can change strategy instead of spending the whole budget
on one hard streak.

SAT-only global frontier strategy experiment:

```bash
venv/bin/python global_sat_strategy_experiment.py \
  --checkpoint-json results_optimized/alg10_checkpoints_global_strategy_div/custom_epfl_arithmetic_div_242292af29fd.json \
  --checkpoint-frontier candidates \
  --solver cadical153 \
  --orders current,reverse,untried_first,tried_asc,depth_desc,fanout_desc \
  --budget-kinds conf \
  --budget 1000 \
  --reuse-modes incremental,rebuild:20 \
  --phase-modes none,model \
  --max-candidates 80 \
  --output-dir results_optimized/global_sat_strategy_div
```

Run Alg10 with the best current SAT-side strategy observed on hard frontiers:

```bash
ALG10_GLOBAL_SOLVER=cadical153 \
ALG10_GLOBAL_FRONTIER_ORDER=untried_first \
ALG10_GLOBAL_PHASE_MODE=model \
ALG10_GLOBAL_MAX_CONSEC_TIMEOUTS=80 \
ALG10_AUDIT_ASSUMPTIONS=1 \
venv/bin/python main.py
```

These knobs do not change the proof obligation. They only reorder the global
frontier and set SAT polarity hints; every UNSAT acceptance still uses the same
global assumptions, assumption audit, and final ABC CEC.

Run the transactional parallel Algorithm 10 coordinator on one circuit:

```bash
venv/bin/python alg10_parallel_commit_coordinator.py \
  path/to/source.aag \
  results_optimized/parallel_commit/source.aag \
  --checkpoint-dir results_optimized/alg10_checkpoints_parallel_commit \
  --checkpoint-json path/to/source_checkpoint.json \
  --jobs 3 \
  --budgets 1000000,2000000,5000000 \
  --batch-size 16 \
  --seconds 3600 \
  --solver cadical153 \
  --order untried_first
```

Use the checkpoint's exact `source_path` as the first argument; source hashes
must match. Worker processes classify a frozen frontier and never edit the
AAG. The coordinator serially rechecks queued UNSAT proposals in one cumulative
solver, performs the rewrite, requires direct ABC CEC `PASS`, saves the
checkpoint, and only then starts a new generation. With a four-core machine,
`--jobs 3` reserves one core for the coordinator and system work.

The `--seconds` limit is checked between generations. A SAT wave already in
progress may finish after the nominal deadline.

## Focused Checks

Run individual validation scripts:

```bash
python3 test_baselines.py
python3 test_miter_integrity.py
python3 test_strict_pipeline.py
python3 test_alg3_sandbox.py
python3 test_encoding_surgery.py
python3 test_alg9_random_observability.py
python3 test_alg10_checkpoint.py
python3 test_alg10_parallel_commit_coordinator.py
python3 test_algorithms_1_to_10.py
```

These files are script-style checks with `if __name__ == "__main__"` blocks, not a fully standardized pytest suite.

Force Algorithm 9's random-observability filter during the focused comparison smoke:

```bash
ALG9_FAULT_SIM_MAX_GATES=0 ALG9_RANDOM_OBS_SIM=1 python3 test_incremental_sat_pipeline.py --epfl
```

## ABC Checks

The verifier expects ABC at:

```text
./abc/abc
```

Use the Python verifier or ABC wrapper for `.aag` files, because this local ABC build rejects ASCII AIGER when called directly with `read_aiger`:

```bash
python3 -c "from verifier import verify_equivalence; print(verify_equivalence('original.aag', 'optimized.aag'))"
```

Manual binary AIGER check after conversion:

```bash
./aiger/aigtoaig original.aag /tmp/original.aig
./aiger/aigtoaig optimized.aag /tmp/optimized.aig
./abc/abc -c "cec -n /tmp/original.aig /tmp/optimized.aig; quit"
```

## File Discovery

Find Python optimizer entry points:

```bash
rg "def solve_circuit" *.py
```

Find ABC usage:

```bash
rg "ABC_PATH|cec|strash" *.py
```

Find generated result reports:

```bash
find results_optimized -name "*.csv" -maxdepth 2
```
