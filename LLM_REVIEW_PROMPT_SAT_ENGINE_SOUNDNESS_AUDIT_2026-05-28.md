# External Review Prompt: Alg10 SAT Engine Soundness Audit, 2026-05-28

We are finishing a thesis tool for SAT-based stuck-at constant redundancy removal on AIG/AAG circuits. Please review only the SAT engine, encoding soundness, and next SAT-side development steps. Do not recommend non-SAT rewriting, unsafe simulation acceptance, timeout-as-rejection, MaxSAT pivots, or broad optimizer redesigns.

## Correctness Boundary

- A gate replacement is committed only after an UNSAT SAT proof in a sound tier.
- CEX, pre-simulation, and CEX-pool replay are rejection-only. They may reject/delay candidates with a concrete observable mismatch, but must never accept redundancy.
- Final optimized AAGs must pass independent ABC CEC.
- We cannot tolerate false UNSAT acceptance. Even a tiny bug in assumptions, stale CNF context, or control-literal handling is unacceptable.

## Current Alg10 SAT Tiers

1. Persistent full-good-circuit TFI constancy solver:
   - Encode current phase good circuit once.
   - For SA0 candidate at gate `g`, solve `GoodCNF AND g=1`.
   - For SA1 candidate, solve `GoodCNF AND g=0`.
   - UNSAT proves functional constancy in the current phase.
   - Solver is phase-local; after physical commit/strash/rebuild, a fresh phase rebuilds SAT CNF.

2. Audited bounded TFO window:
   - Local window miter may accept only if the observable-cut audit passes.
   - UNSAT-only acceptance.

3. Exact affected-root cone miter:
   - Single-candidate hardcoded fault miter remains available.
   - New grouped configurable-fault cone miter groups candidates by identical affected observable root set within one phase.
   - Grouped solver has per-gate `f0_i/f1_i` controls inside the exact cone.
   - For each query, all inactive controls must be disabled, current candidate alone activated, accepted controls activated, and miter asserted.
   - Group solvers are local to `_run_cone_miter_tier` and deleted at tier exit.

4. Global configurable-fault miter:
   - Increasing conflict budgets.
   - Phase-local global unresolved queue and per-candidate max-budget tried are persisted only when the checkpoint work AAG hash and gate count match.

## New Safety Patch To Review

Production code now includes `_audit_cone_group_assumptions(assumptions, state, candidate, accepted=None)`.

The grouped cone audit checks:

- exact assumption count `2 * len(state.controls) + 1`;
- no duplicate assumption literal;
- no contradictory pair `lit` and `-lit`;
- candidate is present in the grouped control set;
- every inactive gate has `[-f0_i, -f1_i]`;
- current SA0 candidate has `[f0_i, -f1_i]`;
- current SA1 candidate has `[-f0_i, f1_i]`;
- accepted SA0 controls have `[f0_i, -f1_i]`;
- accepted SA1 controls have `[-f0_i, f1_i]`;
- final assumption is the grouped miter literal;
- the full ordered assumption vector exactly matches the expected vector.

The audit is called in the production grouped-cone solve path whenever `ALG10_AUDIT_ASSUMPTIONS=1`.

## Tests Run And Passed

1. Focused grouped-cone audit test:
   - `test_alg10_grouped_cone_audit.py`
   - Valid vector passes.
   - Deliberately missing control fails.
   - Deliberately flipped inactive control fails.
   - Deliberately activated opposite candidate fault fails.
   - Deliberately tampered accepted control fails.
   - Full c432 grouped-cone tier runs with production audit enabled.

2. Bounded exhaustive encoding checker extended:
   - `test_encoding_soundness_bounded.py`
   - Now checks global miter, old local TFI, persistent TFI, single exact cone, grouped exact cone, audited window UNSAT, and rewrite semantics against brute-force truth tables.
   - `--max-inputs 3 --max-gates 2`: PASS on 133,176 candidate checks.
   - `--max-inputs 2 --max-gates 2 --include-depth3`: PASS on 536,376 candidate checks.

3. Pipeline/resume safety:
   - `test_alg10_checkpoint.py`: PASS.
   - `test_alg10_resume_pool.py`: PASS.
   - `test_alg10_hybrid_safety.py`: PASS.
   - Includes safe checkpoint resume, stale phase-state fallback, repeated equal-budget skip, CEX-pool rejection-only replay, and c432 full pipeline with `ALG10_CONE_ENGINE=grouped`, `ALG10_AUDIT_ASSUMPTIONS=1`, final CEC PASS.

4. Broad smoke regression:
   - `test_algorithms_1_to_10.py`: PASS.
   - `git diff --check`: PASS.

## Current Questions

1. Is the grouped-cone assumption audit sufficient to rule out free inactive fault controls, wrong accepted controls, and candidate/opposite-control leakage?
2. Are there any remaining false-UNSAT risks in the grouped configurable cone encoding, given that solvers are phase-local and deleted at tier exit?
3. Is persistent full-good-circuit TFI sound under the stated phase-local rebuild model?
4. What extra bounded or adversarial test would you add before trusting this in thesis experiments?
5. For the next SAT-engine speed step, should we implement full exact unresolved queue persistence across all tiers, or first strengthen the existing global phase-local queue with better scheduling and telemetry?
6. If the goal is to find more stuck-at redundancies before June 5, which SAT-only change has the highest return without changing the acceptance boundary?

Please classify each risk as Sound / Conditionally Sound / Unsound, and give concrete tests or code-level invariants rather than broad ideas.
