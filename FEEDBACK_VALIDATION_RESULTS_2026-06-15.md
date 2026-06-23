# Feedback Validation Results

Date: 2026-06-15

## Decision

The pipeline is thesis worthy after the final controlled experiment matrix,
but it should be framed as an exact, checkpointed SAT proof framework rather
than as a better area optimizer than ABC.

No production TFO soundness bug was found in the reviewed encoding. The one
confirmed campaign failure was a live source compatibility error: old worker
callers reloaded a newly edited optimizer API. That path is now guarded by
worker-local module caching, source hashes, backward-compatible audit calls,
and a stop-and-checkpoint regression test.

No long campaign was launched during this validation phase.

## Correctness Evidence

- Exact TFO targeted tests pass for complemented literals, constants,
  reconvergence, side-input sharing, multiple outputs, latch-next roots,
  latch cuts, full-cone agreement, and end-to-end ABC CEC.
- Larger bounded production-encoding validation passed:
  116,748 circuits and 632,136 candidate obligations.
- Bounded multi-output partition validation passed:
  401,096 output sets and 2,390,128 candidate obligations.
- Dynamic shared-pool, exact resume, checkpoint compatibility, stale
  generation, sequential recheck, transactional CEC, and source-change tests
  pass.
- Every recovered output and every output from the final real-checkpoint
  smoke tests passed ABC CEC.

These tests are strong evidence, not a proof that arbitrary implementation
bugs are impossible. ABC CEC remains the final trusted commit boundary.

## Controlled Results

### Persistent Versus Fresh TFO

Five fixed `hyp` survivors, budgets `10k,50k,250k`:

- fresh: 329.977s, 1,550,006 conflicts, 15 solver instances;
- persistent: 218.271s, 1,250,000 conflicts, 5 solver instances;
- both left all five unresolved at 250k;
- persistent reduced wall time by 33.9%.

Five fixed `sin` survivors:

- both modes classified all five SAT;
- fresh: 5.749s and 126,669 conflicts;
- persistent: 2.701s and 60,918 conflicts.

Decision: persistence has real algorithmic value, but remains experimental
until retry work has candidate-to-worker affinity or a candidate-owned actor.
The current process pool cannot safely assume that a retry reaches the worker
holding the learned clauses.

### Dynamic Pooling

One fixed 90-second heterogeneous treatment over identical `sin`, `sqrt`, and
`hyp` checkpoints:

- dynamic: 1,204 candidate results in 159.055 actual seconds, 7.570 results/s;
- round robin: 316 results in 91.123 seconds, 3.468 results/s;
- both had zero worker errors and zero verified commits;
- dynamic delivered 2.18 times the candidate-result throughput after counting
  its drain time.

Decision: retain dynamic pooling. This is a strong controlled treatment, not
yet a general superiority claim; repetitions are still required.

### Worker Count

Fixed 256-candidate `sin` sample at 10k, two repetitions:

- 4 workers, batch 4: about 30.55s;
- 6 workers, batch 4: about 23.51s;
- 8 workers, batch 4: about 20.70s.

Fixed 24-candidate `hyp` sample:

- 6 workers: about 77.45s;
- 8 workers: about 72.80s.

Eight workers were about 13% faster than six on `sin` and 6.5% faster on
`hyp`. Decision: use eight workers for the next performance campaign, while
reporting six physical cores as the clean baseline. Eight is the best tested
count, not a proven global optimum.

### Microbatching

The production trace contained 2,048 tasks. `hyp` batch-16 tasks had median
latency 200.657s and mean candidate wait behind earlier batch members of
108.490s. Replay accounting also showed that singleton low-budget tasks pay
heavy repeated parse/CNF overhead:

- six-worker replay, batch 1: estimated 3,855.9s;
- batch 4: 1,675.2s;
- batch 16: 1,130.3s.

Decision: keep batch 16 for broad untried low-budget work and use singleton
tasks for timeout retries. A universal batch size of one is not supported by
the data.

### TFO, Partitioning, And Full Cone

On five easy multi-root `div` cases:

- partitioned TFO: 0.432s;
- ordinary TFO: 0.451s;
- full cone: 1.010s.

The approximately 4% partition benefit is too small and narrow to promote.
Earlier `sin` partitioning repeated overlapping good cones and was about 24
times slower. Decision: ordinary exact TFO remains production first; full
cone and structurally eligible partitioning remain experiment-only baselines.

### ABC Baselines

All 18 baseline outputs passed CEC against the same recovered SAT outputs:

- `strash`: 0 gates removed;
- `fraig`: 28,265 gates removed in 2.929s ABC time;
- `dc2`: 32,484 gates removed in 10.008s ABC time.

The largest single result was `div`, where `fraig` removed 27,953 gates
(49.05%). The thesis must not claim area or runtime dominance over ABC.
The defensible contribution is exact candidate classification, proof
orchestration, recovery, and experimentally characterized hard SAT tails.

## Production Changes Accepted

- Independent fanin-dependency audit for exact TFO closure.
- Worker-local optimizer module caching; no reload on every process task.
- Source SHA manifest with stop-and-checkpoint behavior on a live edit.
- Batch 16 for untried work and batch 1 for timeout retries.
- Generated conflict ceiling of 40M.
- Proposal rechecks capped at the same configured maximum.
- Deadline-aware task admission using measured candidate times.
- Unknown-duration tasks blocked in the final 15 minutes.
- Five-minute reserve for checkpointing and final CEC.
- Late proposal barriers are deferred; their candidates remain unresolved.
- Eight workers selected in the long-run launcher.

The 40M ceiling is evidence-based: three verified `sin` candidates timed out
at 10M and 20M, then resolved at 40M.

## Final Smoke Tests

Before deadline admission, the exact next-run configuration processed 1,248
candidate obligations across 79 tasks with:

- eight active workers;
- zero worker errors;
- zero stale results;
- all six final CEC checks passing.

Its 60-second dispatch window took 295.646 seconds after draining, confirming
the deadline concern.

After deadline admission was added, a five-second real-checkpoint test:

- dispatched no unknown-duration task inside its guard window;
- completed in 5.689 seconds;
- saved the exact frontier;
- passed final CEC;
- recorded zero errors.

This reduces expected tail overrun but does not create a hard operating-system
wall-time guarantee. A solver interrupt watchdog or killable candidate
subprocess remains future work.

## Frozen Next-Run Configuration

- dynamic shared cross-circuit pool;
- eight worker processes;
- exact candidate-local TFO with CaDiCaL 1.5.3;
- `proof_reverse_portfolio` candidate ordering;
- budgets `10k,50k,250k,1M,5M`, then `10M,20M,40M`;
- hard generated-budget ceiling `40M`;
- untried microbatch 16;
- timeout-retry microbatch 1;
- deadline reserve 300 seconds;
- unknown-duration guard 900 seconds;
- source manifest frozen for the whole campaign;
- sequential exact TFO recheck and ABC CEC before every commit.

Persistent TFO, partitioned TFO, full-cone fallback, and learned-clause
sharing are not enabled in this production configuration.

## Remaining Thesis Work

1. Repeat dynamic versus round robin and 6 versus 8 workers at least three
   times from identical checkpoints.
2. Run candidate-order ablations with fixed CPU and wall budgets.
3. Report configured time, actual time, drain time, CPU time, and confidence
   intervals separately.
4. Add crash injection around proposal completion, CEC PASS, and atomic
   checkpoint replacement.
5. Archive source/work hashes, tool hashes, solver versions, hardware, and
   complete command lines with every thesis result.

## Post-ABC And Ordering Update

The first ABC baseline used recovered SAT outputs, so a direct-original ABC
control was added.

On five circuits where direct-original `dc2_fraig` passed CEC:

- `original -> dc2_fraig -> 60s TFO`: 115,764 gates;
- `SAT -> dc2_fraig -> 60s TFO`: 115,537 gates;
- SAT preprocessing improved the aggregate by 227 gates;
- it improved `sin`, `sqrt`, `log2`, and `mem_ctrl`, but made `div` 27 gates
  worse.

Residual exact-TFO screens directly after original-source ABC found:

- six verified gates after `dc2`;
- zero after `fraig`;
- four after `dc2_fraig`.

The residual commits occurred in `sin` and `log2`. A screen after
`SAT -> dc2_fraig` found no further proposal in the sampled 265 obligations.

Direct-original `dc2` and `dc2_fraig` on `hyp` produced smaller outputs but
their CEC checks timed out at 300 seconds. They are not counted as verified.
The `SAT -> dc2_fraig` `hyp` output had 211,611 gates and passed CEC.

The recommended thesis experiment now includes all four ordering lanes:

- SAT only;
- ABC only;
- SAT then ABC;
- ABC then SAT.

Detailed interpretation is in
`LLM_FEEDBACK_DEFENSE_AND_STRATEGY_2026-06-15.md`.
