# Skeptical Review Prompt: Post-Validation Exact TFO And ABC Ordering

Date: 2026-06-15

You are reviewing a thesis codebase for exact SAT-based stuck-at redundancy
classification and CEC-verified AIG rewriting. Be skeptical. Verify whether
the conclusions below follow from the implementation and artifacts. Look for
soundness bugs, experimental confounds, misleading aggregation, incorrect
ordering comparisons, and unsupported thesis claims.

Do not merely summarize or approve the work. Distinguish:

- confirmed implementation bugs;
- plausible risks requiring a test;
- methodological limitations;
- claims that are supported by the current evidence.

## System Under Review

For every AND gate, the system considers `(gate_index, SA0)` and
`(gate_index, SA1)`.

One candidate-local exact TFO miter:

1. finds every observable root reachable from the target;
2. constructs the complete good fanin cone of those roots;
3. constructs the faulty copy for the target-dependent observable TFO;
4. shares exact good values only for side inputs outside that dependency
   closure;
5. forces the target to the selected constant;
6. asserts at least one affected root differs.

SAT rejects the candidate. UNSAT proposes a rewrite. Timeout remains
unresolved. The coordinator rebuilds each proposal sequentially against the
current modified generation. The combined AAG is committed only after ABC CEC
passes.

## Current Production Configuration

- dynamic shared pool across circuits;
- eight worker processes on a Ryzen 5 5600X;
- CaDiCaL 1.5.3 through PySAT;
- order `proof_reverse_portfolio`;
- conflict ladder `10k,50k,250k,1M,5M,10M,20M,40M`;
- hard 40M generated cap;
- untried microbatch 16;
- timeout-retry microbatch 1;
- worker optimizer module cached instead of reloaded per task;
- source SHA manifest; a live edit stops dispatch and checkpoints;
- stale work rejected by generation and work-AAG SHA;
- observed-time deadline admission;
- unknown-duration work blocked in the final 900 seconds;
- 300 seconds reserved for checkpointing/final CEC;
- late proposal barriers deferred, with candidates left unresolved;
- exact sequential recheck and CEC before commit.

Persistent solver state, partitioned TFO, full-cone fallback, and clause
sharing are not enabled in production.

## Prior Campaign Evidence

Completed cyclic campaign:

- nominal six-hour dispatch window;
- actual 12h 15m before deadline hardening;
- 10 CEC-passed commits;
- zero CEC failures;
- 35 new verified gate removals;
- 791 reported cumulative removals across the selected six circuits.

Three `sin` candidates timed out at 10M and 20M, then produced UNSAT at 40M.
All three passed sequential recheck and final CEC.

The later dynamic campaign stopped because old worker caller code reloaded a
new optimizer API after a live source edit. It was not OOM and produced no
unsound commit. All recovered outputs passed CEC. Source freezing and worker
module caching were added afterward.

## Correctness Validation

Targeted tests cover:

- complemented literals and constants;
- intentionally corrupted TFO closure;
- independent shared side inputs;
- target-dependent reconvergence;
- multiple outputs;
- latch-next roots and latch cuts;
- exact TFO versus full affected-root cone;
- sequential proposal application;
- stale generations and checkpoint compatibility;
- source-change stop/checkpoint behavior;
- end-to-end CEC.

Bounded checks:

- 116,748 generated circuits;
- 632,136 exact-TFO candidate obligations;
- 401,096 multi-output sets;
- 2,390,128 multi-output candidate obligations;
- no semantic disagreement in those bounded spaces.

Please inspect whether those tests exercise the same production encoding and
whether any shared helper could invalidate their independence.

## Feedback Claims Already Investigated

The following alleged bugs were not confirmed:

- complemented fanout omission: fanout literals are normalized with `& ~1`;
- side-input reuse unsoundness: a target-dependent side input belongs to the
  complete target fanout closure;
- multi-proposal interaction: every proposal is rechecked after earlier
  accepted substitutions;
- verified-output frontier mixing: verified outputs regenerate a fresh
  frontier with no old history;
- pending/escalated double counting: duplicates and overlap are rejected.

The TFO audit previously shared too much traversal logic with construction.
It now includes an independent fanin-dependency derivation.

Check these conclusions against:

- `optimizer_alg10_tiered.py`;
- `alg10_frontier_shard_probe.py`;
- `alg10_parallel_commit_coordinator.py`;
- `alg10_dynamic_tfo_pool_campaign.py`;
- `test_alg10_tfo_miter.py`;
- `test_partitioned_miter_soundness.py`;
- `test_alg10_dynamic_tfo_pool_campaign.py`;
- `test_alg10_parallel_commit_coordinator.py`.

## Controlled Scheduler And SAT Results

Persistent versus fresh TFO:

- five `hyp` survivors: 329.977s fresh versus 218.271s persistent;
- five `sin` survivors: 5.749s fresh versus 2.701s persistent.

Production persistence remains disabled because retry worker affinity is not
guaranteed.

Dynamic versus round robin on one fixed treatment:

- dynamic: 7.570 candidate results/s;
- round robin: 3.468 candidate results/s;
- 2.18x for that treatment, not yet a general claim.

Worker scaling:

- eight workers were about 13% faster than six on `sin`;
- eight workers were about 6.5% faster than six on `hyp`.

Batching:

- batch 16 amortizes parse/CNF cost on broad frontiers;
- hard `hyp` batches showed severe head-of-line waiting;
- production uses batch 16 only for untried work and singleton retries.

## ABC Baselines And Ordering Results

The six original sources total 380,512 gates. The recovered SAT outputs total
379,703 gates.

On recovered SAT outputs:

- `dc2`: 32,484 gates removed;
- `fraig`: 28,265 removed;
- `dc2_fraig`: 52,555 removed;
- all six `SAT -> dc2_fraig` outputs passed CEC;
- final aggregate: 327,148 gates.

Directly from original sources:

- `dc2_fraig` was best area on five circuits;
- direct-original `dc2` and `dc2_fraig` on `hyp` produced smaller AAGs but
  their CEC checks timed out at 300 seconds;
- direct `fraig` on `hyp` passed CEC and must be the verified baseline there.

Five directly comparable circuits:

| Circuit | Original -> dc2_fraig -> TFO | SAT -> dc2_fraig -> TFO | Delta favoring SAT preprocessing |
| --- | ---: | ---: | ---: |
| `sin` | 5,024 | 4,997 | 27 |
| `sqrt` | 18,409 | 18,399 | 10 |
| `div` | 20,722 | 20,749 | -27 |
| `log2` | 29,006 | 28,841 | 165 |
| `mem_ctrl` | 42,603 | 42,551 | 52 |
| Total | 115,764 | 115,537 | 227 |

Thus SAT preprocessing improved four circuits, hurt `div`, and improved the
aggregate by 227 gates. The SAT runtime is many orders larger than ABC's
transformation time.

For `hyp`:

- original: 214,335;
- SAT output: 214,331;
- original `dc2_fraig`: 211,601 but CEC timed out, so unverified;
- `SAT -> dc2_fraig`: 211,611 and CEC passed.

Do not treat the unverified 211,601 result as a valid baseline win.

## Residual TFO After ABC

Sixty-second, 10k-conflict exact-TFO screens on five CEC-passed
original-source ABC outputs:

- after `dc2`: 689 candidate results, three UNSAT proposals, two CEC-passed
  commits, six gates removed;
- after `fraig`: 635 results, no UNSAT proposal;
- after `dc2_fraig`: 784 results, two UNSAT proposals, two CEC-passed commits,
  four gates removed.

The removals were in `sin` and `log2`.

A 60-second screen after `SAT -> dc2_fraig` classified 265 obligations across
six circuits and found no UNSAT proposal.

A separate broad `sin` experiment after `SAT -> dc2` and `SAT -> fraig`
classified 16,941 candidate results:

- 15,471 SAT rejects;
- 1,470 timeouts;
- zero UNSAT proposals.

These are fixed-time/fixed-conflict screens, not exhaustive proofs of no
remaining redundancy.

Artifacts:

- `FEEDBACK_VALIDATION_RESULTS_2026-06-15.md`;
- `LLM_FEEDBACK_DEFENSE_AND_STRATEGY_2026-06-15.md`;
- `ABC_SAT_ORDERING_COMPARISON_2026-06-15.csv`;
- `results_optimized/feedback_validation_20260615/`;
- `post_abc_residual_tfo_experiment.py`.

## Proposed Interpretation To Challenge

1. Exact SAT preprocessing can change later ABC optimization and produced a
   modest 227-gate aggregate improvement on five comparable circuits.
2. ABC can expose sparse new exact constant redundancies, especially after
   `dc2`-based flows.
3. `fraig` exposed no residual in this limited screen.
4. For fast practical optimization, `dc2_fraig` followed by a short TFO
   residual screen is the best tested cost-aware path.
5. For the smallest verified result found here, run SAT preprocessing, then
   `dc2_fraig`, then optionally a short fresh TFO screen, while selecting the
   best verified path per circuit.
6. The thesis contribution is exact classification, proof orchestration,
   checkpoint/recovery semantics, and ordering analysis, not superiority over
   ABC.

## Questions You Must Answer

### 1. Correctness Audit

Are any of the dismissed soundness concerns actually valid? Give concrete
file/function-level counterexamples. Check constants, complemented literals,
latches, root discovery, side-input sharing, stale generations, multi-proposal
transactions, and checkpoint import.

### 2. Test Independence

Could the bounded oracle and production encoder share a bug? Which additional
independent tests, mutation tests, proof logging, or verifier should be added?

### 3. Ordering Methodology

Is the five-circuit 227-gate conclusion statistically and methodologically
valid? Identify confounds involving:

- different initial gate numbering;
- fixed wall versus fixed CPU budget;
- candidate ordering;
- regenerated frontiers after commits;
- CEC timeout censoring on `hyp`;
- depth degradation;
- selecting the best path per circuit;
- multiple-comparison bias.

### 4. Strategy Decision

Is the proposed fast path and deep path correct? Should `dc2_fraig` be replaced
or supplemented by `resyn2`, `resyn2x2`, `dch`, or another documented ABC
script? Should TFO run before ABC, after ABC, both, or only on structurally
eligible circuits?

### 5. Residual SAT Interpretation

What can legitimately be inferred from six/four residual gates after
`dc2`/`dc2_fraig`, zero after `fraig`, and zero after `SAT -> dc2_fraig`?
What sample size, budget ladder, repetitions, and controls would make this a
thesis-quality ordering claim?

### 6. Scheduler And Persistence

Review deadline admission, source freezing, retry singleton batching, the 40M
cap, and proposal deferral. Design a sound production persistent-TFO
architecture that does not rely on fragile binary solver checkpoints.

### 7. Thesis Verdict

Choose one:

- thesis worthy now;
- thesis worthy after specific required experiments/fixes;
- not yet thesis worthy.

Separate standard SAT/AIG techniques from the actual contribution. State
whether this framing is accurate:

> A checkpointed parallel SAT framework for exact stuck-at redundancy
> classification in AIGs, with candidate-local TFO encoding,
> generation-safe scheduling, cyclic conflict escalation, transactional
> CEC-verified rewriting, and an empirical study of SAT/ABC transformation
> ordering.

### 8. Claims

List:

- claims supported now;
- claims that remain too strong;
- the three most decisive next experiments;
- any result that should be removed or reworded.

### 9. Direct Challenge

Is our interpretation correct? What important bug, baseline, ablation, or
alternative explanation have we still missed?
