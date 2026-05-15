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

## Files To Watch

- `main.py`: experiment orchestration, dataset generation, optimizer selection, report writing.
- `abc_utils.py`: required ABC/AIGER bridge for conversion, CEC, and strash.
- `generators.py`: synthetic AAG benchmark generation.
- `verifier.py`: ABC CEC first through `abc_utils`, Python SAT miter fallback.
- `optimizer_alg*.py`: optimizer engines called by `main.py`.
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
