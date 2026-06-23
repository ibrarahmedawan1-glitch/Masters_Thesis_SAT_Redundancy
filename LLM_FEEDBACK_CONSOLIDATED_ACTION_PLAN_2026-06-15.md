# Consolidated Feedback Audit And Thesis Action Plan

Date: 2026-06-15

## Direct Verdict

The project is thesis worthy after a focused correctness freeze and a
controlled experimental evaluation.

The four reviews agree on the correct overall positioning:

- the strongest contribution is the exact, checkpointed, generation-safe
  parallel proof framework;
- the work does not yet support claims of practical superiority over ABC;
- the current evidence demonstrates feasibility and verified discoveries, not
  broad performance dominance;
- deadline control, baselines, repetitions, and scheduler ablations are the
  main missing pieces.

No reviewed feedback established a confirmed soundness bug in the current
candidate-local TFO production path. Several reviews labeled hypotheses as
confirmed without checking the implementation.

## Claim-By-Claim Resolution

### TFO side-input reuse

Verdict: sound for an exact AIG DAG TFO, with stronger validation added.

If a side-input gate depends on the target, there is a directed path from the
target to that gate. Complete forward closure therefore places that gate in the
faulty slice. A gate outside the closure cannot be changed by the injected
fault, so sharing its exact good value is valid. A path cannot leave and later
re-enter the target's transitive fanout in a DAG.

The existing implementation:

- normalizes literals with `lit & ~1`;
- computes every affected observable root;
- builds the complete good fanin cone;
- builds the faulty copy over target-reachable gates in that cone;
- retains literal polarity when reading both good and faulty values.

The audit previously recomputed the slice using the same forward traversal.
That was a validation weakness, not evidence of an encoding bug. It now also
derives target dependence independently from gate fanins and rejects a slice
that omits any dependent gate.

### Complemented fanout

Verdict: the alleged bug is absent.

`_fanout_graph(...)` indexes both gate definitions and fanins by base literal
using `& ~1`. Positive and complemented uses therefore create the same
structural fanout edge. A dedicated complemented-only fanout test now passes.

### Reconvergence

Verdict: the alleged failure scenario is structurally impossible for a
complete transitive fanout closure.

New tests cover both cases:

- a truly independent side input remains outside the faulty slice and safely
  reuses its good value;
- a reconvergent side input that depends on the target is included in the
  faulty slice.

Both SA0 and SA1 SAT results are compared with direct truth-table semantics.

### Sequential multi-proposal commits

Verdict: sound as implemented.

The coordinator:

1. starts from the current work AAG;
2. rechecks proposal A exactly;
3. replaces A in `working_gates` only after UNSAT;
4. rebuilds the graph and exact miter for proposal B against that modified
   generation;
5. repeats for later proposals;
6. applies the same accepted substitutions to the work AAG;
7. requires ABC CEC against the original source before committing.

This proves a chain `C0 == C1 == ... == Cn`; equivalence transitivity proves
the final batch. A separate combined miter or pairwise compatibility test is
not required for soundness. It could be added as diagnostic redundancy, but
intermediate CEC after every proposal would add substantial cost without
strengthening the mathematical argument.

### Verified-output restart and checkpoint mixing

Verdict: the alleged generation-mixing bug is absent.

A CEC-verified output seed is serialized with `phase_resume: null`. The next
campaign copies that exact work AAG and regenerates a full frontier with empty
conflict history. It does not attach an old frontier to new gate indices.

Saved exact frontiers are accepted only when both `work_sha256` and
`gate_count` match. TFO conflict history is also discarded when the stored
engine is incompatible.

### Frontier double counting

Verdict: the alleged confirmed bug is absent.

Resume validation rejects:

- duplicate candidates within `pending`;
- duplicate candidates within `escalated`;
- overlap between `pending` and `escalated`;
- duplicate global frontier candidates;
- invalid gate indices or stuck values.

The unresolved rank uses the complete valid frontier and deliberately avoids
under-counting. The remaining issue is reporting clarity, not frontier
integrity.

### Full-frontier regeneration

Verdict: correctness-preserving but potentially expensive.

After a committed rewrite, gate indices, observability, and redundancy status
can change. Regenerating all `2 * A` obligations is conservative and complete.
It does not drop old timeout or SAT candidates; it recreates every current
candidate.

Avoiding regeneration safely would require stable gate identities and a
proved affected-region invalidation scheme. This is future performance work,
not an immediate correctness fix.

### Deadline and tail latency

Verdict: confirmed methodological and engineering weakness.

The nominal six-hour campaign consumed 44,130.52 seconds because running SAT
calls and unlimited proposal rechecks were drained. Results must therefore be
reported as a 12h 15m run with a six-hour dispatch deadline.

PySAT CaDiCaL 1.5.3 exposes conflict/decision/propagation budgets and
`interrupt()`. It does not expose the `set_time_budget()` API suggested by
some reviews. A real wall-time limit requires a tested interrupt watchdog or
a killable subprocess boundary.

Any timed-out recheck must return the candidate to unresolved. It must never
be accepted without exact UNSAT.

### Conflict cap

Verdict: a configurable cap is needed for controlled experiments, but a fixed
5M or 10M production cap is not justified.

Three verified `sin` candidates timed out at 10M and 20M and resolved at 40M.
A universal 5M/10M cap would have discarded the strongest escalation result.
Use deadline-aware admission, an explicit maximum tested budget, and a
separate high-budget tail experiment.

### Microbatching

Verdict: credible performance risk requiring measurement.

A hard candidate can delay the other candidates in its sequential
microbatch. Use singleton tasks at high budgets and compare batch sizes
`1`, `4`, and `16` at low budgets. Record p50/p95/p99 task time and idle time
before selecting a final policy.

### Persistent TFO

Verdict: promising, but not production-ready and not yet a thesis result.

Persistence is sound only while the candidate CNF is unchanged. The correct
unit is a candidate solver, not one generic persistent solver per circuit,
because different candidates have different TFO CNFs.

Practical options are:

- worker-affine candidate solvers held in an LRU cache;
- one long-lived candidate task that advances through several budget tiers;
- reconstruction after process restart, accepting loss of learned clauses.

Binary solver state should not be required for checkpoint correctness.

### Solver portfolio wording

Verdict: current framing should be narrowed.

`proof_reverse_portfolio` is an ordering interleave, but production uses one
SAT solver. Call the system a checkpointed parallel SAT framework or scheduler
unless multiple solver/configuration strategies are experimentally deployed.
Likewise, "cyclic conflict escalation" is more precise than "adaptive" until
online decisions use measured candidate behavior.

## Validation Added On 2026-06-15

- independent fanin-dependency TFO closure audit;
- complemented-only target fanout regression;
- independent boundary-side-input truth-table regression;
- reconvergent target-dependent side-input truth-table regression;
- focused latch-cut, full-cone agreement, and CEC pipeline suite;
- bounded exhaustive production-encoding check:
  - 9,468 small circuits;
  - 37,416 candidate obligations;
  - every TFO result agreed with brute-force truth-table semantics.

Existing checkpoint and coordinator tests were rerun:

- tier pending/escalated accounting passed;
- overlap and duplicate rejection passed;
- verified-output seed regeneration passed;
- cyclic timeout return and untried-first scheduling passed;
- sequential exact TFO recheck plus ABC CEC commit passed.

## Required Correctness Freeze

Complete these before declaring the implementation frozen:

1. Run the larger bounded depth-3 and multi-output suites on the final code.
2. Add explicit multiple-output plus latch-next-root reconvergence tests.
3. Add crash-injection tests at:
   - worker result before checkpoint;
   - proposal barrier before CEC;
   - CEC PASS before checkpoint serialization;
   - atomic checkpoint replacement.
4. Add a test that corrupts affected-root discovery and proves validation or
   the independent oracle detects it.
5. Run final CEC on every produced benchmark output and archive command,
   version, exit status, stdout, and stderr.
6. Freeze solver, ABC, Python, PySAT, CPU, worker-count, and environment
   versions in the experiment manifest.

No finite test suite proves absence of all bugs. The defensible standard is a
small trusted acceptance boundary, bounded exhaustive checks, independent CEC,
fault-injection tests, and reproducible artifacts.

## Required Experimental Matrix

Use identical starting AAGs, exact frontiers, solver version, conflict ladder,
and wall/CPU limits. Perform at least three repetitions when scheduling order
or concurrency can change the reached work.

### Scheduler

Compare:

- dynamic shared pool;
- fixed round-robin pool;
- per-circuit static allocation.

Worker counts:

- 4;
- 6 physical cores;
- 8 SMT workers.

Metrics:

- candidates classified per wall hour and CPU hour;
- SAT rejects, UNSAT proposals, accepted rewrites;
- verified gates removed;
- utilization and per-circuit CPU share;
- p50/p95/p99 task latency;
- deadline overrun and drain time;
- stale work and checkpoint overhead.

### Solver persistence

Use a frozen list of hard candidates and identical CNFs.

Compare:

- fresh reconstruction at every tier;
- persistent cumulative retries;
- persistent retries with a memory/rebuild threshold.

Measure cumulative conflicts, wall time, peak RSS, construction time, and
resolution status. Production promotion requires a repeatable benefit over
more than one `sin` candidate.

### Candidate ordering

Compare current order, reverse topological, proof cost, and the interleaved
order. Use the same fixed time limit and report resolved candidates plus
verified removals, not only how quickly easy SAT cases are rejected.

### Microbatching

Compare batch sizes `1`, `4`, and `16`, plus high-budget singleton dispatch.
Stop when confidence intervals clearly separate throughput or after the fixed
CPU-hour budget.

### High-budget escalation

Compare maximum tested budgets of 10M, 20M, 40M, and 80M. Report marginal
verified removals per additional CPU hour. Do not describe a candidate as
permanently hard; report "unresolved up to X conflicts and Y seconds."

### Structural strategy

Compare exact TFO with full affected-root cone on the same sampled candidates.
Test output partitioning only where measured root-cone overlap is low. Treat
the existing negative partition result as useful evidence rather than forcing
it into production.

### Baselines

Run local ABC on the exact same starting AAGs:

- `strash`;
- `dc2`;
- `fraig`;
- a documented standard script used by the project.

Report final gates, runtime, peak memory, and CEC. The key question is whether
this framework finds verified redundancies beyond or differently from the
chosen baseline, not whether SAT is broadly faster than synthesis.

## Reporting Rules

Every result row should include:

- source circuit and source SHA;
- work AAG SHA and generation;
- starting and final gates;
- frontier origin: full regenerated or exact resumed;
- initial frontier size and remaining candidate obligations;
- configured and actual wall time;
- CPU time and worker count;
- SAT/UNSAT/timeout counts by tier;
- CNF variables/clauses and conflicts per second;
- proposal/recheck/CEC time;
- verified removals and CEC result.

Never compare `hyp = 935` resumed survivors directly with
`sin = 10,726` freshly regenerated obligations.

## Defensible Thesis Framing

Recommended title-level framing:

> A checkpointed parallel SAT framework for exact stuck-at redundancy
> classification in AIGs, with candidate-local TFO encoding,
> generation-safe scheduling, cyclic conflict escalation, and
> transactionally CEC-verified rewrites.

This framing is accurate. "Portfolio" should be used only for the tested
ordering combination or a real solver/strategy portfolio. "Resource-aware"
requires measured resource-based decisions, not only a fixed physical-core
count.

## Claims Supported Now

- candidate-local TFO miters have matched full-cone and brute-force semantics
  in the tested validation spaces;
- every committed rewrite in the completed campaign passed ABC CEC;
- cyclic escalation resolved three `sin` candidates at 40M that timed out at
  10M and 20M;
- generation metadata, stale-result rejection, exact frontier resume, and
  transactional commits work in the tested paths;
- the completed campaign produced 35 new verified removals and 791 cumulative
  removals across the selected six circuits.
- larger bounded checks passed 632,136 exact TFO obligations and 2,390,128
  multi-output obligations without a semantic mismatch;
- one controlled dynamic-pool treatment delivered 2.18x the candidate-result
  throughput of round robin after including drain time;
- eight workers beat six on both tested real-circuit samples;
- persistent retries reduced time and conflicts on fixed `sin` and `hyp`
  samples;
- all `strash`, `dc2`, and `fraig` baseline outputs passed CEC.

## Claims Not Supported Yet

- faster or better optimization than ABC;
- dynamic pooling is superior across the benchmark population;
- eight workers are globally optimal on the Ryzen 5 5600X;
- persistent TFO improves production throughput generally or is production
  enabled;
- the current candidate order is best;
- conflict budgets are comparable across different CNF sizes;
- a six-hour dispatch deadline is a six-hour completed experiment;
- all redundancies are found;
- zero CEC failures alone proves the encoder has no bugs.

## Before The Professor Meeting

Minimum concrete package:

1. Present the corrected 12h 15m runtime and the 35 verified removals.
2. Show the `sin` 10M/20M/40M escalation trace.
3. Show the new TFO correctness tests and bounded 37,416-candidate result.
4. State that the reviews found no confirmed production soundness bug after
   code inspection, while deadline control remains unresolved.
5. Bring the fixed experiment matrix and ABC baseline plan.
6. Show the controlled scheduler, worker-count, persistence, and ABC baseline
   results in `FEEDBACK_VALIDATION_RESULTS_2026-06-15.md`.
7. Avoid performance or novelty claims that have not yet been measured.

## Professor Summary

The implementation now has a stronger exactness check for the candidate-local
TFO encoder, including independent structural dependency validation and
targeted complemented-edge and reconvergence tests. A bounded exhaustive run
checked 37,416 candidate obligations against truth-table semantics with no
disagreement. The completed campaign made 35 additional gate removals through
10 CEC-passed commits, including three `sin` candidates that required
escalation from 10M and 20M to 40M conflicts.

The main remaining weakness is experimental control rather than a demonstrated
soundness failure: a nominal six-hour dispatch window took 12h 15m after
draining long SAT calls and unlimited rechecks. The next work is a bounded
deadline policy, ABC baselines, and controlled ablations for scheduler policy,
worker count, persistent retries, ordering, and microbatch size. The thesis
should be positioned as a formally guarded parallel SAT framework and an
empirical study of hard redundancy proofs, not yet as a replacement for
standard synthesis.
