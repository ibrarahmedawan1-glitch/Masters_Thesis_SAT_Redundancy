# Professor Meeting Summary, 2026-06-23

## Completed DCH Wave-2 Post-ABC Residual Run

The second DCH residual wave was run on the CEC-passed ABC `dch` outputs for
five circuits that were not covered by the earlier interrupted phase-1 run:
`square`, `sin`, `div`, `bar`, and `i2c`.

Command wrapper:

```bash
./run_dch_wave2_until_0900.sh results_optimized/dch_focused_wave2_until_0900_20260623
```

Configuration:

- Flow: ABC `dch` output, filtered through direct ABC CEC before use.
- Native pass: exact TFO residual SAT redundancy removal.
- Workers: 12, with memory oversubscription enabled.
- Solver: `cadical153`.
- Budgets: `10000,50000`.
- Worker cache entries: 2.
- Persistent retry tiers: 2.
- Runtime: 21,593.84 s, approximately 5 h 59 min.
- Worker utilization: 0.811.

Aggregate result:

| Metric | Value |
|---|---:|
| Circuits | 5 |
| Starting gates | 77,551 |
| Final gates | 56,895 |
| Residual gates removed | 20,656 |
| Candidate results | 286,643 |
| SAT rejects | 267,661 |
| UNSAT proposals | 42 |
| Timeouts | 18,940 |
| CEC-pass commits | 19 |
| Worker errors | 0 |
| Remaining obligations | 17,452 |

Per-circuit result:

| Circuit | Start | Final | Removed | Remaining | Status | CEC commits |
|---|---:|---:|---:|---:|---|---:|
| `epfl_arithmetic_bar` | 4,934 | 2,952 | 1,982 | 0 | complete | 1 |
| `epfl_arithmetic_div` | 34,913 | 31,200 | 3,713 | 17,207 | time budget checkpoint | 4 |
| `epfl_arithmetic_sin` | 8,920 | 5,009 | 3,911 | 245 | budget cap reached | 7 |
| `epfl_arithmetic_square` | 26,121 | 16,642 | 9,479 | 0 | complete | 6 |
| `epfl_random_control_i2c` | 2,663 | 1,092 | 1,571 | 0 | complete | 1 |

This run is useful for the thesis because it shows that the native SAT-based
engine can still remove substantial residual semantic redundancy after an ABC
output that has already passed direct CEC. The `dch` baseline must be discussed
carefully: in the whole-suite ABC baseline table, `dch` increases total area on
the selected benchmark set, so this is not a clean area-winning comparison
against ABC. It is instead a strong recovery and residual-redundancy case: the
ABC output is functionally valid, but the SAT ATPG pass identifies many
unobservable stuck-at replacements that remain in that valid netlist.

## Correctness Position

The run should be reported only as CEC-checked optimization evidence. The native
SAT miter proves individual candidate redundancy under the encoded observable
root boundary. ABC CEC is used as an independent transaction-time audit of the
physically rewritten AAG output. This distinction is important in the defense:
CEC is not the proof mechanism for a SAT result, but it validates every saved
artifact that is counted in the results.

The key defense sentence is:

> SAT establishes candidate redundancy under the exact encoded observable-root
> boundary; bounded exhaustive tests, full-miter/TFO agreement tests, closure
> audits, and negative controls validate the encoding implementation; ABC CEC
> independently verifies every committed output circuit.

## Chapter 1 Introduction Plan

Chapter 1 should begin from the engineering problem rather than from the tool.
Modern AIG optimization relies heavily on structural rewriting, hashing, and
resynthesis. These methods are fast and effective, but structural reducibility
does not fully capture semantic observability. A gate can remain structurally
present even though forcing it to a constant cannot affect any primary output or
observable cut boundary.

The motivation should then introduce stuck-at redundancy as a precise way to
phrase the problem. For each candidate AND gate, the tool asks whether replacing
the gate by stuck-at-0 or stuck-at-1 is observable at any real output. A SAT
result is a counterexample and rejects the candidate. An UNSAT result proves
that the replacement is unobservable under the encoded boundary. A timeout is
not accepted and remains unresolved.

The research gap is the space between fast synthesis and auditable exact
classification. ABC-style flows optimize aggressively, but they do not provide a
candidate-by-candidate ATPG proof log with SAT, UNSAT, timeout, checkpoint,
resume, and transactional commit accounting. A research ATPG optimizer must
also address implementation hazards that are not visible in the mathematical
miter alone: incomplete TFO slices, missing observable roots, stale parallel
worker results, checkpoint mismatch, and unsafe batch commits.

The contributions should be stated as:

1. An exact candidate-local TFO miter with closure and affected-root audits.
2. Rejection-only simulation and SAT counterexample filtering.
3. A transactional parallel coordinator that treats worker UNSAT as proposals,
   sequentially rechecks before commit, regenerates the frontier after each
   rewrite, and requires final CEC before saving an output.
4. Checkpointed budget laddering with explicit unresolved accounting.
5. A validation suite covering bounded exhaustive checks, professor-facing
   controls, full-miter/TFO agreement, negative corruption controls, checkpoint
   resume, and CEC-gated artifact validation.
6. An empirical study on ISCAS/EPFL and ABC residual outputs showing both useful
   semantic removals and the hard SAT frontier on large arithmetic circuits.

The scope should be honest. The thesis should not claim to replace ABC or to
classify every large EPFL arithmetic circuit to zero within a fixed time. The
defensible claim is a formally audited, checkpointed SAT proof framework for
exact stuck-at redundancy removal in AIG/AAG circuits, with independent CEC
verification for every reported optimized output.
