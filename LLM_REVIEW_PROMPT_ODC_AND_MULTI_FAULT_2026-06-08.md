# External LLM Review Prompt: Exact ODC And Multi-Fault Stuck-At Extensions

Use this prompt with external LLMs/reviewers before changing Algorithm 10.
The goal is to decide whether adding a stronger don't-care/ODC proof path and
then multi-fault stuck-at injection is a sound and useful next step.

Do not ask for generic encouragement. Ask reviewers to attack soundness,
encoding, implementation complexity, and thesis value.

## Current Thesis Boundary

The project optimizes combinational AIG/AAG circuits by SAT-proving stuck-at
constant redundancies.

Current safe boundary:

- Circuits are combinational AIG/AAG.
- Latches, if present, are treated only as combinational cut boundaries.
- A committed change replaces an internal AND gate by constant 0 or constant 1.
- A replacement may be committed only after a sound SAT proof tier returns
  `UNSAT`.
- `SAT` means there is an observable counterexample, so the candidate is
  rejected or delayed.
- Timeout means unresolved, never accepted.
- CEX pool, CEX replay, and pre-SAT simulation are rejection-only.
- Final independent ABC CEC is mandatory for every reported output.
- We cannot tolerate false-UNSAT acceptance, free fault controls, stale CNF,
  missing observable roots, bad assumptions, or checkpoint invalidation bugs.

Current Algorithm 10 proof tiers:

1. Persistent TFI constancy SAT:
   - For SA0 on gate `g`, solve `GoodCNF AND g=1`.
   - For SA1 on gate `g`, solve `GoodCNF AND g=0`.
   - `UNSAT` proves functional constancy.

2. Audited bounded TFO window:
   - Uses local roots only if runtime audit proves the roots form a complete
     observable cut.
   - `UNSAT` commits; otherwise escalate.

3. Exact affected-output cone miter:
   - Finds all output/latch-next roots affected by the candidate.
   - Encodes complete fanin cones for those roots.
   - Single-candidate and grouped configurable-fault cone solvers exist.
   - Grouped assumptions are audited when `ALG10_AUDIT_ASSUMPTIONS=1`.

4. Full global configurable-fault miter:
   - Good and faulty copies share PI/latch-current variables.
   - Faulty copy has controls `f0_i` and `f1_i` for each AND gate.
   - Mutex: `not f0_i OR not f1_i`.
   - Faulty gate behavior is `(normal AND not f0_i) OR f1_i`.
   - Assumptions disable inactive controls, activate accepted replacements,
     activate the current candidate, disable the opposite stuck value, and
     assert the output miter.
   - `UNSAT` commits; `SAT` rejects; timeout remains unresolved.

Important note about "don't care":

- There is no external input don't-care specification in the current thesis
  flow. Every primary-input assignment is a care case.
- Therefore "don't-care optimization" must mean **internal observability
  don't-care** only: a candidate may change an internal gate value, but the
  changed value is unobservable at all real outputs/latch-next roots.
- Any external care-set or constrained-equivalence idea would change the thesis
  problem and would not pass ordinary ABC CEC unless ABC is also given the same
  care constraints. Treat that as out of scope unless explicitly justified.

## Latest Evidence

Latest Alg10 full run:

- CSV:
  `results_optimized/thesis_results_ALG10_alg10_strict_audit_resume_pool_presim_deep_current_real_suites_planted_2026-06-08_20-39-34.csv`
- 38/38 final ABC CEC `PASS`.
- Total removed: 2224 gates.
- New removals in latest run: 2.
- Remaining unresolved: 73872.
- One new `UNSAT` acceptance was found in `mem_ctrl`.

Current hard unresolved frontier:

- `mem_ctrl`: 45385 unresolved, 4 removed.
- `sqrt`: 9020 unresolved, 50 removed.
- `hyp`: 8504 unresolved, 4 removed.
- `log2`: 5531 unresolved, 416 removed.
- `arbiter`: 3993 unresolved, 0 removed.
- `div`: 1391 unresolved, 233 removed.
- `sin`: 26 unresolved, 41 removed.
- `voter`: 22 unresolved, 1434 removed.

ABC baseline comparison:

- ABC-only flows were run on the same 38 circuits:
  `strash`, `dc2`, `dch`, `fraig`, `resyn2`, `resyn2x2`.
- Best ABC flow per circuit removed 56791 total gates.
- Alg10 removed 2224 total gates.
- ABC is much stronger for raw area because it performs broad resynthesis.
- Alg10's thesis contribution is narrower: strict SAT proof architecture for
  stuck-at constant redundancy, with unresolved/proof telemetry.

## Proposed Ideas To Review

### Idea 1: Stronger exact ODC/don't-care proof path

Clarify first whether this is already covered by the existing single-fault
global miter. The current global miter should already prove a single candidate
redundant when its changed value is internally unobservable at all outputs.

Possible additions reviewers should evaluate:

- Better exact affected-output root computation, so the cone tier proves more
  ODC cases before falling to global SAT.
- Adaptive exact output partitioning: prove candidate unobservable on all
  affected roots by partitioned miters, while preserving a complete-root audit.
- Larger or smarter audited windows that are still complete cuts.
- Candidate generation using simulation or structural ODC hints, but only as a
  scheduling/filtering hint. Acceptance still requires exact `UNSAT`.
- Explicit ODC telemetry separating:
  - functional constants proved by TFI;
  - single-fault ODC proofs from exact cone/window/global miter;
  - SAT observable counterexamples;
  - timeouts/unresolved.

Questions:

1. Is there any sound "don't-care injection" we can add without changing the
   external equivalence problem?
2. Does the current global configurable-fault miter already cover all
   single-gate internal ODC stuck-at redundancies, assuming enough SAT budget?
3. If yes, is the useful patch not a new proof semantics, but better
   scheduling, exact affected-root decomposition, or stronger local proof tiers?
4. What exact encoding would prove an internal ODC redundancy that current
   tiers miss due to timeout?
5. What runtime audit proves that a local ODC/window proof did not omit an
   affected output/latch-next root?

### Idea 2: Multi-fault / pair stuck-at injection

Test whether two stuck-at replacements can be accepted together even if one or
both replacements are not individually redundant.

Candidate example:

- Pair candidate: `(g1 = stuck_value_1, g2 = stuck_value_2)`.
- Solve a good-vs-faulty miter with both fault controls active at once.
- Previously accepted replacements also remain active.
- Assert the output miter.
- If `UNSAT`, commit both replacements atomically.
- If `SAT`, reject the pair or use the CEX to prune similar pairs.
- If timeout, keep unresolved.

Important safety question:

- Pair `UNSAT` can be sound even when each member is individually SAT, but only
  if the rewrite applies both replacements atomically and every later proof
  includes both accepted controls in the committed context.

Concerns:

- Candidate space grows from `2A` to roughly `4 * A * (A-1) / 2`.
- Pair acceptance can interact badly with current candidate IDs, checkpoints,
  accepted maps, rebuilds, and assumption audits.
- TFI constancy does not naturally prove a pair replacement. The first safe
  implementation may need to skip TFI/window and use only exact cone/global
  configurable-fault miters.
- Physical rewriting must support multiple accepted replacements in one commit
  and must reject pairs that target the same gate with contradictory values.
- Assumption audits must verify exactly two active new candidate controls, all
  accepted controls active, all inactive controls disabled, opposite controls
  disabled, and the miter literal asserted.

Questions:

1. Is pair stuck-at injection a sound extension of the current SAT model?
2. Should pair acceptance be implemented first only in the global miter, or can
   exact cone/grouped-cone support it safely?
3. What candidate-pair filters keep the search finite without missing the most
   likely useful pairs?
   Consider:
   - same affected output root set;
   - nearby TFO/TFI relation;
   - pairs where each single fault has related CEX patterns;
   - pairs near already accepted replacements;
   - small/medium circuits first;
   - top-k unresolved candidates per hard circuit.
4. What telemetry should distinguish:
   - individually redundant single faults;
   - pair-only redundancies;
   - pair SAT rejections;
   - pair timeouts;
   - pair candidates skipped by filters?
5. What checkpoint schema is needed for pair candidates?
   Include stable IDs, source/work AAG hash, accepted context hash, candidate
   pair list, max budget tried, and invalidation after rebuild.
6. What tests would catch false-UNSAT pair acceptance?
   Include bounded exhaustive brute-force checks where two faults together are:
   - both individually redundant;
   - one individually redundant and one not;
   - both individually nonredundant but jointly equivalent;
   - jointly non-equivalent;
   - same gate/opposite stuck values, which must be rejected.

## Required Reviewer Answer

Please answer in this exact structure:

1. **Do Not Break Invariants**
   - List the invariants that must remain true for every SAT call and every
     committed rewrite.

2. **Don't-Care/ODC Assessment**
   - Is "don't-care injection" a new sound proof capability, or is it already
     covered by the current global miter?
   - If it is new, give the exact encoding and proof obligation.
   - If it is not new, explain what scheduling/local-proof improvement is
     worth implementing instead.

3. **Multi-Fault Assessment**
   - Is pair stuck-at injection sound?
   - Is it thesis-useful or too expensive/noisy?
   - Should it start as global-only, cone-only, or an ablation script outside
     `main.py`?

4. **Encoding Plan**
   - Assumption vector layout.
   - Control-literal mutexes.
   - Accepted-control handling.
   - Candidate-control handling for pairs.
   - Miter assertion.
   - Audit checks.
   - Solver/rebuild/checkpoint invalidation rules.

5. **Implementation Plan**
   - Specific functions likely to change in `optimizer_alg10_tiered.py`.
   - Whether to add a separate experiment script first.
   - Environment flags.
   - CSV telemetry.
   - Checkpoint schema.

6. **Tests**
   - Unit tests.
   - Bounded exhaustive truth-table tests.
   - Negative tests that deliberately corrupt assumptions.
   - End-to-end smoke circuits.
   - ABC CEC validation.

7. **Experiment Matrix**
   - Which circuits to test first.
   - Expected runtime.
   - What result would justify promotion into the main engine.

8. **Stop Conditions**
   - When to abandon the idea as too expensive or not thesis-useful.

9. **Thesis-Safe Wording**
   - How to describe this without claiming general ABC-style resynthesis.

## My Preferred Conservative Path, To Critique

Before touching the main engine:

1. Add an experiment-only script for pair stuck-at candidates on small/medium
   circuits and selected hard frontiers.
2. Use the existing global configurable-fault encoding, extended only at the
   assumption layer to activate two candidate controls at once.
3. Add an aggressive production audit for the pair assumption vector.
4. Commit pair replacements atomically only after global `UNSAT`.
5. Verify every output with ABC CEC.
6. Add bounded exhaustive tests comparing the pair-miter result to brute-force
   truth tables before running thesis benchmarks.
7. If pair-only UNSAT acceptances are rare or too expensive, do not promote it
   to `main.py`.

Ask reviewers whether this path is sound, too conservative, or missing the
highest-value ODC/multi-fault opportunity.
