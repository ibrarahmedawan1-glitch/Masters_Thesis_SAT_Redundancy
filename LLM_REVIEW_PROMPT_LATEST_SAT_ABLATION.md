# Prompt For External LLM Review: Latest SAT-Side Ablation

Use this prompt with Gemini, Perplexity, Claude, ChatGPT, or another reviewer. The requested role is intentionally strict.

```text
Act as a strict SAT/ATPG/AIG optimization researcher and thesis examiner. Do not sugarcoat. I want technical criticism, not encouragement.

Context:

I am implementing a thesis tool for SAT-based redundancy removal on combinational AIG/AAG circuits. The project is not a sequential redundancy-removal tool. Latches, if present, are treated as combinational cut boundaries only. Final reported results are valid only when ABC combinational equivalence checking returns PASS.

Professor/thesis guardrails:

- Stay focused on combinational AIG/AAG circuits.
- Do not drift into sequential optimization or unreachable-state reasoning unless explicitly labeled as future work.
- Do not claim maximum or optimal reduction. Current approach is greedy and proof-driven.
- Do not treat simulation as proof of redundancy.
- Do not accept candidates from unsound truncated windows.
- Do not skip final ABC CEC.
- Avoid broad, high-risk pivots such as full MaxSAT/FRAIG as the main thesis direction unless a small prototype shows clear benefit.
- The thesis needs defensible SAT-side contribution, not only engineering polish.

Pipeline architecture:

1. Input circuits are ASCII AIGER `.aag`.
2. `main.py` generates/copies benchmarks into `dataset_benchmarks/`.
3. The selected optimizer writes an optimized `.aag`.
4. `verifier.py` verifies original vs optimized using ABC CEC through `abc_utils.py`.
5. Local ABC rejects direct ASCII `.aag` in `read_aiger`, so `abc_utils.py` converts `.aag` to binary `.aig` with bundled `aiger/aigtoaig`, runs ABC CEC on binary AIGs, then reports PASS/FAIL.
6. A result is thesis-valid only if final `Verify = PASS`.

Current key engines:

Algorithm 9:

- Mature committed in-memory incremental SAT optimizer.
- Builds a good circuit copy and a configurable faulty circuit copy in one CNF.
- Primary inputs/latch-current variables are shared.
- Each AND gate in the faulty copy has controls:
  - `f0_i`: stuck-at-0;
  - `f1_i`: stuck-at-1;
  - mutex: `not f0_i OR not f1_i`.
- Faulty gate behavior is `(normal AND not f0_i) OR f1_i`.
- For each candidate, assumptions activate all previously accepted replacements, activate the candidate, disable its opposite stuck-at control, disable inactive controls, and assert the output miter.
- SAT means a counterexample exists, so reject.
- UNSAT means the current accumulated replacement set is equivalent to the original, so commit.
- Final optimized circuit is still checked with ABC CEC.

Algorithm 10:

- Checkpointed budget-cycling SAT engine for longer runs.
- Writes safe partial outputs and checkpoints.
- It now has proof tiers:
  1. TFI constancy SAT:
     - encode the complete transitive fanin of the target gate;
     - ask if the opposite target value is reachable;
     - UNSAT can commit.
  2. Optional bounded TFO window miter:
     - enabled by `ALG10_WINDOW_MITER=1`;
     - follows target fanout for `ALG10_WINDOW_LEVELS`, then treats reached boundary gates or real outputs as observable roots;
     - encodes the complete fanin cones of those boundary roots;
     - this is intentionally over-observable, so window UNSAT can commit safely, while SAT/timeout/skip escalates;
     - the implementation now audits that the boundary roots form a complete observable cut: every fanout path from the target to any real output/latch-next root must pass through one of the window roots;
     - if the audit fails, the whole window tier skips/escalates; the cone-size cap also skips the whole window rather than dropping individual roots;
     - knobs: `ALG10_WINDOW_LEVELS`, `ALG10_WINDOW_BUDGET`, `ALG10_WINDOW_MAX_CONE_GATES`.
  3. Exact affected-output cone miter:
     - finds all output/latch-next roots in the candidate fanout;
     - encodes the complete fanin cone of those affected roots;
     - compares good vs single-fault cone;
     - cone UNSAT can commit safely, SAT/timeout/skip escalates.
  4. Full global configurable-fault miter.

Important implementation details:

- Global miter assumption audit exists via `ALG10_AUDIT_ASSUMPTIONS=1`.
- The global path passes exactly `2A + 1` assumptions: every fault control disabled except committed/candidate controls, plus the miter assertion.
- This directly addresses the risk of free fault-control variables.
- `ALG10_CANDIDATE_ORDER` supports `current`, `reverse_topo`, `cone_size`, `fanout_desc`, and `random`.
- `sat_ablation_experiments.py` runs variant matrices with isolated checkpoints and final ABC CEC on every row.
- `ALG10_CEX_PRUNING=1` is now implemented as rejection-only pruning:
  - TFI SAT models only skip future TFI-constancy checks when the concrete assignment disproves a candidate stuck value. This does not reject output-redundancy candidates globally.
  - Window, exact-cone, and global SAT models are converted into concrete PI/latch assignments. The tool then bit-parallel simulates the full circuit for each pending candidate and prunes only candidates whose own stuck-at fault creates a real output/latch-next mismatch.
  - CEX pruning never accepts a candidate and final ABC CEC is still mandatory.

Latest ablation results:

All listed rows had final ABC CEC PASS.

CSV result files:

- `results_optimized/sat_ablation_2026-05-17_18-21-22/sat_ablation_2026-05-17_18-21-22.csv`
- `results_optimized/sat_ablation_2026-05-17_18-23-29/sat_ablation_2026-05-17_18-23-29.csv`
- `results_optimized/sat_ablation_2026-05-17_18-25-23/sat_ablation_2026-05-17_18-25-23.csv`
- `results_optimized/sat_ablation_2026-05-17_18-31-37/sat_ablation_2026-05-17_18-31-37.csv`
- `results_optimized/sat_ablation_2026-05-17_19-18-58/sat_ablation_2026-05-17_19-18-58.csv`
- `results_optimized/sat_ablation_2026-05-17_19-22-44/sat_ablation_2026-05-17_19-22-44.csv`
- `results_optimized/sat_ablation_2026-05-17_19-24-37/sat_ablation_2026-05-17_19-24-37.csv`
- `results_optimized/sat_ablation_2026-05-17_19-28-09/sat_ablation_2026-05-17_19-28-09.csv`

Key observations:

1. `benchmarks/c7552.aag`, 15s budget:
   - current: removed 4, SAT 10.77s, cone UNSAT 2.
   - reverse: removed 6, SAT 10.64s, cone UNSAT 3.
   - window_reverse: removed 14, SAT 11.01s, window UNSAT 7.
   - global_only_audit: removed 14, SAT 14.99s, global UNSAT 7.

2. `benchmarks/c7552.aag`, 30s budget:
   - current: removed 6, SAT 20.39s, cone UNSAT 3.
   - window_current: removed 14, SAT 23.71s, window UNSAT 7.
   - window_reverse: removed 14, SAT 23.51s, window UNSAT 7.
   - global_only_current/audit: removed 14, SAT about 30s, global UNSAT 7.

3. `benchmark_suites/epfl/epfl_random_control_router.aag`, 20s budget:
   - current/reverse/window/global-only all removed 6.
   - global-only was fastest on this small circuit.

4. `benchmark_suites/epfl/epfl_arithmetic_sin.aag`, 20-30s budget:
   - current/window_current/rebuild_current removed 31.
   - reverse/window_reverse removed fewer.
   - global-only removed 0.
   - TFI current-order dominated on this circuit.

5. `benchmarks/c6288.aag`, `epfl_random_control_arbiter.aag`, and `epfl_arithmetic_sqrt.aag`, 20s budget:
   - current/window_current/global-only removed 0.
   - These are poor short ablation targets without stronger candidate pruning or longer budgets.

6. New CEX-pruning rows, all ABC CEC PASS:
   - `c7552`, 15s:
     - current: removed 4, SAT 10.89s, timeout.
     - cex_current: removed 14, SAT 8.60s, complete, `CEX_Pruned=19238`.
     - window_current: removed 14, SAT 10.15s, timeout.
     - cex_window_current: removed 14, SAT 4.34s, complete, `CEX_Pruned=11975`.
     - global_only_cex_current: removed 14, SAT 3.12s, complete, `CEX_Pruned=6477`.
   - EPFL `sin`, 20s:
     - current: removed 31, SAT 19.98s, `TFI_Query_UNSAT=15`.
     - cex_current: removed 39, SAT 16.89s, `TFI_Query_UNSAT=19`, `CEX_TFI_Pruned=21232`.
     - cex_window_current: removed 39, SAT 11.16s, `CEX_TFI_Pruned=21232`, `CEX_Pruned=9863`.
     - global_only_cex_current: removed 0, still timed out.
   - `c6288`, 20s:
     - current: removed 0, SAT 16.28s, timeout.
     - cex_current: removed 0, SAT 2.46s, complete, `CEX_Pruned=7413`, `CEX_TFI_Pruned=3521`.
     - global_only_cex_current: removed 0, SAT 1.69s, complete, `CEX_Pruned=3712`.
   - EPFL `sqrt`, 20s:
     - earlier current/window/global-only short profiles removed 0.
     - cex_window_current removed 36, SAT 3.16s, `Window_Query_UNSAT=13`, `CEX_Pruned=28378`, `CEX_TFI_Pruned=48978`.
   - EPFL `arbiter`, 20s:
     - CEX profiles still removed 0, but pruned many candidates; useful diagnostic, not a reduction win.

Current interpretation:

- Reverse order is not safe as a global default because it hurts EPFL `sin`.
- Global-only is not safe as a global default because it is poor on EPFL `sin`, although fast on small examples.
- The normal `main.py` Algorithm 10 path now defaults to the best tested profile, corresponding to `cex_window_current`: current ordering, TFI constancy, audited bounded window, exact cone, global fallback, and CEX pruning.
- Global-only CEX is excellent for fast rejection on `c7552/c6288`, but still fails to find EPFL `sin` redundancies, so it should not replace the tiered architecture.
- CEX pruning remains separately reported by telemetry and can be disabled with env vars for ablations; it should not be hidden when reporting thesis rows.

Questions for you:

1. Is the bounded TFO window tier sound as an UNSAT-only over-observable proof?
2. Are there any hidden soundness risks in the way the window boundary roots are chosen?
3. Does the data justify making `ALG10_WINDOW_MITER=1` the default, or should it remain an experimental profile?
4. How should the thesis describe why window UNSAT is safe but window SAT is inconclusive?
5. Why does global-only beat cone/window on small router/c432, while failing on `sin`?
6. Why does current ordering dominate reverse ordering on EPFL `sin`?
7. What candidate ordering should be tested next: fanout-desc, depth-asc, TFI-size, affected-cone-size, dominator-based, or SAT-history-based?
8. Should CEX-guided pruning be applied only to TFI constancy candidates, or can it soundly reject stuck-at output-redundancy candidates too? Be precise.
9. What is the safest next experiment that could improve hard circuits like `c6288`, EPFL `sqrt`, and EPFL `arbiter`?
10. Is a micro-solver exact cone architecture still worth pursuing now that global-only is faster on some small circuits?
11. Which additions are thesis-worthy versus just engineering?
12. What should I explicitly avoid because it would violate the professor/thesis guardrails?

Required answer format:

- First: identify correctness risks.
- Second: rank the next SAT-side improvements by expected impact.
- Third: explain whether each improvement is sound, conditionally sound, or heuristic only.
- Fourth: propose 3-5 concrete experiments using the listed available circuits.
- Fifth: give a strict thesis verdict: what should become part of the contribution, what should remain future work, and what should be discarded.

Do not give generic advice. Tie every recommendation to SAT encoding, proof tiers, candidate ordering, CEX use, or formal equivalence.
```
