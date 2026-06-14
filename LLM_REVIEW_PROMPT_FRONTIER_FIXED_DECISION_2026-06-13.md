# LLM Review Prompt: Alg10 Frontier-Fixed Decision Point

You are reviewing a thesis codebase for SAT-based redundancy removal in AIG/AAG circuits.
Please give concrete technical feedback. The goal is to decide whether to run one more patched 12-hour campaign or change strategy before writing to the professor.

## Project Goal

We are trying to reduce stuck-at fault candidates to `SAT_Unresolved = 0` while preserving formal equivalence. Every optimized AAG is verified by ABC CEC through the project's verifier.

Main files:

- `main.py`: interactive experiment driver, dataset/profile selection, CSV reporting.
- `optimizer_alg10_tiered.py`: Algorithm 10, checkpointed tiered SAT engine.
- `test_alg10_resume_pool.py`: focused tests for checkpoint resume, CEX pool, exact frontier resume.
- `test_alg10_checkpoint.py`: basic Algorithm 10 correctness/checkpoint tests.

## Latest Completed Overnight Run

Report:

`results_optimized/thesis_results_ALG10_alg10_strict_audit_zero_resume_pool_presim_current_real_suites_planted_2026-06-12_21-41-14.csv`

Log:

`alg10_best_protected_12h_20260612_214114.log`

Headline results:

- CEC PASS rows: `144/144`
- CEC PASS latest circuits: `38/38`
- Total removed latest circuits: `2303` gates
- New removed events this run from checkpoints: `40` gates
- SAT unresolved latest circuits: `116619`
- Best SAT unresolved seen by the old report summary: `65324`
- SAT calls: `48089` checks, `36163` SAT rejects, `20` UNSAT accepts, `11906` timeouts
- Main timeout bottleneck: global tier

Latest unresolved circuits:

| Circuit | Latest unresolved | Latest removed | Notes |
| --- | ---: | ---: | --- |
| `epfl_epfl_arithmetic_hyp.aag` | `50141` | `4` | old summary was misleading; realistic best checkpoint is around `946` unresolved |
| `epfl_epfl_random_control_mem_ctrl.aag` | `45133` | `4` | hard case; best realistic checkpoint found is `8466`, but frontier metadata is not valid there |
| `epfl_epfl_arithmetic_log2.aag` | `10381` | `416` | realistic best seed around `10764`, still large |
| `epfl_epfl_arithmetic_sqrt.aag` | `9667` | `54` | realistic best seed around `368`; old `94` was misleading frontier accounting |
| `epfl_epfl_arithmetic_div.aag` | `1254` | `233` | div seed issue fixed; now uses `233` removed instead of `227` |
| `epfl_epfl_arithmetic_sin.aag` | `43` | `41` | realistic best seed around `16` |

Important correction about `voter`:

- We remembered `voter` having unresolved values around `1900`.
- That was true historically: examples include `1908`, `2003`, `2211`, `2483`.
- But later runs solved it: latest relevant checkpoints show `removed=1509`, `SAT_Unresolved=0`.
- So `voter` is not a current blocker.

## Problem Found After Latest Run

The campaign appeared to improve to very low unresolved values for some circuits, but some of those values were not true total unresolved counts.

Root cause:

- Some checkpoint `phase_resume` states save tier frontiers with `pending` and `escalated` lists.
- The old ranking/reporting used only `telemetry["unresolved"]`, which sometimes counted only pending candidates.
- It ignored escalated candidates still needing SAT work.
- This made the checkpoint selector chase fake "best" states, for example `sqrt=94` and `hyp=259`.

Patch made on 2026-06-13:

- Added `_phase_resume_unresolved_count(state)`.
- Added `_checkpoint_unresolved_from_data(data)`.
- Checkpoint ranking now uses true frontier size for tier checkpoints: `max(telemetry_unresolved, pending + escalated)`.
- Saving a checkpoint now stores `telemetry["unresolved"]` as at least the full frontier size when a phase frontier exists.
- External checkpoint loading no longer discards valid `phase_resume` metadata; validation still checks `work_sha256` and `gate_count`.
- Runtime telemetry is guarded so a saved phase frontier cannot report a lower unresolved count than its true frontier.

After the patch, the corrected selector chooses:

| Circuit | Corrected selected unresolved | Valid exact global frontier? |
| --- | ---: | --- |
| `hyp` | `946` | yes |
| `mem_ctrl` | `8466` | no |
| `log2` | `10764` | yes |
| `sqrt` | `368` | yes |
| `div` | `955` | yes |
| `sin` | `16` | yes |

## Tests Already Run After Patch

Syntax:

```bash
venv/bin/python -m py_compile optimizer_alg10_tiered.py test_alg10_resume_pool.py main.py
```

Focused new tests:

```bash
venv/bin/python -c "import test_alg10_resume_pool as t; t.test_external_checkpoint_preserves_valid_phase_resume(); t.test_checkpoint_rank_counts_tier_pending_and_escalated(); print('new resume/frontier tests passed')"
```

Full resume/checkpoint behavior tests:

```bash
venv/bin/python test_alg10_resume_pool.py
```

Core Alg10 checkpoint tests:

```bash
venv/bin/python test_alg10_checkpoint.py
```

Whitespace/diff hygiene:

```bash
git diff --check
```

All passed.

Additional diagnostics run:

- Parsed all `voter` CSV rows and checkpoints; confirmed `voter` is already solved at `SAT_Unresolved=0`.
- Compared previous overnight report `2026-06-12_01-00-36` against latest report `2026-06-12_21-41-14`.
- Recomputed checkpoint selection after the patch for hard circuits.
- Validated that exact frontier resume now works for external checkpoints when `work_sha256` and `gate_count` match.

## Proposed Next Run Command

This is the patched 12-hour decision run currently under consideration:

```bash
nohup bash -lc "printf '10\n4\n3\n0\n' | ALG10_TOTAL_SECONDS=43200 ALG10_RESET_CHECKPOINT=0 ALG10_CHECKPOINT_DIR=results_optimized/alg10_checkpoints_frontier_fixed_campaign ALG10_EXTRA_CHECKPOINT_DIRS=results_optimized/alg10_checkpoints_best_protected_campaign,results_optimized/alg10_checkpoints_best_unresolved_campaign,results_optimized/alg10_checkpoints_global_strategy_div,results_optimized/alg10_checkpoints_global_strategy_sqrt,results_optimized/alg10_checkpoints_final_sat_strategy,results_optimized/alg10_checkpoints_strict_audit,results_optimized/alg10_checkpoints_resume_pool_presim ALG10_CHECKPOINT_SELECT=unresolved ALG10_PROTECT_BEST_CHECKPOINT=1 ALG10_PHASE_LOCAL_RESUME=1 ALG10_EXACT_FRONTIER_RESUME=1 ALG10_GLOBAL_SOLVER=cadical153 ALG10_GLOBAL_FRONTIER_ORDER=tried_asc ALG10_GLOBAL_PHASE_MODE=model ALG10_GLOBAL_MAX_CONSEC_TIMEOUTS=160 ALG10_AUTO_PLOTS=1 venv/bin/python main.py" > alg10_frontier_fixed_12h_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

## Questions For Review

Please answer directly:

1. Should we run this patched 12-hour command, or is there enough evidence to stop and change strategy?
2. Is the frontier accounting patch logically sound, or is there another hidden source of misleading unresolved counts?
3. For `mem_ctrl`, what strategy should we use given that the best realistic checkpoint lacks a valid exact frontier?
4. For `hyp`, `sqrt`, `div`, and `sin`, does exact global frontier resume from the corrected seeds look like the right next step?
5. Would a different global frontier order, budget schedule, solver, or phase policy be more promising than `tried_asc + cadical153 + model phase`?
6. Should we split the remaining hard circuits into focused custom runs instead of running the full real-suites campaign again?
7. What result threshold is reasonable for the thesis if zero unresolved is not reached by the meeting?
8. How should we frame the contribution: checkpointed SAT frontier management, sound CEC-verified reduction, empirical bottleneck analysis, or something else?
9. What should we tell the professor before the meeting: run one more patched decision experiment, or switch immediately to a revised strategy?

Please include:

- a prioritized next-action plan;
- any risks in the current patch;
- any quick additional tests we should run before a 12-hour experiment;
- a concise suggested paragraph for an email to the professor.
