# Alg10 Frontier-Fixed Run Protocol - 2026-06-13

This is the decision protocol after outside feedback on the frontier-accounting fix.
Do not start another full 38-circuit overnight campaign before completing the preflight checks.

## Decision

Run the patched experiment, but split the workload and treat it as validation, not as a guaranteed breakthrough.

The goal is to answer:

- Did corrected checkpoint accounting and exact frontier resume remove wasted cycling?
- Are the remaining candidates SAT-hard rather than checkpoint/scheduling artifacts?
- Which circuits can realistically reach `SAT_Unresolved = 0` before the meeting?

## Required Preflight Checks

Run these first:

```bash
venv/bin/python -m py_compile optimizer_alg10_tiered.py test_alg10_resume_pool.py main.py
venv/bin/python -c "import test_alg10_resume_pool as t; t.test_external_checkpoint_preserves_valid_phase_resume(); t.test_checkpoint_rank_counts_tier_pending_and_escalated(); t.test_tier_frontier_overlap_and_duplicates_are_rejected(); t.test_untried_first_global_frontier_order(); print('frontier preflight tests passed')"
venv/bin/python test_alg10_checkpoint.py
git diff --check
```

Optional but recommended before the long run:

```bash
venv/bin/python test_alg10_resume_pool.py
```

## Success Criteria

Use corrected selected checkpoint unresolved counts as the baseline.

| Circuit | Baseline unresolved | Validation target | Verdict if missed |
| --- | ---: | ---: | --- |
| `sin` | `16` | `0` | inspect last candidates/tier |
| `div` | `955` | `<= 764` (20% reduction) | likely SAT hardness |
| `sqrt` | `368` | `<= 331` (10% reduction) | likely plateau |
| `hyp` | `946` | `<= 851` (10% reduction) | likely plateau |
| `log2` | `10764` | any clear reduction, record rate | hard frontier |
| `mem_ctrl` | `8466` realistic seed, no valid exact frontier | separate diagnostic, not main success metric | rebuild/fresh strategy needed |
| `voter` | `0` | stay `0` | regression if nonzero |

If `sin` reaches zero and `div` improves by at least 20%, the patch is validated even if `sqrt`, `hyp`, `log2`, and `mem_ctrl` plateau.

## Create Split Custom Suites

```bash
mkdir -p custom_circuits/alg10_preflight_sin custom_circuits/alg10_finishline custom_circuits/alg10_heavyweights
cp benchmark_suites/epfl/epfl_arithmetic_sin.aag custom_circuits/alg10_preflight_sin/
cp benchmark_suites/epfl/epfl_arithmetic_sin.aag benchmark_suites/epfl/epfl_arithmetic_div.aag benchmark_suites/epfl/epfl_arithmetic_sqrt.aag benchmark_suites/epfl/epfl_arithmetic_hyp.aag benchmark_suites/epfl/epfl_random_control_voter.aag custom_circuits/alg10_finishline/
cp benchmark_suites/epfl/epfl_arithmetic_log2.aag benchmark_suites/epfl/epfl_random_control_mem_ctrl.aag custom_circuits/alg10_heavyweights/
```

The custom filenames are okay. Alg10 checkpoint matching uses content hash, so these runs can still import existing checkpoints.

## 30-Minute Ordering Preflight On `sin`

Run these two short jobs. Compare the resulting CSVs before launching a 12-hour run.
Use fresh higher budgets here. The first preflight using the default
`1000,5000,20000,100000,500000` budgets was non-informative because the
checkpoint had already exhausted those budgets and the run correctly skipped
all remaining `sin` candidates.

`tried_asc`:

```bash
nohup bash -lc "printf '10\n4\n5\ncustom_circuits/alg10_preflight_sin\n' | ALG10_TOTAL_SECONDS=1800 ALG10_BUDGETS=1000000,2000000,5000000 ALG10_RESET_CHECKPOINT=0 ALG10_CHECKPOINT_DIR=results_optimized/alg10_checkpoints_preflight_sin_tried_asc_high_budget ALG10_EXTRA_CHECKPOINT_DIRS=results_optimized/alg10_checkpoints_best_protected_campaign,results_optimized/alg10_checkpoints_best_unresolved_campaign,results_optimized/alg10_checkpoints_global_strategy_div,results_optimized/alg10_checkpoints_global_strategy_sqrt,results_optimized/alg10_checkpoints_final_sat_strategy,results_optimized/alg10_checkpoints_strict_audit,results_optimized/alg10_checkpoints_resume_pool_presim ALG10_CHECKPOINT_SELECT=unresolved ALG10_PROTECT_BEST_CHECKPOINT=1 ALG10_PHASE_LOCAL_RESUME=1 ALG10_EXACT_FRONTIER_RESUME=1 ALG10_GLOBAL_SOLVER=cadical153 ALG10_GLOBAL_FRONTIER_ORDER=tried_asc ALG10_GLOBAL_PHASE_MODE=model ALG10_GLOBAL_MAX_CONSEC_TIMEOUTS=80 ALG10_AUTO_PLOTS=1 venv/bin/python main.py" > alg10_preflight_sin_tried_asc_high_budget_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

`untried_first`:

```bash
nohup bash -lc "printf '10\n4\n5\ncustom_circuits/alg10_preflight_sin\n' | ALG10_TOTAL_SECONDS=1800 ALG10_BUDGETS=1000000,2000000,5000000 ALG10_RESET_CHECKPOINT=0 ALG10_CHECKPOINT_DIR=results_optimized/alg10_checkpoints_preflight_sin_untried_first_high_budget ALG10_EXTRA_CHECKPOINT_DIRS=results_optimized/alg10_checkpoints_best_protected_campaign,results_optimized/alg10_checkpoints_best_unresolved_campaign,results_optimized/alg10_checkpoints_global_strategy_div,results_optimized/alg10_checkpoints_global_strategy_sqrt,results_optimized/alg10_checkpoints_final_sat_strategy,results_optimized/alg10_checkpoints_strict_audit,results_optimized/alg10_checkpoints_resume_pool_presim ALG10_CHECKPOINT_SELECT=unresolved ALG10_PROTECT_BEST_CHECKPOINT=1 ALG10_PHASE_LOCAL_RESUME=1 ALG10_EXACT_FRONTIER_RESUME=1 ALG10_GLOBAL_SOLVER=cadical153 ALG10_GLOBAL_FRONTIER_ORDER=untried_first ALG10_GLOBAL_PHASE_MODE=model ALG10_GLOBAL_MAX_CONSEC_TIMEOUTS=80 ALG10_AUTO_PLOTS=1 venv/bin/python main.py" > alg10_preflight_sin_untried_first_high_budget_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

Use the better ordering for the 12-hour finish-line run. If tied, prefer `untried_first`.

Summarize both CSVs after they finish:

```bash
venv/bin/python alg10_decision_summary.py $(ls -t results_optimized/thesis_results_ALG10_*custom_only*.csv | head -n 2)
```

## Finish-Line 12-Hour Run

Use this for `sin`, `div`, `sqrt`, `hyp`, and `voter` after preflight:

```bash
nohup bash -lc "printf '10\n4\n5\ncustom_circuits/alg10_finishline\n' | ALG10_TOTAL_SECONDS=43200 ALG10_BUDGETS=1000000,2000000,5000000 ALG10_RESET_CHECKPOINT=0 ALG10_CHECKPOINT_DIR=results_optimized/alg10_checkpoints_frontier_fixed_finishline ALG10_EXTRA_CHECKPOINT_DIRS=results_optimized/alg10_checkpoints_preflight_sin_untried_first_high_budget,results_optimized/alg10_checkpoints_preflight_sin_tried_asc_high_budget,results_optimized/alg10_checkpoints_best_protected_campaign,results_optimized/alg10_checkpoints_best_unresolved_campaign,results_optimized/alg10_checkpoints_global_strategy_div,results_optimized/alg10_checkpoints_global_strategy_sqrt,results_optimized/alg10_checkpoints_final_sat_strategy,results_optimized/alg10_checkpoints_strict_audit,results_optimized/alg10_checkpoints_resume_pool_presim ALG10_CHECKPOINT_SELECT=unresolved ALG10_PROTECT_BEST_CHECKPOINT=1 ALG10_PHASE_LOCAL_RESUME=1 ALG10_EXACT_FRONTIER_RESUME=1 ALG10_GLOBAL_SOLVER=cadical153 ALG10_GLOBAL_FRONTIER_ORDER=untried_first ALG10_GLOBAL_PHASE_MODE=model ALG10_GLOBAL_MAX_CONSEC_TIMEOUTS=80 ALG10_AUTO_PLOTS=1 venv/bin/python main.py" > alg10_finishline_12h_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

## Parallel Finish-Line Portfolio

Preferred after the high-budget `sin` preflight showed real progress
(`16 -> 13`). This uses multiple independent `main.py` workers, one circuit
per process, with separate checkpoint directories. It is sound because every
worker still performs the normal Alg10 checkpointing and ABC CEC verification.

Important guardrail:

- Use only the patched `alg10_parallel_portfolio.py`.
- The launcher now assigns a unique `THESIS_RUN_TIMESTAMP` to each worker.
- This is necessary because parallel `main.py` workers started in the same
  second otherwise collide on the same dataset directory, output directory, and
  report CSV.
- If a worker hits a fatal per-circuit exception, `main.py` now marks that path
  stalled instead of repeating the same error forever.

Run up to four finish-line workers in parallel:

```bash
nohup venv/bin/python alg10_parallel_portfolio.py --scenario finishline --jobs 4 --seconds 43200 --budgets 1000000,2000000,5000000 --tag finishline_parallel_$(date +%Y%m%d_%H%M%S) > alg10_parallel_finishline_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

If the first wave improves any circuit, run a follow-up wave that can import
the newly produced same-tag checkpoint dirs:

```bash
venv/bin/python alg10_parallel_portfolio.py --scenario finishline --jobs 4 --seconds 43200 --budgets 1000000,2000000,5000000 --tag <same_tag> --include-finished-siblings
```

For a same-circuit strategy race on `sin`, use:

```bash
nohup venv/bin/python alg10_parallel_portfolio.py --scenario sin-portfolio --jobs 4 --seconds 7200 --budgets 1000000,2000000,5000000 --tag sin_portfolio_$(date +%Y%m%d_%H%M%S) > alg10_parallel_sin_portfolio_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

## Heavyweight Diagnostic Run

Run `log2` and `mem_ctrl` separately. Treat this as bottleneck analysis, not a pass/fail run.

```bash
nohup bash -lc "printf '10\n4\n5\ncustom_circuits/alg10_heavyweights\n' | ALG10_TOTAL_SECONDS=21600 ALG10_BUDGETS=1000000,2000000,5000000 ALG10_RESET_CHECKPOINT=0 ALG10_CHECKPOINT_DIR=results_optimized/alg10_checkpoints_frontier_fixed_heavyweights ALG10_EXTRA_CHECKPOINT_DIRS=results_optimized/alg10_checkpoints_best_protected_campaign,results_optimized/alg10_checkpoints_best_unresolved_campaign,results_optimized/alg10_checkpoints_global_strategy_div,results_optimized/alg10_checkpoints_global_strategy_sqrt,results_optimized/alg10_checkpoints_final_sat_strategy,results_optimized/alg10_checkpoints_strict_audit,results_optimized/alg10_checkpoints_resume_pool_presim ALG10_CHECKPOINT_SELECT=unresolved ALG10_PROTECT_BEST_CHECKPOINT=1 ALG10_PHASE_LOCAL_RESUME=1 ALG10_EXACT_FRONTIER_RESUME=1 ALG10_GLOBAL_SOLVER=cadical153 ALG10_GLOBAL_FRONTIER_ORDER=untried_first ALG10_GLOBAL_PHASE_MODE=model ALG10_GLOBAL_MAX_CONSEC_TIMEOUTS=80 ALG10_AUTO_PLOTS=1 venv/bin/python main.py" > alg10_heavyweights_6h_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

Parallel heavyweight version:

```bash
nohup venv/bin/python alg10_parallel_portfolio.py --scenario heavyweights --jobs 2 --seconds 21600 --budgets 1000000,2000000,5000000 --tag heavyweights_parallel_$(date +%Y%m%d_%H%M%S) > alg10_parallel_heavyweights_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

## Watch And Summarize

Watch newest matching log:

```bash
tail -f "$(ls -t alg10_*_*.log | head -n 1)"
```

Check running processes:

```bash
ps -eo pid,etime,cmd | grep '[m]ain.py'
```

Stop a parallel portfolio cleanly:

```bash
ps -eo pid,ppid,etime,cmd | grep 'alg10_parallel_portfolio.py\|[m]ain.py'
kill <launcher_pid>
```

The patched launcher handles `SIGTERM` and terminates active child workers. If
children survive because the launcher was already gone, kill only the listed
`venv/bin/python main.py` PIDs from that run.

After a run, compare latest CSV rows against the success criteria before deciding on another run.

```bash
venv/bin/python alg10_decision_summary.py <report.csv>
```
