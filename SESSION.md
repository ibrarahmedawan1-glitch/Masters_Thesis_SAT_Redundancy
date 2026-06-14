# Session Notes

This file is the working map for a VS Code session on the thesis project. Use it to restart context quickly before editing algorithms, running experiments, or interpreting results.

## Project Purpose

The project studies SAT-based redundancy removal in AIG/AAG logic circuits. The current main entry point is `main.py`, which:

- creates a generated benchmark dataset in `dataset_benchmarks/`;
- lets the user choose one optimizer engine interactively;
- runs that optimizer over generated circuits and copied ISCAS-style `.aag` benchmarks;
- verifies optimized circuits with formal equivalence checking;
- writes a timestamped CSV report under `results_optimized/`.

The core thesis workflow is optimization plus verification. A result is only useful when the optimized circuit passes equivalence checking against the original.

## Current Entry Point

Run the main experiment with:

```bash
python3 main.py
```

`main.py` asks for an algorithm number and dynamically imports the matching optimizer module:

| Choice | Module | Role |
| --- | --- | --- |
| 1 | `optimizer_alg1.py` | Naive SAT miter baseline |
| 2 | `optimizer_alg2.py` | Structural universal-machine approach |
| 3 | `optimizer_alg3.py` | Base incremental ATPG |
| 4 | `optimizer_alg3_saf.py` | SAF batch injection variant |
| 5 | `optimizer_alg3_sim.py` | Simulation filter plus incremental SAT |
| 6 | `optimizer_alg3_timeout_cadical.py` | Budget/timeout variant |
| 7 | `optimizer_alg7_iterative.py` | Simulation filter plus iterative surgery |
| 8 | `optimizer_alg8_hybrid.py` | Pure Python hybrid optimizer with ABC CEC verification |
| 9 | `optimizer_alg9_incremental.py` | Committed in-memory incremental SAT optimizer |
| 10 | `optimizer_alg10_tiered.py` | Checkpointed budget-cycling global SAT optimizer |

The menu has been corrected to accept choices `1-10`. Choice `7` maps to `optimizer_alg7_iterative.py`, choice `8` maps to `optimizer_alg8_hybrid.py`, choice `9` maps to `optimizer_alg9_incremental.py`, and choice `10` maps to `optimizer_alg10_tiered.py`.

## Current Debugging State

The important finding from the ABC investigation is that this local ABC build rejects ASCII AIGER `.aag` when called with `read_aiger`. It accepts binary AIGER `.aig`.

The project now uses `abc_utils.py` as the shared bridge:

- convert ASCII `.aag` to binary `.aig` with bundled `aiger/aigtoaig`;
- run ABC `cec -n` on binary `.aig` files so primary inputs and outputs are matched by order;
- run ABC `strash` on binary `.aig` files;
- convert ABC output back to normalized ASCII `.aag`;
- add deterministic `i0`, `o0`, etc. symbols after conversion.

This keeps Python algorithms free to write readable ASCII `.aag`, while thesis verification still uses industrial-grade ABC CEC.

## Verification Policy

`verifier.py` now tries ABC CEC first through `abc_utils.run_abc_cec(...)`. The direct Python SAT miter remains as a fallback, but thesis claims should be based on `PASS` from the standard verifier path, which now routes through ABC conversion.

Do not call ABC directly on `.aag` with:

```bash
./abc/abc -c "read_aiger file.aag; ..."
```

Use the wrapper or convert to `.aig` first.

## Recent Fixes

- Added `abc_utils.py` for robust AAG-to-AIG conversion, ABC CEC, ABC strash, and ASCII normalization.
- Patched `verifier.py` so ABC CEC works with this ABC build instead of silently failing on ASCII input.
- Patched algorithms 1, 2, 3, 4, 5, 6, 7, and base `optimizer.py` to use the ABC wrapper for cleanup.
- Rebuilt `optimizer_alg8_hybrid.py` so Algorithm 8 runs again and verifies with ABC CEC.
- Fixed Algorithm 7's stuck-at-0 check; it was unreachable after a `continue`.
- Fixed `main.py` option `7`, which had pointed at a non-existing/incorrect module name.
- Added a CEC safety fallback to `optimizer_alg3_saf.py`, because its batch SAF result failed on `c17` before the safety check.
- Hardened `abc_utils.py` ASCII conversion by using `aigtoaig -a input -` and writing stdout to `.aag`, because this bundled `aigtoaig` rejects `-a` together with a destination file.
- Added mutex clauses `(-f0_i or -f1_i)` to Algorithm 8's fault-control SAT encoding.
- Added `optimizer_alg9_incremental.py`, a committed in-memory incremental SAT optimizer that keeps accepted stuck-at replacements active while testing later candidates.
- Added `test_incremental_sat_pipeline.py`, which writes comparison CSVs under `results_optimized/incremental_sat_test/`.
- Added AND-equivalent area columns to result CSVs: `Area_Before_AND2`, `Area_After_AND2`, `Area_Saved_AND2`, and `Area_Red%`.
- Added `prepare_benchmark_suites.py` for one-time conversion/import of EPFL and external `.aig`/`.aag`/Verilog `.v` benchmark suites.
- Prepared 20 local EPFL benchmark circuits under `benchmark_suites/epfl/`; manifest is `benchmark_suites/manifest.csv`.
- Smoke-tested external Verilog import into `/tmp/bench_suite_test`: 14 existing Verilog files synthesized to AAG with Yosys, 0 errors.
- Added `aag_metrics.py` and depth columns to reports: `Depth_Before`, `Depth_After`, and `Depth_Red%`.
- Changed the terminal wording from generic area to explicit `AND2 area saved: N nodes`.
- Changed Algorithm 9 default mode from exhaustive to filtered. Set `ALG9_EXHAUSTIVE=1` for the old full stuck-at sweep.
- Added Algorithm 9 large-circuit guards: large circuits use a lower SAT budget/candidate cap, and circuits above `ALG9_VERY_LARGE_GATE_LIMIT` skip SAT unless `ALG9_ALLOW_VERY_LARGE_SAT=1`.
- Added `MAX_DATASET_GATES` for full pipeline runs; circuits above the cap are recorded as `SKIPPED_GATE_LIMIT`.
- Added structural-vs-SAT accounting for Algorithm 9 reports: `Initial_AND2`, `After_Structural_AND2`, `After_SAT_AND2`, `Structural_Removed_AND2`, `SAT_Induced_Removed_AND2`, `SAT_Accepted_SA0`, `SAT_Accepted_SA1`, `SAT_Query_SAT`, and `SAT_Query_UNSAT`.
- Added Algorithm 9 adaptive SAT abort reporting. Hard circuits can now stop the SAT phase with `SAT_Abort_Reason` such as `SAT_TIME_BUDGET`, `CONSECUTIVE_TIMEOUTS`, `TIMEOUT_RATE`, or `SKIP_VERY_LARGE` while still writing an output that must pass final CEC.
- Added `SAT_Abort_Reason` to the full `main.py` CSV and the focused `test_incremental_sat_pipeline.py` CSV.
- Added planted-live ATPG benchmark generation in `generators.py`. The suite starts from real combinational AAGs and wraps live outputs with three SAT-redundant motifs: `absorb_or`, `absorb_and`, and `covered_product`. Each plant is in a primary-output cone and is recorded in a manifest with the expected stuck-at value.
- Added `ONLY_PLANTED_LIVE=1` to `main.py` for quick planted-only experiments, plus `PLANTED_LIVE_PER_BASE` and `PLANTED_LIVE_SEED`.
- Fixed the terminal timing label in `main.py`: it now prints actual SAT phase time plus total optimizer time, instead of labeling total time as SAT time.

## Latest Smoke Tests

Focused tests after the fixes:

- ABC CEC wrapper on `benchmarks/c17.aag` vs itself: `PASS`.
- Algorithm 1 on `c17`: `PASS`.
- Algorithm 2 on `c17`: `PASS`.
- Algorithm 3 on `c17`: `PASS`.
- Algorithm 4 on `c17`: `PASS` after safety fallback.
- Algorithm 5 on `c17`: `PASS`.
- Algorithm 6 on `c17`: `PASS`.
- Algorithm 7 on `c17`: `PASS`.
- Algorithm 7 on `c432`: removed 2 gates, ABC CEC `PASS`.
- Algorithm 8 on `c432`: removed 2 gates, ABC CEC `PASS`.
- Algorithm 9 smoke test on `odc_redundant`: 2 gates to 0 gates, ABC CEC `PASS`.
- Algorithm 9 smoke test on `c432`: 125 gates to 121 gates, ABC CEC `PASS`.
- Algorithm 9 EPFL smoke tests: `epfl_dec` 304 to 304 `PASS`, `epfl_priority` 978 to 978 `PASS`, `epfl_router` 257 to 251 `PASS`.
- Latest comparison CSV: `results_optimized/incremental_sat_test/2026-05-08_17-09-38/incremental_sat_comparison_2026-05-08_17-09-38.csv`.
- Latest area-column smoke CSV: `results_optimized/incremental_sat_test/2026-05-08_17-27-41/incremental_sat_comparison_2026-05-08_17-27-41.csv`.
- Latest filtered Algorithm 9 smoke CSV: `results_optimized/incremental_sat_test/2026-05-08_18-09-58/incremental_sat_comparison_2026-05-08_18-09-58.csv`.
- Direct filtered Algorithm 9 on `epfl_arithmetic_div`: skipped SAT because it is above the default very-large threshold, wrote equivalent output, ABC CEC `PASS` in about 0.08s.
- Latest structural-vs-SAT accounting smoke CSV: `results_optimized/incremental_sat_test/2026-05-08_20-40-38/incremental_sat_comparison_2026-05-08_20-40-38.csv`.
- Compile check after abort-policy reporting: `venv/bin/python -m py_compile optimizer_alg9_incremental.py main.py test_incremental_sat_pipeline.py` passed.
- Latest abort-reporting smoke CSV: `results_optimized/incremental_sat_test/2026-05-08_20-47-05/incremental_sat_comparison_2026-05-08_20-47-05.csv`.
- Forced hard-case abort test on `benchmark_suites/epfl/epfl_arithmetic_log2.aag` with `ALG9_MAX_SAT_SECONDS=1`: removed 0 unproven gates, reported `SAT_Abort_Reason=SAT_TIME_BUDGET`, and final CEC returned `PASS`.
- Full Algorithm 9 run CSV: `results_optimized/thesis_results_ALG9_2026-05-08_20-54-10.csv`.
  Summary: 235/235 CEC `PASS`, optimizer time 111.27s, CEC time 6.00s, SAT phase 103.74s. Total reductions by category: Benchmark 26 AND2 nodes removed (24 SAT-induced), EPFL 6 removed (all from router), Injected_Idem 38,705 removed (mostly structural), Injected_Stuck 40,083 removed (structural), Pure_Random 85,538 removed (83,491 structural, 2,047 SAT-induced). Abort rows: `div` and `hyp` skipped as very large, `log2` and `voter` aborted by consecutive timeouts, `sin` and `mem_ctrl` aborted by SAT time budget.
- Planted-live fast-mode run: `results_optimized/thesis_results_ALG9_2026-05-08_21-29-13.csv`, manifest `results_optimized/planted_live_manifest_2026-05-08_21-29-13.csv`. Generated 15 planted records over 5 base circuits, 5/5 CEC `PASS`, removed 40 AND2 nodes, all 40 SAT-induced, 1,645 SAT checks, 20 UNSAT acceptances, 0 timeouts, 0.97s optimizer time.
- Planted-live exhaustive-mode run: `results_optimized/thesis_results_ALG9_2026-05-08_21-29-45.csv`, manifest `results_optimized/planted_live_manifest_2026-05-08_21-29-45.csv`. Same 40 SAT-induced removals and 5/5 CEC `PASS`, but 7,457 SAT checks and 20.68s optimizer time. This is useful evidence that fast filtering found the planted faults on this suite while exhaustive was much more expensive.
- Interactive Algorithm 9 planted-live smoke after adding mode/profile prompts: `results_optimized/thesis_results_ALG9_alg9_fast_filtered_planted_live_only_2026-05-09_15-36-47.csv`, manifest `results_optimized/planted_live_manifest_2026-05-09_15-36-47.csv`. Used fast filtered mode, planted-live-only profile, 1 plant/base, 5/5 CEC `PASS`, and removed 20 AND2 nodes.

## Algorithm 9 Runtime Modes

After selecting option `9` in `main.py`, the pipeline now asks for an Algorithm 9 mode:

- `1` fast filtered run: default thesis mode; filtered candidates, standard large-circuit guards, no SAT on very-large circuits.
- `2` exhaustive stuck-at sweep: sets `ALG9_EXHAUSTIVE=1` and caps the dataset at 50k gates with `MAX_DATASET_GATES=50000` to avoid huge EPFL outliers.
- `3` large-circuit filtered survey: keeps filtering enabled, sets `ALG9_ALLOW_VERY_LARGE_SAT=1`, and uses conservative large-circuit candidate/time budgets.
- `4` full exhaustive stuck-at sweep: sets `ALG9_EXHAUSTIVE=1`, removes the dataset gate cap, disables the per-circuit SAT wall-clock abort, disables adaptive timeout aborts, and checks SA0/SA1 candidates across all included circuits. This can take a very long time on large EPFL/external circuits.

It then asks for a dataset profile:

- `1` full mixed run: synthetic fuzz, ISCAS, prepared suites such as EPFL/external, and planted-live.
- `2` planted-live only: quick ATPG sanity check.
- `3` real suites plus planted-live: ISCAS, prepared suites, and planted-live, with no synthetic fuzz.
- `4` fuzz plus planted-live: synthetic AIGER fuzz and planted-live only.
- `5` custom circuit(s) only: accepts a single `.aag`/`.aig` file or a folder of `.aag`/`.aig` files. The default drop folder is `custom_circuits/`; binary `.aig` files are converted to normalized ASCII `.aag` before optimization.

The selected mode/profile are written into the report filename and into CSV columns `Run_Mode` and `Dataset_Profile`.

Default mode is practical/filtered:

```bash
python3 main.py
```

Exhaustive proof-sweep mode:

```bash
ALG9_EXHAUSTIVE=1 python3 main.py
```

Allow SAT on very large EPFL arithmetic circuits:

```bash
ALG9_ALLOW_VERY_LARGE_SAT=1 ALG9_LARGE_MAX_CANDIDATES=100 python3 main.py
```

Exhaustive Algorithm 9 without the huge EPFL arithmetic outliers:

```bash
MAX_DATASET_GATES=50000 ALG9_EXHAUSTIVE=1 python3 main.py
```

Full exhaustive Algorithm 9 with no dataset gate cap and no SAT wall-clock abort:

```bash
ALG9_EXHAUSTIVE=1 ALG9_ALLOW_VERY_LARGE_SAT=1 ALG9_MAX_CANDIDATES=0 ALG9_MAX_SAT_SECONDS=0 ALG9_MAX_CONSEC_TIMEOUTS=0 ALG9_MIN_CHECKS_TIMEOUT_RATE=0 python3 main.py
```

Useful Algorithm 9 knobs:

- `ALG9_EXHAUSTIVE`: default `0`; set `1` to test both SA0/SA1 for every gate.
- `ALG9_FAULT_SIM_MAX_GATES`: default `2000`; circuits up to this size use stronger fault simulation filtering.
- `ALG9_RANDOM_OBS_SIM`: default `1`; above the exact fault-simulation threshold, use deterministic random-pattern observability to nominate ODC-like stuck-at candidates for SAT. Set `0` to fall back to the older constant-signature filter.
- `ALG9_MAX_CANDIDATES`: default `2000`; filtered candidate cap for normal circuits.
- `ALG9_LARGE_GATE_LIMIT`: default `10000`; threshold for lower SAT budget and smaller candidate cap.
- `ALG9_LARGE_MAX_CANDIDATES`: default `100`.
- `ALG9_VERY_LARGE_GATE_LIMIT`: default `50000`; above this, SAT is skipped unless explicitly allowed.
- `ALG9_ALLOW_VERY_LARGE_SAT`: default `0`; set `1` for overnight large arithmetic experiments.
- `ALG9_MAX_SAT_SECONDS`: default `30`; per-circuit SAT-phase wall-clock budget for Algorithm 9.
- `ALG9_MAX_CONSEC_TIMEOUTS`: default `20`; aborts the SAT phase after this many consecutive limited SAT calls return unknown.
- `ALG9_MIN_CHECKS_TIMEOUT_RATE`: default `50`; minimum SAT checks before timeout-rate abort can trigger.
- `ALG9_MAX_TIMEOUT_RATE`: default `0.80`; aborts the SAT phase when timeout rate is too high after the minimum check count.

Algorithm 10 checkpoint/budget knobs:

- `ALG10_MODE`: `fast_save` or `deep_resume`; controls default budgets and per-circuit time.
- `ALG10_BUDGETS`: comma-separated increasing conflict budgets, for example `100,1000,5000`.
- `ALG10_MAX_CIRCUIT_SECONDS`: per-circuit wall-clock budget. On expiry, Algorithm 10 writes the latest safe AAG and checkpoint, then returns so `main.py` can verify and move to the next circuit.
- `ALG10_CHECKPOINT_DIR`: default `results_optimized/alg10_checkpoints`; stores `<circuit>.json` and `<circuit>.work.aag`.
- `ALG10_RESET_CHECKPOINT`: set `1` to ignore a previous checkpoint and restart from the current input.
- `ALG10_TFI_CONSTANCY`: default `1`; try a sound TFI constancy SAT proof before the global miter.
- `ALG10_TFI_BUDGET`: default `500` in fast-save and `2000` in deep-resume.
- `ALG10_TFI_MAX_CONE_GATES`: default `2000` in fast-save and `10000` in deep-resume; larger cones skip TFI and go to global SAT.

Planted-live benchmark knobs:

- `ONLY_PLANTED_LIVE`: default `0`; set `1` to generate and run only planted-live ATPG benchmarks.
- `INCLUDE_PLANTED_LIVE`: default `1`; set `0` to disable planted-live generation in full runs.
- `PLANTED_LIVE_PER_BASE`: default `6`; number of plants inserted into each base circuit.
- `PLANTED_LIVE_SEED`: default `20260508`; deterministic seed for side-signal selection.

## Terminal Note

Algorithm 1 is the slowest baseline. If `main.py` appears stuck on `alu_8bit.aag` after selecting `1`, that is expected for the naive baseline. Also, pressing `Ctrl+Z` suspends the process rather than stopping it. Use `fg` to resume or `kill %1` to terminate the suspended job.

## 2026-05-27 Alg10 Overnight Status

The Alg10 24h unresolved-to-zero campaign was stopped at the end of the session. Two `python main.py` processes had been observed during the run; the active high-CPU one had already exited, and the remaining low-CPU `python main.py` process was killed manually. A final process check showed no remaining `python main.py` process.

Latest checkpoint family:

- Checkpoint dir: `results_optimized/alg10_checkpoints_resume_pool_presim`

## 2026-06-13 Alg10 Frontier Accounting Decision Point

Latest completed overnight run:

- Log: `alg10_best_protected_12h_20260612_214114.log`
- Report: `results_optimized/thesis_results_ALG10_alg10_strict_audit_zero_resume_pool_presim_current_real_suites_planted_2026-06-12_21-41-14.csv`
- Finished cleanly; no `main.py` process remained afterward.
- CEC PASS rows: `144/144`.
- CEC PASS latest circuits: `38/38`.
- Total removed latest circuits: `2303` gates.
- SAT unresolved latest circuits: `116619`.
- Main remaining latest unresolved circuits: `hyp=50141`, `mem_ctrl=45133`, `log2=10381`, `sqrt=9667`, `div=1254`, `sin=43`.
- Div checkpoint seeding was fixed: div now starts from `233` removed rather than the weaker `227` removed seed.

Important correction:

- The remembered `voter` unresolved range around `1900` was real historically (`1908`, `2003`, `2211`, etc.).
- Later checkpoints solved voter: latest useful result is `removed=1509`, `SAT_Unresolved=0`.
- Do not spend debugging time on voter unless a new run regresses it.

Problem found:

- Some low unresolved numbers from previous summaries were misleading because tier frontier checkpoints stored `pending` and `escalated` lists.
- The old checkpoint ranking used only `telemetry["unresolved"]`, which could count pending candidates while ignoring escalated candidates.
- Examples: `sqrt=94` and `hyp=259` were not reliable total-frontier unresolved counts.

Patch made:

- Added `_phase_resume_unresolved_count(state)` in `optimizer_alg10_tiered.py`.
- Added `_checkpoint_unresolved_from_data(data)`.
- Checkpoint selection now ranks by true frontier size, using `max(telemetry_unresolved, pending + escalated)` where applicable.
- Checkpoint saving now stores unresolved as at least the full saved frontier size.
- External checkpoints keep valid `phase_resume` metadata; validation still requires matching `work_sha256` and `gate_count`.
- Runtime telemetry is guarded so a saved phase frontier cannot report less unresolved than its true frontier.

Corrected checkpoint selection for remaining hard circuits:

- `hyp`: selects realistic unresolved `946`, valid global frontier.
- `mem_ctrl`: selects realistic unresolved `8466`, no valid exact frontier.
- `log2`: selects realistic unresolved `10764`, valid global frontier.
- `sqrt`: selects realistic unresolved `368`, valid global frontier.
- `div`: selects realistic unresolved `955`, valid global frontier.
- `sin`: selects realistic unresolved `16`, valid global frontier.

Tests run after the patch:

- `venv/bin/python -m py_compile optimizer_alg10_tiered.py test_alg10_resume_pool.py main.py`
- `venv/bin/python -c "import test_alg10_resume_pool as t; t.test_external_checkpoint_preserves_valid_phase_resume(); t.test_checkpoint_rank_counts_tier_pending_and_escalated(); print('new resume/frontier tests passed')"`
- `venv/bin/python test_alg10_resume_pool.py`
- `venv/bin/python test_alg10_checkpoint.py`
- `git diff --check`

All passed.

Review prompt created for outside feedback:

- `LLM_REVIEW_PROMPT_FRONTIER_FIXED_DECISION_2026-06-13.md`

Feedback received:

- Run the patched experiment, but treat it as validation rather than a guaranteed breakthrough.
- Do not run a full 38-circuit campaign again; split finish-line circuits from heavyweight diagnostics.
- Add explicit success criteria before running.
- Preflight `tried_asc` versus `untried_first` on `sin` for 30 minutes.
- Add invariants for duplicate/overlapping frontier candidates before trusting saved frontier counts.
- Keep `voter` out of the blocker list; it is already solved.

Follow-up changes made:

- Added `ALG10_GLOBAL_FRONTIER_ORDER=untried_first`; this schedules candidates with no previous budget before tried candidates, then falls back to tried-budget ascending order.
- Hardened saved frontier validation: duplicate global candidates, duplicate tier candidates, and pending/escalated overlap now invalidate phase-resume metadata and fall back safely.
- Added `alg10_decision_summary.py` to compare run CSVs against corrected baselines/targets and flag non-informative runs that only skipped already exhausted budgets.
- Added tests:
  - `test_tier_frontier_overlap_and_duplicates_are_rejected`
  - `test_untried_first_global_frontier_order`
- Added run protocol with thresholds and split commands:
  - `ALG10_FRONTIER_FIXED_RUN_PROTOCOL_2026-06-13.md`

Preflight outcome on 2026-06-13:

- Commands were launched for `sin` using the default mode budgets (`1000,5000,20000,100000,500000`).
- Both `tried_asc` and `untried_first` finished quickly and were non-informative.
- Result for both: `SAT_Unresolved=16`, `Global_Budget_History_Loaded=16`, `Global_Budget_History_Skipped=80`, `Global_Budget_History_Exhausted=16`, `SAT_Checks=0`.
- Cause: the exact `sin` frontier had already been tried through the configured max budget, so the engine correctly skipped repeated budget work.
- Protocol updated: use fresh higher budgets (`ALG10_BUDGETS=1000000,2000000,5000000`) for the next preflight and focused finish-line/heavyweight runs.
- High-budget `sin` preflight finished with useful progress:
  - Report: `results_optimized/thesis_results_ALG10_alg10_strict_audit_zero_resume_pool_presim_current_custom_only_2026-06-13_11-56-31.csv`
  - `SAT_Unresolved=13`, improved from corrected baseline `16`.
  - `SAT_Checks=9`, `SAT_Query_SAT=2`, `SAT_Query_UNSAT=0`, `SAT_Timeouts=7`.
  - This validates that higher budgets are worth running, but progress is slow and CPU-bound.
- Added `alg10_parallel_portfolio.py` for safe process-level parallelism:
  - `finishline`: runs `sin`, `div`, `sqrt`, `hyp`, and `voter` as independent workers.
  - `heavyweights`: runs `log2` and `mem_ctrl` separately.
  - `sin-portfolio`: runs multiple global frontier orders for `sin`.
  - Each worker has its own checkpoint dir and normal CEC verification; use later waves or `ALG10_EXTRA_CHECKPOINT_DIRS` to import the best produced checkpoints.
- Parallel launcher bug found and fixed:
  - Bad run: `finishline_parallel_20260613_131546`.
  - Symptom: huge repeated missing-file loop in `alg10_parallel_finishline_parallel_20260613_131546_sin.log` and a huge shared CSV at `results_optimized/thesis_results_ALG10_alg10_strict_audit_zero_resume_pool_presim_current_custom_only_2026-06-13_13-15-46.csv`.
  - Root cause: several `main.py` workers started in the same second and shared the same timestamp-derived dataset directory, output directory, and report CSV.
  - Fix: `main.py` now accepts `THESIS_RUN_TIMESTAMP`, and `alg10_parallel_portfolio.py` gives each worker a unique microsecond timestamp containing the tag and task name.
  - Additional guard: a fatal per-circuit exception in repeat-until-zero mode now marks that path stalled instead of repeating the same error forever.
  - Launcher now handles `SIGTERM`/`SIGINT` and terminates active child workers.
  - Verified with `sin-portfolio` smoke run using two concurrent workers; separate report CSVs were produced.
  - Verified signal cleanup with `signal_cleanup_smoke`: killing only the launcher terminated both active `main.py` child workers; final process table had no Alg10 workers.

Do not blindly start another 12-hour full-suite run. Follow the protocol:

1. Run preflight tests.
2. Create split custom suites.
3. Run 30-minute high-budget `sin` preflight; if ordering ties, prefer `untried_first`.
4. Run finish-line 12-hour focused campaign, preferably with `alg10_parallel_portfolio.py --scenario finishline --jobs 4`.
5. Run `log2`/`mem_ctrl` as separate diagnostics.
- Latest run-local dataset marker: `dataset_2026-05-26_03-02-39`
- Latest checkpoint timestamp: `2026-05-27 00:09:17`
- Circuits in marker: 38
- Circuits with nonzero `SAT_Unresolved`: 8
- Raw latest checkpoint total `SAT_Unresolved`: 475986

Remaining nonzero latest checkpoint rows:

| Circuit | SAT_Unresolved | Status | Latest checkpoint |
| --- | ---: | --- | --- |
| `epfl_epfl_arithmetic_hyp.aag` | 428670 | `USER_INTERRUPT_CHECKPOINT` | `2026-05-27 00:09:17` |
| `epfl_epfl_arithmetic_log2.aag` | 13439 | `TIME_BUDGET_CHECKPOINT` | `2026-05-26 23:15:20` |
| `epfl_epfl_random_control_arbiter.aag` | 12403 | `TIME_BUDGET_CHECKPOINT` | `2026-05-26 23:35:26` |
| `epfl_epfl_random_control_mem_ctrl.aag` | 8466 | `TIME_BUDGET_CHECKPOINT` | `2026-05-26 23:45:26` |
| `epfl_epfl_arithmetic_sqrt.aag` | 7649 | `TIME_BUDGET_CHECKPOINT` | `2026-05-26 23:25:24` |
| `epfl_epfl_random_control_voter.aag` | 3942 | `TIME_BUDGET_CHECKPOINT` | `2026-05-26 23:55:27` |
| `epfl_epfl_arithmetic_div.aag` | 1390 | `TIME_BUDGET_CHECKPOINT` | `2026-05-27 00:05:30` |
| `epfl_epfl_arithmetic_sin.aag` | 27 | `UNRESOLVED_TIMEOUTS` | `2026-05-26 19:28:57` |

Interpretation note: the `hyp` row is a `USER_INTERRUPT_CHECKPOINT`, so its raw unresolved count is an interrupted in-circuit checkpoint and should be interpreted cautiously against previous completed-cycle counts. The last clearly completed checkpoint before that was `div` with 1390 unresolved.

## Files To Watch

- `main.py`: experiment orchestration, dataset generation, optimizer selection, report writing.
- `abc_utils.py`: required ABC/AIGER bridge for conversion, CEC, and strash.
- `generators.py`: synthetic AAG benchmark generation.
- `verifier.py`: ABC CEC first through `abc_utils`, Python SAT miter fallback.
- `optimizer_alg*.py`: optimizer engines called by `main.py`.

## Closeout 2026-05-18: Algorithm 10 CEX-Window Audit State

Current thesis boundary is unchanged and must stay explicit:

- combinational AIG/AAG only;
- latches only as combinational cut boundaries;
- greedy proof-driven stuck-at constant redundancy removal;
- no maximum/optimal reduction claim;
- no sequential redundancy claim;
- no simulation-based acceptance;
- final ABC CEC is mandatory for every reported optimized circuit.

### Current Algorithm 10 Default

When Algorithm 10 is selected through `main.py`, the best current point-of-time profile is now:

- current candidate ordering;
- TFI constancy SAT;
- audited bounded TFO window miter;
- exact affected-output cone miter;
- global configurable-fault miter fallback;
- rejection-only CEX pruning.

The run labels are:

- `alg10_fast_save_cex_window`;
- `alg10_deep_resume_cex_window`.

The most important environment knobs are:

- `ALG10_CEX_PRUNING=1`;
- `ALG10_WINDOW_MITER=1`;
- `ALG10_WINDOW_AUDIT=1`;
- `ALG10_AUDIT_CEX_PRUNING=1` for expensive recall auditing, off by default;
- `ALG10_AUDIT_CEX_PRUNING_BUDGET`;
- `ALG10_AUDIT_CEX_PRUNING_MAX`.

### Latest Result Interpretation

Latest broad fast/resumed CSV:

```text
results_optimized/thesis_results_ALG10_alg10_fast_save_cex_window_real_suites_planted_2026-05-17_23-22-24.csv
```

It reported 38/38 `Verify=PASS`.

Important rows:

- `c7552`: 1693 -> 1679, removed 14, PASS.
- `c6288`: 1870 -> 1870, removed 0, PASS, but many candidates were rejected by CEX pruning.
- EPFL `sin`: 5416 -> 5389, removed 27, PASS, TFI dominated.
- EPFL `sqrt`: 24618 -> 24582, removed 36, PASS, window tier found 13 UNSAT proofs.
- EPFL `div`: 57247 -> 57203, removed 44, PASS, TFI dominated.
- EPFL `log2`: 32060 -> 32052, removed 8, PASS.
- EPFL `mem_ctrl`: 46836 -> 46834, removed 2, PASS.

Caveat: this broad run resumed checkpoints. Thesis tables should use clean isolated runs with `ALG10_RESET_CHECKPOINT=1`.

Clean ablation evidence before closeout:

- `c7552`, 15s: `cex_window_current` matched the 14-removal best result with much lower SAT time than non-CEX profiles.
- EPFL `sin`, 20s: `cex_window_current` reached 39 removals versus 31 for the non-CEX current profile.
- EPFL `sqrt`, 20s: `cex_window_current` found 36 removals where earlier short current/window/global-only profiles found 0.
- `c6288`, 20s: CEX pruning made the run complete quickly but still found 0 removals, which is useful negative evidence for a hard multiplier.

### CEX Recall Audit

External review correctly identified that final CEC cannot validate CEX pruning quality. CEX pruning is rejection-only, so a bad prune causes a missed redundancy, not a wrong circuit. ABC CEC would still return PASS.

Implemented `ALG10_AUDIT_CEX_PRUNING=1`:

- every output-level CEX prune candidate is immediately rechecked by a full exact observable miter in the same committed context;
- SAT confirms the prune;
- UNSAT is counted as `CEX_Audit_False_Prunes` and the candidate is not dropped;
- timeout/skip also leaves the candidate alive in audit mode.

Audit telemetry:

- `CEX_Audit_Enabled`;
- `CEX_Audit_Checked`;
- `CEX_Audit_SAT`;
- `CEX_Audit_False_Prunes`;
- `CEX_Audit_Timeouts`;
- `CEX_Audit_Skipped`;
- `CEX_Audit_Limit_Hit`.

Final smoke before closing:

```text
venv/bin/python -m py_compile optimizer_alg10_tiered.py main.py sat_ablation_experiments.py
venv/bin/python test_alg10_checkpoint.py
venv/bin/python sat_ablation_experiments.py --circuits benchmarks/c432.aag --variants cex_window_audit --seconds 5 --budgets 100,1000 --output-dir /tmp/alg10_audit_ablation_final_smoke
```

Results:

- compile passed;
- Algorithm 10 checkpoint tests passed;
- audit ablation on `c432` produced 125 -> 121, removed 4, `Verify=PASS`;
- `CEX_Audit_Checked=1088`;
- `CEX_Audit_SAT=1088`;
- `CEX_Audit_False_Prunes=0`;
- `Window_Query_UNSAT=2`.

### Contribution Assessment

Current state is more than a simple software project if it is written carefully. The contribution is not "beating ABC" and not "a general AIG optimizer." The defensible research contribution is:

> A correctness-gated SAT architecture for combinational AIG stuck-at constant redundancy removal, combining tiered proof obligations, audited bounded-window acceptance, rejection-only CEX pruning, recall auditing for missed-prune risk, and final independent ABC CEC.

Research-grade elements:

- formal proof tiers with explicit soundness conditions;
- global configurable-fault encoding with assumption audit;
- audited bounded window that converts a risky local technique into a conditional proof tier;
- CEX pruning separated from acceptance;
- CEX recall audit that measures pruning omissions instead of relying on CEC;
- tier-by-tier telemetry and ablation evidence.

Engineering/project elements:

- menu pipeline;
- checkpointing;
- CSV/report plumbing;
- ABC conversion wrapper;
- benchmark orchestration.

The thesis should present both, but the contribution claim should focus on the SAT-side proof/pruning architecture and the empirical ablations.

### Next Best Steps

1. Run capped CEX recall audit on `c7552` and EPFL `sqrt`.
   - Start with `ALG10_AUDIT_CEX_PRUNING_MAX=500` or `1000`.
   - Goal: show zero false prunes on more meaningful circuits before trusting large CEX pruning tables.

2. Run clean deep mode on promising circuits with isolated checkpoints:
   - `sin`;
   - `sqrt`;
   - `div`;
   - `log2`;
   - `mem_ctrl`.

3. Build ABC baseline runner:
   - `strash`;
   - `dc2`;
   - `dch`;
   - `fraig`;
   - `resyn2` or explicit equivalent rewrite/refactor script.

4. Keep hard zero circuits as diagnostic:
   - `c6288`;
   - EPFL `multiplier`;
   - EPFL `hyp`;
   - EPFL `arbiter`.

5. Consider next SAT-side implementation after audit/deep evidence:
   - structural blocked-candidate detection after commits;
   - adaptive tier routing;
   - candidate ordering by TFI or affected-cone size.

Do not pivot to MaxSAT, full FRAIG, or sequential reasoning in the main thesis path.

### Final Reviewer Prompt

The final closeout prompt for external reviewers is:

```text
LLM_REVIEW_PROMPT_FINAL_SAT_CEX_AUDIT_CLOSEOUT.md
```

It includes the current architecture, latest results, CEX recall audit, and asks specifically whether this is research-grade and what the next SAT-side step should be.
- `benchmarks/`: static `.aag` benchmark inputs copied into the generated dataset.
- `benchmark_suites/`: reusable prepared benchmark suites copied into each `main.py` dataset run when `INCLUDE_BENCHMARK_SUITES` is enabled.
- `dataset_benchmarks/`: regenerated by `main.py`; do not treat contents as permanent source.
- `results_optimized/`: generated optimized circuits and CSV reports.
- `thesis_plots.py`: plot generation from result CSVs.

## Safe Session Workflow

1. Open `main.py` first to understand which algorithm path is being tested.
2. Check the target `optimizer_alg*.py` return signature before changing it.
3. For ABC operations, use `abc_utils.py` instead of raw `read_aiger file.aag`.
4. Run focused scripts or tests before launching the full experiment, because `main.py` generates hundreds of circuits.
5. Preserve original circuit files and generated reports when comparing algorithm changes.
6. Consider a run successful only when the `Verify` column is `PASS` for the circuits being claimed.

## Generated State

`main.py` deletes and recreates these paths on each full run:

- `dataset_benchmarks/`
- `results_optimized/latest_run/`

Do not keep manual-only work in those directories.

## 2026-05-09 Session Checkpoint

Today's goal was to make the current pipeline professor-ready, add an easy way to run future professor-supplied circuits, deeply check algorithms `1-9`, and commit the verified state.

Implemented and verified:

- Added interactive Algorithm 9 runtime/profile prompts in `main.py`.
- Added Algorithm 9 dataset profile `5`: custom circuit(s) only.
- Added `custom_circuits/README.md` as the default drop folder instruction.
- Custom profile accepts either a single `.aag`/`.aig` file or a folder of `.aag`/`.aig` files.
- Binary `.aig` custom files are converted to normalized ASCII `.aag` through `abc_utils.to_ascii_aag(...)`.
- Added `Run_Mode` and `Dataset_Profile` CSV columns and put the selected Algorithm 9 mode/profile into report filenames.
- Added prepared EPFL benchmark suite under `benchmark_suites/` plus `benchmark_suites/manifest.csv`.
- Updated docs: `ARCHITECTURE.md`, `COMMANDS.md`, `CONVENTIONS.md`, and this `SESSION.md`.
- Fixed one small Algorithm 9 reporting bug: exhaustive mode now reports `SAT_Candidates = 2 * gate_count`, matching the actual SA0/SA1 sweep. This was telemetry only; optimization correctness was already protected by SAT plus final CEC.

Professor-facing Algorithm 9 explanation:

- Build two circuit copies in one CNF: good and configurable-faulty.
- Primary inputs/latches are shared so both copies receive the same assignment.
- Each AND gate is encoded with standard Tseitin CNF for `out = a AND b`.
- The faulty copy gives every gate two control literals: `f0_i` for stuck-at-0 and `f1_i` for stuck-at-1.
- Add mutex `not f0_i OR not f1_i`.
- Faulty gate behavior is encoded as `faulty_out = (normal_out AND not f0_i) OR f1_i`.
- Build a miter as OR of output XORs between good and faulty circuits.
- For a candidate replacement, solve under assumptions: previous accepted replacements stay active, the new candidate stuck-at control is active, the opposite stuck-at control is disabled, and the miter is asserted.
- `SAT` means a counterexample exists, so reject the candidate.
- `UNSAT` means no input distinguishes the circuits, so commit the replacement in memory.
- After accepted replacements, rebuild and structurally clean the AAG, then run final ABC CEC. Thesis claims should count only `Verify = PASS`.

Checks completed after the changes:

- `venv/bin/python -m py_compile main.py optimizer.py optimizer_alg1.py optimizer_alg2.py optimizer_alg3.py optimizer_alg3_saf.py optimizer_alg3_sim.py optimizer_alg3_timeout_cadical.py optimizer_alg7_iterative.py optimizer_alg8_hybrid.py optimizer_alg9_incremental.py verifier.py abc_utils.py aag_metrics.py generators.py test_incremental_sat_pipeline.py prepare_benchmark_suites.py thesis_plots.py`
- Custom `/tmp/check_algorithms_1_to_9.py` smoke: algorithms `1-9` on `benchmarks/c17.aag`, all outputs produced, all ABC CEC `PASS`.
- `venv/bin/python test_incremental_sat_pipeline.py`: ALG8/ALG9 on `odc_redundant`, `c17`, `c432`, all `PASS`.
- ABC wrapper smoke: CEC `benchmarks/c17.aag` vs itself `PASS`; ABC strash wrapper returned output.
- Algorithm 9 planted-live-only main run: fast filtered mode, 1 plant/base, 5/5 `PASS`, 20 AND2 nodes removed.
- Algorithm 9 custom `.aag` profile smoke: `benchmarks/c17.aag`, `PASS`.
- Algorithm 9 custom `.aig` profile smoke: `/tmp/custom_profile_c17.aig`, `PASS`.
- Algorithm 9 modes `1`, `2`, and `3` were each tested through `main.py` using custom `benchmarks/c17.aag`, all `PASS`.
- CSV alignment checked by header: latest comparison, planted-live, and custom reports all had consistent columns and `Verify = PASS`.
- `git diff --cached --check` passed after normalizing `benchmark_suites/manifest.csv` line endings.

Useful smoke report paths from today:

- `results_optimized/incremental_sat_test/2026-05-09_17-37-33/incremental_sat_comparison_2026-05-09_17-37-33.csv`
- `results_optimized/thesis_results_ALG9_alg9_fast_filtered_planted_live_only_2026-05-09_17-37-41.csv`
- `results_optimized/thesis_results_ALG9_alg9_fast_filtered_custom_only_2026-05-09_17-26-08.csv`
- `results_optimized/thesis_results_ALG9_alg9_exhaustive_cap50k_custom_only_2026-05-09_17-38-18.csv`
- `results_optimized/thesis_results_ALG9_alg9_large_filtered_custom_only_2026-05-09_17-38-25.csv`

Git state:

- Local commit created: `5aa5ff3 Add verified in-memory SAT thesis pipeline`.
- Push was attempted with `git push origin main` but failed because this shell has no GitHub HTTPS credentials: `fatal: could not read Username for 'https://github.com': No such device or address`.
- `gh` is not installed.
- SSH auth also was not available in this shell: host key verification / askpass failure.
- Branch state after commit: `main...origin/main [ahead 1]`.
- To push from an authenticated terminal, run:

```bash
git push origin main
```

Files intentionally left untracked and not committed:

- `binary_encoding_test.py`
- `sandbox_in_memory.py`
- `temp_mod.aag`
- `test_binary.aig`
- `test_encoding_surgery.py`
- `test_python_strash_out.aag`
- `test_surgery_out.aag`
- `verify_final.py`

Near-term thesis plan:

- Use Algorithm 9 as the main thesis engine.
- Use planted-live fast vs exhaustive runs as evidence that filtering finds planted redundancies much faster.
- Use full mixed and real-suite profiles for final evaluation tables.
- Use custom profile `5` for any new circuits from the professor.
- Stop changing core Algorithm 9 soon; focus next on final benchmark matrix, plots, chapter writing, and presentation preparation.

## 2026-05-15 Random Simulation Checkpoint

Added Algorithm 9 random-observability candidate filtering for circuits above the exact fault-simulation threshold. This is not a proof step: simulation only nominates candidates, incremental SAT still proves each accepted stuck-at replacement, and final ABC CEC remains mandatory for reported results.

New/updated files:

- `optimizer_alg9_incremental.py`: added `ALG9_RANDOM_OBS_SIM`, deterministic primary signatures, and a linear-time random observability pass for large-circuit candidate nomination.
- `test_alg9_random_observability.py`: focused smoke where signature-only filtering misses `out = x OR (x AND y)`, while random observability nominates the ODC stuck-at-0 candidate and SAT proves it.

Smoke checks:

- `venv/bin/python -m py_compile optimizer_alg9_incremental.py test_alg9_random_observability.py`
- `venv/bin/python test_alg9_random_observability.py`: signature-only `2 -> 2`, random-observability `2 -> 0`, CEC `PASS`.
- `venv/bin/python test_incremental_sat_pipeline.py`: ODC, `c17`, and `c432` all CEC `PASS`.
- `ALG9_FAULT_SIM_MAX_GATES=0 ALG9_RANDOM_OBS_SIM=1 venv/bin/python test_incremental_sat_pipeline.py --epfl`: forced observability path on ODC/ISCAS/EPFL smoke, all CEC `PASS`.
- Capped large-circuit spot check on `benchmark_suites/epfl/epfl_arithmetic_sqrt.aag`: `24618 -> 24618`, abort reason `CONSECUTIVE_TIMEOUTS` under tight smoke budget, CEC `PASS`.

## 2026-05-15 Algorithm 10 Checkpointed SAT

Added `optimizer_alg10_tiered.py` and wired it into `main.py` as option `10`. Algorithm 10 is intentionally conservative: it does not use simulation or local windows as acceptance proofs. It checks all SA0/SA1 candidates through the global Algorithm-9-style miter, cycling through increasing conflict budgets and saving the latest safe optimized AAG when a per-circuit time limit or user interrupt occurs.

Implemented behavior:

- Fast-save mode: bounded per-circuit run, writes checkpoint and latest safe `.aag`, then returns to `main.py` for final CEC and the next circuit.
- Deep-resume mode: loads the checkpoint work AAG for the same dataset path/hash and retries with larger budgets.
- Checkpoint files: JSON telemetry plus `.work.aag`; live solver state is not serialized.
- Correctness boundary: every accepted stuck-at replacement is global-SAT UNSAT under the currently committed replacements; final ABC CEC is still required.

Smoke checks:

- `venv/bin/python test_alg10_checkpoint.py`: ODC `2 -> 0` CEC `PASS`; forced c432 checkpoint `125 -> 125` CEC `PASS`; deep-resume c432 `125 -> 121` CEC `PASS`.
- `venv/bin/python test_algorithms_1_to_10.py`: algorithms `1-10` on `c17`, all CEC `PASS`; algorithms `8-10` on `c432`, all CEC `PASS`.
- `main.py` Algorithm 10 custom `benchmarks/c432.aag`, fast-save with `ALG10_MAX_CIRCUIT_SECONDS=0.001`: row reports `TIME_BUDGET_CHECKPOINT`, `125 -> 125`, CEC `PASS`.
- `main.py` Algorithm 10 custom `benchmarks/c432.aag`, deep-resume from the same checkpoint: row reports `125 -> 121`, CEC `PASS`.

## 2026-05-15 Algorithm 10 TFI Tier

Added a sound TFI constancy tier to Algorithm 10. For a candidate stuck-at value, it encodes only the complete transitive fanin of the target gate and asks whether the opposite gate value is reachable. If the local SAT instance is `UNSAT`, the gate is functionally constant and the stuck-at replacement is safe. If it is `SAT`, times out, or is skipped due to cone size, the candidate still escalates to the existing global miter path.

Telemetry added to new CSVs:

- `TFI_Checks`, `TFI_Query_SAT`, `TFI_Query_UNSAT`, `TFI_Timeouts`, `TFI_Skipped`
- `Global_Checks`, `Global_Query_SAT`, `Global_Query_UNSAT`, `Global_Timeouts`

Smoke checks:

- `venv/bin/python test_alg10_checkpoint.py`: ODC case still accepted by global miter; TFI-constant case `3 -> 0` accepted by `TFI_Query_UNSAT=1`; checkpoint/resume c432 still CEC `PASS`.
- `venv/bin/python test_algorithms_1_to_10.py`: algorithms `1-10` on `c17`, all CEC `PASS`; algorithms `8-10` on `c432`, all CEC `PASS`.
- `main.py` Algorithm 10 custom `benchmarks/c432.aag`: `125 -> 121`, CEC `PASS`, CSV includes TFI/global split.
- 5-second EPFL `sqrt` smoke with TFI enabled: `24618 -> 24618`, `TFI_Checks=1642`, no TFI UNSAT, checkpointed by time budget, CEC `PASS`.

## 2026-05-15 End-of-Day Checkpoint

Today added and verified the current Algorithm 10 direction:

- `optimizer_alg10_tiered.py`: checkpointed budget-cycling global SAT engine.
- Algorithm 10 fast-save mode: bounded per-circuit runtime, latest safe `.aag`, checkpoint JSON/work AAG, then return to `main.py`.
- Algorithm 10 deep-resume mode: resumes checkpoint work AAG and retries with larger budgets.
- Algorithm 10 TFI constancy tier: sound local SAT proof before global miter. TFI `UNSAT` can commit; TFI `SAT`, timeout, or skip still escalates globally, so candidate coverage is not reduced.
- Algorithm 9 random-observability candidate nomination is present and documented; SAT remains the proof step.
- `main.py`: menu now includes Algorithm 10 and CSV telemetry for checkpoint/TFi/global split.
- `Readme.md`, `COMMANDS.md`, and `custom_circuits/README.md` updated for the current pipeline.

Latest important reports:

- Fast full mixed Algorithm 10 survey: `results_optimized/thesis_results_ALG10_alg10_fast_save_full_mixed_2026-05-15_19-06-11.csv`.
  - 240/240 `PASS`.
  - 226 complete, 14 `TIME_BUDGET_CHECKPOINT`.
  - Total saved: 165,902 AND2 nodes.
- Deep real-suites + planted-live resume: `results_optimized/thesis_results_ALG10_alg10_deep_resume_real_suites_planted_2026-05-15_19-32-25.csv`.
  - 38/38 `PASS`.
  - Same 62 AND2 saved as fast mode on the overlapping circuits.
  - Better coverage than fast mode but no new reductions in that run.

Interpretation:

- Algorithm 10 checkpointing works and is safe.
- Deep global SAT alone is not enough for hard EPFL arithmetic circuits such as `div`, `hyp`, `sqrt`, and `multiplier`; it spends time but found no new UNSAT reductions in the latest deep run.
- The TFI tier is sound and useful for local constants, but the quick EPFL `sqrt` smoke found no TFI UNSAT. Next improvement should likely be exact affected-output cone miter or stronger candidate ordering, not blind longer global runs.

Useful checks already run after today's edits:

- `venv/bin/python -m py_compile main.py optimizer_alg10_tiered.py optimizer_alg9_incremental.py test_alg10_checkpoint.py test_algorithms_1_to_10.py test_alg9_random_observability.py`
- `venv/bin/python test_alg10_checkpoint.py`
- `venv/bin/python test_algorithms_1_to_10.py`
- `venv/bin/python test_alg9_random_observability.py`
- `main.py` Algorithm 10 custom `benchmarks/c432.aag`: `125 -> 121`, CEC `PASS`.

Tomorrow's recommended next step:

1. Do not spend another overnight run on plain global SAT for EPFL arithmetic yet.
2. Implement exact affected-output cone miter as the next sound middle tier.
3. Keep Algorithm 10's checkpoint/resume wrapper as the orchestration shell.
4. Add telemetry separating inherited checkpoint reductions from newly found reductions in the current run.

## 2026-05-17 Algorithm 10 Cone-Miter Tier

Implemented the recommended exact affected-output cone miter as a new sound Algorithm 10 middle tier between TFI constancy and full global SAT.

Behavior:

- `optimizer_alg10_tiered.py` now runs proof tiers in this order: TFI constancy, exact affected-output cone miter, then full global miter.
- The cone tier identifies only output/latch-next roots in the candidate's fanout, then encodes the complete fanin cone for those affected roots.
- Cone `UNSAT` can safely commit a stuck-at replacement; cone `SAT`, timeout, or skip still falls through toward global SAT.
- Accepted cone replacements are accumulated against a working gate list, so later cone proofs see earlier committed replacements before the phase rebuild.
- New knobs: `ALG10_CONE_MITER`, `ALG10_CONE_BUDGET`, and `ALG10_CONE_MAX_GATES`.
- New CSV telemetry: `Cone_Checks`, `Cone_Query_SAT`, `Cone_Query_UNSAT`, `Cone_Timeouts`, and `Cone_Skipped`.

Smoke checks:

- `venv/bin/python -m py_compile main.py optimizer_alg10_tiered.py test_alg10_checkpoint.py`
- `venv/bin/python test_alg10_checkpoint.py`
  - ODC case: `Cone_Query_UNSAT=1`, `Global_Query_UNSAT=0`, CEC `PASS`.
  - TFI-constant case still accepted by TFI, CEC `PASS`.
  - c432 checkpoint/deep-resume still CEC `PASS`; deep resume reports cone UNSAT reductions.
- `venv/bin/python test_algorithms_1_to_10.py`: algorithms `1-10` on `c17` all CEC `PASS`; algorithms `8-10` on `c432` all CEC `PASS`.
- `main.py` Algorithm 10 custom `benchmarks/c432.aag`: `125 -> 121`, CEC `PASS`, CSV had 53 header fields and 53 row fields, with `Cone_Query_UNSAT=2`.

Remaining recommended next step:

- Add telemetry separating reductions inherited from a checkpoint from newly found reductions in the current run.

## 2026-05-17 SAT Ablation Experiments

Responded to external LLM feedback by adding testable Algorithm 10 SAT-side knobs instead of guessing a new default.

Implemented:

- `ALG10_CANDIDATE_ORDER`: `current`, `reverse_topo`, `cone_size`, `fanout_desc`, `random`, and related order aliases.
- `ALG10_AUDIT_ASSUMPTIONS`: asserts the global configurable-fault miter receives exactly `2A + 1` non-contradictory assumptions. This directly tests the "free fault controls" criticism. Current global path passes the audit because it builds `control_state = [-f0...] + [-f1...]`.
- Optional bounded TFO window tier:
  - knobs: `ALG10_WINDOW_MITER`, `ALG10_WINDOW_LEVELS`, `ALG10_WINDOW_BUDGET`, `ALG10_WINDOW_MAX_CONE_GATES`;
  - the window tier is UNSAT-only and over-observable: it compares complete fanin cones of nearby fanout boundary roots;
  - window `UNSAT` can commit; `SAT`, timeout, or skip still escalates.
- New telemetry: `Window_Checks`, `Window_Query_SAT`, `Window_Query_UNSAT`, `Window_Timeouts`, and `Window_Skipped`.
- Added `sat_ablation_experiments.py` for repeatable variant matrices with isolated checkpoints and final ABC CEC on every row.
- Added a window-only ODC regression to `test_alg10_checkpoint.py`.

Checks:

- `venv/bin/python test_alg10_checkpoint.py`: ODC cone-only and window-only reductions both CEC `PASS`; c432 checkpoint/deep-resume still CEC `PASS`.
- `venv/bin/python test_algorithms_1_to_10.py`: algorithms `1-10` on `c17` all CEC `PASS`; algorithms `8-10` on `c432` all CEC `PASS`.
- `main.py` Algorithm 10 custom `benchmarks/c432.aag`: `125 -> 121`, CEC `PASS`, CSV had 58 header fields and 58 row fields after adding window telemetry.

Ablation result CSVs:

- `results_optimized/sat_ablation_2026-05-17_18-21-22/sat_ablation_2026-05-17_18-21-22.csv`
- `results_optimized/sat_ablation_2026-05-17_18-23-29/sat_ablation_2026-05-17_18-23-29.csv`
- `results_optimized/sat_ablation_2026-05-17_18-25-23/sat_ablation_2026-05-17_18-25-23.csv`
- `results_optimized/sat_ablation_2026-05-17_18-31-37/sat_ablation_2026-05-17_18-31-37.csv`

Observed so far:

- `c7552`, 15s: current found 4 removed, reverse found 6, `window_reverse` found 14, and global-only audit found 14. Window got the same reduction as global-only with lower SAT time.
- `c7552`, 30s: current found 6, `window_current` and `window_reverse` found 14, global-only current/audit found 14. Window used about 23.5-23.7s SAT; global-only used about 30s SAT.
- EPFL `router`: all variants found the same 6 removals; global-only was fastest on this small circuit.
- EPFL `sin`: current-order TFI dominated. Current/window-current/rebuild-current found 31 removed; reverse/window-reverse found fewer; global-only found 0 under 20-30s.
- `c6288`, EPFL `arbiter`, and EPFL `sqrt`: no reductions in 20s for current/window-current/global-only. These are not useful short ablation targets without stronger pruning or longer budgets.

Current interpretation:

- Do not promote reverse ordering globally; it hurts EPFL `sin`.
- Do not promote global-only globally; it is fast on small router/c432 but poor on `sin`.
- The best candidate for a next experimental profile is current ordering plus optional bounded window before exact cone/global. It improves `c7552` without hurting `sin` in the tested budget, but it still needs broader validation.
- The next truly new improvement should likely be CEX-guided pruning or a more selective candidate generator for hard circuits where all current tiers spend the whole budget with zero removals.

## 2026-05-17 External Feedback Follow-Up

External reviewers flagged the bounded TFO window as correctness-critical. The right conclusion is:

- A bounded window UNSAT proof is sound only if the chosen boundary roots form a complete observable cut: every fanout path from the candidate gate to any real PO/latch-next root must pass through at least one monitored window root.
- Window SAT is inconclusive and must not be used as a global counterexample.
- Local/window CEX values must not be reused for global candidate pruning. Future CEX pruning must use concrete global PI assignments and directly simulate each candidate's faulty output behavior.

Implemented hardening:

- Added `ALG10_WINDOW_AUDIT`, default enabled.
- Added `_window_roots_form_observable_cut(...)`; if the audit fails, the window tier returns skip/escalates instead of committing.
- Added `Window_Audit_Fail` telemetry to Algorithm 10, `main.py`, and `sat_ablation_experiments.py`.
- Updated `LLM_REVIEW_PROMPT_LATEST_SAT_ABLATION.md`, `THESIS_EXPERIMENT_HISTORY.md`, `Readme.md`, and `COMMANDS.md` to state the complete-cut condition.

Checks after hardening:

- `venv/bin/python -m py_compile main.py optimizer_alg10_tiered.py sat_ablation_experiments.py test_alg10_checkpoint.py`
- `venv/bin/python test_alg10_checkpoint.py`: window-only ODC still CEC `PASS`, `Window_Query_UNSAT=1`, `Window_Audit_Fail=0`.
- `sat_ablation_experiments.py --circuits benchmarks/c7552.aag --seconds 15 --variants current window_current global_only_current`:
  - current: `1693 -> 1689`, 4 removed, `PASS`.
  - `window_current`: `1693 -> 1679`, 14 removed, `PASS`, `Window_Query_UNSAT=7`, `Window_Audit_Fail=0`, SAT 10.93s.
  - `global_only_current`: `1693 -> 1679`, 14 removed, `PASS`, SAT 14.98s.
- `main.py` Algorithm 10 custom `benchmarks/c432.aag` with `ALG10_WINDOW_MITER=1`: `125 -> 121`, CEC `PASS`, CSV had 59 header fields and 59 row fields, `Window_Audit_Fail=0`.

Decision:

- Keep bounded window optional, not default, until broader validation.
- Treat CEX-guided pruning as the next implementation target, but only using global PI assignments plus direct faulty-circuit simulation per candidate.

## 2026-05-17 Algorithm 10 CEX-Guided Pruning

Implemented `ALG10_CEX_PRUNING=1` in Algorithm 10 as a rejection-only optimization.

Soundness rule:

- CEX pruning never accepts a stuck-at replacement.
- TFI SAT models can only skip future TFI-constancy checks when the concrete assignment disproves the candidate's stuck value.
- Window, exact-cone, and global SAT models are converted to concrete PI/latch assignments, then each pending candidate is simulated through the full circuit. A candidate is pruned only if its own stuck-at faulty circuit differs from the good circuit at a real output/latch-next root.
- Local/window SAT CEXs are still not treated as proofs by themselves.

Implementation:

- Added bit-parallel full-circuit candidate simulation for output-CEX pruning.
- Added TFI-CEX pruning for the TFI tier.
- Added telemetry: `CEX_Prune_Events`, `CEX_Prune_Checked`, `CEX_Pruned`, `CEX_TFI_Prune_Events`, `CEX_TFI_Prune_Checked`, `CEX_TFI_Pruned`, and `CEX_Pruning_Enabled`.
- Added ablation variants: `cex_current`, `cex_window_current`, and `global_only_cex_current`.

Validation:

- `venv/bin/python -m py_compile optimizer_alg10_tiered.py main.py sat_ablation_experiments.py test_alg10_checkpoint.py`: pass.
- `venv/bin/python test_alg10_checkpoint.py`: all Algorithm 10 smoke checks CEC `PASS`.
- `c7552`, 15s:
  - `current`: 4 removed, SAT 10.89s, checkpoint timeout, CEC `PASS`.
  - `cex_current`: 14 removed, SAT 8.60s, complete, `CEX_Pruned=19238`, CEC `PASS`.
  - `window_current`: 14 removed, SAT 10.15s, checkpoint timeout, CEC `PASS`.
  - `cex_window_current`: 14 removed, SAT 4.34s, complete, `CEX_Pruned=11975`, CEC `PASS`.
  - `global_only_cex_current`: 14 removed, SAT 3.12s, complete, `CEX_Pruned=6477`, CEC `PASS`.
- EPFL `sin`, 20s:
  - `current`: 31 removed, SAT 19.98s, `TFI_Query_UNSAT=15`, CEC `PASS`.
  - `cex_current`: 39 removed, SAT 16.89s, `TFI_Query_UNSAT=19`, `CEX_TFI_Pruned=21232`, CEC `PASS`.
  - `cex_window_current`: 39 removed, SAT 11.16s, `CEX_TFI_Pruned=21232`, `CEX_Pruned=9863`, CEC `PASS`.
  - `global_only_cex_current`: 0 removed, still timed out, CEC `PASS`; global-only is still not a good `sin` default.
- `c6288`, 20s:
  - `current`: 0 removed, SAT 16.28s, checkpoint timeout, CEC `PASS`.
  - `cex_current`: 0 removed, SAT 2.46s, complete, `CEX_Pruned=7413`, `CEX_TFI_Pruned=3521`, CEC `PASS`.
  - `global_only_cex_current`: 0 removed, SAT 1.69s, complete, `CEX_Pruned=3712`, CEC `PASS`.
- Broader CEX-enabled pass:
  - EPFL `router`, 20s: CEX profiles remove 6; `global_only_cex_current` SAT 0.05s, CEC `PASS`.
  - EPFL `arbiter`, 20s: CEX profiles remove 0; `cex_current` pruned 23568 TFI candidates and 2792 output candidates, CEC `PASS`.
  - EPFL `sqrt`, 20s: `cex_window_current` removed 36 where earlier short profiles found 0; SAT 3.16s, `Window_Query_UNSAT=13`, `CEX_Pruned=28378`, `CEX_TFI_Pruned=48978`, CEC `PASS`.

Decision:

- CEX pruning is now one of the strongest additions to test broadly.
- It improves `c7552` reduction/time, improves EPFL `sin` reduction under the same budget, unlocks verified short-budget reductions on EPFL `sqrt`, and makes several hard zero-removal circuits spend far less time in SAT.
- Keep it optional until broader validation, but it is thesis-worthy if the broader matrix confirms these trends.

Pipeline attachment:

- `main.py` Algorithm 10 now defaults to the best tested profile when selected from the menu:
  - `ALG10_CANDIDATE_ORDER=current`
  - `ALG10_TFI_CONSTANCY=1`
  - `ALG10_WINDOW_MITER=1`
  - `ALG10_WINDOW_AUDIT=1`
  - `ALG10_WINDOW_LEVELS=5`
  - `ALG10_CONE_MITER=1`
  - `ALG10_CEX_PRUNING=1`
- Fast-save and deep-resume labels now include `cex_window` so CSV files make the profile visible.
- Environment variables can still override these defaults for ablations.

## 2026-05-19 End-of-Day Closeout: Algorithm 10 CEX Audit, Deep Runs, and Professor Pack

Current thesis framing:

- The work should be presented as a correctness-gated SAT framework for single-gate stuck-at constant redundancy removal on combinational AIG/AAG circuits.
- Do not claim sequential optimization, optimality, exhaustive redundancy discovery when unresolved candidates remain, or superiority over ABC `fraig`, `dc2`, `dch`, or `resyn2`.
- Every reported optimization must still end with final ABC combinational equivalence checking (`Verify=PASS`).
- Safe wording: "verified stuck-at replacement", "tiered SAT proof architecture", "audited bounded-window proofs", "rejection-only CEX pruning", and "complete under the tested budget only when `SAT_Unresolved=0`."

Current Algorithm 10 profile:

- `ALG10_CANDIDATE_ORDER=current`
- `ALG10_TFI_CONSTANCY=1`
- `ALG10_WINDOW_MITER=1`
- `ALG10_WINDOW_AUDIT=1`
- `ALG10_WINDOW_LEVELS=5`
- `ALG10_CONE_MITER=1`
- `ALG10_CEX_PRUNING=1`
- `ALG10_CEX_PRUNING_BATCH_SIZE=512`
- Fast mode: `ALG10_MODE=fast_save`, budgets `100,1000,5000`, default 60s/circuit.
- Deep mode: `ALG10_MODE=deep_resume`, budgets `1000,5000,20000,100000`, default 600s/circuit.

Algorithm explanation for the professor:

- The algorithm tests whether an internal AIG node can be safely replaced by constant 0 or constant 1 without changing real circuit outputs.
- It first tries cheap SAT proofs and escalates only when needed.
- Tier 1, TFI constancy: encode the complete transitive fanin of the target and ask if the opposite value is reachable. UNSAT means the node is functionally constant, so the replacement is committed. SAT only means "not TFI-constant"; it does not reject output-level redundancy.
- Tier 2, bounded TFO window: build a local fanout window and prove that the target fault cannot be observed at the window roots. This tier is accepted only if the runtime audit proves the roots form a complete observable cut from the target to all real observable roots.
- Tier 3, exact affected-output cone: encode the full affected real output/latch-next cones and compare good vs faulty behavior.
- Tier 4, full global configurable-fault miter: encode the whole circuit with stuck-at controls and use assumptions to activate only the current candidate plus committed replacements.
- CEX pruning is rejection-only. It uses SAT counterexamples to eliminate candidates that are demonstrably non-redundant under a concrete PI/latch assignment. It never commits a replacement.
- CEX recall audit checks the pruning itself: when output-level CEX pruning wants to drop a candidate, audit mode rechecks that exact candidate using the exact observable miter. SAT confirms the prune; UNSAT would mean a false prune and the candidate is kept.

Important correctness clarification:

- Final ABC CEC catches wrong commits, but it cannot catch false pruning because false pruning only misses possible reductions.
- Therefore the CEX audit is important evidence for pruning quality, not just for output equivalence.
- TFI-CEX pruning is lower risk because it only skips future TFI-constancy checks; it does not skip the output-redundancy tiers.
- For circuits with `SAT_Unresolved=0`, the current candidate set was fully classified under this algorithm, candidate ordering, proof tiers, budgets, and stuck-at replacement model. It does not mean globally optimal AIG optimization and it does not rule out non-constant rewrites or ABC-style equivalent-node merging.

CEX audit results:

- `results_optimized/cex_audit_c7552/sat_ablation_2026-05-18_01-53-05.csv`
  - `c7552`: `1693 -> 1679`, removed 14, `Verify=PASS`.
  - `CEX_Audit_Checked=5263`, `CEX_Audit_SAT=5263`, `CEX_Audit_False_Prunes=0`, `CEX_Audit_Timeouts=0`.
  - `SAT_Unresolved=712`, `SAT_Abort_Reason=TIME_BUDGET_CHECKPOINT`.
  - Interpretation: strong audit evidence for the pruning events completed in this run, but not exhaustive completion because unresolved candidates remain.
- `results_optimized/cex_audit_sqrt/sat_ablation_2026-05-18_01-55-23.csv`
  - EPFL `sqrt`: `24618 -> 24618`, removed 0, `Verify=PASS`.
  - `T_Total=4552.19s`, `T_SAT=3970.33s`.
  - `CEX_Audit_Checked=6955`, `CEX_Audit_SAT=6923`, `CEX_Audit_False_Prunes=0`, `CEX_Audit_Timeouts=32`.
  - `SAT_Unresolved=42308`.
  - Interpretation: no false prunes among completed audits, but full audit on large circuits is too expensive and can starve optimization.

Deep clean results:

- ISCAS deep CSV: `results_optimized/deep_clean_overnight_2026-05-18/sat_ablation_2026-05-18_03-22-57.csv`
  - `c432`: `125 -> 121`, removed 4, `Verify=PASS`, `SAT_Unresolved=0`.
  - `c7552`: `1693 -> 1679`, removed 14, `Verify=PASS`, `SAT_Unresolved=0`.
  - `c6288`: `1870 -> 1870`, removed 0, `Verify=PASS`, `SAT_Unresolved=0`.
  - Note: this CSV also contains an interrupted `sin` row from a killed run; plots filter to PASS rows.
- EPFL deep CSV: `results_optimized/deep_clean_overnight_epfl_remaining_run2_2026-05-18/sat_ablation_2026-05-18_03-29-06.csv`
  - `sin`: `5416 -> 5375`, removed 41, `Verify=PASS`, `TFI_Query_UNSAT=19`, `Window_Query_UNSAT=1`, `SAT_Unresolved=179`.
  - `sqrt`: `24618 -> 24562`, removed 56, `Verify=PASS`, `Window_Query_UNSAT=22`, `SAT_Unresolved=19747`.
  - `div`: `57247 -> 57014`, removed 233, `Verify=PASS`, `TFI_Query_UNSAT=8`, `Window_Query_UNSAT=74`, `SAT_Unresolved=21490`.
  - `log2`: `32060 -> 32037`, removed 23, `Verify=PASS`, `TFI_Query_UNSAT=13`, `SAT_Unresolved=19132`.
  - `mem_ctrl`: `46836 -> 46761`, removed 75, `Verify=PASS`, `TFI_Query_UNSAT=1`, `Window_Query_UNSAT=34`, `SAT_Unresolved=48193`.

Deep-run interpretation:

- Deep mode found more verified removals than fast/short runs, especially on EPFL circuits:
  - `sqrt`: 36 -> 56 removals.
  - `div`: 44 -> 233 removals.
  - `log2`: 8 -> 23 removals.
  - `mem_ctrl`: 2 -> 75 removals.
  - `sin`: 39 -> 41 removals.
- ISCAS `c432`, `c7552`, and `c6288` are fully resolved under this algorithm and stuck-at model (`SAT_Unresolved=0`).
- EPFL circuits remain time-budgeted and should not be called exhaustive.
- The useful tier differs by benchmark: TFI constancy is important for `sin`/`log2`; audited window proofs are important for `sqrt`/`div`/`mem_ctrl`.
- CEX pruning is now the largest practical accelerator, but the large audit run shows full audit should be used as validation evidence, not the default optimization mode.

Professor meeting pack:

- Directory: `thesis_plots/alg10_current/`
- Main notes: `thesis_plots/alg10_current/MEETING_NOTES.md`
- Charts:
  - `01_removed_fast_short_deep.png`: shows removal improvement from fast/short/deep runs.
  - `02_deep_tier_commits.png`: shows which SAT proof tier accepted removals.
  - `03_deep_unresolved.png`: shows coverage/unresolved candidates; use this to be honest about non-exhaustive EPFL runs.
  - `04_deep_cex_pruning.png`: shows how much candidate space CEX pruning removes.
  - `05_cex_audit_outcomes.png`: shows audit-confirmed prunes and zero false prunes in the completed audit checks.
- Summary CSVs:
  - `summary_removed_fast_short_deep.csv`
  - `summary_deep_tier_commits.csv`
  - `summary_deep_unresolved.csv`
  - `summary_deep_cex_pruning.csv`
  - `summary_cex_audit.csv`

Suggested meeting story:

- Start with: "Last time the pipeline was correct but still weak on scalability and proof discipline. Since then I added a tiered SAT structure with audited windows and CEX-guided pruning, then validated pruning with a recall audit."
- Then show `01_removed_fast_short_deep.png`: deep mode finds more verified reductions, especially on EPFL `div`, `sqrt`, and `mem_ctrl`.
- Then show `02_deep_tier_commits.png`: the contribution is not just more runtime; different proof tiers are useful on different families.
- Then show `03_deep_unresolved.png`: be clear that ISCAS examples are resolved under the current stuck-at model, while EPFL remains budget-limited.
- Then show `04_deep_cex_pruning.png`: explain why the approach became fast enough to run.
- Then show `05_cex_audit_outcomes.png`: explain why CEX pruning is not being trusted blindly.

Checkpoint/resume clarification:

- `sat_ablation_experiments.py` runs are clean ablation rows and currently reset the checkpoint for fairness.
- Algorithm 10 checkpoints save the last safe optimized circuit, not a precise "resume from candidate number 179" unresolved queue.
- A resumed optimization starts from the last safe optimized AAG and sweeps again on that circuit. It does not continue exactly from the previous unresolved candidate list.
- For thesis experiments, use clean runs for fair comparison. For engineering improvement, a future enhancement could store unresolved candidate IDs and continue from them directly.

Potential next steps:

- Before changing the algorithm further, discuss the current evidence with the professor.
- Strong next experiment after the meeting: add an ABC baseline table with `strash` and `fraig` for the same circuits, reporting AND count and runtime, while clearly explaining that ABC does different transformations.
- Strong SAT-side improvement idea: improve resume/checkpoint metadata so unresolved candidates can be carried forward exactly.
- Another SAT-side improvement idea: adaptive tier routing, for example sending high-fanout or window-friendly candidates to the window tier earlier.
- Future work only: FRAIG/MaxSAT/sequential optimization. These drift away from the current SAT-side thesis scope.

Git state:

- Local commit created: `6bebd97 Add Alg10 CEX audit and deep thesis results`.
- Commit includes Algorithm 10 code changes, `main.py`, tests, ablation runner, selected CSV result files, professor plots, summaries, prompts/history/session, and run log.
- Checks before commit:
  - `git diff --check`: pass.
  - Python compile check: pass.
  - `venv/bin/python test_alg10_checkpoint.py`: pass.
- Push status:
  - Local branch is ahead of `origin/main` by 1 commit.
  - `git push origin main` failed because the remote is HTTPS and this terminal could not prompt for GitHub credentials.
  - SSH also failed because no GitHub SSH key is configured for this machine.
  - To push later, run `git push origin main` from a terminal with GitHub credentials configured, or configure an SSH key/credential manager first.
- Untracked scratch files intentionally left out of the commit:
  - `binary_encoding_test.py`
  - `sandbox_in_memory.py`
  - `temp_mod.aag`
  - `test_binary.aig`
  - `test_encoding_surgery.py`
  - `test_python_strash_out.aag`
  - `test_surgery_out.aag`
  - `verify_final.py`

## 2026-05-28 Alg10 Strict-Audit SAT Engine Update

Context:

- Goal is still SAT-side stuck-at constant redundancy removal only.
- Acceptance boundary remains strict: a replacement is committed only after an UNSAT proof in TFI/window/cone/global tier, and final ABC CEC must pass.
- CEX pool, pre-SAT simulation, and CEX replay remain rejection-only. They never accept redundancy.
- We cannot tolerate false UNSAT acceptance, stale CNF context, free fault controls, or wrong assumption vectors.

Implemented and tested SAT-engine changes:

- Persistent full-good-circuit TFI constancy solver is now part of Alg10.
  - For SA0 on gate `g`, query `GoodCNF AND g=1`.
  - For SA1 on gate `g`, query `GoodCNF AND g=0`.
  - UNSAT proves functional constancy in the current phase.
  - Solver is phase-local and rebuilt after physical commit/rebuild.
- Hybrid grouped exact-cone configurable-fault miter is now part of Alg10.
  - Groups candidates with identical affected observable root sets.
  - Uses one configurable cone solver for large groups and falls back to single-candidate cone for small groups.
  - Production assumption audit is enabled by `ALG10_AUDIT_ASSUMPTIONS=1`.
- Grouped-cone assumption audit checks:
  - exact count `2 * len(controls) + 1`;
  - no duplicates or contradictory assumptions;
  - every inactive control disabled;
  - current candidate control activated exactly;
  - accepted controls activated exactly;
  - miter literal is final;
  - full ordered vector equals expected vector.
- Checkpoint loader was fixed after discovering a branch-selection bug.
  - Problem: strict-audit `div` had multiple checkpoints for the same source SHA; a newer weaker branch with 173 removed could be loaded instead of an older/better 227/233 branch.
  - Fix: `_load_checkpoint()` now scans same-basename checkpoints, accepts only exact matching `source_sha256`, validates the work AAG, then chooses best safe checkpoint by lowest current gate count and then lower unresolved.
  - Future CSVs include `Checkpoint_JSON_Loaded` and `Checkpoint_Work_Loaded`.
  - `main.py` also prints `Reset checkpoint: 0/1` in the config block.
- `alg10_report_plots.py` was added.
  - Alg10 CSVs now get companion chart folders automatically when the run completes.
  - Generated files include dashboard, reduction/unresolved chart, coverage/runtime chart, rejection-only pruning chart, checkpoint resume progress chart, `summary_by_circuit.csv`, `summary_key_metrics.csv`, and `top_unresolved.csv`.
- `prepare_benchmark_suites.py` was extended for IWLS2005 Verilog benchmark preparation.
  - User has extracted IWLS folders under `benchmark_suites/IWLS_benchmarks_2005_V_1.0/`.
  - Do not convert IWLS while a heavy Alg10 run is active.
  - Later command:
    `venv/bin/python prepare_benchmark_suites.py --iwls2005-dir benchmark_suites/IWLS_benchmarks_2005_V_1.0 --yosys-timeout 180`

Soundness/regression checks passed:

- `venv/bin/python test_alg10_grouped_cone_audit.py`
- `venv/bin/python test_encoding_soundness_bounded.py --max-inputs 2 --max-gates 2 --include-depth3 --progress-interval 0`
  - PASS on 536,376 candidate checks.
  - Covered global miter, old TFI, persistent TFI, single cone, grouped cone, audited window, and rewrite semantics against brute force.
- `venv/bin/python test_alg10_hybrid_safety.py`
- `venv/bin/python test_alg10_resume_pool.py`
  - Includes CEX pool replay, stale metadata fallback, phase-local resume, path-change content checkpoint resume, and new best-same-source checkpoint selection regression.
- `venv/bin/python test_alg10_checkpoint.py`
- `venv/bin/python test_algorithms_1_to_10.py`
- `venv/bin/python -m py_compile main.py optimizer_alg10_tiered.py alg10_report_plots.py test_alg10_resume_pool.py`
- `git diff --check`

Important result history:

- Strict audit fast seed:
  - CSV: `results_optimized/thesis_results_ALG10_alg10_strict_audit_fast_save_current_real_suites_planted_2026-05-28_00-27-00.csv`
  - CEC PASS 38/38.
  - Total removed 619.
  - Total unresolved 131,863.
- Strict audit deep run 1:
  - CSV: `results_optimized/thesis_results_ALG10_alg10_strict_audit_resume_pool_presim_deep_current_real_suites_planted_2026-05-28_00-42-35.csv`
  - CEC PASS 38/38.
  - Total removed 1,173.
  - New removed 554.
  - Total unresolved 293,918.
- Strict audit deep run 2:
  - CSV: `results_optimized/thesis_results_ALG10_alg10_strict_audit_resume_pool_presim_deep_current_real_suites_planted_2026-05-28_02-33-45.csv`
  - CEC PASS 38/38.
  - Total removed 1,722.
  - New removed 549.
  - Total unresolved 392,706.
  - This run exposed the confusing `div` checkpoint behavior.
- Bad/cancelled cold-ish run:
  - CSV: `results_optimized/thesis_results_ALG10_alg10_strict_audit_resume_pool_presim_deep_current_real_suites_planted_2026-05-28_04-05-36.csv`
  - `div` had `Checkpoint_Resume=0`, so it started cold and created a weaker 173-removed checkpoint.
  - Do not use this as final evidence.
- Latest good strict-audit full run:
  - CSV: `results_optimized/thesis_results_ALG10_alg10_strict_audit_resume_pool_presim_deep_current_real_suites_planted_2026-05-28_04-34-18.csv`
  - Charts: `results_optimized/thesis_results_ALG10_alg10_strict_audit_resume_pool_presim_deep_current_real_suites_planted_2026-05-28_04-34-18_charts/`
  - CEC PASS 38/38.
  - Total removed 2,130.
  - New removed 408.
  - Total unresolved 352,820.
  - SAT checks 26,923.
  - UNSAT accepts 119.
  - Timeouts 3,319.
  - All 38 rows resumed from checkpoint.

Latest important per-circuit rows from `04-34-18`:

- `div`: removed 233, new 6, unresolved 76,194, checkpoint `epfl_epfl_arithmetic_div_de1d46d85707.json`.
- `voter`: removed 1,342, new 402, unresolved 2,003, checkpoint `epfl_epfl_random_control_voter_786133f41231.json`.
- `sin`: removed 41, new 0, unresolved 93.
- `sqrt`: removed 50, new 0, unresolved 9,140.
- `log2`: removed 416, new 0, unresolved 13,460.
- `mem_ctrl`: removed 2, new 0, unresolved 66,264.
- `hyp`: removed 4, new 0, unresolved 173,217.
- `arbiter`: removed 0, unresolved 12,449.

Interpretation of latest unresolved counts:

- The total unresolved decreased from the previous full strict-audit branch: 392,706 -> 352,820.
- This is useful progress, but some per-circuit frontiers can increase after commits/rebuilds because the candidate frontier is regenerated on the new safe AAG.
- `div` now correctly starts from the 233 branch, not the bad 173 branch.
- `voter` is the strongest new success: 940 -> 1,342 removed.

Current overnight/cycling setup:

- Menu option 4 was changed to strict-audit cycling:
  - label: `alg10_strict_audit_zero_resume_pool_presim_current`
  - `ALG10_REPEAT_UNTIL_ZERO=1`
  - strict checkpoint directory: `results_optimized/alg10_checkpoints_strict_audit`
  - assumption audit enabled
  - CEX pool enabled
  - pre-SAT rejection enabled
  - phase-local resume enabled
  - budgets: `1000,5000,20000,100000,500000`
- Recommended overnight command:
  - `ALG10_TOTAL_SECONDS=43200 ALG10_RESET_CHECKPOINT=0 ALG10_CHECKPOINT_DIR=results_optimized/alg10_checkpoints_strict_audit python main.py`
  - choose `10`, then `4`, then dataset profile `3`, then plants `0`.
- Before walking away, config should show:
  - `Mode: alg10_strict_audit_zero_resume_pool_presim_current`
  - `Total campaign seconds: 43200`
  - `Repeat unresolved circuits: 1`
  - `Assumption audit: 1`
  - `Checkpoint dir: results_optimized/alg10_checkpoints_strict_audit`
  - `Reset checkpoint: 0`

What to inspect when the campaign finishes:

- Latest CSV total:
  - CEC PASS count must be all PASS rows.
  - `Total removed`.
  - `New_Removed_This_Run`.
  - `SAT_Unresolved`.
  - `SAT_Query_UNSAT`.
  - `SAT_Timeouts`.
- Per hard circuit:
  - `div`, `voter`, `sin`, `sqrt`, `log2`, `mem_ctrl`, `hyp`, `arbiter`.
  - Check `Checkpoint_JSON_Loaded` to confirm the intended checkpoint branch was used.
  - Check `Checkpoint_Unresolved_Delta`.
  - Positive delta means unresolved decreased from the loaded checkpoint.
  - Negative delta usually means new frontier was created after commits/rebuild.
- The generated chart folder beside the latest CSV should contain:
  - `01_alg10_dashboard.png`
  - `02_circuit_reduction_and_unresolved.png`
  - `03_coverage_and_runtime.png`
  - `04_rejection_only_pruning.png`
  - `05_checkpoint_resume_progress.png`
  - `README.md`

Current working tree notes:

- Modified tracked files include `main.py`, `optimizer_alg10_tiered.py`, `COMMANDS.md`, `SESSION.md`, `prepare_benchmark_suites.py`, and `sat_ablation_experiments.py`.
- Important untracked files include:
  - `alg10_report_plots.py`
  - `test_alg10_grouped_cone_audit.py`
  - `test_alg10_hybrid_safety.py`
  - `test_alg10_resume_pool.py`
  - `test_encoding_soundness_bounded.py`
  - `sat_cone_group_experiments.py`
  - `sat_tfi_solver_experiments.py`
  - `LLM_REVIEW_PROMPT_SAT_ENGINE_SOUNDNESS_AUDIT_2026-05-28.md`
  - `LLM_REVIEW_PROMPT_SAT_ENGINE_TFI_CONE_2026-05-27.md`
  - `thesis_plots/alg10_current/ENCODING_SOUNDNESS_ARGUMENT.md`
  - extracted IWLS raw tree under `benchmark_suites/IWLS_benchmarks_2005_V_1.0/`

## 2026-05-29 Late Session Update

We ran a focused strict-audit near-zero campaign after the May 28 full-suite materialization.

Focused target setup:

- Target folder used:
  - `custom_circuits/alg10_near_zero_only`
- Contents:
  - normalized `epfl_epfl_arithmetic_sin.aag`
  - normalized `epfl_epfl_random_control_voter.aag`
- Reason for normalized copies:
  - The checkpoint `source_sha256` is based on the pipeline-normalized `epfl_epfl_*` files, not the raw `benchmark_suites/epfl/*` files.
  - A checkpoint lookup patch now scans strict-audit checkpoints by matching `source_sha256`, so custom-target runs can reuse existing best checkpoints even when the filename prefix changes to `custom_`.

Focused campaign command that was run:

```bash
printf '10\n4\n5\ncustom_circuits/alg10_near_zero_only\n' | \
ALG10_BUDGETS=500000 \
ALG10_MAX_CIRCUIT_SECONDS=1800 \
ALG10_TOTAL_SECONDS=21600 \
ALG10_RESET_CHECKPOINT=0 \
ALG10_CHECKPOINT_DIR=results_optimized/alg10_checkpoints_strict_audit \
venv/bin/python main.py
```

Focused campaign result:

- CSV:
  - `results_optimized/thesis_results_ALG10_alg10_strict_audit_zero_resume_pool_presim_current_custom_only_2026-05-28_22-35-35.csv`
- Charts:
  - `results_optimized/thesis_results_ALG10_alg10_strict_audit_zero_resume_pool_presim_current_custom_only_2026-05-28_22-35-35_charts/`
- CEC:
  - PASS on all 6 campaign rows.
- Important interpretation:
  - The printed `SAT unresolved remaining: 166` is a sum across repeated campaign rows and is not the final frontier.
  - Grouped by latest row per circuit, the real final focused frontier is:
    - `sin`: removed 41, unresolved 26, coverage 99.76%, CEC PASS.
    - `voter`: removed 1434, unresolved 22, coverage 99.91%, CEC PASS.
  - Unique latest focused total:
    - removed 1475
    - unresolved 48
- Main gain:
  - `voter` improved from removed 1402 / unresolved 87 to removed 1434 / unresolved 22.
  - This is +32 strict-audit removals and -65 unresolved on `voter`.
- `sin` improved from unresolved 51 to 26, but removed stayed 41.
- Both `sin` and `voter` ended in `UNRESOLVED_TIMEOUTS` at the focused budget frontier.

After the focused campaign, we ran a clean full-suite materialization:

```bash
ALG10_RESET_CHECKPOINT=0 \
ALG10_CHECKPOINT_DIR=results_optimized/alg10_checkpoints_strict_audit \
venv/bin/python main.py
```

Menu choices:

- `10`
- `6`
- `3`
- plants `0`

Latest best full-suite result:

- CSV:
  - `results_optimized/thesis_results_ALG10_alg10_strict_audit_resume_pool_presim_deep_current_real_suites_planted_2026-05-29_01-02-16.csv`
- Charts:
  - `results_optimized/thesis_results_ALG10_alg10_strict_audit_resume_pool_presim_deep_current_real_suites_planted_2026-05-29_01-02-16_charts/`
- CEC:
  - 38/38 PASS.
- Total removed:
  - 2222 gates.
- Previous clean full-suite total removed:
  - 2190 gates.
- Improvement:
  - +32 gates, from the focused `voter` campaign.
- SAT unresolved:
  - 102521.
- Previous clean full-suite unresolved:
  - 102522.
- SAT checks:
  - 8367, down from 9054.
- SAT timeouts:
  - 1121, down from 1446.

Important latest full-suite per-circuit rows:

- `epfl_epfl_random_control_voter.aag`
  - removed 1434
  - unresolved 22
  - coverage 99.91%
  - abort `UNRESOLVED_TIMEOUTS`
  - global exhausted 22
  - CEC PASS
- `epfl_epfl_arithmetic_sin.aag`
  - removed 41
  - unresolved 26
  - coverage 99.76%
  - abort `UNRESOLVED_TIMEOUTS`
  - global exhausted 26
  - CEC PASS
- `epfl_epfl_arithmetic_div.aag`
  - removed 233
  - unresolved 1732
  - coverage 98.48%
  - CEC PASS
- `epfl_epfl_arithmetic_sqrt.aag`
  - removed 50
  - unresolved 9020
  - coverage 81.64%
  - CEC PASS
- `epfl_epfl_arithmetic_log2.aag`
  - removed 416
  - unresolved 13154
  - coverage 79.22%
  - CEC PASS
- `epfl_epfl_random_control_mem_ctrl.aag`
  - removed 2
  - unresolved 66177
  - coverage 29.35%
  - CEC PASS
- `epfl_epfl_random_control_arbiter.aag`
  - removed 0
  - unresolved 12209
  - coverage 48.44%
  - CEC PASS
- `epfl_epfl_arithmetic_hyp.aag`
  - removed 4
  - unresolved 181
  - coverage 99.96%
  - CEC PASS

Current interpretation:

- The latest full-suite result is the current best thesis-ready strict-audit report.
- The near-zero capstone circuits are now:
  - `voter`: 99.91% coverage, 22 unresolved.
  - `sin`: 99.76% coverage, 26 unresolved.
- Repeating the same deep mode is probably low value now because `sin` and `voter` hit `UNRESOLVED_TIMEOUTS` at the current frontier.
- More SAT budget alone is unlikely to help much unless we either:
  - raise budgets substantially for a final focused attempt, or
  - improve scheduling/frontier persistence.

Recommended next engineering discussion:

1. Add completion/exhaustion-aware skipping:
   - If a checkpoint has `unresolved=0`, skip SAT entirely and only materialize/verify.
   - If a checkpoint/candidate is already exhausted at the same budget policy, do not retry the same cone/window/global budget path.
2. Persist per-tier exhaustion, not only global budget history:
   - The remaining bottleneck after the focused run is not purely global SAT.
   - The focused run reported cone-tier as the main timeout bottleneck.
   - The clean full-suite still has many repeated frontier checks.
3. Consider a new SAT-only candidate ordering experiment:
   - PO-to-PI / reverse-topological.
   - Dominator-first where structurally meaningful.
   - Goal: expose more redundant dominators early and make downstream candidates easier by BCP.
4. For finding more redundancies after a circuit reaches `SAT_Unresolved=0`:
   - More SAT on the same candidate queue cannot find more in the same stuck-at constant model.
   - To expose new candidates, we need a new phase after commits/cleanup/strash, then regenerate candidates and run SAT again to a fixpoint.
   - This must stay strict: only UNSAT accepts, CEX rejection-only, final ABC CEC PASS.

Next session reminder:

- First, read this `SESSION.md`.
- Remind the user:
  - The latest best full-suite CSV is `results_optimized/thesis_results_ALG10_alg10_strict_audit_resume_pool_presim_deep_current_real_suites_planted_2026-05-29_01-02-16.csv`.
  - Current best total removed is 2222 gates with 38/38 CEC PASS.
  - `voter` is the best capstone: 1434 removed, 22 unresolved, 99.91% coverage.
  - `sin` is also near complete: 41 removed, 26 unresolved, 99.76% coverage.
  - The next sensible work is not another identical run, but efficiency/frontier improvements: completion/exhaustion-aware skip, per-tier budget persistence, and possibly candidate ordering.

## 2026-06-03 Pre-SAT Rejection Recheck

After a few-day pause, we rechecked the opt-in Algorithm 10 pre-SAT simulation
rejection path against the non-pre-sim CEX-window profile. The acceptance
boundary is unchanged: pre-SAT simulation is rejection-only and never commits a
replacement.

Regression checks:

- `venv/bin/python -m py_compile main.py optimizer_alg10_tiered.py sat_ablation_experiments.py probe_alg10_presat_sim.py`
- `venv/bin/python test_alg10_checkpoint.py`
- Capped audit smoke:
  `venv/bin/python sat_ablation_experiments.py --circuits benchmarks/c432.aag --variants presim_cex_window_audit_capped --seconds 5 --budgets 100,1000 --output-dir /tmp/alg10_presim_audit_recheck`
  - `c432`: 125 -> 121, removed 4, `Verify=PASS`
  - `CEX_Audit_Checked=708`
  - `CEX_Audit_False_Prunes=0`

Quick 20s comparison:

- CSV: `/tmp/alg10_presim_recheck_quick/sat_ablation_2026-06-03_20-02-34.csv`
- `c432`: same 4 removals and PASS; pre-sim reduced SAT checks 208 -> 11 and SAT time 0.064s -> 0.006s.
- `c7552`: same 14 removals and PASS; pre-sim reduced SAT checks 1709 -> 790 and SAT time 1.53s -> 0.96s.
- `sin`: same 39 removals and PASS; pre-sim reduced SAT checks 1246 -> 1014 and SAT time 10.88s -> 9.63s, but worsened `SAT_Unresolved` 8 -> 86 in this short budget.

Hard 30s deep-style comparison:

- CSV: `/tmp/alg10_presim_recheck_hard30/sat_ablation_2026-06-03_20-03-36.csv`
- `sqrt`: same 44 removals and PASS; pre-sim improved unresolved 20389 -> 13123 and coverage 58.52% -> 73.30%, but SAT time rose 3.32s -> 3.98s.
- `log2`: same 416 removals and PASS; pre-sim reduced SAT time 29.58s -> 16.81s, but unresolved rose slightly 136 -> 159.
- `div`: same 44 removals and PASS; pre-sim improved unresolved 86372 -> 5032, coverage 24.50% -> 95.60%, and SAT time 15.98s -> 13.68s.
- `mem_ctrl`: same 0 removals and PASS; pre-sim reduced SAT time 29.78s -> 20.07s, but unresolved rose 5639 -> 6517.

Decision:

- Keep pre-SAT rejection. It is sound as rejection-only, improves several
  important cases dramatically (`div`, `sqrt`) and reduces SAT time on many
  rows without reducing removals or breaking CEC.
- Do not claim it universally dominates. In short fixed budgets it can worsen
  unresolved on some circuits (`sin`, `log2`, `mem_ctrl`) because pre-sim uses
  wall-clock time that might otherwise classify late candidates through SAT/CEX.
- Current `main.py` structure is appropriate: pre-sim remains enabled in the
  enhanced/strict Alg10 modes (`3`, `4`, `6`), while the plain deep CEX-window
  mode (`2`) remains available as the non-pre-sim comparison.
- Next improvement should be adaptive pre-sim/tier scheduling rather than
  removing pre-sim: cap or skip pre-sim when prior CEX pruning is already near
  completion, and spend more pre-sim budget on circuits like `div` where it
  sharply reduces unresolved.

Reviewer prompt prepared after this decision:

- `LLM_REVIEW_PROMPT_STRICT_SAT_MORE_REDUNDANCIES_2026-06-03.md`
- Use Prompt A to ask for SAT-engine changes that prove more redundancies and
  more removals.
- Use Prompt B to ask a separate reviewer to attack soundness: fault masking,
  stale CNF, bad assumptions, incomplete observable roots, and checkpoint
  invalidation.
- Only implement a suggestion if it includes proof obligations, audit
  invariants, negative tests, bounded exhaustive tests, and an experiment
  matrix.

## 2026-06-03 Strict SAT Feedback Implementation Screen

After reviewing four external-feedback responses, the strongest actionable
feedback was not a new acceptance proof tier. It was stricter phase-local
frontier continuation and exhaustion-aware scheduling. The other recurring
idea, audited dominator/cut windows, was implemented only as an opt-in
experiment because it changes local SAT root selection and can easily become a
performance trap.

Implemented:

- Added `ALG10_EXACT_FRONTIER_RESUME=1`.
  - Only applies when a checkpoint contains a valid same-work-AAG global
    frontier.
  - Validation still requires checkpoint work SHA and gate count match.
  - When active, it skips already-completed lower tiers and resumes the global
    frontier directly.
  - It does not introduce any new acceptance rule.
  - Main Alg10 modes `3`, `4`, and `6` now enable it by default.
- Added exact-frontier telemetry:
  - `Exact_Frontier_Resume_Enabled`
  - `Exact_Frontier_Resume_Used`
  - `Exact_Frontier_Resume_Candidates`
  - `Exact_Frontier_Skipped_Lower_Tiers`
- Added `ALG10_WINDOW_ROOT_STRATEGY` with values:
  - `bounded`: existing default.
  - `dominator`: use only audited single-root TFO cuts.
  - `hybrid`: try an audited dominator root first; if inconclusive, fall back
    to the existing audited bounded window.
- Added dominator-window telemetry:
  - `Window_Root_Strategy`
  - `Window_Dominator_Attempts`
  - `Window_Dominator_Used`
  - `Window_Dominator_Fallbacks`

Important soundness boundary:

- Exact-frontier resume is scheduling only. It reuses no stale solver and no
  stale candidate metadata unless the work AAG hash and gate count match.
- Dominator windows remain UNSAT-only and runtime-audited. The complete-cut
  audit still gates every window acceptance.
- Hybrid dominator falls back to bounded windows when the dominator root is
  SAT, timeout, skipped, or audit-failed. This matters because a fault visible
  at a dominator root may still be masked downstream.

Focused checks passed:

- `venv/bin/python -m py_compile optimizer_alg10_tiered.py main.py sat_ablation_experiments.py test_alg10_checkpoint.py test_alg10_resume_pool.py test_encoding_soundness_bounded.py`
- `venv/bin/python test_alg10_checkpoint.py`
  - Added hybrid-dominator ODC smoke: removed 2, `Verify=PASS`,
    `Window_Dominator_Used > 0`, `Window_Audit_Fail=0`.
- `venv/bin/python test_alg10_resume_pool.py`
  - Added exact-frontier resume smoke: valid global frontier resumed,
    `Exact_Frontier_Resume_Used=1`, lower tiers skipped in the one-phase check,
    final CEC `PASS`.
- `venv/bin/python test_alg10_grouped_cone_audit.py`
- `venv/bin/python test_alg10_hybrid_safety.py`
- `venv/bin/python test_algorithms_1_to_10.py`
- `env ALG10_WINDOW_ROOT_STRATEGY=hybrid venv/bin/python test_encoding_soundness_bounded.py --max-inputs 2 --max-gates 2 --progress-interval 0`
  - PASS on 37,416 candidate checks.
- `env ALG10_WINDOW_ROOT_STRATEGY=hybrid venv/bin/python test_encoding_soundness_bounded.py --max-inputs 2 --max-gates 2 --include-depth3 --progress-interval 0`
  - PASS on 536,376 candidate checks.
- `git diff --check`

Ablation results:

- Revised hybrid dominator screen:
  - CSV: `/tmp/alg10_hybrid_dominator_window_screen2/sat_ablation_2026-06-03_20-51-28.csv`
  - `c432`: bounded and hybrid both removed 4, CEC PASS; bounded was faster.
  - `c7552`: bounded and hybrid both removed 14, CEC PASS; bounded was faster.
  - `sin`: both removed 39, CEC PASS; hybrid reduced SAT time but worsened
    unresolved in this short budget.
- Hard 30s deep-style screen:
  - CSV: `/tmp/alg10_hybrid_dominator_hard30/sat_ablation_2026-06-03_20-52-43.csv`
  - `sqrt`: both removed 44, CEC PASS; hybrid was slightly cheaper but had
    slightly worse unresolved.
  - `log2`: both removed 416, CEC PASS; hybrid was effectively neutral.
  - `div`: both removed 44, CEC PASS; hybrid was effectively neutral.
  - `mem_ctrl`: both removed 0, CEC PASS; hybrid was neutral.

Decision:

- Keep `ALG10_EXACT_FRONTIER_RESUME=1` in enhanced/strict modes. This is a
  conservative scheduling improvement and is directly aligned with the strongest
  feedback.
- Keep dominator/hybrid window code as an opt-in experimental strategy only.
  It passed soundness screens, but it did not find more removals in the short
  A/B matrices and can worsen unresolved/time. Do not promote it to default.
- Next high-value work should continue along feedback-2 lines:
  - exact per-tier frontier persistence with explicit escalated-vs-remaining
    candidate sets;
  - per-tier exhaustion history, not only global budget history;
  - adaptive scheduling that avoids repeated lower-tier work without relying on
    stale candidate IDs after rebuild.

2026-06-03 follow-up: implemented and tested the feedback-2 per-tier frontier
slice.

What changed:

- Added exact tier-frontier checkpoint schema `alg10_tier_frontier_v1` for
  `tfi`, `window`, and `cone`.
- A tier frontier stores explicit `pending` and `escalated` candidate lists.
  Validation still requires the checkpoint work AAG SHA and gate count to match.
- Exact resume can now restart from:
  - TFI pending, then continue window/cone/global from the merged escalated set.
  - Window pending, skipping TFI for that resumed phase.
  - Cone pending, skipping TFI and window for that resumed phase.
- Fixed telemetry so a fresh tier handoff into global is not counted as
  `Phase_Local_Resume_Used`; only a valid checkpoint frontier is counted.
- Added `Exact_Frontier_Resume_Tier` telemetry.

Focused resume comparison on `benchmarks/c432.aag`:

- TFI late frontier seed: exact resume used tier `tfi`, CEC PASS, 52 SAT checks
  vs 75 without exact tier resume in a one-phase comparison.
- Window frontier seed: exact resume used tier `window`, CEC PASS, 28 checks vs
  75 without exact tier resume; TFI checks were 0 in the resumed phase.
- Cone frontier seed: exact resume used tier `cone`, CEC PASS, 35 checks vs 75
  without exact tier resume; TFI/window checks were 0 in the resumed phase.

Checks passed after this slice:

- `venv/bin/python -m py_compile optimizer_alg10_tiered.py main.py sat_ablation_experiments.py test_alg10_resume_pool.py test_alg10_checkpoint.py test_encoding_soundness_bounded.py`
- `venv/bin/python test_alg10_resume_pool.py`
- `venv/bin/python test_alg10_checkpoint.py`
- `venv/bin/python test_alg10_hybrid_safety.py`
- `venv/bin/python test_alg10_grouped_cone_audit.py`
- `env ALG10_WINDOW_ROOT_STRATEGY=hybrid venv/bin/python test_encoding_soundness_bounded.py --max-inputs 2 --max-gates 2 --progress-interval 0`
  - PASS on 37,416 candidate checks.
- `env ALG10_WINDOW_ROOT_STRATEGY=hybrid venv/bin/python test_encoding_soundness_bounded.py --max-inputs 2 --max-gates 2 --include-depth3 --progress-interval 0`
  - PASS on 536,376 candidate checks.
- `venv/bin/python test_algorithms_1_to_10.py`
- `git diff --check`

Decision:

- Keep the per-tier exact frontier implementation. It is scheduling-only, does
  not add a new acceptance rule, and the strict checks found no encoding or CEC
  regression.
- Do not claim it improves fresh one-shot runs; it helps interrupted/resumed SAT
  campaigns by avoiding repeated already-completed lower-tier work.

## 2026-06-05 Scheduling Patch Screen From Prompt A/B Feedback

We tried the next low-risk scheduling ideas without changing the SAT acceptance
boundary. All attempted changes remain UNSAT-only for commits; CEX and pre-sim
remain rejection-only.

Added opt-in ablation knobs/variants:

- fair CEX-enabled ordering variants: `cex_window_reverse`,
  `cex_window_cone_size`;
- fair rebuild-cadence variants: `cex_window_rebuild25_current`,
  `cex_window_rebuild25_reverse`;
- adaptive pre-sim stop:
  - `ALG10_PRE_SIM_ADAPTIVE=1`;
  - `ALG10_PRE_SIM_ADAPTIVE_MIN_RANDOM_PRUNED`;
  - `ALG10_PRE_SIM_ADAPTIVE_MIN_RANDOM_FRACTION`;
  - `ALG10_PRE_SIM_ADAPTIVE_RANDOM_PATIENCE`;
- post-TFI pre-sim scheduling:
  - `ALG10_PRE_SIM_AFTER_TFI=1`, which runs TFI first and applies pre-sim only
    to TFI-escalated candidates.

Safety checks passed:

- `venv/bin/python -m py_compile optimizer_alg10_tiered.py main.py sat_ablation_experiments.py`
- `venv/bin/python test_alg10_checkpoint.py`
- `venv/bin/python test_alg10_resume_pool.py`
- `venv/bin/python test_alg10_hybrid_safety.py`
- `venv/bin/python test_alg10_grouped_cone_audit.py`
- `env ALG10_PRE_SIM_ADAPTIVE=1 ALG10_WINDOW_ROOT_STRATEGY=hybrid venv/bin/python test_encoding_soundness_bounded.py --max-inputs 2 --max-gates 2 --progress-interval 0`
  - PASS on 37,416 candidate checks.
- `env ALG10_PRE_SIM_REJECTION=1 ALG10_PRE_SIM_AFTER_TFI=1 ALG10_WINDOW_ROOT_STRATEGY=hybrid venv/bin/python test_encoding_soundness_bounded.py --max-inputs 2 --max-gates 2 --progress-interval 0`
  - PASS on 37,416 candidate checks.
- `venv/bin/python test_algorithms_1_to_10.py`
- `git diff --check`

Ablation files:

- Fair ordering screen:
  `/tmp/alg10_cex_order_screen/sat_ablation_2026-06-05_21-38-08.csv`
- Rebuild cadence screen:
  `/tmp/alg10_rebuild25_screen/sat_ablation_2026-06-05_21-43-28.csv`
- Adaptive pre-sim quick:
  `/tmp/alg10_adaptive_presim_quick/sat_ablation_2026-06-05_21-47-24.csv`
- Adaptive pre-sim hard:
  `/tmp/alg10_adaptive_presim_hard25/sat_ablation_2026-06-05_21-48-52.csv`
- Post-TFI pre-sim hard:
  `/tmp/alg10_post_tfi_presim_hard25/sat_ablation_2026-06-05_21-57-04.csv`

Results and decision:

- CEX-enabled reverse/cone ordering did not increase removals. Current ordering
  remains the best default.
- Rebuild-after-25 was neutral on c432/c7552/sin and did not justify changing
  the default `REBUILD_AFTER_COMMITS=100`.
- Adaptive pre-sim was mixed:
  - helped runtime on some rows;
  - did not rescue `log2`;
  - missed a `sqrt` removal that fixed pre-sim found in one hard 25s run.
- Post-TFI pre-sim preserved `log2`'s 416 removals, while fixed pre-sim dropped
  to about 263 in the hard 25s run. But post-TFI lost the fixed pre-sim runtime
  and unresolved-count benefit on `div`/`mem_ctrl`.

Do not promote adaptive pre-sim or post-TFI pre-sim to the main strict/default
Alg10 modes yet. Keep them as opt-in experiment knobs. The data suggests
circuit-specific profiles:

- `div`, `sqrt`, and sometimes `mem_ctrl`: pre-sim before TFI can reduce
  unresolved/runtime and sometimes expose a small number of extra removals.
- `log2`: avoid pre-sim before TFI; use no pre-sim or post-TFI pre-sim so the
  TFI proof tier gets the wall-clock budget.

## 2026-06-13 Intra-Circuit Parallel SAT Frontier Probe

Goal: test the idea of using multiple cores inside one circuit, without
changing the production optimizer or writing live checkpoints while the
`finishline_parallel_safe_20260613_132711` campaign was running.

Implementation:

- Added `alg10_frontier_shard_probe.py`.
- The probe reuses Alg10's existing global SAT encoding and assumption audit.
- It freezes a work AAG/frontier, shards candidate SAT checks across worker
  processes, and compares against a serial run.
- Workers are read-only: no AAG rewrite, no checkpoint save, no CEX save, and
  no direct gate commit.
- UNSAT results are labeled `UNSAT_PROPOSED_ACCEPT` only. The transactional
  coordinator added on 2026-06-14 rechecks and commits these sequentially
  through the strict audit/CEC path.
- Added explicit `--checkpoint-json` mode because historical `sin` checkpoints
  were made from normalized dataset copies whose `source_sha256` differs from
  the raw benchmark file. Automatic checkpoint loading remains source-hash
  strict.

Safety checks passed:

- `venv/bin/python -m py_compile alg10_frontier_shard_probe.py test_alg10_frontier_shard_probe.py`
- `venv/bin/python test_alg10_frontier_shard_probe.py`
- `git diff --check`

## 2026-06-14 Transactional Parallel Commit Coordinator

Implemented `alg10_parallel_commit_coordinator.py`.

Architecture:

- Worker solvers receive one immutable AAG generation and enqueue
  `SAT_REJECT`, `TIMEOUT`, or `UNSAT_PROPOSED_ACCEPT` classifications.
- Workers never write the AAG or checkpoint.
- The coordinator validates the generation SHA-256 before consuming results.
- At the generation barrier, it serially rechecks queued UNSAT proposals in one
  cumulative global-miter solver context.
- Compatible UNSAT proofs are applied together, forward-strashed, and accepted
  only after direct ABC CEC returns `PASS`.
- A failed CEC removes the candidate AAG and leaves the active generation
  byte-for-byte unchanged.
- After a commit, the old frontier is discarded because gate indices may have
  changed; the next generation builds a fresh frontier.
- Without a commit, SAT rejects are removed from the current frontier, timeout
  budget history is persisted, and restart resumes at the next candidates.
- Checkpoints and per-generation JSONL records are written after every wave.

Important boundary:

- Parallelism accelerates classification only.
- The single coordinator is the sole writer and sole commit authority.
- The wall-clock limit is checked between generations; an active SAT wave is
  allowed to return cleanly before exit.

Validation:

- Tiny ODC circuit: worker produced UNSAT proposals, coordinator rechecked and
  committed a reduction, and direct ABC CEC returned `PASS`.
- Forced CEC failure: transaction rolled back and the active work-AAG hash was
  unchanged.
- `c432` two-generation smoke: generation 2 processed different candidates,
  proving the in-memory frontier advances.
- `c432` restart smoke: resumed from the persisted frontier rather than
  repeating earlier batches; final ABC CEC returned `PASS`.
- Latch next-state functions were added to the shard probe's observable roots
  so worker semantics match Algorithm 10's combinational cut-boundary policy.

Checks passed:

- `venv/bin/python -m py_compile alg10_parallel_commit_coordinator.py test_alg10_parallel_commit_coordinator.py alg10_frontier_shard_probe.py`
- `venv/bin/python test_alg10_parallel_commit_coordinator.py`
- `venv/bin/python test_alg10_frontier_shard_probe.py`
- `git diff --check`

### Active 30-Minute Go/No-Go Pilot

Started at `2026-06-14 00:50:52 CEST` as user service:

```text
alg10-parcommit-sin-30m-20260614-0050.service
```

Configuration:

- target: `epfl_arithmetic_sin`, corrected frontier `9`, removed `41`;
- three worker processes plus the coordinator;
- one generation, three candidates;
- fresh conflict budget `2,500,000` for candidates previously tried through
  `2,000,000`;
- direct ABC CEC required before any commit;
- nominal generation deadline `1800s`;
- script: `run_alg10_parallel_commit_sin_30m.sh`;
- log: `alg10_parallel_commit_sin_30m_20260614_0050.log`;
- output/report: `results_optimized/parallel_commit_sin_30m_20260614_0050/`;
- checkpoint dir:
  `results_optimized/alg10_checkpoints_parallel_commit_sin_30m_20260614_0050/`.

Go/no-go rule:

- Strong go: at least one coordinator-confirmed UNSAT acceptance and CEC
  `PASS`.
- Conditional go: useful classifications are persisted, runtime is practical,
  and no stale/repeated work occurs, but no acceptance is found.
- No-go for a 12-hour run on this frontier: all candidates time out or are SAT
  rejects with no accepted reduction.

Sin pilot result:

- finished in `558.06s`;
- all three fresh `2,500,000`-conflict checks timed out;
- no UNSAT proposal and no new commit;
- final direct ABC CEC `PASS`;
- the nine-candidate frontier and upgraded budget history were persisted;
- decision: do not spend 12 hours on the exhausted `sin` frontier.

Next pilot:

- target: `epfl_arithmetic_sqrt`, unresolved `368`, removed `54`;
- script: `run_alg10_parallel_commit_sqrt_30m.sh`;
- three workers, 12 candidates, fresh `500,000`-conflict budget;
- most candidates were previously tried only through `100,000`, with eight
  candidates only through `20,000`;
- one generation with a nominal 30-minute deadline.

Started at `2026-06-14 01:28:59 CEST` as:

```text
alg10-parcommit-sqrt-30m-20260614-0129.service
```

Sqrt pilot result:

- finished in `686.05s`;
- all 12 fresh `500,000`-conflict checks timed out;
- no SAT reject, UNSAT proposal, coordinator acceptance, commit, or new
  reduction;
- final direct ABC CEC `PASS`;
- checkpoint persisted under
  `results_optimized/alg10_checkpoints_parallel_commit_sqrt_30m_20260614_0129/`;
- decision: do not spend 12 hours on the current global-miter `sqrt` frontier.

Automatic overnight handoff:

- wrapper: `run_alg10_sqrt_pilot_then_12h.sh`;
- overnight runner: `run_alg10_parallel_commit_sqrt_12h.sh`;
- waits for the pilot service to stop;
- requires final CEC `PASS`, zero failed CEC commits, and at least one SAT
  reject or coordinator-confirmed UNSAT acceptance;
- all-timeout pilot is a no-go and does not start the 12-hour run;
- overnight configuration uses three workers, budgets
  `1,000,000,2,000,000,5,000,000`, batch size `12`, and `43200s`.

The handoff correctly returned `NO-GO`; no overnight service was launched.
No Algorithm 10, CaDiCaL, or `main.py` experiment process remained running at
the final check. The next experiment should change the SAT decomposition or
candidate strategy before increasing the runtime budget.

Probe results:

- `c432`, fresh, 24 candidates, `glucose4`, budget 1000:
  - serial 0.016s, parallel 0.028s, exact match, 0.58x speedup.
  - Decision: not useful for easy SAT rejects; overhead dominates.
- `c432`, fresh, 24 candidates, `cadical153`, model phase, budget 1000:
  - serial 0.019s, parallel 0.026s, exact match, 0.71x speedup.
  - Decision: model phase path is tested, but easy candidates are still too
    cheap for sharding.
- `sin`, explicit high-budget preflight checkpoint
  `custom_epfl_arithmetic_sin_b17da687e8a4.json`, dry-run:
  - loaded valid global checkpoint frontier, 13 candidates available.
- `sin`, same checkpoint, 4 candidates, `glucose4`, budget 1000:
  - serial 0.647s, parallel 0.416s, exact match, 1.56x speedup.
- `sin`, same checkpoint, 8 candidates, `glucose4`, budget 1000:
  - serial 1.383s, parallel 0.694s, exact match, 1.99x speedup.
- `sin`, same checkpoint, 8 candidates, `cadical153`, budget 1000:
  - serial 1.047s, parallel 0.964s, exact match, 1.09x speedup.
- `sin`, same checkpoint, 8 candidates, `cadical153`, budget 10000, 2 jobs:
  - serial 11.648s, parallel 6.554s, exact match, 1.78x speedup.
- `sin`, same checkpoint, 8 candidates, `cadical153`, budget 10000, 4 jobs:
  - serial 10.796s, parallel 4.007s, exact match, 2.69x speedup.

Decision:

- Intra-circuit parallelism is worth pursuing for hard frontier SAT candidates,
  especially at nontrivial budgets.
- It should not replace the current long run today. The current safe campaign
  is already running and producing CEC PASS cycles.
- The safe next implementation is a coordinator, not direct parallel commits:
  freeze frontier, shard SAT classification, merge SAT rejects/timeouts/proposed
  UNSATs, then sequentially recheck and commit proposed UNSATs through the
  existing strict audit/CEC pipeline.

## 2026-06-13 Ranked Intra-Circuit Frontier Campaign Runner

Implemented `alg10_ranked_frontier_campaign.py` as the safe 6-hour runner for
the intra-circuit parallel idea.

Behavior:

- Scans valid Alg10 checkpoint JSON files.
- Validates that checkpoint `phase_resume.work_sha256`, `phase_resume.gate_count`,
  checkpoint `current_gates`, and the work-AAG header agree.
- Deduplicates by normalized circuit name.
- Sorts targets by lowest true unresolved count, then highest removed-gate
  count.
- Runs one circuit at a time, sharding frontier SAT checks across worker
  processes.
- Writes JSONL and summary files under `results_optimized/`.
- Remains read-only: no AAG rewrite, no checkpoint save, no CEX save, and no
  direct commit.

Real dry-run ranking after the finishline campaign had progressed:

1. `epfl_arithmetic_sin`: unresolved 9, removed 41.
2. `epfl_arithmetic_sqrt`: unresolved 368, removed 54.
3. `epfl_arithmetic_hyp`: unresolved 939, removed 4.
4. `epfl_arithmetic_div`: unresolved 955, removed 233.
5. `epfl_arithmetic_log2`: unresolved 10764, removed 416.
6. `epfl_random_control_mem_ctrl`: unresolved 52546, removed 2, valid TFI
   frontier.

Final probe before implementation:

- `sin`, high-budget preflight checkpoint, 13 candidates, `cadical153`, budget
  10000, 4 jobs:
  - serial 16.310s;
  - parallel 5.090s;
  - exact match;
  - 3.20x speedup.

Checks passed:

- `venv/bin/python -m py_compile alg10_ranked_frontier_campaign.py test_alg10_ranked_frontier_campaign.py alg10_frontier_shard_probe.py test_alg10_frontier_shard_probe.py`
- `venv/bin/python test_alg10_ranked_frontier_campaign.py`
- `venv/bin/python test_alg10_frontier_shard_probe.py`
- Ranked campaign smoke:
  - `sin`, 9 candidates, budget 1000, 2 jobs, exact read-only JSONL/summary
    output generated.
- `git diff --check`
