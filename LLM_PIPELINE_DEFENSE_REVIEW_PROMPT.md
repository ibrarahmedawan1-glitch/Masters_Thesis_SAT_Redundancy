# External Review Prompt: Pipeline Defense And Validation Evidence

Act as a senior EDA researcher, formal verification engineer, and thesis examiner
with experience in SAT-based ATPG, AIG rewriting, CDCL SAT solvers, and
combinational equivalence checking. I want a critical professional assessment of
the following master's thesis tool and validation evidence. Please do not give
generic encouragement. Evaluate whether the architecture is defensible, whether
the correctness argument is stated properly, and what remaining risks a professor
or reviewer is most likely to challenge.

## Thesis Tool Under Review

The tool is a SAT-based redundancy-removal engine for combinational AIG/AAG
circuits. It searches for semantically redundant stuck-at faults on AND gates.
For each candidate gate, both stuck-at-0 and stuck-at-1 replacements can be
tested. A candidate is accepted only when the corresponding SAT miter proves
that no assignment can distinguish the good circuit from the faulty circuit at
any observable root. A SAT result is interpreted as an observable
counterexample, so the candidate is rejected. A timeout is not accepted; it
remains unresolved and can be retried at a larger conflict budget. Simulation,
random-pattern filtering, and counterexample-guided filtering are rejection-only
mechanisms and never prove redundancy.

The circuit model is AIG/AAG. Primary outputs are observable roots. If latch
support is present, latch-next functions are treated as observable cut
boundaries. The intended proof obligation is therefore not structural
equivalence of local cones, but functional indistinguishability at all real
observable roots under the chosen combinational/cut-boundary model.

## Current Architecture

The implementation evolved from full per-candidate miters into an audited,
checkpointed, parallel exact-TFO pipeline. The current proof tiers include
transitive-fanin constancy checks, audited bounded TFO windows, exact
affected-output cone miters, grouped cone miters, global configurable-fault
miters, and exact candidate-local TFO miters. The exact TFO miter computes the
candidate's transitive fanout and then derives the affected observable root set.
It builds the good fanin cone for those roots, duplicates only the faulty
candidate-local TFO slice, and reuses good-circuit values for side inputs
outside the faulty slice. This side-input reuse is intended to be safe only
because the faulty slice is audited for closure and the affected roots are
audited for completeness.

The parallel engine treats worker UNSAT as a proposal rather than as a direct
commit. Workers classify candidates on immutable work-AAG snapshots. If a
worker proposes UNSAT, the dynamic scheduler stops dispatching fresh work for
that circuit generation, waits for the generation barrier, and passes the
proposal to a single coordinator. The coordinator sequentially rechecks the
proposal against the current circuit state, applies at most the accepted rewrite,
regenerates the frontier after any commit, and requires ABC CEC before saving a
new optimized AAG. Stale worker results are rejected by generation and snapshot
hash checks. Checkpoints store source/work hashes and enough frontier state to
resume timeout candidates at the next budget tier instead of restarting blindly.

The intended thesis claim is deliberately limited. SAT proves candidate
redundancy under the encoded observable-root boundary. Bounded exhaustive tests,
full-miter/TFO agreement tests, closure-audit tests, and negative controls
validate the encoding implementation. ABC CEC is an independent transaction-time
audit of every reported optimized AAG. CEC is not being claimed as the proof of
each SAT result, and it is not a substitute for a correct encoding. If every
implementation layer is correct, a no-CEC proof-only mode should still produce
equivalent outputs; the production pipeline keeps CEC because it is standard
defense-in-depth for a research optimizer that physically rewrites circuits.

## Validation Already Performed

The latest full professor-facing validation run was:

```bash
VALIDATION_STEP_TIMEOUT_SECONDS=7200 \
  ./run_professor_encoding_validation.sh full \
  results_optimized/professor_encoding_validation_full_20260622
```

The run completed successfully. The logged results include:

1. `test_professor_encoding_controls.py`: PASS. This focused test covers the
   high-value remaining soundness questions: committed-side-input behavior after
   an earlier accepted replacement, explicit two-latch observable boundary
   handling, TFO worker plus global/full-miter coordinator recheck, false-worker
   UNSAT injection rejected by the coordinator, and a long reconvergent TFO path.

2. `test_alg10_tfo_miter.py`: PASS. This validates exact TFO closure and
   end-to-end candidate-local TFO behavior against expected semantics, including
   cases where an under-approximated slice would be dangerous.

3. `test_alg10_frontier_shard_probe.py`: PASS. This checks the exact-TFO worker
   classification path used in parallel campaigns.

4. `test_alg10_parallel_commit_coordinator.py`: PASS. This checks the sequential
   recheck and CEC-gated transaction boundary used after worker proposals.

5. `test_encoding_soundness_bounded.py --max-inputs 2 --max-gates 2
   --include-depth3`: PASS. The depth-3 bounded exhaustive sweep covered
   536,376 candidate checks over 92,628 small circuits. The tested encodings
   include global, TFI, persistent TFI, cone, grouped cone, exact TFO cone,
   audited window, and rewrite paths.

6. `thesis_correctness_stress.py`: PASS. The stress run produced 36/36 passing
   rows and 0 required failures. It included small-circuit round trips,
   algorithm output checks, c17/c432/c7552 cases, selected EPFL probes, capped
   audit runs, resume/continuous runs, full-audited generated cases, and a
   negative corrupt-output control. The corrupt-output control passed because
   both ABC CEC and the internal SAT miter detected the injected mismatch.

Additional repository/test evidence includes:

1. Modern dynamic/native TFO summaries scanned during thesis preparation showed
   CEC-passed commits and no CEC-failed commits in the modern audited pipeline.
   The writing guide records 252 CEC-passed commits and 0 CEC-failed commits
   for the relevant modern dynamic/native TFO summaries.

2. Earlier algorithms were also tested on small benchmarks to establish
   regression safety. Algorithms 1-9 produced ABC CEC PASS on `c17`, and
   Algorithms 8-9 produced ABC CEC PASS on `c432`.

3. The ABC-baseline comparison pipeline was deliberately separated from the
   native-tool correctness claim. ABC outputs are first checked by direct ABC
   CEC, and only CEC-passed ABC outputs are used for residual exact-TFO
   experiments. This avoids counting invalid ABC outputs as fair comparison
   points.

4. Long benchmark campaigns are still performance-limited by hard SAT frontiers.
   The tool does not claim to classify every large EPFL arithmetic circuit to
   zero unresolved within a fixed time. The current contribution is a sound,
   checkpointed, SAT-based ATPG redundancy-removal pipeline with practical
   scheduling and audit mechanisms, not a universal replacement for industrial
   resynthesis.

## Professional Review Questions

Please assess the architecture as if you were reviewing the thesis before a
defense.

1. Is the UNSAT acceptance condition sound under the stated observable-root
   boundary, assuming the affected observable roots are complete?

2. Is the side-input reuse rule in the exact TFO miter sound when the faulty
   TFO slice is closed and all affected roots are included? If not, describe a
   concrete counterexample circuit.

3. Are the TFO closure audit and affected-root completeness audit the right
   implementation invariants? What exact cases remain most dangerous:
   reconvergence, complemented literals, constants, multi-output fanout,
   latch-next roots, stale frontiers, or something else?

4. Does the worker-proposal design plus coordinator recheck plus CEC-gated
   commit close the main parallel-staleness risks? Are there remaining batch
   interaction risks after frontier regeneration?

5. Is the validation evidence strong enough for a master's thesis defense? If
   not, what is the smallest high-value test that should still be added before
   writing, given limited time?

6. How should I answer a professor who asks: "If the encoding is correct, why
   do you need final ABC CEC? Would the tool produce faulty output without CEC?"
   Please provide a precise defense that does not overclaim.

7. Does the thesis claim sound properly scoped if phrased as:
   "a formally audited, checkpointed SAT proof framework for exact stuck-at
   redundancy removal in AIG/AAG circuits, with independent CEC verification of
   each committed rewrite"?

8. What should be emphasized as the main contribution: the exact TFO encoding,
   the transactional parallel coordinator, the checkpoint/budget ladder, the
   validation methodology, or the empirical finding that semantic redundancies
   remain after structural/ABC flows?

9. Which evidence belongs in the main evaluation chapter, and which belongs in
   an engineering-validation appendix?

10. Please list any remaining thesis-defense risks in severity order. For each
    risk, give one concrete mitigation or one sentence I can use to state the
    limitation honestly.

Please be strict. If you think a claim is too strong, rewrite it into a
defensible claim. If you think a test is missing, specify the exact circuit
shape and expected outcome rather than giving general advice.
