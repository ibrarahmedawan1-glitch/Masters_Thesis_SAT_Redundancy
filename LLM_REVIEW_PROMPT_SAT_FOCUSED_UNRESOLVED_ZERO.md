# Prompt For External LLM Review: SAT-Focused Path To SAT_Unresolved = 0

Use this prompt with Gemini, Claude, ChatGPT, Perplexity, or another strict
technical reviewer. The goal is to get SAT-centered feedback. I already tested
pre-SAT simulation rejection and it helps, but I do not want the thesis to drift
into "mostly filtering." I want a stronger SAT/ATPG plan that keeps accepted
optimizations 100% correctness-gated and drives unresolved candidates toward
zero.

```text
Act as a strict SAT/ATPG/AIG optimization researcher and thesis examiner. Do
not sugarcoat. I need a SAT-focused technical plan for driving SAT_Unresolved
toward 0 while keeping every optimized circuit ABC CEC PASS and every accepted
replacement formally justified.

Core thesis boundary:

- Circuit model: combinational AIG/AAG.
- Latches, if present, are treated only as combinational cut boundaries.
- Optimization action: greedy single-gate stuck-at constant replacement of
  internal AND gates.
- A candidate may be accepted only when a sound SAT proof tier returns UNSAT.
- Simulation or CEX replay may reject/non-detect a candidate only when it gives
  a concrete observable output mismatch. It must never accept redundancy.
- Timeout is unresolved. Timeout must never be treated as nonredundant.
- Every reported optimized output must pass final independent ABC CEC.
- Do not claim optimality, full AIG optimization, sequential reasoning, or
  superiority over ABC as a general optimizer.

Current Algorithm 10:

Algorithm 10 is a tiered SAT optimizer:

1. TFI constancy SAT:
   - encode complete transitive fanin of target gate;
   - ask whether the opposite stuck value is reachable;
   - UNSAT means target is functionally constant and can be committed;
   - SAT/timeout/skip escalates.

2. Audited bounded TFO window miter:
   - encode complete fanin cones of bounded fanout window roots;
   - accept UNSAT only if runtime audit proves the window roots form a complete
     observable cut from the candidate to all real output/latch-next roots;
   - SAT/timeout/skip escalates.

3. Exact affected-output cone miter:
   - find all real output/latch-next roots in candidate fanout;
   - encode complete fanin cones for those affected roots;
   - UNSAT commits; SAT rejects; timeout/skip escalates.

4. Full global configurable-fault miter:
   - good and faulty circuit copies with shared PI/latch-current variables;
   - two controls per AND gate: `f0_i` and `f1_i`;
   - mutex `not f0_i OR not f1_i`;
   - faulty behavior `(normal AND not f0_i) OR f1_i`;
   - assumptions disable inactive controls, activate committed replacements,
     activate the current candidate, disable its opposite stuck value, and
     assert the output miter;
   - UNSAT commits; SAT rejects; timeout remains unresolved.

Current practical features:

- CEX pruning is rejection-only. SAT models from window/cone/global are
  converted to concrete PI/latch assignments and replayed against pending
  candidates by full-circuit simulation. A candidate is pruned only if its own
  stuck-at fault causes a real observable mismatch.
- CEX audit exists because final CEC cannot catch false pruning. With
  `ALG10_AUDIT_CEX_PRUNING=1`, every output-level prune can be rechecked using
  an exact observable miter. SAT confirms prune; UNSAT is a false prune and the
  candidate is kept.
- Checkpoints currently save the latest safe optimized AAG and telemetry. They
  do not yet save an exact unresolved queue, per-candidate tier history, CEX
  pool, or solver-progress metadata.

Recent feedback and experiment:

Other reviewers recommended pre-SAT deterministic simulation rejection. I
implemented it opt-in as `ALG10_PRE_SIM_REJECTION=1`.

What it does:

- generate deterministic structured/random PI/latch assignments;
- simulate each single stuck-at candidate;
- if a real output/latch-next mismatch occurs, reject the candidate as
  nonredundant;
- if no mismatch is found, make no conclusion and send the candidate to SAT.

This is sound rejection, but it is still a filter. I want the next review to
focus more on SAT-side classification/proof/search improvements, not only
simulation prefiltering.

Early opt-in results:

| Circuit | Variant | Removed | Verify | SAT_Unresolved | T_SAT | T_Total | PreSAT pruned |
|---|---|---:|---|---:|---:|---:|---:|
| c432 | baseline cex_window | 4 | PASS | 0 | 0.0828s | 0.1169s | 0 |
| c432 | pre-sim cex_window | 4 | PASS | 0 | 0.0064s | 0.0413s | 732 |
| c7552 | baseline cex_window | 14 | PASS | 2 | 2.8350s | 5.9541s | 0 |
| c7552 | pre-sim cex_window | 14 | PASS | 0 | 1.9327s | 3.6614s | 5829 |
| sin | baseline cex_window | 39 | PASS | 3612 | 11.7239s | 20.0227s | 0 |
| sin | pre-sim cex_window | 39 | PASS | 201 | 8.7659s | 20.0097s | 18075 |

Audit smoke with pre-sim on c432:

- `Verify=PASS`;
- `PreSAT_Sim_Pruned=633`;
- `CEX_Audit_Checked=751`;
- `CEX_Audit_False_Prunes=0`.

Deep run unresolved problem:

| Circuit | Gates Before | Gates After | Removed | TFI UNSAT | Window UNSAT | SAT_Unresolved | Final CEC |
|---|---:|---:|---:|---:|---:|---:|---|
| c432 | 125 | 121 | 4 | 0 | 2 | 0 | PASS |
| c7552 | 1693 | 1679 | 14 | 0 | 7 | 0 | PASS |
| c6288 | 1870 | 1870 | 0 | 0 | 0 | 0 | PASS |
| sin | 5416 | 5375 | 41 | 19 | 1 | 179 | PASS |
| sqrt | 24618 | 24562 | 56 | 0 | 22 | 19747 | PASS |
| div | 57247 | 57014 | 233 | 8 | 74 | 21490 | PASS |
| log2 | 32060 | 32037 | 23 | 13 | 0 | 19132 | PASS |
| mem_ctrl | 46836 | 46761 | 75 | 1 | 34 | 48193 | PASS |

What I want now:

I want ideas that improve exact candidate classification and SAT proof/search
efficiency while keeping the acceptance boundary unchanged. Filtering is useful
but should support the SAT architecture, not replace it.

Questions:

1. What are the best SAT-side changes to drive `SAT_Unresolved` toward 0?
   Consider exact checkpoint/resume, per-candidate budget history, incremental
   solvers, learned clause reuse, assumption design, UNSAT cores, cone caching,
   solver phase hints, proof-tier scheduling, and candidate decomposition.

2. How should I redesign checkpoint/resume so deep runs truly continue progress
   instead of restarting from the latest safe AAG?
   - Should I persist unresolved candidates?
   - Should I persist rejected candidates?
   - Should I persist CEX patterns?
   - Should I persist per-candidate tier/budget history?
   - How do I avoid stale candidate IDs after strash/cleanup?

3. What is the safest candidate identity scheme?
   Options:
   - phase-local gate index only;
   - original AAG literal plus stuck value;
   - structural hash / TFI hash;
   - simulation signature plus local structure;
   - avoid stable IDs and instead replay CEX pool after each rebuild.
   Which is robust enough for thesis experiments?

4. Can incremental SAT be used more effectively here?
   - One solver per tier?
   - One global configurable-fault solver per phase?
   - Persist learned clauses within a committed context?
   - Rebuild solver after every commit?
   - How to avoid unsound learned-clause reuse across changed circuits?

5. Can UNSAT cores or failed assumptions help reduce unresolved candidates?
   - Can they identify irrelevant committed controls?
   - Can they shrink global assumptions?
   - Can they inform candidate ordering or grouping?
   - Are they likely to help in PySAT/Glucose for this workload?

6. How should exact affected-output cone SAT be improved?
   - cache cone CNFs by root set or structural hash;
   - incremental cone solvers for candidates sharing output roots;
   - split large output cones;
   - use dominators or cuts;
   - strengthen boundary constraints.
   Which of these are sound and practical?

7. How should audited bounded windows be improved without becoming unsound?
   - adaptive window levels;
   - dynamically choose complete observable cuts;
   - prefer dominator cuts;
   - widen until the cut audit passes;
   - cache cut/cone encodings.

8. How can fault detection be maximized without letting filtering dominate?
   I want high coverage of detected nonredundant stuck-at candidates, but the
   thesis should still be SAT-centered. How should I combine:
   - SAT-generated CEX pool;
   - deterministic pre-SAT rejection;
   - exact SAT proof tiers;
   - CEX audit;
   - final ABC CEC?

9. What is the right metric framework?
   I am thinking of:
   - `Faults_Total`;
   - `Faults_Detected_By_SAT_CEX`;
   - `Faults_Detected_By_Sim_CEX`;
   - `Faults_Redundant_Proved_UNSAT`;
   - `Faults_Unresolved`;
   - `Fault_Coverage% = (detected + proved redundant) / total`;
   - `CEC_PASS%`.
   Is this a valid ATPG/SAT framing for the thesis?

10. For hard circuits like `sqrt`, `div`, `log2`, and `mem_ctrl`, should the
    strategy prioritize:
    - quickly detecting/rejecting SAT candidates;
    - proving UNSAT redundancies;
    - reducing timeout rate;
    - reaching every candidate at least once;
    - exact multi-session continuation?
    Rank these by thesis value.

11. Which SAT-focused improvement can be implemented and tested in 2-4 days?
    Please be concrete. I need a patch plan, data structures, and experiments.

12. Which ideas are attractive but should be avoided because they are too risky
    or drift away from the thesis?
    Examples: MaxSAT, full FRAIG, sequential reasoning, unsafe simulation
    acceptance, repeated-timeout classification, broad parallel portfolios that
    break greedy committed-context semantics.

13. How should I compare against ABC fairly?
    My tool does single-gate stuck-at constant replacement with proof/audit
    telemetry. ABC `dc2`, `dch`, `fraig`, `resyn2` do broader transformations.
    What should the baseline table report so the comparison is honest?

Required answer format:

1. Correctness invariants that must not change.
2. Ranked SAT-focused improvements for reducing `SAT_Unresolved`.
3. For each improvement: soundness classification, expected impact, risk, and
   implementation complexity.
4. Exact patch plan for the best 2-4 day implementation.
5. Data structures to add, especially for checkpoint/resume, candidate status,
   CEX pool, and proof context hash.
6. Experiment matrix on `sin`, `sqrt`, `div`, `log2`, and `mem_ctrl`.
7. Metrics and CSV telemetry to add for fault detection, SAT proof coverage,
   and unresolved-to-zero progress.
8. How to use pre-SAT filtering without making the thesis look like a
   simulation-filter project.
9. Thesis-safe wording for "fault coverage," "unresolved to zero," and
   "100% CEC."
10. Final verdict: what to implement first, what to postpone, and what to avoid.

Do not give generic advice. Tie every recommendation to SAT encoding, proof
tiers, candidate classification, fault detection, CEX audit, exact
checkpoint/resume, final ABC CEC, or benchmark methodology.
```
