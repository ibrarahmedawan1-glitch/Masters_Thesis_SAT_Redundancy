# External LLM Review Prompt: Dynamic Cyclic Exact-TFO Thesis System

> Status note: this prompt captures the pre-validation campaign state and is
> retained for provenance. Use
> `LLM_REVIEW_PROMPT_POST_VALIDATION_ABC_ORDERING_2026-06-15.md` for the
> current implementation, corrected campaign status, completed tests, ABC
> ordering results, and new review questions.

You are reviewing a thesis codebase for formally verified redundancy removal
in AIG/AAG circuits. Be skeptical and concrete. Do not merely summarize or
approve the approach. Look for soundness bugs, misleading metrics, scheduler
pathologies, weak experimental methodology, unsupported claims, and missing
baselines.

The requested review has four goals:

1. Find correctness or implementation bugs.
2. Decide whether the engineering and experimental contribution is thesis
   worthy.
3. Identify claims that are too strong for the current evidence.
4. Propose prioritized improvements and decisive experiments.

## Project Goal

For every AND gate in an AIG, the system considers two single stuck-at fault
obligations:

- `(gate_index, SA0)`
- `(gate_index, SA1)`

A candidate is redundant only if an exact SAT miter proves that forcing the
gate to the selected constant cannot change any real observable root. Real
roots include primary outputs and latch-next-state functions.

The system rewrites only exact UNSAT candidates. SAT candidates are rejected.
Timeouts remain unresolved and return at a larger conflict budget. Every
committed rewrite is checked against the original source circuit using ABC
combinational equivalence checking (CEC). A failed CEC must roll back or stop
the circuit.

## Important Terminology

`unresolved` is a count of candidate fault obligations, not a count of gates,
outputs, TFO nodes, or circuits.

For a circuit with `A` AND gates, a freshly regenerated frontier contains at
most `2 * A` candidates. A resumed exact frontier can be much smaller because
previous SAT candidates were already rejected and only timeout survivors
remain.

Therefore these values are not directly comparable without their frontier
origin:

- `hyp = 935` means 935 surviving `(gate, stuck_value)` obligations from a
  valid resumed exact frontier.
- `sin = 10,726` immediately after rewriting a 5,363-gate verified output means
  a regenerated full frontier of `2 * 5,363`; it does not mean the previous
  three difficult candidates became 10,726 difficult candidates.

Each candidate is solved independently. The TFO encoder is not solving “one
gate of the TFO.” It encodes one stuck-at fault at one target gate, against all
observable roots affected by that target.

## Main Files To Review

- `optimizer_alg10_tiered.py`
  - AAG parsing and rewriting
  - affected-root discovery
  - fanin-cone and exact TFO-slice construction
  - CNF construction
  - TFO closure audit
  - checkpoint validation and frontier accounting
- `alg10_frontier_shard_probe.py`
  - candidate-local exact TFO workers
  - SAT/UNSAT/timeout classification
- `alg10_parallel_commit_coordinator.py`
  - exact sequential proposal recheck
  - rewrite transaction
  - ABC CEC commit gate
  - checkpoint frontier serialization
- `alg10_dynamic_tfo_pool_campaign.py`
  - six-worker dynamic cross-circuit scheduler
  - candidate ownership
  - cyclic conflict-budget escalation
  - asynchronous proposal barriers
  - stale-generation rejection
- `alg10_parallel_tfo_benchmark_campaign.py`
  - checkpoint discovery and ranking
  - verified-output restart seeds
  - hardware-aware worker count
- `hard_candidate_strategy_experiment.py`
  - experiment-only fresh versus persistent solver comparison
  - exact TFO, partitioned TFO, and full-cone order comparison
- `monitor_alg10_campaign.py`
  - live summary rendering
- `test_alg10_tfo_miter.py`
- `test_partitioned_miter_soundness.py`
- `test_alg10_dynamic_tfo_pool_campaign.py`
- `test_alg10_parallel_commit_coordinator.py`

## Exact Candidate-Local TFO Encoding

For candidate `(idx, stuck_value)`:

1. Compute every observable root reachable through the target's transitive
   fanout.
2. Build the complete good-circuit fanin cone for those affected roots.
3. Build the faulty copy only for gates in the target's observable TFO slice.
4. Reuse exact good-circuit values for side inputs outside the faulty slice.
5. Force the target's faulty value to SA0 or SA1.
6. Assert that at least one affected real root differs between good and faulty
   copies.

Interpretation:

- SAT means a distinguishing input/state assignment exists, so reject the
  candidate.
- UNSAT means the fault is unobservable at every affected real root, so propose
  the rewrite.
- timeout means retain the candidate for a larger budget.

`_audit_tfo_slice(...)` independently recomputes the expected slice and rejects
missing targets, missing/extra relevant gates, or affected roots outside the
slice.

Workers only propose UNSAT candidates. Before rewriting, the coordinator
rebuilds and solves the exact TFO miter sequentially against the current
progressively modified generation. Accepted proposals are then applied
together and the candidate AAG must pass ABC CEC against the original source.

## Current Dynamic Scheduler

The current production run uses:

- one global process pool shared across six circuits;
- six worker slots on a Ryzen 5 5600X with 6 physical / 12 logical CPUs;
- one independent candidate-local CNF per candidate;
- microbatches of 16 candidates per process task for broad frontiers;
- one candidate per task when a frontier is smaller than the worker count;
- untried candidates before timeout retries within each circuit;
- circuits with fewer in-flight tasks preferred when assigning a free worker;
- immutable work-AAG SHA and generation metadata on every task;
- stale worker results rejected after a committed rewrite;
- one proposal barrier at a time in a separate single-process executor;
- proposal barriers count against the six-slot capacity, leaving at most five
  classification slots while a barrier is active;
- unrelated circuits continue while one circuit is in sequential recheck/CEC.

Configured conflict ladder:

`10k -> 50k -> 250k -> 1M -> 5M -> 10M -> 20M -> 40M -> 80M -> ...`

The generated ladder doubles without a configured cap until the wall-clock
deadline. In-flight SAT calls and proposal barriers are drained after the
deadline.

Current solver: PySAT CaDiCaL 1.5.3 (`cadical153`).

Current candidate order: `proof_reverse_portfolio`, an interleaving of
proof-cost and reverse-topological rankings. It reorders but does not filter
the frontier.

## Checkpoint And Frontier Rules

- A checkpoint frontier is valid only if `work_sha256` and `gate_count` match
  its work AAG.
- A global frontier stores every remaining candidate plus its maximum tried
  conflict budget.
- A tier frontier stores both `pending` and `escalated`; unresolved accounting
  must include both.
- If the work AAG is unchanged, resume its exact saved frontier and compatible
  TFO conflict history.
- If a CEC-passed rewrite changes the AAG, regenerate the full candidate
  frontier because gate indices and observability can change.
- SAT rejects are removed from the current generation.
- Timeouts remain and advance to the next budget.
- The checkpoint selector prioritizes lower current gate count before smaller
  unresolved count.
- A prior campaign output with `final_verify=PASS` may become a restart seed
  after an independent CEC check, even if no post-commit exact frontier was
  serialized.

## Completed Campaign Evidence

Completed directory:

`results_optimized/parallel_tfo_benchmarks_6h_20260614_215326/`

Results:

- final status: `TIME_BUDGET_COMPLETE`;
- nominal budget: six hours;
- actual wall time: 44,130.52 seconds, about 12h 15m;
- reason for overrun: in-flight exact SAT and unlimited sequential rechecks
  were drained;
- 10 CEC-passed commits;
- zero CEC failures;
- 35 additional verified AND-gate removals;
- cumulative removals across the selected six circuits: 791.

New removals in that campaign:

| Circuit | New removals | Final gates |
| --- | ---: | ---: |
| `sin` | 6 | 5,363 |
| `div` | 17 | 56,997 |
| `log2` | 6 | 31,638 |
| `mem_ctrl` | 6 | 46,828 |
| `sqrt` | 0 | 24,564 in that campaign |
| `hyp` | 0 | 214,331 |

The key cyclic-budget result was `sin`:

- three candidates timed out at 10M;
- the same three timed out at 20M;
- all three returned worker UNSAT proposals at 40M;
- worker times were approximately 10,544s, 10,842s, and 11,746s;
- sequential rechecks took approximately 6,329s, 0.018s, and 8,359s;
- the near-zero recheck became structurally unobservable after an earlier
  accepted rewrite;
- all three were accepted;
- rewrite reduced `sin` from 5,369 to 5,363 gates;
- ABC CEC passed.

This is evidence that escalation can resolve genuine survivors, but it also
shows severe tail latency and deadline overrun.

## Current Running Campaign

Service:

`alg10-dynamic-tfo-benchmarks-6h-20260615-103558.service`

Output:

`results_optimized/parallel_tfo_benchmarks_dynamic_tfo_6h_20260615_103558/`

Started:

`2026-06-15 10:36:12 CEST`

Nominal deadline:

`2026-06-15 16:36:12 CEST`

Starting gate counts:

| Circuit | Gates | Frontier origin |
| --- | ---: | --- |
| `sin` | 5,363 | verified output, full frontier regenerated |
| `sqrt` | 24,562 | lower-gate valid checkpoint |
| `hyp` | 214,331 | resumed 935-candidate exact frontier |
| `div` | 56,997 | verified output, full frontier regenerated |
| `log2` | 31,638 | resumed exact frontier |
| `mem_ctrl` | 46,828 | verified output, full frontier regenerated |

Early dynamic telemetry showed:

- all six worker slots active;
- mixed-circuit initial dispatches rather than one-circuit-at-a-time visits;
- measured utilization around 76-77%;
- no worker errors, stale results, proposals, or CEC failures at the early
  observation point;
- broad regenerated frontiers shrinking rapidly through SAT rejection;
- `hyp` candidates producing large CNFs around 643k clauses even when the
  faulty TFO itself is small, because the complete good cone is about 214k
  gates.

## Validation Already Performed

- exact TFO closure-corruption test;
- exact TFO versus full-cone agreement tests;
- full `c432` TFO pipeline with ABC CEC pass;
- bounded exact encoding checks over hundreds of thousands of candidates in
  prior validation;
- bounded multi-output partition/TFO checks;
- dynamic two-circuit shared-pool test;
- proposal barriers and CEC-passed commits under a shared worker limit;
- stale generation metadata checks;
- checkpoint selection and verified-output seed tests;
- cyclic timeout-return and generated-budget tests;
- Python compilation and `git diff --check`.

## Experimental Persistent Solver Work

`hard_candidate_strategy_experiment.py` compares:

- fresh solver reconstruction at every conflict tier;
- one persistent solver retaining learned clauses across cumulative tiers;
- exact TFO;
- exact output-partitioned TFO;
- full affected-root cone;
- every configured stop-on-first-resolution process order.

Preliminary evidence:

- persistent TFO reduced repeated conflicts and solver construction on a hard
  `sin` candidate;
- full cone was generally larger and slower than TFO;
- one-root partitioning is identical to ordinary TFO and should not be a
  separate production stage;
- `sin` output partitioning repeated heavily overlapping good cones and was
  about 24 times slower at a low-budget screen;
- `div` TFO found SAT while the full cone timed out in the sampled case.

Important limitation: persistent learned-clause TFO is experiment-only. The
current production campaign still creates a fresh solver for each candidate
and each retry tier. Do not credit production with persistence.

## Known Concerns To Challenge

Please investigate these rather than accepting them as harmless:

1. Does the exact TFO encoding correctly handle complemented AIG literals,
   constants, latch cut boundaries, multiple outputs, and latch-next roots?
2. Is reusing good values for faulty side inputs outside the TFO slice always
   semantically exact?
3. Is `_audit_tfo_slice(...)` sufficient to prevent an under-approximate faulty
   cone from producing an unsound UNSAT?
4. Can sequentially applying multiple individually rechecked stuck-at
   constants create an interaction not covered by the recheck ordering?
5. Is one final ABC CEC enough evidence, and are there cases where the verifier
   or AAG conversion path could produce a false PASS?
6. Can checkpoint selection accidentally combine a source, work AAG, frontier,
   or conflict history from incompatible generations?
7. Are `unresolved`, removed-gate totals, and regenerated-frontier counts
   reported in a way that could mislead readers?
8. Does prioritizing fewer in-flight tasks and untried work produce starvation
   or excessive preference for fast circuits?
9. Does a microbatch of 16 cause head-of-line blocking when one candidate is
   much harder than the other 15?
10. Does parsing the full AAG and rebuilding the good cone/CNF for every
    microbatch or candidate dominate runtime?
11. Is it valid to compare conflict budgets across candidate CNFs of very
    different sizes?
12. Can unbounded 2x generated budgets cause impractical tail latency or memory
    growth?
13. Proposal rechecks are currently unlimited. They can overrun the nominal
    campaign deadline by hours. What bounded-but-sound policy should replace
    this?
14. The production workers do not retain learned clauses across retries. How
    should persistent state be integrated without making checkpoint recovery
    fragile?
15. Is process-level parallelism on six physical cores the right baseline?
    Should eight SMT workers, solver portfolios, or per-candidate parallel SAT
    be measured?
16. Are the current baselines sufficient to claim novelty or practical value?
17. Does the system optimize gate count at the cost of enormous SAT time, and
    is that tradeoff meaningful for the thesis?
18. Could repeated full-frontier regeneration after every commit cause
    quadratic rescanning and duplicate SAT work?
19. Is the candidate ordering experiment statistically meaningful, or is it
    overfit to a few EPFL circuits?
20. Are there race conditions around proposals, in-flight tasks, stale results,
    checkpoint writes, or commit barriers?

## Questions You Must Answer

Please structure your response as follows.

### 1. Critical Findings

List correctness bugs or plausible unsoundness risks first, ordered by
severity. Cite file/function names and explain a concrete failure scenario.
Distinguish confirmed bugs from hypotheses requiring a test.

### 2. Metric And Experimental Audit

Assess:

- unresolved-count semantics;
- gate-removal accounting;
- fairness of comparing resumed and regenerated frontiers;
- conflict-budget comparability;
- wall-clock deadline overruns;
- whether the 35 new removals and 10 commits are enough evidence;
- missing baselines, repetitions, confidence intervals, and ablations.

### 3. Scheduler Review

Evaluate:

- global queue fairness;
- worker utilization;
- microbatch size;
- cyclic escalation;
- deadline draining;
- proposal barrier isolation;
- checkpoint frequency;
- recovery after interruption.

Suggest a better policy if appropriate.

### 4. SAT Strategy Review

Compare the likely value of:

- fresh TFO;
- persistent TFO across retries;
- full cone fallback;
- eligible output partitioning;
- global fault-sweep solver;
- CaDiCaL versus other solvers;
- solver portfolios;
- assumptions-based reusable CNFs;
- learned-clause sharing, only where logically sound.

Provide a recommended production order with eligibility rules and budgets.

### 5. Thesis-Worthiness Decision

Give one direct verdict:

- thesis worthy as currently implemented;
- thesis worthy after specific required fixes/experiments;
- not yet thesis worthy.

Explain the defensible contribution. Separate genuine contribution from
engineering implementation and from standard SAT/AIG techniques.

Potential framing to assess:

> A resource-aware, checkpointed SAT portfolio scheduler for exact
> candidate-local TFO redundancy proofs, with adaptive conflict budgets,
> generation-safe parallelism, and transactional CEC-verified commits.

State whether this framing is accurate or overstated.

### 6. Prioritized Improvement Plan

Give:

- fixes required before trusting more results;
- experiments required before thesis claims;
- performance improvements ranked by expected benefit and implementation risk;
- what should be completed before the professor meeting;
- what can be future work.

### 7. Decisive Experiments

Design a compact experiment matrix that can decide:

- whether dynamic pooling beats round-robin;
- whether six physical workers beat four workers and eight SMT workers;
- whether persistent TFO beats fresh retries;
- whether candidate ordering matters;
- whether partitioned TFO has any eligible structural region;
- whether high-budget escalation is cost-effective.

Specify metrics, controls, repetitions, and stop criteria.

### 8. Suggested Thesis Claims

Provide:

- claims currently supported;
- claims not yet supported;
- a concise proposed contribution paragraph;
- a concise limitations paragraph.

### 9. Professor Summary

Write a short, technically honest update suitable for a professor. It should
mention the verified reductions, exactness safeguards, scheduler improvement,
remaining hard cases, and the next validation experiments.

Do not assume that zero unresolved candidates is necessary for a successful
thesis. Judge the work by correctness, methodological quality, novelty,
experimental evidence, and clarity of limitations.
