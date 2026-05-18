# Prompt For External LLM Review: Final SAT-Side CEX Audit And Thesis Direction

Use this prompt with Gemini, Perplexity, Claude, ChatGPT, or another strict reviewer. The goal is not encouragement. I want a technical assessment of whether the current work is thesis/research-grade and what the next SAT-side step should be.

```text
Act as a strict SAT/ATPG/AIG optimization researcher and thesis examiner. Do not sugarcoat. Focus on correctness, proof obligations, SAT-side efficiency, and thesis contribution.

Project boundary:

I am implementing a thesis tool for SAT-based redundancy removal on combinational AIG/AAG circuits. Latches, when present, are only combinational cut boundaries. I must not claim sequential optimization, unreachable-state reasoning, retiming, maximum/optimal reduction, or simulation-based acceptance. Every reported optimized circuit must pass final ABC combinational equivalence checking.

Professor guardrails:

- Stay on combinational AIG/AAG circuits.
- Focus on SAT-side contribution.
- Do not pivot to full FRAIG/MaxSAT/sequential optimization as the main thesis unless a tiny prototype clearly wins.
- Do not claim optimality or exhaustive redundancy discovery when timeouts/unresolved candidates remain.
- Do not use simulation as proof of redundancy.
- Do not accept from an unsound truncated window.
- Do not skip final ABC CEC.

Pipeline:

1. Input circuits are ASCII AIGER `.aag`.
2. `main.py` copies/generates benchmarks into `dataset_benchmarks/`.
3. The selected optimizer writes optimized `.aag`.
4. `verifier.py` verifies original vs optimized through `abc_utils.py`.
5. Since local ABC rejects ASCII `.aag` directly, `abc_utils.py` converts `.aag` to binary `.aig` with bundled `aiger/aigtoaig`, runs ABC CEC on binary AIGs, and returns PASS/FAIL.
6. Thesis-valid result means final `Verify = PASS`.

Current main algorithm:

Algorithm 10 is the current point-of-time pipeline. `main.py` now defaults to:

- `ALG10_CANDIDATE_ORDER=current`;
- `ALG10_TFI_CONSTANCY=1`;
- `ALG10_WINDOW_MITER=1`;
- `ALG10_WINDOW_AUDIT=1`;
- `ALG10_WINDOW_LEVELS=5`;
- `ALG10_CONE_MITER=1`;
- `ALG10_CEX_PRUNING=1`;
- `ALG10_CEX_PRUNING_BATCH_SIZE=512`.

Fast mode:

- `ALG10_MODE=fast_save`;
- budgets `100,1000,5000`;
- default max 60s/circuit.

Deep mode:

- `ALG10_MODE=deep_resume`;
- budgets `1000,5000,20000,100000`;
- default max 600s/circuit.

Proof tiers:

1. TFI constancy SAT:
   - encode complete transitive fanin of the target gate;
   - ask if opposite stuck value is reachable;
   - UNSAT commits;
   - SAT only means not TFI-constant and does not reject output redundancy.

2. Audited bounded TFO window miter:
   - follow target fanout for bounded depth;
   - treat reached boundary gates or real output/latch-next roots as observable roots;
   - encode complete fanin cones of all roots;
   - runtime audit checks that roots form a complete observable cut: every fanout path from target to any real observable root must pass through a window root;
   - if audit fails or cone cap is exceeded, skip/escalate the whole window;
   - UNSAT commits, SAT/timeout/skip escalates.

3. Exact affected-output cone miter:
   - find all real output/latch-next roots in candidate fanout;
   - encode complete fanin cones of those roots;
   - compare good vs faulty cone;
   - UNSAT commits, SAT/timeout/skip escalates.

4. Full global configurable-fault miter:
   - good copy and configurable faulty copy;
   - shared PIs/latch-current variables;
   - per-gate stuck-at controls `f0_i` and `f1_i`;
   - mutex `not f0_i OR not f1_i`;
   - faulty behavior `(normal AND not f0_i) OR f1_i`;
   - assumption audit can enforce exactly `2A + 1` assumptions: all controls disabled except committed/candidate controls plus miter assertion.

CEX pruning:

- `ALG10_CEX_PRUNING=1` is rejection-only.
- It never accepts/commits a candidate.
- TFI SAT CEX only skips future TFI-constancy checks for candidates disproved under the concrete assignment. It does not globally reject output-redundancy candidates.
- Window/cone/global SAT CEX is converted into concrete PI/latch assignment. The full current circuit is bit-parallel simulated for each pending candidate. A candidate is pruned only if its own stuck-at fault creates a real output/latch-next mismatch under that concrete assignment.
- Final CEC cannot validate pruning quality, because false pruning causes missed reductions, not wrong commits.

New CEX recall audit:

External reviewers correctly pointed out that CEX pruning errors are omission errors, not commission errors. Therefore ABC CEC cannot catch false prunes.

I implemented:

- `ALG10_AUDIT_CEX_PRUNING=1`.
- When output-level CEX simulation flags a candidate for pruning, audit mode immediately re-checks that exact candidate with a full exact observable miter in the same committed context.
- SAT confirms the prune.
- UNSAT means the prune would have silently discarded a valid redundancy. It is counted as `CEX_Audit_False_Prunes`, and the candidate is not dropped.
- Timeout/skip also leaves the candidate alive in audit mode.
- Audit telemetry:
  - `CEX_Audit_Enabled`;
  - `CEX_Audit_Checked`;
  - `CEX_Audit_SAT`;
  - `CEX_Audit_False_Prunes`;
  - `CEX_Audit_Timeouts`;
  - `CEX_Audit_Skipped`;
  - `CEX_Audit_Limit_Hit`.

Latest relevant results:

1. Fast/resumed broad run:

CSV:
`results_optimized/thesis_results_ALG10_alg10_fast_save_cex_window_real_suites_planted_2026-05-17_23-22-24.csv`

38/38 rows had final `Verify=PASS`.

Selected rows:

- `c432`: 125 -> 121, removed 4, PASS, `CEX_Pruned=648`, `CEX_TFI_Pruned=210`.
- `c7552`: 1693 -> 1679, removed 14, PASS, `CEX_Pruned=9187`, `CEX_TFI_Pruned=3201`.
- `c6288`: 1870 -> 1870, removed 0, PASS, `CEX_Pruned=11041`, `CEX_TFI_Pruned=3521`.
- EPFL `sin`: 5416 -> 5389, removed 27, PASS, `TFI_Query_UNSAT=14`, `CEX_Pruned=25034`, `CEX_TFI_Pruned=21072`, `SAT_Unresolved=1382`.
- EPFL `sqrt`: 24618 -> 24582, removed 36, PASS, `Window_Query_UNSAT=13`, `CEX_Pruned=28916`, `CEX_TFI_Pruned=48834`, `SAT_Unresolved=12548`.
- EPFL `div`: 57247 -> 57203, removed 44, PASS, `TFI_Query_UNSAT=8`, `CEX_TFI_Pruned=217384`, `SAT_Unresolved=4405`.
- EPFL `log2`: 32060 -> 32052, removed 8, PASS, `TFI_Query_UNSAT=4`, `CEX_Pruned=37893`, `CEX_TFI_Pruned=126643`, `SAT_Unresolved=25960`.
- EPFL `mem_ctrl`: 46836 -> 46834, removed 2, PASS, `TFI_Query_UNSAT=1`, `CEX_TFI_Pruned=89202`, `SAT_Unresolved=2191`.
- EPFL `hyp`: 214335 -> 214335, removed 0, PASS, `CEX_TFI_Pruned=244965`, `SAT_Unresolved=183289`.
- EPFL `multiplier`: 27062 -> 27062, removed 0, PASS, `CEX_Pruned=36217`, `CEX_TFI_Pruned=49877`, `SAT_Unresolved=17799`.

2. Clean ablation highlights:

- `c7552`, 15s:
  - current: removed 4, SAT 10.89s, timeout.
  - `cex_current`: removed 14, SAT 8.60s, complete, `CEX_Pruned=19238`.
  - `window_current`: removed 14, SAT 10.15s, timeout.
  - `cex_window_current`: removed 14, SAT 4.34s, complete, `CEX_Pruned=11975`.
  - `global_only_cex_current`: removed 14, SAT 3.12s, complete, `CEX_Pruned=6477`.

- EPFL `sin`, 20s:
  - current: removed 31, SAT 19.98s, `TFI_Query_UNSAT=15`.
  - `cex_current`: removed 39, SAT 16.89s, `TFI_Query_UNSAT=19`, `CEX_TFI_Pruned=21232`.
  - `cex_window_current`: removed 39, SAT 11.16s, `CEX_TFI_Pruned=21232`, `CEX_Pruned=9863`.
  - `global_only_cex_current`: removed 0, timed out.

- `c6288`, 20s:
  - current: removed 0, SAT 16.28s, timeout.
  - `cex_current`: removed 0, SAT 2.46s, complete, `CEX_Pruned=7413`, `CEX_TFI_Pruned=3521`.
  - `global_only_cex_current`: removed 0, SAT 1.69s, complete, `CEX_Pruned=3712`.

- EPFL `sqrt`, 20s:
  - earlier current/window/global-only short profiles removed 0.
  - `cex_window_current`: removed 36, SAT 3.16s, `Window_Query_UNSAT=13`, `CEX_Pruned=28378`, `CEX_TFI_Pruned=48978`.

3. CEX audit smoke:

Command used a clean c432 run with `cex_window_audit`, 5s, budgets `100,1000`.

Result:

- `c432`: 125 -> 121, removed 4, `Verify=PASS`;
- `CEX_Audit_Checked=1088`;
- `CEX_Audit_SAT=1088`;
- `CEX_Audit_False_Prunes=0`;
- `CEX_Audit_Timeouts=0`;
- `Window_Query_UNSAT=2`.

Current interpretation:

- The current contribution is not “best AIG optimizer versus ABC.”
- It is a correctness-gated SAT proof architecture for stuck-at constant redundancy removal:
  - tiered exactness;
  - audited bounded window acceptance;
  - rejection-only CEX pruning;
  - CEX recall audit for missed-redundancy risk;
  - final ABC CEC.
- CEX pruning is the biggest practical accelerator.
- The audited window tier is valuable on `sqrt`.
- TFI constancy dominates useful reductions on `sin`, `div`, `log2`, `mem_ctrl`.
- Some arithmetic/control circuits remain hard or zero-yield under this stuck-at model.

Questions:

1. Given the exact architecture above, do you see any remaining correctness risks in the SAT encoding, proof tiers, CEX pruning, or CEX audit?
2. Is the CEX recall audit logically sufficient to detect false-prune/missed-redundancy errors for output-level CEX pruning?
3. Should the audit also be extended to TFI-CEX pruning, or is TFI-CEX safe because it only skips future TFI checks and not output-redundancy tiers?
4. Is the bounded window tier thesis-valid under the complete observable cut audit?
5. Based on these results, is this closer to a research contribution or just an engineering project? Be strict.
6. How should the thesis contribution be phrased to avoid overclaiming against ABC `fraig`, `dc2`, `dch`, and `resyn2`?
7. Should the next step be:
   - clean deep-mode runs on `sin`, `sqrt`, `div`, `log2`, `mem_ctrl`;
   - full/capped CEX audit on `c7552` and `sqrt`;
   - ABC baseline comparison runner;
   - structural blocked-candidate detection;
   - adaptive tier routing;
   - candidate ordering experiments;
   - something else SAT-side?
8. Which next experiment gives the strongest thesis evidence per hour of compute?
9. Which current result is most vulnerable to examiner criticism?
10. Which ideas should remain future work because they drift from the SAT-side thesis scope?

Required answer format:

1. Correctness risks.
2. Judgment: research contribution vs engineering project.
3. Ranked next steps focused on SAT-side improvement.
4. Concrete experiments to run next.
5. How to compare fairly against ABC and related tools.
6. Thesis wording: what to claim and what not to claim.
7. Final verdict.

Do not give generic advice. Tie every point to SAT encoding, proof tiers, CEX pruning/audit, candidate ordering, final CEC, or benchmark methodology.
```
