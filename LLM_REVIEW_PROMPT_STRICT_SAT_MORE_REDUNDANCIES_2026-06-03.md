# External LLM Review Prompt: Strict SAT Engine Next Step For More Redundancies

Use this with two or more external LLMs/reviewers. The goal is not to get more
generic encouragement. The goal is to identify the next SAT-engine patch that
can prove more stuck-at redundancies while preserving a strict audit boundary.

Recommended use:

1. Send **Prompt A** to one reviewer and ask for an implementation plan.
2. Send **Prompt B** to another reviewer and ask them to attack the soundness of
   the proposed plan.
3. Only implement a suggestion if it comes with clear proof obligations,
   encoding invariants, tests, and an experiment matrix.

Do not let reviewers redirect the thesis toward unsafe simulation acceptance,
MaxSAT, sequential reasoning, broad FRAIG, or a generic ABC optimizer.

## Project Snapshot

The thesis tool performs SAT-based single-gate stuck-at constant redundancy
removal on combinational AIG/AAG circuits.

Strict boundary:

- Circuit model: combinational AIG/AAG.
- Latches, if present, are treated only as combinational cut boundaries.
- Optimization action: greedily replace one internal AND gate by constant 0 or
  constant 1.
- A replacement may be committed only after a sound SAT proof tier returns
  `UNSAT`.
- `SAT` counterexamples, CEX replay, CEX pool, and pre-SAT simulation may only
  reject/non-detect a candidate when they produce a concrete observable
  output/latch-next mismatch.
- Timeout remains unresolved. Timeout is never nonredundant.
- Every reported optimized AAG must pass independent final ABC CEC.
- Do not claim optimality, full AIG optimization, sequential optimization, or
  superiority over ABC as a general optimizer.

Current Algorithm 10 proof tiers:

1. Persistent full-good-circuit TFI constancy SAT:
   - Encode the current phase good circuit once.
   - For SA0 at gate `g`, solve `GoodCNF AND g=1`.
   - For SA1 at gate `g`, solve `GoodCNF AND g=0`.
   - `UNSAT` proves functional constancy in the current phase.
   - Solver is phase-local and rebuilt after physical commit/rebuild.

2. Audited bounded TFO window miter:
   - Encode complete fanin cones of bounded fanout window roots.
   - Accept `UNSAT` only if a runtime audit proves the window roots form a
     complete observable cut from the candidate to all real output/latch-next
     roots.
   - `SAT`, timeout, skip, or audit failure escalates.

3. Exact affected-output cone miter:
   - Find all real output/latch-next roots affected by the candidate.
   - Encode the complete fanin cones for those roots.
   - Single-candidate hardcoded fault miter and grouped configurable-fault cone
     miter exist.
   - Grouped cone controls are audited with `ALG10_AUDIT_ASSUMPTIONS=1`.
   - `UNSAT` commits; `SAT` rejects; timeout escalates/remains unresolved.

4. Full global configurable-fault miter:
   - Good and faulty circuit copies share PI/latch-current variables.
   - Faulty copy has controls `f0_i` and `f1_i` for each AND gate.
   - Mutex: `not f0_i OR not f1_i`.
   - Faulty behavior: `(normal AND not f0_i) OR f1_i`.
   - Assumptions disable inactive controls, activate previously committed
     replacements, activate the current candidate, disable the opposite stuck
     value, and assert the output miter.
   - `UNSAT` commits; `SAT` rejects; timeout remains unresolved.

Existing rejection-only accelerators:

- CEX pruning/replay is rejection-only.
- CEX pool is rejection-only.
- Pre-SAT simulation rejection is rejection-only.
- These features may reduce SAT workload but must never accept a redundancy.

Important recent results:

- Latest best full-suite strict-audit report:
  `results_optimized/thesis_results_ALG10_alg10_strict_audit_resume_pool_presim_deep_current_real_suites_planted_2026-05-29_01-02-16.csv`
- CEC: 38/38 PASS.
- Total removed: 2222 gates.
- `voter`: 1434 removed, 22 unresolved, 99.91% coverage.
- `sin`: 41 removed, 26 unresolved, 99.76% coverage.
- `div`: 233 removed, 1732 unresolved, 98.48% coverage.
- `sqrt`: 50 removed, 9020 unresolved, 81.64% coverage.
- `log2`: 416 removed, 13154 unresolved, 79.22% coverage.
- `mem_ctrl`: 2 removed, 66177 unresolved, 29.35% coverage.

Pre-SAT rejection recheck on 2026-06-03:

- Keep pre-SAT rejection as a useful rejection-only accelerator, but do not make
  the next review about simulation.
- It helped important cases such as `div` and `sqrt`, but it did not
  universally dominate unresolved counts in short fixed budgets.
- I now want SAT-engine changes that can prove more redundancies, not just
  reject more nonredundant candidates.

## Prompt A: SAT Engine Improvement Proposal

```text
Act as a strict SAT/ATPG/AIG optimization researcher and thesis examiner. Do
not sugarcoat. I need the next SAT-engine patch that can find more formally
proved stuck-at redundancies, not merely detect/reject more nonredundant faults.

The current engine already has TFI constancy SAT, audited bounded TFO windows,
exact affected-output cone miters, grouped cone configurable-fault miters,
global configurable-fault miters, strict assumption audits, CEX audit, and final
ABC CEC. Pre-SAT simulation exists but is rejection-only and should not be your
main recommendation.

Main question:

What should I implement next to get more `UNSAT` redundancy proofs and more
gate removals while preserving the strict acceptance boundary?

Please focus on SAT-side improvements such as:

- stronger or better scheduled exact proof tiers;
- better candidate ordering that exposes redundancy earlier after commits;
- exact multi-phase/fixpoint scheduling after commits and strash;
- adaptive tier routing for candidates likely to be redundant;
- affected-output cone decomposition or output partitioning;
- grouped cone solver reuse within a phase;
- audited dominator/cut selection that is sound for `UNSAT` acceptance;
- incremental SAT and learned-clause reuse only within a sound unchanged
  context;
- UNSAT cores or failed assumptions if they can practically improve proof
  search/order;
- exact checkpointing of proof frontier and per-tier exhaustion;
- budget policies that avoid retrying known exhausted tier/budget pairs;
- proof obligations and telemetry that make the thesis defensible.

Questions to answer:

1. Where are additional redundancies most likely hiding under this stuck-at
   constant model: TFI constants, local observability don't-cares, output-cone
   ODCs, globally masked faults, or candidates revealed only after rebuilds?

2. What SAT proof tier should be added or changed to prove more UNSAT cases?
   Give exact encoding sketches and the soundness condition.

3. Can exact affected-output cone proofs be strengthened without becoming
   unsound?
   Consider root-set grouping, output partitioning, dominator cuts, complete
   cut audits, cone splitting, and incremental configurable-fault cone solvers.

4. Can audited windows be improved to prove more redundancies?
   Consider adaptive widening until the complete-cut audit passes, dominator
   cut roots, cached audit results, and avoiding incomplete cuts.

5. Can the algorithm get more removals by changing phase/fixpoint behavior?
   For example, after commits and cleanup/strash, regenerate candidates and run
   again to a strict fixpoint. What makes this sound, and when should the run
   stop?

6. How should candidate ordering prioritize possible UNSAT commits rather than
   only easy SAT rejections?
   Consider depth, fanout, affected output count, TFI cone size, window-cut
   success history, dominator structure, previous timeout history, and
   candidates near already accepted replacements.

7. Can UNSAT cores help in practice?
   Evaluate whether failed assumptions can shrink accepted-control assumption
   vectors, identify irrelevant observable roots, improve ordering, or reduce
   exact cone size. Be realistic about solver/API limitations.

8. How should exact checkpoint/resume be redesigned so deep runs continue
   progress and do not simply resweep from the safe AAG?
   Specify candidate IDs, phase hashes, tier histories, exhausted budgets,
   accepted/rejected/unresolved states, and invalidation rules after rebuilds.

9. What is the single best patch implementable in 2-4 days?
   Provide:
   - data structures;
   - functions to add/change;
   - checkpoint JSON schema;
   - CSV telemetry;
   - tests;
   - expected impact on `sin`, `voter`, `div`, `sqrt`, `log2`, and `mem_ctrl`.

10. What should be avoided because it is risky, unsound, or thesis drift?

Required answer format:

1. Correctness invariants that must not change.
2. Diagnosis of where the current engine misses additional redundancies.
3. Ranked SAT-engine changes for more `UNSAT` proofs and more removals.
4. For each change: soundness classification, false-UNSAT risks, expected
   removal impact, implementation complexity, and tests.
5. One concrete 2-4 day patch plan.
6. Experiment matrix and success criteria.
7. Thesis-safe wording for the contribution.
```

## Prompt B: Adversarial Soundness And Audit Review

```text
Act as an adversarial SAT encoding and formal-verification reviewer. Your job
is to find ways a proposed SAT-engine improvement could accidentally accept a
wrong stuck-at replacement. Do not be polite. Assume I cannot tolerate a false
UNSAT commit, fault masking bug, stale CNF context, missing assumption, free
fault control, or invalid local proof.

The optimization model:

- Current circuit is combinational AIG/AAG.
- A candidate is `(gate, stuck_value)`.
- Accepted replacements are part of the current committed context.
- A new candidate may be committed only when a sound SAT tier proves no real
  output/latch-next root can distinguish the current committed-good circuit
  from the current committed-plus-candidate faulty circuit.
- Final ABC CEC is mandatory, but final CEC cannot detect missed redundancies
  caused by false pruning. It only detects wrong commits.

Known false-UNSAT risk classes:

- fault controls left free in configurable-fault miter;
- opposite stuck control not disabled;
- accepted controls encoded incorrectly;
- candidate not actually present in the cone/control set;
- miter literal missing or not asserted;
- comparing incomplete observable roots;
- local window roots not forming a complete observable cut;
- reusing learned clauses after committed circuit semantics changed;
- stale gate IDs after strash/rebuild;
- cone root set computed from stale fanout;
- treating timeout, repeated timeout, simulation no-detect, or local SAT as a
  proof;
- fault masking by simultaneously activating more controls than the committed
  context plus current candidate;
- ABC CEC used as a substitute for proving pruning quality.

Please review any proposed next patch under these questions:

1. What exact theorem does the proposed proof tier rely on?
   State the formula that must be `UNSAT` and why that implies safe
   replacement in the current committed context.

2. Does the proposal compare all real observable roots affected by the
   candidate?
   If not, what audit proves the chosen roots form a complete cut?

3. Could fault masking occur because accepted controls and current candidate
   controls interact?
   Which assumptions must be present exactly?

4. What must be rebuilt after each commit, cleanup, strash, or phase change?
   Which solver clauses may be reused, and which reuse would be unsound?

5. Are candidate IDs stable enough?
   If not, what phase hash, AAG hash, gate structural fingerprint, or
   invalidation rule is required?

6. How should assumption vectors be audited?
   Give exact count checks, duplicate/contradiction checks, inactive-control
   checks, accepted-control checks, current-candidate checks, opposite-control
   checks, and miter assertion checks.

7. What negative tests should deliberately break the implementation and fail?
   Include missing miter literal, free inactive control, flipped accepted
   control, incomplete output roots, stale checkpoint, stale candidate ID,
   corrupt output, and timeout misclassification.

8. What bounded exhaustive test should be run?
   Specify max inputs/gates/depth and compare SAT-tier claims against brute
   force truth tables.

9. What final integration tests should be required before thesis use?
   Include c17/c432/c7552, planted-live cases, hard EPFL smoke cases, CEX audit,
   final ABC CEC, checkpoint/resume, and `git diff --check`.

10. Which proposed ideas should be rejected as unsound or too risky?

Required answer format:

1. Soundness invariants.
2. Main false-UNSAT/fault-masking risks.
3. Required assumption audits.
4. Required rebuild/invalidation rules.
5. Required negative tests and bounded exhaustive tests.
6. Verdict: safe, conditionally safe, or unsafe.
```

