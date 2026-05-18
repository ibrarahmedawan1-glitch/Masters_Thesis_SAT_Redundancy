# Thesis Experiment History And Decisions

This file records the development path of the SAT-based AIG redundancy-removal tool: what was implemented, how it was tested, what worked, what failed, and why certain ideas were deferred. It is intended as thesis-writing material, not just developer notes.

## Correctness Boundary

The tool targets combinational AIG/AAG circuits. Latches are treated as boundary cuts when present; the project does not claim sequential redundancy removal or unreachable-state optimization.

A reported optimization is useful only when final verification returns:

```text
Verify = PASS
```

The final verifier uses ABC CEC through `abc_utils.py`. Because the local ABC build rejects ASCII `.aag` through direct `read_aiger`, the wrapper converts `.aag` to binary `.aig` with bundled `aiger/aigtoaig`, runs ABC CEC on binary AIGs, and reports PASS/FAIL.

## Algorithm Evolution

| Stage | Implementation | Purpose | Status |
| --- | --- | --- | --- |
| Algorithm 1 | `optimizer_alg1.py` | Naive SAT miter baseline | Kept as baseline; slow |
| Algorithm 2 | `optimizer_alg2.py` | Structural universal-machine approach | Kept for comparison |
| Algorithm 3 | `optimizer_alg3.py` | Base incremental ATPG | Kept for comparison |
| Algorithm 3 variants | `optimizer_alg3_saf.py`, `optimizer_alg3_sim.py`, `optimizer_alg3_timeout_cadical.py` | SAF batch, simulation filter, timeout/budget variants | Kept; safety fallback added where needed |
| Algorithm 7 | `optimizer_alg7_iterative.py` | Simulation filter plus iterative surgery | Fixed stuck-at-0 path and menu mapping |
| Algorithm 8 | `optimizer_alg8_hybrid.py` | Pure Python hybrid optimizer with ABC CEC verification | Rebuilt and verified |
| Algorithm 9 | `optimizer_alg9_incremental.py` | Committed in-memory incremental SAT optimizer | Main mature thesis engine |
| Algorithm 10 | `optimizer_alg10_tiered.py` | Checkpointed budget-cycling SAT engine with proof tiers | Current experimental SAT research shell |

## Important Fixes And Why They Matter

| Fix | Why It Was Needed | Result |
| --- | --- | --- |
| ABC wrapper in `abc_utils.py` | Direct ABC `read_aiger file.aag` failed locally | Verification became reliable through `.aag -> .aig -> ABC CEC` |
| Final CEC-first verifier path | Prevented trusting only the Python SAT encoder | Thesis claims can use `Verify = PASS` |
| Algorithm 7 menu/fault-path fixes | Menu pointed incorrectly and SA0 code path was unreachable | Algorithm 7 smoke tests passed |
| Algorithm 8 mutex clauses | Prevented simultaneous SA0/SA1 activation | Safer fault-control SAT encoding |
| Algorithm 9 committed SAT state | Needed to test later candidates in the context of accepted replacements | Correctly handles greedy masking context |
| Algorithm 9 abort reporting | Large circuits could otherwise look like silent failure | Reports `SAT_TIME_BUDGET`, `CONSECUTIVE_TIMEOUTS`, etc. |
| Structural-vs-SAT accounting | Needed to separate cheap cleanup from SAT-proven removals | CSV records both categories |
| Planted-live suite | Needed known SAT-redundant motifs for recall/sanity evidence | Fast vs exhaustive comparison became possible |
| Algorithm 10 checkpointing | Long circuits need safe partial outputs and resumability | Time-budgeted outputs still verified by CEC |
| Algorithm 10 TFI tier | Cheap proof for functional constants | Useful on EPFL `sin` |
| Algorithm 10 exact cone tier | Sound middle tier before full global SAT | Found cone UNSAT reductions on `c432` |
| Algorithm 10 bounded window tier | Test over-observable UNSAT-only proof before exact cone/global | Improved `c7552` efficiency in ablations |
| Window cut audit | External feedback warned that bounded windows are sound only when the boundary roots form a complete observable cut | Added `ALG10_WINDOW_AUDIT`; audit failures skip/escalate instead of committing |

## Key Verified Runs

| Run | Command/Context | Result | Decision |
| --- | --- | --- | --- |
| Algorithms 1-9 on `c17` | Custom smoke script | All ABC CEC `PASS` | Baselines considered functional |
| Algorithms 8-9 on `c432` | Focused smoke | Both ABC CEC `PASS`; Algorithm 9 removed 4 gates | Algorithm 9 became main SAT engine |
| Algorithm 9 full mixed run | `results_optimized/thesis_results_ALG9_2026-05-08_20-54-10.csv` | 235/235 `PASS`; 111.27s optimizer time; category reductions recorded | Useful broad thesis evidence |
| Algorithm 9 planted-live fast | `results_optimized/thesis_results_ALG9_2026-05-08_21-29-13.csv` | 5/5 `PASS`; 40 SAT-induced AND2 removals; 0.97s optimizer time | Fast filtering found planted faults |
| Algorithm 9 planted-live exhaustive | `results_optimized/thesis_results_ALG9_2026-05-08_21-29-45.csv` | Same 40 removals; 20.68s optimizer time | Evidence that exhaustive is much more expensive |
| Algorithm 10 checkpoint smoke | `venv/bin/python test_alg10_checkpoint.py` | ODC, TFI-constant, c432 checkpoint/resume all `PASS` | Checkpoint/resume safe |
| Algorithm 10 full mixed fast survey | `results_optimized/thesis_results_ALG10_alg10_fast_save_full_mixed_2026-05-15_19-06-11.csv` | 240/240 `PASS`; 165,902 AND2 nodes saved; 14 checkpoint rows | Checkpoint shell works |
| Algorithm 10 deep real-suites resume | `results_optimized/thesis_results_ALG10_alg10_deep_resume_real_suites_planted_2026-05-15_19-32-25.csv` | 38/38 `PASS`; no new hard EPFL arithmetic reductions | Blind longer global SAT not enough |
| Algorithm 10 cone tier smoke | `test_alg10_checkpoint.py` | ODC accepted by cone, CEC `PASS` | Exact cone tier kept |
| Algorithm 10 window tier smoke | `test_alg10_checkpoint.py` | ODC accepted by window-only, CEC `PASS` | Window tier kept as optional |

## SAT Encoding Notes

### Global Configurable-Fault Miter

Algorithm 9 and Algorithm 10 global SAT use:

- good circuit copy;
- faulty configurable circuit copy;
- shared primary input/latch-current variables;
- output/latch-next XOR miter;
- `f0_i` and `f1_i` controls for every AND gate;
- mutex `not f0_i OR not f1_i`;
- faulty gate behavior: `(normal AND not f0_i) OR f1_i`.

For each candidate:

- all inactive controls are disabled;
- accepted controls remain active;
- candidate control is active;
- opposite candidate control is disabled;
- miter is asserted.

The assumption audit added in Algorithm 10 checks that global calls receive exactly `2A + 1` assumptions and no contradictory assumption literals.

### TFI Constancy Tier

This tier encodes one complete transitive fanin cone and asks if the opposite target value is reachable. UNSAT means the target gate is constant in the current working circuit and the stuck-at replacement is safe.

This is a sufficient condition only; SAT does not prove the candidate is nonredundant.

### Exact Affected-Output Cone Tier

This tier finds real observable roots in the candidate fanout, encodes complete fanin cones for those roots, and compares good vs faulty copies. It is sound only because the fanin cones are complete down to the input/latch boundary.

### Bounded TFO Window Tier

This tier follows fanout only for a bounded number of levels and treats the boundary as observable. This over-approximates observability. Therefore:

- window UNSAT is safe for acceptance;
- window SAT is inconclusive and must escalate;
- timeout or skip must escalate.

After external review, the implementation was hardened with a cut audit. The boundary roots must disconnect the candidate gate from every reachable real output/latch-next root in the fanout graph. If not, the tier returns skip and escalates. The `WINDOW_MAX_CONE_GATES` cap is also whole-window only: if the complete fanin cone of all boundary roots is too large, the tier skips the entire window rather than encoding a partial root set.

Local/window SAT counterexamples are not redundancy proofs. They may only seed pruning when converted into a concrete PI/latch assignment and the full circuit is directly simulated for the candidate being rejected. A candidate is pruned only if that exact candidate's stuck-at faulty circuit differs from the good circuit at a real output/latch-next root under the concrete assignment.

This tier is optional because it helps some circuits and not others.

### CEX-Guided Pruning

Algorithm 10 now supports `ALG10_CEX_PRUNING=1`.

There are two conservative uses:

- TFI-CEX pruning: a SAT model from a TFI constancy query gives a concrete assignment where some gates are not equal to their hypothesized stuck value. Those candidates can skip the TFI tier only; they are not globally rejected.
- Output-CEX pruning: a SAT model from window, exact cone, or global miter gives a concrete PI/latch assignment. The tool then bit-parallel simulates the full circuit for each pending candidate. Only candidates whose own stuck-at fault produces a real observable mismatch are skipped in the current phase.

No candidate is accepted by CEX pruning. It is rejection/skip only, and every emitted optimized circuit is still checked by ABC CEC.

## Ablation Experiments

Script:

```bash
python3 sat_ablation_experiments.py
```

The script runs Algorithm 10 variants with isolated checkpoints and final ABC CEC per row.

### Variants Tested

| Variant | Meaning |
| --- | --- |
| `current` | Current ordering, TFI + exact cone + global |
| `reverse` | Reverse topological ordering |
| `cone_size` | Small affected-cone candidates first |
| `window_current` | Current ordering plus bounded window tier |
| `window_reverse` | Reverse ordering plus bounded window tier |
| `rebuild25_current` | Current ordering, rebuild after 25 commits |
| `rebuild25_reverse` | Reverse ordering, rebuild after 25 commits |
| `no_commit_units_reverse` | Reverse ordering without permanent commit unit clauses |
| `global_only_current` | Global configurable-fault miter only, current ordering |
| `global_only_audit` | Global-only with reverse ordering and assumption audit |
| `cex_current` | Current tiered profile plus CEX pruning |
| `cex_window_current` | Window-current profile plus CEX pruning |
| `global_only_cex_current` | Global-only current ordering plus CEX pruning |

### Result Files

| CSV | Scope |
| --- | --- |
| `results_optimized/sat_ablation_2026-05-17_18-21-22/sat_ablation_2026-05-17_18-21-22.csv` | `c432`, `c7552`, 15s matrix |
| `results_optimized/sat_ablation_2026-05-17_18-23-29/sat_ablation_2026-05-17_18-23-29.csv` | EPFL `router`, EPFL `sin`, 20s matrix |
| `results_optimized/sat_ablation_2026-05-17_18-25-23/sat_ablation_2026-05-17_18-25-23.csv` | `c7552`, EPFL `sin`, 30s matrix |
| `results_optimized/sat_ablation_2026-05-17_18-31-37/sat_ablation_2026-05-17_18-31-37.csv` | `c6288`, EPFL `arbiter`, EPFL `sqrt`, 20s hard pass |
| `results_optimized/sat_ablation_2026-05-17_19-18-58/sat_ablation_2026-05-17_19-18-58.csv` | `c7552`, CEX pruning comparison |
| `results_optimized/sat_ablation_2026-05-17_19-22-44/sat_ablation_2026-05-17_19-22-44.csv` | EPFL `sin`, TFI-CEX pruning comparison |
| `results_optimized/sat_ablation_2026-05-17_19-24-37/sat_ablation_2026-05-17_19-24-37.csv` | `c6288`, hard-circuit CEX pruning comparison |
| `results_optimized/sat_ablation_2026-05-17_19-28-09/sat_ablation_2026-05-17_19-28-09.csv` | EPFL `router`, `arbiter`, `sqrt`, CEX-enabled broader pass |

### Main Observations

| Circuit | Observation | Decision |
| --- | --- | --- |
| `c432` | Global-only fastest; all major variants remove 4 gates | Do not overfit to this tiny circuit |
| `c7552`, 15s | current removed 4; reverse removed 6; `window_reverse` removed 14; global-only removed 14 | Window tier promising |
| `c7552`, 30s | current removed 6; `window_current/window_reverse/global-only` removed 14 | Window reaches global-only reduction with less SAT time |
| EPFL `router` | all found 6; global-only fastest | Small control circuit does not justify global default |
| EPFL `sin` | current/window-current/rebuild-current removed 31; reverse fewer; global-only 0 | Do not promote reverse/global-only globally |
| `c6288` | 0 removals in 20s | Needs better pruning or longer targeted run |
| EPFL `arbiter` | 0 removals in 20s | Poor short ablation target |
| EPFL `sqrt` | 0 removals in 20s | Hard arithmetic still not solved by current tiers |

### CEX Pruning Results

All rows below had final ABC CEC `PASS`.

| Circuit and budget | Baseline | CEX result | Interpretation |
| --- | --- | --- | --- |
| `c7552`, 15s, global-only current | 14 removed, SAT 14.98s, timeout checkpoint | 14 removed, SAT 3.12s, complete, 6477 output-CEX prunes | Same reduction with much less SAT time |
| `c7552`, 15s, current tiered | 4 removed, SAT 10.89s, timeout checkpoint | 14 removed, SAT 8.60s, complete, 19238 output-CEX prunes | CEX lets tiered profile reach the useful global/cone work |
| `c7552`, 15s, window-current | 14 removed, SAT 10.15s, timeout checkpoint | 14 removed, SAT 4.34s, complete, 11975 output-CEX prunes | Window plus CEX is faster than window alone |
| EPFL `sin`, 20s, current | 31 removed, SAT 19.98s, 15 TFI UNSAT | 39 removed, SAT 16.89s, 19 TFI UNSAT, 21232 TFI-CEX prunes | TFI-CEX pruning reaches more productive candidates |
| EPFL `sin`, 20s, window-current | 31 removed, SAT 19.98s | 39 removed, SAT 11.16s, 21232 TFI-CEX prunes, 9863 output-CEX prunes | Best tested `sin` profile so far |
| `c6288`, 20s, current | 0 removed, SAT 16.28s, timeout checkpoint | 0 removed, SAT 2.46s, complete, 7413 output-CEX prunes and 3521 TFI-CEX prunes | Pruning proves fast rejection; it does not invent redundancies |
| `c6288`, 20s, global-only CEX | baseline global-only timed out at about 20s | 0 removed, SAT 1.69s, complete, 3712 output-CEX prunes | Strong diagnostic for hard multipliers |
| EPFL `router`, 20s | previous profiles all removed 6 | CEX profiles also remove 6; global-only CEX SAT 0.05s | Small circuit still favors global-only CEX |
| EPFL `arbiter`, 20s | previous profiles removed 0 | CEX profiles removed 0, but TFI-CEX pruned 23568 candidates | Still no redundancy, but pruning avoids much SAT work |
| EPFL `sqrt`, 20s | previous current/window/global-only removed 0 | `cex_window_current` removed 36, SAT 3.16s, `Window_Query_UNSAT=13`, CEC `PASS` | Window plus CEX finds new hard arithmetic reductions |

### External Feedback Follow-Up On Window Soundness

Reviewers correctly identified the bounded window tier as a place where sloppy wording could become a correctness bug. The project response was to add an explicit complete-cut audit.

| Check | Result |
| --- | --- |
| Window roots must cut all paths from candidate to real observable roots | Implemented by `ALG10_WINDOW_AUDIT=1` |
| Partial window due to cone-size cap | Not allowed; the whole window skips/escalates |
| Local/window SAT CEX reuse | Not allowed for global pruning |
| Window-only ODC smoke | CEC `PASS`, `Window_Query_UNSAT=1`, `Window_Audit_Fail=0` |
| `c7552` 15s after audit | `window_current`: 14 removed, CEC `PASS`, `Window_Audit_Fail=0`, SAT 10.93s |

This means the window tier remains a thesis-valid optional proof tier only under the complete-cut condition. It should not be described as a heuristic acceptance rule.

## Ideas Considered But Not Promoted Yet

| Idea | Reason Not Promoted Yet |
| --- | --- |
| Reverse topological ordering as default | Helped `c7552`, hurt EPFL `sin` |
| Global-only SAT as default | Fast on `c432/router`, removed 0 on EPFL `sin` under 20-30s |
| Bounded TFO window as default | Promising on `c7552`, but needs broader validation; currently optional |
| CEX pruning as default | Promising enough to test broadly, but newly added; keep behind `ALG10_CEX_PRUNING=1` until more circuits are covered |
| Blind longer global SAT on EPFL arithmetic | Previous deep runs found no new hard arithmetic reductions; inefficient |
| MaxSAT/MUS/MCS reformulation | Potentially thesis-interesting but high complexity; should remain future work unless small prototype wins |
| FRAIG/node merging | Could find more than stuck-at constants, but it is a separate major algorithm; not safe to pivot without time |
| Unsound truncated TFO acceptance | Rejected. Only over-observable UNSAT is allowed; SAT escalates |
| Simulation as redundancy proof | Rejected. Simulation is filtering/rejection aid only |
| Sequential redundancy claims | Rejected. Tool is combinational-boundary only |

## External Review Conclusions After CEX-Window Prompt

External feedback on the latest Algorithm 10 profile converged on the same thesis boundary:

- The core contribution should remain a combinational, proof-gated SAT pipeline for stuck-at constant redundancy removal.
- Deep mode should be evaluated with clean isolated checkpoints for thesis tables (`ALG10_RESET_CHECKPOINT=1`), even though checkpoint resume is useful operationally.
- CEX pruning must remain rejection-only. A bad CEX prune would normally cause a missed redundancy, not an incorrect circuit, because pruned candidates are not committed.
- Local/window/cone CEX models are safe for full-circuit pruning only when converted to concrete PI/latch assignments and then verified by simulating the full current circuit for the specific candidate being rejected. The current window and cone implementations encode complete fanin cones of their roots, so their models provide real PI/latch assignments; no free internal cut variables are used.
- Audited bounded windows are thesis-valid only under the complete observable cut condition. The runtime audit and whole-window skip on cap overflow are part of the proof story.
- ABC `strash`, `dc2`, `dch`, `fraig`, and `resyn2` should be used as external context baselines, but the thesis must state that these flows perform broader transformations than stuck-at constant replacement.

Immediate follow-up decisions:

| Decision | Reason |
| --- | --- |
| Run clean deep-mode experiments on `sin`, `sqrt`, `div`, `log2`, and `mem_ctrl` | These circuits had nonzero verified removals and/or large unresolved counts in fast mode |
| Do not spend first deep-mode budget on completed small circuits | `c432`, `router`, `c7552`, and `c6288` are already complete or near-complete under the current profile |
| Treat `c6288`, `multiplier`, `hyp`, and `arbiter` as diagnostic hard/zero cases | They are useful for showing pruning efficiency and limits, not guaranteed reduction wins |
| Add ABC baseline runner before claiming external competitiveness | Needed for fair thesis comparison and context |
| Consider structural blocked-candidate detection as next implementation | Sound if every path from a candidate to real observables is blocked by committed constants |
| Defer MaxSAT, joint multi-candidate SAT, FRAIG, and sequential reasoning | Too large or outside professor guardrails |

Implemented follow-up:

- Added `ALG10_AUDIT_CEX_PRUNING=1`.
- In audit mode, when output-level CEX simulation flags a candidate for pruning, the tool immediately re-checks that candidate with a full exact observable miter under the same committed context.
- If the audit miter returns SAT, the prune is confirmed.
- If the audit miter returns UNSAT, the prune is counted as `CEX_Audit_False_Prunes` and the candidate is not dropped.
- If the audit times out or skips, the candidate is not dropped in audit mode.
- The audit is intentionally expensive and stays off by default.
- Telemetry added: `CEX_Audit_Enabled`, `CEX_Audit_Checked`, `CEX_Audit_SAT`, `CEX_Audit_False_Prunes`, `CEX_Audit_Timeouts`, `CEX_Audit_Skipped`, and `CEX_Audit_Limit_Hit`.

## Current Best Thesis Narrative

The strongest current thesis line is:

> A verified SAT-based redundancy-removal pipeline for combinational AIGs, moving from baseline stuck-at ATPG toward a tiered proof architecture: cheap TFI constancy, optional over-observable bounded-window UNSAT proofs, exact affected-output cone miters, and global configurable-fault SAT, all guarded by final ABC CEC.

The evidence should emphasize:

- final ABC CEC pass rate;
- structural-vs-SAT-induced reductions;
- planted-live fast vs exhaustive comparison;
- Algorithm 10 checkpoint safety;
- tier-by-tier telemetry showing where reductions are proven;
- ablation evidence that no single ordering/tier dominates all circuits.

## Current Pipeline Default

When Algorithm 10 is selected through `main.py`, the default profile is now:

- current candidate ordering;
- TFI constancy enabled;
- audited bounded TFO window enabled;
- exact affected-output cone enabled;
- global SAT fallback enabled;
- rejection-only CEX pruning enabled.

This corresponds to the `cex_window_current` ablation profile. It is currently the best tested point because it matched or improved reductions on `c7552`, improved EPFL `sin` from 31 to 39 removals in 20s, and found 36 removals on EPFL `sqrt` where earlier short profiles found none. It remains configurable through environment variables for ablation discipline.

## Recommended Next Experiments

1. Broaden CEX-guided pruning validation.
   - Test `cex_current`, `cex_window_current`, and `global_only_cex_current` across `max`, `i2c`, and planted-live circuits.
   - Track `CEX_Pruned` separately from `CEX_TFI_Pruned`; the first is output-redundancy rejection, the second only skips TFI constancy.

2. Add candidate-size telemetry.
   - TFI cone size.
   - affected-output cone size.
   - number of affected roots.
   - SAT time per accepted replacement.

3. Test `window_current` on a broader but bounded set:
   - `benchmarks/c7552.aag`
   - `benchmark_suites/epfl/epfl_random_control_router.aag`
   - `benchmark_suites/epfl/epfl_arithmetic_sin.aag`
   - `benchmark_suites/epfl/epfl_arithmetic_max.aag`
   - `benchmark_suites/epfl/epfl_random_control_i2c.aag`

4. Keep hard arithmetic runs capped and diagnostic.
   - `sqrt`, `multiplier`, `log2`, `div`, and `hyp` should not consume long runs until candidate pruning improves.

5. Write the formal proof obligations.
   - Global committed-fault miter soundness.
   - TFI constancy soundness.
   - exact affected-output cone soundness.
   - bounded-window UNSAT-only soundness.
