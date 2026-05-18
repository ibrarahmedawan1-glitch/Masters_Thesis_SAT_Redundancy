# Prompt For External LLM Review: CEX-Window Algorithm 10, Deep Mode, And Thesis Baselines

Use this prompt with Gemini, Perplexity, Claude, ChatGPT, or another reviewer. The requested role is intentionally strict.

```text
Act as a strict SAT/ATPG/AIG optimization researcher and thesis examiner. Do not sugarcoat. I want technical criticism, not encouragement.

Context:

I am implementing a thesis tool for SAT-based redundancy removal on combinational AIG/AAG circuits. The project is not a sequential redundancy-removal tool. Latches, if present, are treated only as combinational cut boundaries. A result is thesis-valid only when final ABC combinational equivalence checking returns PASS.

Professor/thesis guardrails:

- Stay focused on combinational AIG/AAG circuits.
- Do not drift into sequential optimization, unreachable-state reasoning, retiming, or sequential ODCs except as future work.
- Do not claim maximum or optimal reduction. The method is greedy and proof-driven.
- Do not treat simulation as proof of redundancy.
- Do not accept candidates from unsound truncated windows.
- Do not skip final ABC CEC.
- Avoid broad, high-risk pivots such as full MaxSAT/FRAIG as the main thesis direction unless a small prototype clearly wins.
- The thesis needs a defensible SAT-side contribution, not only engineering polish.

Pipeline architecture:

1. Input circuits are ASCII AIGER `.aag`.
2. `main.py` generates/copies benchmarks into `dataset_benchmarks/`.
3. The selected optimizer writes an optimized `.aag`.
4. `verifier.py` verifies original vs optimized using ABC CEC through `abc_utils.py`.
5. Local ABC rejects direct ASCII `.aag` in `read_aiger`, so `abc_utils.py` converts `.aag` to binary `.aig` with bundled `aiger/aigtoaig`, runs ABC CEC on binary AIGs, then reports PASS/FAIL.
6. A result is thesis-valid only if final `Verify = PASS`.

Original mature engine, Algorithm 9:

- In-memory incremental SAT optimizer.
- Builds a good circuit copy and a configurable faulty circuit copy in one CNF.
- Primary inputs/latch-current variables are shared.
- Each AND gate in the faulty copy has controls:
  - `f0_i`: stuck-at-0;
  - `f1_i`: stuck-at-1;
  - mutex: `not f0_i OR not f1_i`.
- Faulty gate behavior is `(normal AND not f0_i) OR f1_i`.
- For each candidate, assumptions activate all previously accepted replacements, activate the candidate, disable the opposite stuck-at control, disable inactive controls, and assert the output miter.
- SAT means a counterexample exists, so reject.
- UNSAT means the current accumulated replacement set is equivalent to the original, so commit.
- Final optimized circuit is checked with ABC CEC.

Current latest engine, Algorithm 10:

- Checkpointed budget-cycling SAT engine for longer runs.
- Writes safe partial outputs and checkpoints.
- `main.py` now defaults to the best current profile:
  - `ALG10_MODE=fast_save` for normal fast runs;
  - `ALG10_CANDIDATE_ORDER=current`;
  - `ALG10_TFI_CONSTANCY=1`;
  - `ALG10_WINDOW_MITER=1`;
  - `ALG10_WINDOW_AUDIT=1`;
  - `ALG10_WINDOW_LEVELS=5`;
  - `ALG10_CONE_MITER=1`;
  - `ALG10_CEX_PRUNING=1`;
  - `ALG10_CEX_PRUNING_BATCH_SIZE=512`.
- Deep mode uses:
  - `ALG10_MODE=deep_resume`;
  - default budgets `1000,5000,20000,100000`;
  - default max time 600s per circuit;
  - larger TFI/window/cone budgets and cone caps.

Algorithm 10 proof tiers:

1. TFI constancy SAT:
   - encode the complete transitive fanin of the target gate;
   - ask if the opposite target value is reachable;
   - UNSAT can commit.

2. Audited bounded TFO window miter:
   - follows target fanout for `ALG10_WINDOW_LEVELS`;
   - treats reached boundary gates or real output/latch-next roots as observable roots;
   - encodes the complete fanin cones of those roots;
   - window UNSAT can commit only because the implementation audits that the boundary roots form a complete observable cut: every fanout path from the target to any real output/latch-next root must pass through one window root;
   - if the audit fails, the whole window tier skips/escalates;
   - if the cone-size cap is exceeded, the whole window skips/escalates rather than dropping individual roots;
   - SAT/timeout/skip escalates.

3. Exact affected-output cone miter:
   - finds all output/latch-next roots in the candidate fanout;
   - encodes the complete fanin cones of those affected roots;
   - compares good vs faulty cone;
   - cone UNSAT can commit; SAT/timeout/skip escalates.

4. Full global configurable-fault miter:
   - same configurable stuck-at controls as Algorithm 9;
   - assumption audit exists via `ALG10_AUDIT_ASSUMPTIONS=1`;
   - global calls pass exactly `2A + 1` assumptions: every fault control disabled except committed/candidate controls, plus miter assertion.

CEX-guided pruning:

- `ALG10_CEX_PRUNING=1` is rejection-only.
- TFI SAT models only skip future TFI-constancy checks when the concrete assignment disproves a candidate stuck value. This does not globally reject output-redundancy candidates.
- Window, exact-cone, and global SAT models are converted into concrete PI/latch assignments. The tool then bit-parallel simulates the full circuit for each pending candidate and prunes only candidates whose own stuck-at fault creates a real output/latch-next mismatch.
- CEX pruning never accepts a candidate.
- Final ABC CEC is still mandatory.
- `ALG10_AUDIT_CEX_PRUNING=1` is now implemented as an expensive recall audit:
  - when output-level CEX simulation flags a candidate for pruning, the tool immediately re-checks that same candidate using a full exact observable miter in the same committed context;
  - SAT confirms the prune;
  - UNSAT means the prune would have silently discarded a valid redundancy, so it is counted as `CEX_Audit_False_Prunes` and the candidate is not dropped;
  - timeout/skip leaves the candidate unpruned in audit mode;
  - audit telemetry includes `CEX_Audit_Checked`, `CEX_Audit_SAT`, `CEX_Audit_False_Prunes`, `CEX_Audit_Timeouts`, `CEX_Audit_Skipped`, and `CEX_Audit_Limit_Hit`.

Important recent fast-run result:

CSV:

`results_optimized/thesis_results_ALG10_alg10_fast_save_cex_window_real_suites_planted_2026-05-17_23-22-24.csv`

This was a checkpoint-resumed fast run, so for thesis tables I still need clean isolated runs with `ALG10_RESET_CHECKPOINT=1`. However, the CSV had `Verify=PASS` for all 38 rows.

Selected results:

- `c432`: 125 -> 121 gates, 4 removed, PASS, `CEX_Pruned=648`, `CEX_TFI_Pruned=210`.
- `c7552`: 1693 -> 1679 gates, 14 removed, PASS, `CEX_Pruned=9187`, `CEX_TFI_Pruned=3201`.
- `c6288`: 1870 -> 1870 gates, 0 removed, PASS, but `CEX_Pruned=11041`, `CEX_TFI_Pruned=3521`.
- EPFL `sin`: 5416 -> 5389 gates, 27 removed, PASS, `TFI_Query_UNSAT=14`, `CEX_Pruned=25034`, `CEX_TFI_Pruned=21072`, `SAT_Unresolved=1382`.
- EPFL `sqrt`: 24618 -> 24582 gates, 36 removed, PASS, `Window_Query_UNSAT=13`, `CEX_Pruned=28916`, `CEX_TFI_Pruned=48834`, `SAT_Unresolved=12548`.
- EPFL `div`: 57247 -> 57203 gates, 44 removed, PASS, `TFI_Query_UNSAT=8`, `CEX_TFI_Pruned=217384`, `SAT_Unresolved=4405`.
- EPFL `log2`: 32060 -> 32052 gates, 8 removed, PASS, `TFI_Query_UNSAT=4`, `CEX_Pruned=37893`, `CEX_TFI_Pruned=126643`, `SAT_Unresolved=25960`.
- EPFL `mem_ctrl`: 46836 -> 46834 gates, 2 removed, PASS, `TFI_Query_UNSAT=1`, `CEX_TFI_Pruned=89202`, `SAT_Unresolved=2191`.
- EPFL `hyp`: 214335 -> 214335 gates, 0 removed, PASS, `CEX_TFI_Pruned=244965`, `SAT_Unresolved=183289`.
- EPFL `multiplier`: 27062 -> 27062 gates, 0 removed, PASS, `CEX_Pruned=36217`, `CEX_TFI_Pruned=49877`, `SAT_Unresolved=17799`.
- EPFL `arbiter`: 11839 -> 11839 gates, 0 removed, PASS, `CEX_Pruned=4320`, `CEX_TFI_Pruned=23568`, `SAT_Unresolved=18839`.

Prior clean ablation highlights:

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
  - previous current/window/global-only short profiles removed 0.
  - cex_window_current removed 36, SAT 3.16s, `Window_Query_UNSAT=13`, `CEX_Pruned=28378`, `CEX_TFI_Pruned=48978`.

Current interpretation:

- CEX pruning is the major change. It prevents the solver from spending most of the budget on candidates that a concrete counterexample can reject.
- The audited window tier is now useful on `sqrt`, where earlier short profiles found 0.
- TFI constancy remains important on EPFL `sin`, `div`, `log2`, and `mem_ctrl`.
- Global-only CEX can be fastest on some small/control circuits but fails badly on EPFL `sin`, so it should not replace the tiered architecture.
- Reverse-topological order is not a safe default because it hurts EPFL `sin`.
- `current + TFI + audited window + exact cone + global fallback + CEX pruning` is the best current point-of-time default.

Questions:

1. Given the encoding above, do you see any remaining correctness risks in the global configurable-fault miter, TFI tier, audited window tier, exact cone tier, or CEX pruning?
2. Is the audited bounded TFO window tier sound as an UNSAT-only acceptance proof under the complete-observable-cut condition?
3. Are there hidden risks in converting local/window/cone SAT models into concrete PI/latch assignments for full-circuit candidate simulation?
4. Are the CEX pruning rules sound as stated, especially the distinction between TFI-only pruning and output-redundancy pruning?
5. Does the fast-run evidence justify making CEX pruning and audited window miter part of the default Algorithm 10 pipeline?
6. If fast mode found these reductions, should deep mode be expected to find more? Be precise: which circuits are likely to improve, which are unlikely, and why?
7. For deep mode, should I resume from fast checkpoints or run clean isolated deep experiments with `ALG10_RESET_CHECKPOINT=1`?
8. Should deep mode keep the same candidate order, or test orderings such as TFI-size ascending, affected-cone-size ascending, fanout-desc, dominator-based, or SAT-history-based?
9. Which next SAT-side improvement has the best risk/reward:
   - stronger candidate ordering;
   - adaptive tier routing/global-vs-local crossover;
   - structural blocked-candidate detection after commits;
   - periodic structural rebuild;
   - exact cone micro-solver improvements;
   - joint multi-candidate SAT prototype;
   - other?
10. What should be the fair external comparison methodology?
    - Compare against ABC scripts such as `strash`, `dc2`, `dch`, `fraig`, `resyn2`?
    - Compare against Yosys+ABC?
    - Compare against mockturtle only as related work unless wrapped?
    - What metrics should be reported so the comparison is fair?
11. How should I phrase the thesis contribution so I do not overclaim against ABC/FRAIG tools that perform broader transformations than stuck-at constant replacement?
12. What should I explicitly avoid because it would violate the professor/thesis guardrails?

Required answer format:

1. Correctness risks first.
2. Deep-mode expectation: will it find more, where, and why?
3. Ranked next improvements by expected impact and risk.
4. Soundness classification for each improvement: sound, conditionally sound, or heuristic only.
5. 3-5 concrete experiments to run next, using circuits listed above.
6. Fair baseline/tool comparison plan.
7. Strict thesis verdict: what becomes a contribution, what stays future work, what should be discarded.

Do not give generic advice. Tie every recommendation to SAT encoding, proof tiers, candidate ordering, CEX use, final equivalence, or benchmark methodology.
```
