# Feedback Defense, Validation Method, And Pipeline Strategy

Date: 2026-06-15

## Bottom Line

The skeptical LLM feedback was useful, but it mixed three categories:

1. real weaknesses that required fixes or experiments;
2. plausible hypotheses that required adversarial tests;
3. alleged correctness bugs that were not present in the implementation.

We did not answer the reviews by assertion. We traced the relevant code,
constructed counterexample-oriented tests, compared SAT encodings against
truth tables and full-cone miters, exercised checkpoint and concurrency paths,
ran ABC CEC after every committed rewrite, and measured the proposed
performance alternatives on fixed inputs.

The defensible conclusion is:

> No production exact-TFO soundness bug was found in the reviewed paths.
> Several engineering and experimental weaknesses were confirmed and fixed.
> The remaining risks concern crash recovery, external verifier diversity,
> experimental repetitions, and runtime efficiency rather than a demonstrated
> unsound rewrite.

This is not a claim that the software is bug-free. No finite test campaign can
prove that. The claim is that the current trust argument is concrete,
adversarially tested, and has a small final acceptance boundary: exact UNSAT
followed by ABC CEC.

## What The Other Reviews Got Right

The following feedback was confirmed:

- the nominal six-hour campaign overran to 12h 15m because running SAT calls
  and unlimited proposal rechecks were drained;
- conflict budgets are not directly comparable across very different CNFs;
- batch 16 causes head-of-line delay on hard `hyp` tasks;
- rebuilding candidate CNFs and reparsing AAGs has measurable cost;
- persistent learned clauses can help but were not production-enabled;
- the previous evidence lacked ABC baselines and controlled scheduler,
  worker-count, and ordering comparisons;
- `unresolved` requires explicit frontier-origin labels;
- zero CEC failures alone is not proof that the encoder has no bugs;
- production claims must distinguish candidate classification, verified gate
  removal, wall time, CPU time, and deadline drain;
- the project should not claim area or runtime superiority over ABC.

The reviews also motivated a failure we then observed directly: editing a
worker-facing API while an old process pool was active caused old caller code
to reload a new optimizer signature. This was not OOM or SAT unsoundness, but
it was a real operational bug.

## What Was Not A Confirmed Bug

### Faulty side-input reuse

For a combinational AIG DAG, a side-input node outside the complete target
transitive fanout cannot depend on the target. If it did, a directed path from
the target would place it in the closure. Reusing its exact good value in the
faulty copy is therefore semantically exact.

We added an independent fanin-dependency audit and tested:

- independent boundary inputs;
- target-dependent reconvergent inputs;
- complemented-only uses;
- both SA0 and SA1;
- multiple roots and latch-next roots.

### Complemented fanout

The fanout graph normalizes AIG literals with `lit & ~1`. Positive and
complemented references therefore create the same structural dependency edge.
The dedicated complemented-only regression passes.

### Sequential proposal interaction

Every proposal is rebuilt and rechecked against the progressively modified
generation. Accepted replacement A is installed before proposal B is checked.
The transaction therefore proves an equivalence chain. The final combined AAG
must additionally pass CEC against the original source.

### Checkpoint generation mixing

Saved frontiers require matching work SHA and gate count. Verified-output
seeds start with no old frontier and regenerate all current obligations.
Incompatible TFO history is discarded. Duplicate and overlapping tier
frontiers are rejected.

These mechanisms do not make checkpoint code infallible, but the concrete
generation-mixing scenarios asserted by the reviews did not match the code.

## How Correctness Was Tested

### Targeted adversarial tests

The exact TFO suite covers:

- constants and complemented literals;
- closure corruption;
- independent side-input sharing;
- reconvergent target-dependent inputs;
- multiple primary outputs;
- latch-next-state roots and latch cut boundaries;
- exact TFO versus full affected-root cone;
- sequential recheck and end-to-end CEC.

### Bounded exhaustive checks

- 116,748 generated circuits;
- 632,136 candidate fault obligations checked against direct semantics;
- 401,096 multi-output sets;
- 2,390,128 multi-output candidate obligations.

No semantic disagreement was found in those bounded spaces.

### Transaction and recovery tests

Tests cover:

- exact frontier resume;
- pending and escalated accounting;
- stale-generation rejection;
- timeout return at a larger budget;
- shared-pool proposal barriers;
- CEC-passed commits;
- source-change detection and safe checkpointing;
- worker module caching instead of live reload.

### Final verification boundary

Workers never commit. They only propose exact UNSAT candidates. The
coordinator rechecks each proposal sequentially against the current generation
and commits only if ABC CEC passes.

## Performance And Scheduler Findings

### Persistent solving

Five fixed `hyp` survivors:

- fresh retries: 329.977s and 1,550,006 conflicts;
- persistent retries: 218.271s and 1,250,000 conflicts.

Five fixed `sin` survivors:

- fresh: 5.749s and 126,669 conflicts;
- persistent: 2.701s and 60,918 conflicts.

Persistence is promising but remains experimental because the current process
pool does not guarantee candidate retry affinity.

### Dynamic scheduling

One identical-checkpoint treatment:

- dynamic: 7.570 candidate results/s;
- round robin: 3.468 candidate results/s.

This is a 2.18x result for that treatment, not yet a population-wide claim.

### Worker count

Eight workers beat six:

- about 13% on the fixed `sin` sample;
- about 6.5% on the fixed `hyp` sample.

Eight is therefore the best tested performance configuration. Six physical
workers remains the clean hardware baseline.

### Microbatching

Batch 16 is efficient for broad low-budget work because it amortizes AAG
parsing and CNF construction. It creates severe head-of-line delay on hard
tasks. Production now uses:

- batch 16 for untried low-budget candidates;
- batch 1 for timeout retries.

### Deadline control

Production now has:

- a 40M generated conflict ceiling;
- proposal rechecks capped at the same maximum;
- observed-time deadline admission;
- a 15-minute guard for unknown-duration tasks;
- a five-minute checkpoint/CEC reserve;
- deferred late proposals that remain unresolved;
- source hashes that stop dispatch after a live edit.

This limits expected overrun but is not a hard OS-level wall-time guarantee.

## ABC And SAT Ordering Experiments

### ABC after recovered SAT outputs

On the six recovered SAT outputs:

- `dc2` removed 32,484 gates;
- `fraig` removed 28,265 gates;
- `dc2_fraig` removed 52,555 gates;
- every `SAT -> dc2_fraig` output passed CEC.

The final `SAT -> dc2_fraig` aggregate was 327,148 gates.

### ABC directly from original sources

Direct-original `dc2_fraig` was best for area on five circuits. Direct
`fraig` was the only fully CEC-passed original-source flow for `hyp`; direct
`dc2` and `dc2_fraig` produced smaller `hyp` AAGs but their CEC checks timed
out at 300 seconds, so those outputs cannot be counted as verified results.

### Comparable five-circuit ordering result

For `sin`, `sqrt`, `div`, `log2`, and `mem_ctrl`:

- original sources: 166,177 gates;
- recovered SAT outputs: 165,372 gates;
- `original -> dc2_fraig`: 115,768 gates;
- `original -> dc2_fraig -> 60s TFO`: 115,764 gates;
- `SAT -> dc2_fraig`: 115,537 gates;
- `SAT -> dc2_fraig -> 60s TFO`: unchanged at 115,537 gates.

SAT preprocessing improved the final result by 227 gates in aggregate over
the directly comparable `original -> dc2_fraig -> TFO` chain:

- `sin`: 27 fewer;
- `sqrt`: 10 fewer;
- `div`: 27 more, so preprocessing hurt this case;
- `log2`: 165 fewer;
- `mem_ctrl`: 52 fewer.

This is evidence that exact constant rewrites can alter the later ABC search
trajectory beneficially. It is not evidence that the gain justifies the large
SAT runtime for ordinary area optimization.

### Residual TFO after ABC

On five CEC-passed original-source ABC outputs, 60-second exact-TFO screens
found:

- after `dc2`: three UNSAT obligations, two CEC-passed commits, six gates
  removed (`sin` and `log2`);
- after `fraig`: no UNSAT proposal;
- after `dc2_fraig`: two UNSAT obligations, two CEC-passed commits, four gates
  removed (`sin` and `log2`).

On the `SAT -> dc2_fraig` outputs, a 60-second six-circuit screen classified
265 obligations and found no further UNSAT proposal.

A separate broad `sin` screen after `SAT -> dc2` and `SAT -> fraig` examined
16,941 candidate results at 10k conflicts, with 15,471 SAT rejects, 1,470
timeouts, and no UNSAT proposal.

The correct interpretation is:

- ABC can expose sparse new exact constant redundancies;
- the yield depends on the ABC transformation;
- `dc2` and `dc2_fraig` exposed residuals in this sample, while `fraig` did
  not;
- absence of UNSAT under a 10k/time-limited screen is not proof of no remaining
  redundancy.

Detailed common-circuit comparison:
`ABC_SAT_ORDERING_COMPARISON_2026-06-15.csv`.

## Recommended Strategy

There is no single best order for every objective.

### For minimum wall time and strong area reduction

1. Run `strash; dc2; fraig`.
2. Require CEC.
3. Run a short exact-TFO residual screen.
4. Keep residual time bounded because observed yield is sparse.

This is the practical fast path.

### For the smallest verified result found in this study

1. Run the exact SAT pipeline on the original/selected checkpoint.
2. Run `strash; dc2; fraig`.
3. Require CEC at both stages.
4. Optionally run a short fresh TFO residual screen because ABC changes gate
   indices and observability.
5. Select the best verified path per circuit.

For the tested set, SAT preprocessing helped four of five directly comparable
circuits but hurt `div`. Therefore per-circuit verified selection is better
than forcing one universal order.

### For the thesis

Report separate lanes:

- SAT only;
- ABC only from the original source;
- SAT then ABC;
- ABC then SAT;
- optional SAT then ABC then SAT.

Use identical source AAGs and report wall time, CPU time, gates, depth,
frontier origin, candidate counts, timeouts, and CEC status. This turns
ordering sensitivity into a legitimate experimental contribution instead of
hiding it.

## What Still Must Be Done

1. Repeat scheduler and worker-count treatments at least three times.
2. Run the ordering matrix on more circuits and more ABC scripts.
3. Give post-ABC TFO the same fixed CPU budget, not only fixed wall time.
4. Test whether residual UNSAT candidates recur across repetitions/orderings.
5. Add crash injection around proposal completion, CEC PASS, and atomic
   checkpoint replacement.
6. Add a second independent verifier or direct proof artifact where feasible.
7. Implement persistent TFO only with candidate ownership or retry affinity.
8. Never count a smaller ABC output whose CEC timed out as verified.
