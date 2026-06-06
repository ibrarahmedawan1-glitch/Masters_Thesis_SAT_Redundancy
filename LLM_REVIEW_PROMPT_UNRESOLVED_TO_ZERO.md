# Prompt For External LLM Review: Driving Algorithm 10 SAT_Unresolved Toward Zero

Use this prompt with Gemini, Claude, ChatGPT, Perplexity, or another strict
technical reviewer. The goal is to get criticism and concrete next-step design
ideas, not encouragement.

```text
Act as a strict SAT/ATPG/AIG optimization researcher and thesis examiner. Do
not sugarcoat. I want a technical plan for reducing unresolved candidates
toward zero in my SAT-based AIG redundancy-removal tool without weakening the
correctness boundary.

Important professor update:

I showed the current algorithm, proof tiers, CEX audit, deep results, and
remaining unresolved-candidate problem to my professor. He confirmed that I can
move forward by enhancing the tool further, with the practical goal of driving
SAT_Unresolved closer to 0 on the remaining hard circuits.

Project boundary:

- The circuit model is combinational AIG/AAG.
- Latches, if present, are treated only as combinational cut boundaries.
- The optimization action is greedy single-gate stuck-at constant replacement:
  replace an internal AND gate by constant 0 or 1 if proved safe.
- Do not claim sequential optimization, unreachable-state reasoning, retiming,
  maximum/optimal AIG optimization, or superiority over ABC as a general logic
  optimizer.
- Simulation may reject a candidate if it gives a concrete output
  counterexample, but simulation must never accept a redundancy.
- Every reported optimized circuit must pass final independent ABC
  combinational equivalence checking.

Current tool pipeline:

1. Input circuits are AIGER `.aag`/`.aig`.
2. Python optimizer writes an optimized `.aag`.
3. `verifier.py` verifies original vs optimized through `abc_utils.py`.
4. `abc_utils.py` converts ASCII `.aag` to binary `.aig` with bundled
   `aiger/aigtoaig`, then runs ABC CEC on binary AIGs because this local ABC
   build rejects ASCII `.aag` in `read_aiger`.
5. A benchmark row is thesis-valid only if final `Verify = PASS`.

Current main algorithm:

Algorithm 10 is the current thesis engine. Its current default profile is:

- `ALG10_CANDIDATE_ORDER=current`
- `ALG10_TFI_CONSTANCY=1`
- `ALG10_WINDOW_MITER=1`
- `ALG10_WINDOW_AUDIT=1`
- `ALG10_WINDOW_LEVELS=5`
- `ALG10_CONE_MITER=1`
- `ALG10_CEX_PRUNING=1`
- `ALG10_CEX_PRUNING_BATCH_SIZE=512`

Fast mode:

- `ALG10_MODE=fast_save`
- budgets `100,1000,5000`
- default max 60s/circuit

Deep mode:

- `ALG10_MODE=deep_resume`
- budgets `1000,5000,20000,100000`
- default max 600s/circuit

Current proof tiers:

1. TFI constancy SAT:
   - encode the complete transitive fanin of the target gate;
   - ask if the opposite stuck value is reachable;
   - UNSAT means the node is functionally constant and the stuck replacement
     is committed;
   - SAT, timeout, or skip escalates. SAT does not reject output-level
     redundancy.

2. Audited bounded TFO window miter:
   - choose bounded fanout-window roots around the candidate;
   - encode complete fanin cones of the window roots;
   - accept UNSAT only if a runtime audit proves the roots form a complete
     observable cut: every fanout path from the candidate to every real
     output/latch-next root passes through at least one monitored window root;
   - if the cut audit fails or the cone cap is exceeded, skip/escalate;
   - SAT, timeout, or skip does not reject the candidate.

3. Exact affected-output cone miter:
   - find every real output/latch-next root in the candidate's fanout;
   - encode complete fanin cones for those roots;
   - compare good vs faulty cone;
   - UNSAT commits; SAT, timeout, or skip escalates.

4. Full global configurable-fault miter:
   - build good and faulty circuit copies with shared PI/latch-current vars;
   - faulty copy has controls `f0_i` and `f1_i` for each AND gate;
   - add mutex `not f0_i OR not f1_i`;
   - faulty behavior is `(normal AND not f0_i) OR f1_i`;
   - assumptions disable all inactive controls, activate previously committed
     replacements, activate the current candidate, disable the opposite stuck
     value, and assert the output miter;
   - UNSAT commits; SAT rejects; timeout leaves unresolved.

CEX pruning:

- CEX pruning is rejection-only.
- It never commits a replacement.
- TFI SAT CEX pruning only skips future TFI-constancy checks when the concrete
  assignment disproves a target stuck value. It does not skip output-redundancy
  tiers.
- Window/cone/global SAT models are converted to concrete PI/latch-current
  assignments. The full current circuit is simulated for each pending
  candidate. A candidate is pruned only if its own stuck-at faulty circuit
  differs from the good circuit at a real output/latch-next root under that
  assignment.
- Final ABC CEC cannot detect false pruning because false pruning causes missed
  reductions, not wrong output circuits.
- Therefore audit mode exists: `ALG10_AUDIT_CEX_PRUNING=1` immediately
  rechecks output-level prunes with an exact observable miter. SAT confirms the
  prune. UNSAT means a false prune, so the candidate is kept and counted in
  `CEX_Audit_False_Prunes`. Timeout/skip also keeps the candidate alive.

Current correctness evidence:

- Formal argument document states the proof obligations for global, TFI, cone,
  audited window, CEX pruning, and rewrite soundness.
- Bounded exhaustive validation checked production encodings against
  brute-force truth-table semantics on small AIG spaces:
  - Run 1: 33,588 circuits, 133,176 candidates, 0 failures.
  - Run 2: 92,628 circuits, 536,376 candidates, 0 failures.
- Correctness stress suite includes:
  - algorithm smoke tests;
  - roundtrip/write and strash checks;
  - negative corrupted-output control;
  - checkpoint consistency;
  - planted-live probes;
  - capped CEX audit probes.
- All required rows had final ABC `PASS`.

Clean deep results currently motivating the next step:

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

Interpretation:

- ISCAS c432, c7552, and c6288 reached `SAT_Unresolved=0` under the current
  stuck-at model.
- EPFL `sin` is close to resolved, with only 179 unresolved.
- EPFL `sqrt`, `div`, `log2`, and `mem_ctrl` still have many unresolved
  candidates after deep runs.
- These EPFL rows are still useful because they found verified reductions and
  final ABC CEC passed, but they are not exhaustive completion claims.
- The next goal is not just "find a few more removals." The professor approved
  improving the tool so more candidates are classified, ideally reaching
  `SAT_Unresolved=0` on more circuits or at least sharply reducing it.

Current checkpoint limitation:

- Algorithm 10 checkpoints save the latest safe optimized AAG plus telemetry.
- A resume starts from that safe AAG and sweeps again.
- It does not yet save an exact unresolved-candidate queue, per-candidate
  status, per-candidate budget history, CEX pool, or solver-progress metadata.
- For clean thesis experiments, ablation rows currently reset checkpoints.

My current candidate improvement ideas:

1. Exact unresolved-queue checkpoint/resume:
   - persist stable candidate IDs, accepted candidates, rejected candidates,
     CEX-pruned candidates, unresolved candidates, budget level reached, and
     tier status;
   - resume exactly from the unresolved set instead of sweeping again from the
     beginning;
   - handle candidate renumbering after structural cleanup carefully.

2. Sound pre-SAT counterexample rejection:
   - generate deterministic random or structured PI/latch assignments;
   - for each assignment, simulate the full good circuit and many single
     stuck-at faulty candidates;
   - if a candidate produces a real observable mismatch, reject it as
     nonredundant;
   - this is simulation as rejection witness, not simulation as proof of
     redundancy.

3. CEX pool and batched candidate rejection:
   - keep global PI/latch assignments learned from SAT models and random
     rejection probes;
   - replay the pool after every commit/rebuild only when still valid in the
     current committed context;
   - use bit-parallel batches to reject many candidates cheaply.

4. Adaptive candidate ordering:
   - try to classify easy SAT candidates early so they generate CEXs for
     pruning;
   - try TFI-likely candidates early for quick UNSAT commits;
   - possible order keys: TFI cone size, affected-output cone size, fanout
     count, depth, window-cut success probability, previous timeout history,
     number of CEX-pool mismatches, or SAT tier history.

5. Adaptive tier routing:
   - skip expensive tiers when structural features suggest they will timeout;
   - route small-local-cone candidates to cone/window first;
   - route high-fanout or large-cone candidates to CEX rejection first;
   - tune per-tier budgets from observed success rates.

6. Structural dominated/blocked-candidate detection:
   - after commits and cleanup, detect candidates that are structurally
     equivalent to an already rejected case or obviously controlled by a local
     condition;
   - only use rules that are either sound rejection, sound acceptance, or
     explicitly heuristic nomination with later SAT proof.

7. Solver/CNF engineering:
   - reuse incremental solvers and learned clauses where sound;
   - improve assumption discipline and clause lifetime;
   - consider per-tier CNF caching by cone hash;
   - use UNSAT cores or failed assumptions if useful;
   - avoid changes that make accepted replacements depend on heuristic evidence.

8. Portfolio/decomposition:
   - run multiple sound strategies on the same unresolved set;
   - split unresolved candidates by output cone or structural region;
   - use parallel workers only if it does not break greedy committed-context
     semantics.

Questions I want you to answer:

1. Which of the improvement ideas above are most likely to reduce
   `SAT_Unresolved` toward zero on `sin`, `sqrt`, `div`, `log2`, and
   `mem_ctrl`?
2. Which ideas are sound as stated, which are conditionally sound, and which
   are merely heuristic unless followed by SAT/CEC?
3. What is the best first implementation step if I want a real improvement in
   1-3 days rather than a large research rewrite?
4. Is exact unresolved-queue checkpoint/resume worth implementing before new
   SAT heuristics, or should I first add stronger rejection/ordering?
5. How should stable candidate IDs be represented if structural cleanup can
   remove gates and renumber AAG literals?
6. Should unresolved candidates be tracked relative to the original circuit,
   the current committed circuit, or a phase-local rebuilt circuit?
7. How can I safely reuse CEX assignments across commits? When does a CEX
   remain valid, and when must it be discarded or rechecked?
8. Is deterministic random/structured simulation as a rejection witness a good
   idea for reducing unresolved counts? What patterns should be used?
9. What candidate-ordering signals are most promising for EPFL arithmetic and
   control circuits?
10. Should the tool prioritize quickly rejecting SAT candidates or quickly
    finding UNSAT commits? Which helps unresolved-to-zero more?
11. How should budgets be adapted per candidate after timeouts?
12. Is there a sound way to classify repeated timeouts as "probably
    nonredundant," or must timeout always remain unresolved?
13. Can UNSAT cores, SAT solver phases, assumptions, or learned clauses help
    meaningfully here?
14. Would exact affected-output cone caching by structural hash help, or are
    the cones too candidate-specific?
15. How should the CEX audit be used during development versus final thesis
    runs? Full audit, capped audit, sampled audit, or targeted audit?
16. What experiment matrix should I run next to know whether the enhancement
    truly reduces unresolved candidates, not just runtime?
17. What metrics should be added beyond `SAT_Unresolved`, for example:
    unresolved by tier, unresolved by timeout vs budget cap, unresolved by cone
    size bucket, candidates rejected by pre-SAT CEX, candidates reopened after
    commit, exact resume progress, or CEX-pool hit rate?
18. Which circuits should be used first for fast feedback, and which should be
    saved for overnight validation?
19. What would be the strongest examiner criticism of an "unresolved-to-zero"
    enhancement, and how should I preempt it?
20. If you were supervising this thesis, what exact next patch would you ask me
    to implement first?

Required answer format:

1. Correctness constraints that must not change.
2. Ranked implementation plan for reducing `SAT_Unresolved`.
3. For each proposed step: soundness classification, expected impact, risk,
   and implementation complexity.
4. Exact data structures to add or change, especially for checkpoint/resume and
   candidate identity.
5. Concrete experiment matrix with circuits, budgets, variants, and success
   metrics.
6. Telemetry columns to add.
7. Thesis wording: what this enhancement would let me claim and what it would
   still not let me claim.
8. Final verdict: what to implement first, what to postpone, and what to avoid.

Do not give generic advice. Tie every recommendation to SAT encoding, proof
tiers, candidate classification, CEX rejection/audit, checkpoint semantics,
final ABC CEC, or benchmark methodology.
```
