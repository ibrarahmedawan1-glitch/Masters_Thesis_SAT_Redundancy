# Thesis Report Writing Guide

This file is a living thesis-writing plan for the SAT-based ATPG redundancy
removal project. It collects the framing, chapter structure, claims,
experiments, result tables, and cautions that should go into the final LaTeX
report.

The strongest thesis framing is:

> A sound, checkpointed SAT-based framework for stuck-at redundancy removal in
> combinational AIG/AAG circuits, using exact proof tiers, rejection-only
> simulation, dynamic scheduling, and CEC-gated commits.

Avoid framing the work as "a tool that beats ABC". ABC is a broad synthesis
system. This thesis is stronger as a correctness-gated SAT-side redundancy
removal and analysis framework.

## Thesis Prose Style Lock

Use a formal EDA paper style for architecture and methodology sections. Prefer
continuous paragraphs with precise statements about circuit structure, SAT
semantics, proof boundaries, and empirical evidence. Avoid bullet lists inside
final thesis prose unless presenting an algorithm, theorem, table, or explicit
enumeration of contributions.

Avoid mechanical transition phrases and inflated adjectives. Do not use phrases
such as "delve into", "it is important to note", "crucial", "revolutionary",
"furthermore", "in conclusion", "to summarize", "a tapestry of", "sheds light
on", or "navigating the complexities". Move between paragraphs through the
engineering dependency itself: full-cone miter cost motivates TFO slicing;
TFO slicing requires a closure audit; UNSAT proposals require transactional
CEC-checked commits.

## Working Title Options

1. **A Checkpointed SAT-Based Framework for Sound Stuck-at Redundancy Removal in AIG Circuits**
2. **Sound SAT-Based Redundancy Removal for AIG Circuits Using Exact TFO Miters and Checkpointed Search**
3. **SAT-Based ATPG for CEC-Verified Redundancy Removal in And-Inverter Graphs**
4. **A Resource-Aware SAT Framework for Stuck-at Fault Redundancy Removal in AIG Circuits**

Best current title:

> **Sound SAT-Based Redundancy Removal for AIG Circuits Using Exact TFO Miters and Checkpointed Search**

## One-Sentence Thesis Claim

This thesis develops and evaluates a sound SAT-based optimization framework
that removes stuck-at redundant gates from AIG circuits only after exact UNSAT
proofs and independent CEC validation, while using checkpointing, proof tiers,
counterexample pruning, and dynamic scheduling to make the approach practical
on hard benchmark suites.

## Updated Abstract

This thesis presents the design and evaluation of a SAT-based ATPG and
logic-optimization framework for detecting and removing semantically redundant
stuck-at faults in And-Inverter Graph circuits. Unlike purely structural
optimization methods, which mainly exploit syntactic equivalence and local
rewriting, the proposed tool reasons about functional observability using
SAT-based fault miters. A candidate gate replacement is accepted only when the
corresponding stuck-at fault is proven unobservable; satisfiable queries are
treated as counterexamples, timeouts remain unresolved, and every accepted
circuit modification is verified by independent combinational equivalence
checking.

The work evolves from a baseline per-candidate miter into a checkpointed,
budget-aware optimization engine. The final architecture combines multiple
sound proof tiers, including transitive-fanin constancy checks, audited bounded
TFO windows, exact affected-output cone miters, and candidate-local exact
TFO-slice miters. To make long-running SAT search practical on hard arithmetic
and control benchmarks, the framework adds rejection-only random and
counterexample-guided simulation, conflict-budget laddering, persistent
checkpoint recovery, source-hash validation, and dynamic cross-circuit worker
scheduling. Parallel workers classify candidates on immutable circuit
snapshots, while all UNSAT-based reductions pass through a single
transactional coordinator that performs sequential rechecking, regenerates the
frontier after each commit, and requires ABC CEC before saving a new optimized
circuit.

The implementation is evaluated on ISCAS and EPFL AIGER benchmark circuits,
including difficult arithmetic designs such as division, square root,
logarithm, and sine, as well as control circuits such as memory control and
voter logic. The results show that SAT-based semantic reasoning can expose
redundancies missed by structural hashing and conventional synthesis flows,
but also reveal the central bottleneck of the problem: deep UNSAT proofs and
timeout-heavy hard frontiers. The thesis therefore contributes not only an
ATPG-based reduction tool, but also a practical study of solver selection,
proof decomposition, checkpoint safety, and scheduling strategies required to
make SAT-based redundancy removal robust on realistic benchmark suites.

## Recommended LaTeX Structure

Your current LaTeX skeleton is a good start, but the final thesis should have a
few more sections than the initial draft. A good structure is:

1. **Introduction**
   - Background and motivation
   - Problem statement
   - Research gap
   - Research questions
   - Contributions
   - Scope and assumptions
   - Thesis organization

2. **Background and State of the Art**
   - And-Inverter Graphs
   - AIGER AAG format
   - Boolean satisfiability and CDCL SAT
   - PySAT and solver backends
   - ATPG and stuck-at faults
   - SAT-based miters and CEC
   - ABC and structural synthesis baselines
   - Observability, TFI, TFO, and redundancy

3. **Problem Formulation and Correctness Boundary**
   - Circuit model
   - Candidate stuck-at replacement model
   - SAT query semantics: SAT, UNSAT, timeout
   - Correctness invariants
   - Why simulation is rejection-only
   - Why final ABC CEC is mandatory

4. **Algorithmic Development**
   - Algorithm 1: naive one-shot miter
   - Algorithm 2: structural sharing / early universal model
   - Algorithm 3: incremental ATPG
   - Algorithms 7 and 8: simulation/hybrid development
   - Algorithm 9: in-memory incremental SAT optimizer
   - Algorithm 10: checkpointed tiered SAT engine
   - Lessons learned from each stage

5. **Final Architecture**
   - TFI constancy tier
   - Audited bounded TFO window tier
   - Exact affected-output cone tier
   - Global configurable-fault miter
   - Exact candidate-local TFO miter
   - Counterexample-guided pruning
   - Checkpointing and source-hash validation
   - Parallel immutable workers
   - Sequential recheck and transactional CEC commits
   - Dynamic cross-circuit scheduling

6. **Experimental Methodology**
   - Hardware and software environment
   - Benchmarks: ISCAS, EPFL, synthetic/planted-live
   - Baselines: ABC strash, dc2, dch, fraig, resyn2, resyn2x2, dc2_fraig
   - Metrics
   - Timeout and budget policy
   - CEC validation policy
   - Reproducibility: scripts, checkpoints, result directories

7. **Results and Discussion**
   - Correctness and regression tests
   - Algorithm evolution results
   - Ablation study: proof tiers and CEX pruning
   - ABC baseline comparison
   - SAT/TFO before ABC vs ABC before SAT/TFO
   - Native exact-TFO benchmark campaigns
   - Solver selection and scheduling observations
   - Bottleneck analysis

8. **Limitations and Threats to Validity**
   - Python implementation overhead
   - SAT timeouts and unresolved candidates
   - Candidate-local TFO loses some learned-clause sharing
   - ABC is broader than stuck-at replacement
   - Benchmark representativeness
   - CEC timeout handling

9. **Conclusion and Future Work**
   - Summary of findings
   - What was achieved
   - What remains hard
   - Solver portfolios
   - Better yield-based scheduling
   - Safe grouped TFO solver reuse
   - C/C++ acceleration or ABC integration

## Suggested LaTeX Package Additions

Add these packages to the preamble if your template allows it:

```latex
\usepackage{booktabs}      % Professional tables
\usepackage{siunitx}       % Aligned numbers and units
\usepackage{subcaption}    % Subfigures
\usepackage{algorithm}
\usepackage{algpseudocode} % Pseudocode
\usepackage{xcolor}
\usepackage{listings}      % Code snippets
\usepackage{longtable}     % Long result tables
\usepackage{multirow}
\usepackage{array}
```

Useful `siunitx` setup:

```latex
\sisetup{
  detect-weight=true,
  detect-family=true,
  group-separator={,},
  group-minimum-digits=4
}
```

## Introduction Chapter: What To Add

### Background and Motivation

Important points:

- Digital circuits are optimized to reduce area, power, and delay.
- AIGs are a compact representation using AND nodes and complemented edges.
- Structural methods are fast and essential, but they mainly exploit syntactic
  or easily derivable equivalences.
- Some gates are semantically redundant because their effect cannot be observed
  at any primary output or latch boundary.
- SAT can reason about these semantic conditions, but naive SAT-based ATPG is
  too expensive on large or arithmetic circuits.

Possible paragraph:

> Modern logic synthesis relies heavily on graph-based representations such as
> And-Inverter Graphs, where optimization is commonly driven by structural
> hashing, rewriting, balancing, and equivalence-based merging. These methods
> are fast and effective, but they do not exhaust all semantic redundancies.
> A gate may be structurally unique and still be replaceable by a constant if
> the resulting stuck-at fault is unobservable at all real circuit outputs. Such
> cases require functional reasoning over the surrounding logic cone, which
> naturally leads to SAT-based ATPG and equivalence checking.

### Problem Statement

State the problem precisely:

> Given a combinational AIG/AAG circuit and an internal AND gate, determine
> whether replacing that gate by stuck-at-0 or stuck-at-1 preserves all primary
> output and latch-next behavior. If preservation can be proven, rewrite the
> circuit, reduce gate count, and verify the result against the original source.

### Research Gap

The gap is not "SAT has never been used for ATPG". It has. The gap is:

- making SAT-based stuck-at redundancy removal sound;
- making it resumable on long benchmark campaigns;
- combining exact proof tiers without unsafe heuristic acceptance;
- handling SAT, UNSAT, and timeout correctly;
- comparing it honestly with structural synthesis flows;
- studying the bottlenecks on hard EPFL/ISCAS circuits.

Good wording:

> Existing SAT-based ATPG concepts provide a formal mechanism for detecting
> redundant faults, but a practical optimization tool also needs safe
> checkpointing, repeated circuit mutation, proof-tier management,
> counterexample reuse, and independent validation after each accepted
> reduction. The research gap addressed in this thesis is therefore the design
> of a robust SAT-based reduction pipeline that preserves a strict correctness
> boundary while remaining usable on long-running benchmark suites.

### Research Questions

Use these in Chapter 1:

1. How can stuck-at gate replacement in AIGs be encoded as a SAT problem such
   that UNSAT is a sound acceptance proof?
2. Which proof tiers reduce SAT cost without compromising correctness?
3. How can timeouts and partial progress be represented so that long-running
   optimization remains resumable and auditable?
4. How does SAT-based redundancy removal compare with ABC structural synthesis
   flows, both before and after ABC optimization?
5. What are the main runtime bottlenecks on hard arithmetic and control
   benchmarks?

### Contributions

Use a concrete contribution list:

1. A SAT-based stuck-at redundancy-removal framework for combinational AIG/AAG
   circuits.
2. A sequence of increasingly robust algorithms from naive one-shot miters to
   incremental SAT and checkpointed budget-cycling search.
3. Sound proof tiers: TFI constancy, audited bounded TFO windows, exact
   affected-output cone miters, global configurable-fault miters, and
   candidate-local exact TFO miters.
4. Rejection-only simulation and CEX pruning that reduce SAT work without using
   simulation as an acceptance proof.
5. A checkpoint/resume mechanism with source-hash validation, frontier
   serialization, conflict-budget history, and safe partial outputs.
6. A transactional parallel architecture with immutable worker snapshots,
   sequential UNSAT rechecks, frontier regeneration, and ABC CEC-gated commits.
7. An empirical evaluation on ISCAS and EPFL benchmarks, including comparison
   with ABC flows and analysis of SAT timeout bottlenecks.

### Scope and Assumptions

Be very clear:

- Input circuits are AIG/AAG.
- Latches, if present, are treated as combinational cut boundaries.
- The thesis does not claim sequential redundancy removal.
- A candidate is accepted only by exact UNSAT proof.
- SAT means observable counterexample, so reject or prune.
- Timeout means unresolved, not non-redundant.
- Simulation is never proof of redundancy.
- Final ABC CEC PASS is required for reported optimized outputs.
- ABC baselines perform broader synthesis than stuck-at constant replacement.

## Correct Fault Model To Present

Your old equation only describes one forced-zero style. The final report should
present both stuck-at-0 and stuck-at-1 controls.

For an AIG node:

```latex
n_i = a_i \land b_i
```

Introduce fault controls \(f^0_i\) and \(f^1_i\), where \(f^0_i\) activates a
stuck-at-0 replacement and \(f^1_i\) activates a stuck-at-1 replacement.

```latex
\neg(f^0_i \land f^1_i)
```

The faulty node can be written as:

```latex
n'_i = (n_i \land \neg f^0_i) \lor f^1_i
```

Candidate assumptions:

- SA0 candidate: \(f^0_i = 1\), \(f^1_i = 0\)
- SA1 candidate: \(f^1_i = 1\), \(f^0_i = 0\)
- inactive gates: both controls disabled
- accepted replacements remain active in the greedy context
- miter output asserted

The redundancy condition:

```latex
\mathrm{UNSAT}(C_{\mathrm{good}} \land C_{\mathrm{faulty}} \land M)
```

where \(M\) asserts that at least one observable root differs.

Interpretation:

- SAT: a distinguishing assignment exists, so the candidate is rejected.
- UNSAT: the stuck-at replacement is unobservable under the encoded observable
  boundary, so the candidate may be accepted.
- Timeout: no conclusion; keep candidate unresolved.

## CEC Audit Policy

Do not remove final CEC from the tool or from the thesis methodology. The SAT
encoding is the proof mechanism for a candidate-local stuck-at replacement, but
the implemented tool also performs parsing, candidate indexing, AAG rewriting,
checkpoint recovery, parallel worker scheduling, sequential rechecks, and
optional ABC cleanup. Final CEC is therefore the independent transaction
boundary that validates the complete output artifact, not a substitute for the
SAT proof.

The correct thesis wording is that the encoding is designed to be exact under
its stated observable boundary and that the implementation accepts reductions
only when this exact proof is followed by independent equivalence checking.
This is stronger than omitting CEC, because it records an external audit for
every reported optimized circuit.

Repository scan on 2026-06-22 found that modern summary files with dynamic or
native TFO targets reported `252` CEC-passed commits and `0` CEC-failed
commits. One older dynamic TFO run from 2026-06-15 had worker errors, but those
were worker failures, not CEC-failed commits. Early Algorithm-3 CSV files with
`FAIL` rows should be treated as development history and not as final
architecture results.

## Encoding Soundness Stress Plan

The encoding should be defended with tests that do not rely only on final ABC
CEC. The strongest validation layers are:

1. Bounded exhaustive truth-table checks for all production SAT encodings on
   small AIG spaces.
2. Exact TFO closure and side-input reuse tests against truth-table semantics.
3. Exact TFO versus full-cone/global-miter agreement on the same candidates.
4. Read-only serial/parallel worker agreement to validate the distributed
   worker path.
5. Final CEC-gated pipeline tests to validate the produced AAG artifact.
6. Negative controls where a deliberately corrupted output must fail both ABC
   CEC and the internal SAT miter.

Latest quick validation on 2026-06-22:

```bash
venv/bin/python test_encoding_soundness_bounded.py \
  --max-inputs 2 --max-gates 2 --progress-interval 0
```

Result: `BOUNDED ENCODING SOUNDNESS PASS`; `37,416` candidates checked across
global, TFI, persistent TFI, cone, grouped cone, exact TFO cone, audited window,
and rewrite semantics.

```bash
venv/bin/python test_alg10_tfo_miter.py
```

Result: `Alg10 exact TFO miter tests passed`.

```bash
venv/bin/python test_alg10_frontier_shard_probe.py
```

Result: `alg10 frontier shard probe tests passed`.

The optional depth-3 exhaustive extension is much heavier and should be run
after long benchmark campaigns finish:

```bash
venv/bin/python test_encoding_soundness_bounded.py \
  --max-inputs 2 --max-gates 2 --include-depth3 --progress-interval 10000
```

## Professor Defense: SAT Encoding Versus CEC

The professor's likely question is whether the optimized circuit would still be
correct if CEC were removed. The answer should be precise:

> The SAT encoding is the primary proof engine and is designed to be sufficient
> for each candidate under the stated observable-root boundary. CEC is not used
> to decide SAT or UNSAT. CEC is the final independent audit of the produced AAG
> artifact after parsing, rewriting, checkpointing, worker scheduling, and
> commits. If all implementation layers are correct, a no-CEC run should still
> produce an equivalent circuit. The thesis keeps CEC because independent
> commit-time validation is standard defense-in-depth for a research optimizer,
> not because the encoding is intentionally incomplete.

Do not phrase CEC as "proving the encoding". Phrase it as:

> SAT proves candidate redundancy; bounded exhaustive tests and TFO/full-miter
> agreement validate the encoding; ABC CEC independently validates every
> committed output artifact.

This distinction protects the thesis from the criticism that CEC is a crutch.
The encoding must be defended by truth-table, full-miter, closure-audit, and
negative-control tests. CEC then demonstrates that no reported final output
escaped those safeguards incorrectly.

### Existing Coverage From The Current Codebase

Already covered and suitable for writing:

- Bounded exhaustive production-encoding checks on small AIG spaces:
  `37,416` candidates passed on 2026-06-22.
- Exact TFO tests against truth-table semantics.
- Exact TFO versus full-cone/global-miter agreement.
- Complemented fanout, reconvergence, side-input reuse, multi-output roots,
  and latch-next roots in `test_alg10_tfo_miter.py`.
- Corrupted TFO slice and corrupt fanout negative controls.
- Corrupt grouped-cone and pair-assumption vectors.
- Read-only serial/parallel worker agreement.
- CEC-failure rollback in the parallel coordinator.
- Stale phase-resume and CEX-pool metadata fallback.
- Source-change detection in the dynamic campaign.
- Modern dynamic/native TFO summaries: `252` CEC-passed commits and `0`
  CEC-failed commits in the 2026-06-22 repository scan.

### Remaining High-Value Tests Before Professor Delivery

These are the small tests worth adding or running if time allows. They should
not block writing unless a failure appears.

1. **Committed-side-input test.** Build a small circuit where one accepted
   replacement changes a side-input value used by a later candidate's TFO
   slice. Verify the later TFO miter uses the current committed working AAG,
   not the original source values.
2. **Two-latch boundary test.** Build a small AAG with two latches and verify
   that latch-current variables are treated as primary inputs and latch-next
   functions are included as observable roots.
3. **TFO-worker plus global-recheck mini-run.** Run a small campaign where
   workers use exact TFO but the coordinator uses the global/full miter for
   recheck. This gives encoding diversity: optimized worker proof, simpler
   independent recheck, then CEC.
4. **False-worker-UNSAT injection.** Force a worker to propose a known
   non-redundant candidate and verify that coordinator recheck rejects it.
5. **No-CEC shadow comparison.** On small circuits only, run a proof-only
   variant that does not use CEC as an in-loop commit gate, then run external
   CEC afterward and compare the accepted removals with the normal CEC-gated
   mode. This is a validation experiment, not the production mode.
6. **Long reconvergent path stress.** Generate a candidate with both a short
   fanout path and a long reconvergent path to the same root. Verify affected
   roots and TFO closure remain complete.

`test_professor_encoding_controls.py` was added on 2026-06-22 to cover these
remaining focused cases. It currently checks committed-state side inputs,
two-latch cut roots, TFO workers with global coordinator recheck, false worker
UNSAT proposals, and a long reconvergent TFO path.

Use the following runner after the long benchmark campaign finishes:

```bash
./run_professor_encoding_validation.sh quick \
  results_optimized/professor_encoding_validation_quick_20260622
```

The quick mode runs the compact professor controls, exact TFO miter tests,
frontier shard TFO/global agreement, parallel commit coordinator tests, and
the bounded `2x2` encoding soundness sweep.

```bash
./run_professor_encoding_validation.sh full \
  results_optimized/professor_encoding_validation_full_20260622
```

The full mode additionally runs the depth-3 bounded encoding extension and the
20-second thesis correctness stress suite with `c7552` and EPFL probes.
To cap each individual validation step, set `VALIDATION_STEP_TIMEOUT_SECONDS`.
For example:

```bash
VALIDATION_STEP_TIMEOUT_SECONDS=7200 \
  ./run_professor_encoding_validation.sh full \
  results_optimized/professor_encoding_validation_full_20260622
```

```bash
./run_professor_encoding_validation.sh extended \
  results_optimized/professor_encoding_validation_extended_20260622
```

The extended mode adds a larger `3x2` bounded sweep and a 40-second stress
suite. Use this only when the machine is otherwise free.

Latest full validation result on 2026-06-22:

- Output directory:
  `results_optimized/professor_encoding_validation_full_20260622`
- `test_professor_encoding_controls.py`: PASS.
- `test_alg10_tfo_miter.py`: PASS.
- `test_alg10_frontier_shard_probe.py`: PASS.
- `test_alg10_parallel_commit_coordinator.py`: PASS.
- Bounded depth-3 encoding soundness: PASS; `536,376` candidates over `92,628`
  small circuits checked against truth-table semantics across global, TFI,
  persistent TFI, cone, grouped cone, exact TFO cone, window, and rewrite
  checks.
- Thesis correctness stress: `36/36` rows PASS, `0` required failures.
- Negative corrupt-output control: PASS because ABC CEC and the internal SAT
  miter both reported `FAIL` on the deliberately corrupted circuit.

The current pipeline already supports part of item 3 in
`alg10_parallel_commit_coordinator.py`, where `worker_engine="tfo"` and
`recheck_engine="global"` can be configured in the standalone coordinator.
The dynamic pool currently uses TFO recheck by default, so the global-recheck
mode should be treated as a focused validation run rather than the main
overnight performance configuration.

### Risks And Defenses

The main risks raised by external reviews are real but bounded:

- Missing observable root: defend with latch/output root tests and affected-root
  truth-table checks.
- Incorrect side-input reuse: defend with TFO closure proof plus committed-state
  side-input tests.
- Shared worker/coordinator encoding bug: defend with TFO-vs-global agreement,
  optional global coordinator recheck, and CEC.
- Stale worker proposal: defend with generation hashes, sequential recheck, and
  stale-result tests.
- Checkpoint mismatch: defend with source/work SHA validation and stale-resume
  fallback tests.
- Overclaiming CEC: defend by separating encoding validation from final artifact
  validation in the writing.

Safe claim:

> The tool is a formally audited SAT-based stuck-at redundancy-removal
> framework. Candidate acceptance is based on exact UNSAT proofs under a
> complete observable-root boundary, and every reported optimized circuit is
> independently CEC-checked before being counted as a valid result.

## Methodology Chapter Notes

### Algorithm Evolution Table

Include a table similar to this:

| Stage | File | Purpose | Thesis role |
| --- | --- | --- | --- |
| Algorithm 1 | `optimizer_alg1.py` | Naive per-candidate SAT miter | Baseline |
| Algorithm 2 | `optimizer_alg2.py` | Early structural sharing | Intermediate |
| Algorithm 3 | `optimizer_alg3.py` | Incremental ATPG direction | Intermediate |
| Algorithm 7 | `optimizer_alg7_iterative.py` | Simulation plus iterative surgery | Development step |
| Algorithm 8 | `optimizer_alg8_hybrid.py` | Hybrid optimizer with CEC | Baseline/comparison |
| Algorithm 9 | `optimizer_alg9_incremental.py` | In-memory incremental SAT | Mature SAT engine |
| Algorithm 10 | `optimizer_alg10_tiered.py` | Checkpointed tiered SAT | Main thesis engine |
| Dynamic TFO | `alg10_dynamic_tfo_pool_campaign.py` | Parallel exact-TFO campaign | Final research shell |

### Algorithm 9

Explain:

- one good circuit and one configurable faulty circuit;
- stuck-at controls for every gate;
- solver assumptions activate exactly one candidate plus accepted controls;
- committed replacements remain part of future queries;
- final output is CEC checked.

Good thesis role:

> Algorithm 9 demonstrates the feasibility of committed incremental SAT
> redundancy removal and provides the baseline for the later checkpointed
> architecture.

### Algorithm 10

Explain:

- checkpointing because hard circuits cannot finish in one run;
- conflict-budget ladder;
- proof tiers;
- frontier serialization;
- CEX pruning;
- final CEC.

Good thesis role:

> Algorithm 10 is the main production-style SAT research shell: it stores
> unresolved obligations, preserves safe partial results, and allows later
> deeper runs without changing the correctness boundary.

### Dynamic Exact-TFO Campaign

Explain:

- each worker gets immutable circuit snapshot;
- worker SAT result can reject a candidate;
- worker UNSAT only proposes;
- coordinator sequentially rechecks proposals;
- CEC must pass before commit;
- frontier regenerates after commit because gate indices and observability may
  change;
- unrelated circuits can continue while one circuit is in a recheck/CEC barrier.

This is one of the strongest engineering/research contributions.

## Experiments To Include

### Experiment 1: Correctness and Regression

Goal:

Show that the implementation does not rely on unsafe SAT encodings.

Evidence to include:

- Algorithms 1-9 on `c17`: all ABC CEC PASS.
- Algorithms 8-9 on `c432`: ABC CEC PASS; Algorithm 9 removed gates.
- `test_alg10_checkpoint.py`: checkpoint/resume correctness.
- Exact TFO tests:
  - TFO closure audit;
  - exact TFO vs full-cone agreement;
  - full `c432` TFO pipeline with ABC CEC pass;
  - coordinator recheck and CEC transaction tests;
  - source-change checkpoint guard.

Table columns:

| Test | Purpose | Result |
| --- | --- | --- |
| `test_alg10_checkpoint.py` | checkpoint and resume invariants | PASS |
| `test_alg10_tfo_miter.py` | exact TFO encoding | PASS |
| `test_alg10_parallel_commit_coordinator.py` | transactional commit | PASS |
| `test_algorithms_1_to_10.py` | broad algorithm smoke | PASS |

### Experiment 2: Algorithm Evolution

Goal:

Show why the architecture evolved.

Use:

- Algorithm 1 naive miter as slow baseline.
- Algorithm 9 as mature incremental SAT engine.
- Algorithm 10 as checkpointed hard-circuit engine.

Important recorded result:

- Algorithm 9 full mixed run: `235/235` CEC PASS, `111.27s` optimizer time,
  category reductions recorded.
- Algorithm 9 planted-live fast: `5/5` CEC PASS, `40` SAT-induced AND2
  removals, `0.97s`.
- Algorithm 9 planted-live exhaustive: same `40` removals, `20.68s`, showing
  exhaustive search was much more expensive.

Use file:

- `THESIS_EXPERIMENT_HISTORY.md`

### Experiment 3: Proof-Tier Ablation

Goal:

Show which SAT tiers helped and where.

Important observations from existing ablations:

- `c7552`: window and CEX variants reached `14` removals faster than baseline
  tiering.
- EPFL `sin`: tiered/TFO/TFI profiles found reductions that global-only short
  runs missed.
- `sqrt`: CEX plus window found `36` removals in a short run where earlier
  variants found none.
- `c6288`: no removals, but CEX pruning greatly reduced SAT work; this is a
  useful negative result.

Use table:

| Circuit | Baseline | Variant | Removed | SAT time | CEC |
| --- | ---: | --- | ---: | ---: | --- |

Key numbers from `THESIS_EXPERIMENT_HISTORY.md`:

- `c7552`, 15s, global-only current: `14` removed, SAT `14.98s`.
- `c7552`, 15s, global-only CEX: `14` removed, SAT `3.12s`.
- EPFL `sin`, 20s, current: `31` removed, SAT `19.98s`.
- EPFL `sin`, 20s, CEX window current: `39` removed, SAT `11.16s`.
- `c6288`, 20s, current: `0` removed, SAT `16.28s`.
- `c6288`, 20s, CEX current: `0` removed, SAT `2.46s`.
- EPFL `sqrt`, 20s, CEX window current: `36` removed, SAT `3.16s`.

### Experiment 4: ABC Baseline Comparison

Goal:

Show that ABC is a broader synthesis baseline and that SAT/TFO is
complementary, not a general ABC replacement.

Use script:

- `abc_baseline_runner.py`

ABC flows:

- `strash`
- `dc2`
- `dch`
- `fraig`
- `resyn2`
- `resyn2x2`
- `dc2_fraig`

Important existing baseline facts:

- `strash`: 0 gates removed in recovered-output validation.
- `fraig`: 28,265 gates removed in recovered-output validation.
- `dc2`: 32,484 gates removed in recovered-output validation.
- `dc2_fraig`: strong combined baseline; use for ordering comparison.

Warning:

Do not claim SAT/TFO beats ABC in area. ABC can do broad rewriting, balancing,
fraiging, and resynthesis.

### Experiment 5: Transformation Ordering

Goal:

Answer whether SAT/TFO finds something different from ABC.

Compare:

1. `Original -> ABC`
2. `Original -> SAT/TFO`
3. `Original -> SAT/TFO -> ABC`
4. `Original -> ABC -> SAT/TFO`

Use file:

- `ABC_SAT_ORDERING_COMPARISON_2026-06-15.csv`

Existing key result for common 5 circuits:

| Flow | Total gates |
| --- | ---: |
| Original -> dc2_fraig | 115,768 |
| SAT/TFO -> dc2_fraig | 115,537 |
| Improvement from SAT preprocessing | 227 |

Per-circuit effect:

| Circuit | Effect of SAT before ABC |
| --- | ---: |
| `sin` | +27 gates better |
| `sqrt` | +10 gates better |
| `div` | -27 gates worse |
| `log2` | +165 gates better |
| `mem_ctrl` | +52 gates better |

Interpretation:

> Direct gate-by-gate overlap with ABC is not meaningful because ABC rewrites
> the graph and changes node identities. Instead, transformation ordering shows
> whether SAT/TFO exposes changes that lead to a smaller CEC-equivalent final
> network after ABC.

### Experiment 6: Residual SAT/TFO After ABC

Goal:

Show whether exact stuck-at redundancies remain after ABC.

Use script:

- `post_abc_residual_tfo_experiment.py`
- Preferred wrapper: `abc_then_tfo_whole_suite_experiment.py`

Existing result:

- `Original -> dc2_fraig`: 115,768 gates for common 5.
- `Original -> dc2_fraig -> TFO`: 115,764 gates.
- Residual exact-TFO improvement: 4 gates.

Interpretation:

The residual number is small, but important: it demonstrates that after a
strong structural flow, some exact stuck-at redundancies can still remain.

Important CEC rule:

Do not run the residual SAT/TFO comparison on arbitrary ABC outputs. First run
direct ABC CEC from the original circuit to the ABC output and keep only
`Verify=PASS` rows. The wrapper `abc_then_tfo_whole_suite_experiment.py` does
this filtering automatically:

```bash
venv/bin/python abc_then_tfo_whole_suite_experiment.py \
  --output-root results_optimized/abc_then_tfo_whole_suite_meeting \
  --flows strash,balance,rewrite,refactor,dc2,dch,fraig,resyn2,resyn2x2,dc2_fraig,dch_resyn2 \
  --abc-timeout 300 \
  --cec-timeout 180 \
  --seconds-per-flow 90 \
  --jobs 12 \
  --budgets 10000 \
  --max-generated-budget 10000 \
  --deadline-reserve-seconds 5 \
  --unknown-task-guard-seconds 10
```

The wrapper produces:

- `abc_baselines_original/`: ABC-only details, flow summary, and best-by-circuit
  CSVs.
- `abc_cec_pass_outputs/`: only ABC outputs that passed direct CEC.
- `post_abc_residual/`: per-flow `ABC -> SAT/TFO` residual results.
- `MEETING_SUMMARY.md`: compact table for discussion.

Smoke-test result:

- `results_optimized/abc_then_tfo_smoke_20260621b/MEETING_SUMMARY.md`
- On `c432`, `strash -> SAT/TFO` removed 4 residual gates and
  `dc2_fraig -> SAT/TFO` removed 2 residual gates.
- Both residual tests finished with zero unresolved candidates, zero worker
  errors, and CEC-clean commits.

### Experiment 7: Native Exact-TFO Full-Suite Campaign

Goal:

Show behavior of the final native exact-TFO scheduler on the full raw suite.

Important run:

- `results_optimized/parallel_tfo_native_tfo_main_iscas-epfl_all_2026-06-18_04-19-57`

Result summary:

- Full raw ISCAS + EPFL suite from zero.
- 33 circuits.
- 48-hour time budget.
- Final status: `TIME_BUDGET_COMPLETE`.
- Complete circuits: `26/33`.
- Total removed: `455`.
- Total unresolved: `691230`.
- No worker errors, stale results, CEC failures, or stale commits.

Hard unfinished circuits:

| Circuit | Removed | Unresolved | Notes |
| --- | ---: | ---: | --- |
| `epfl_arithmetic_hyp` | 0 | 427,204 | severe timeout trap |
| `epfl_random_control_mem_ctrl` | 56 | 81,192 | productive but large |
| `epfl_arithmetic_div` | 21 | 66,679 | timeout heavy |
| `epfl_arithmetic_log2` | 145 | 62,335 | productive |
| `epfl_arithmetic_sqrt` | 8 | 32,653 | hard arithmetic |
| `epfl_random_control_voter` | 156 | 21,159 | productive |
| `epfl_arithmetic_sin` | 37 | 8 | near finish, deep recheck pending |

Interpretation:

This run is important because it shows the real bottleneck. The final tool is
sound and robust, but hard circuits become dominated by deep UNSAT timeouts.

### Experiment 8: Solver Selection Study

Goal:

Show that CaDiCaL is strong but not universally best.

Use files:

- `results_optimized/solver_matrix_10k_latest_checkpoints_20260620.json`
- `results_optimized/solver_matrix_50k_latest_checkpoints_20260620.json`

Existing observations:

- `mem_ctrl` at 10k: all solvers quickly found SAT rejects.
- `voter` at 10k: `cadical195` resolved all sampled candidates; `cadical153`
  was fast but had timeouts.
- `sqrt` at 10k and 50k: `m22` and `g4` were often faster than `cadical153`.
- `div` at 50k: all tested solvers found the same 2 UNSAT proposals and 2 SAT
  rejects; `m22` was fastest in the sample.
- `sin` high-tier proposals remained hard; `cadical153` was still competitive
  for deep proof rechecks.

Interpretation:

Solver choice should be discussed as workload-dependent:

- low budget SAT rejection may prefer `g4`, `m22`, or `cadical195`;
- deep UNSAT rechecks may still favor CaDiCaL;
- the thesis should present this as a limited solver study, not a universal
  solver ranking.

### Experiment 9: Non-ABC Tool and Literature Positioning

Goal:

Place the tool against comparable ATPG, synthesis, and formal-reasoning
systems without claiming equivalence where the objectives differ.

Best practical comparisons:

- ABC flows: main industrial-strength synthesis baseline, including `strash`,
  `dc2`, `dch`, `fraig`, `resyn2`, `resyn2x2`, `dc2_fraig`, and `dch_resyn2`.
- Yosys optimization passes: immediate non-ABC structural baseline because
  `yosys` is installed locally and supports `read_aiger`/`write_aiger`.
- Atalanta/HOPE: related-work comparison for stuck-at ATPG and fault
  simulation; useful for positioning, but not a direct AIG optimization
  baseline unless installed, converted, and audited.
- Fault by AUCOHL: open-source DFT toolchain with ATPG and fault simulation;
  useful related work, but installation/licensing/tool-flow differences should
  be handled separately.
- mockturtle/EPFL logic synthesis libraries: modern logic-network framework
  for AIG/MIG/k-LUT optimization; useful as synthesis infrastructure context,
  not as a direct stuck-at redundancy-removal competitor.
- SAT-based ATPG literature: use papers on SAT-modeled stuck-at faults,
  redundant fault detection, and conflict-driven ATPG to show that the thesis
  contribution is a sound, checkpointed, CEC-gated optimization pipeline rather
  than the invention of SAT-based ATPG itself.

Expected standing:

- Against ABC, the tool should be presented as complementary. ABC will often
  win total area because it performs broad rewriting and fraiging. The SAT/TFO
  tool is strongest where it removes CEC-proven stuck-at redundancies that
  remain before or after a structural flow.
- Against Yosys, the tool is expected to find different reductions because
  Yosys optimizations are structural/RTL-oriented, while this work accepts only
  SAT-proven unobservability of gate replacements. Yosys is a good additional
  baseline because it is independent of ABC.
- Against Atalanta/Fault, the tool is not a test-pattern generator replacement.
  Its distinct contribution is using ATPG-style stuck-at reasoning to mutate
  and reduce AIGs under transactional CEC validation.
- Against mockturtle, the distinction is similar to ABC: mockturtle provides
  synthesis algorithms and data structures, while this work studies
  proof-driven redundancy removal with persistent unresolved obligations.

## Result Tables To Prepare

### Table A: Benchmark Suite

Columns:

- Circuit
- Suite
- Inputs
- Outputs
- AND gates
- Category
- Notes

### Table B: Correctness Tests

Columns:

- Test
- Purpose
- Circuits
- Result
- Notes

### Table C: Algorithm Evolution

Columns:

- Algorithm
- Main idea
- Main limitation
- What it contributed to final design

### Table D: Main SAT/TFO Reductions

Columns:

- Circuit
- Original gates
- Final gates
- Gates removed
- SAT rejects
- UNSAT accepts
- Timeouts
- Unresolved
- CEC result
- Runtime

### Table E: ABC Baseline

Columns:

- Circuit
- Original gates
- ABC flow
- ABC final gates
- ABC removed
- CEC result
- Runtime

### Table F: Ordering Comparison

Columns:

- Circuit
- ABC only gates
- SAT/TFO then ABC gates
- ABC then SAT/TFO gates
- Delta favoring SAT preprocessing
- Interpretation

### Table G: Solver Matrix

Columns:

- Circuit
- Budget
- Solver
- SAT rejects
- UNSAT proposals
- Timeouts
- Wall time
- Best observed use

### Table H: Native Full-Suite Campaign

Columns:

- Circuit
- Removed
- Unresolved
- Worker SAT rejects
- Worker timeouts
- UNSAT proposals
- CEC commits
- Status

## Figures To Create

1. AIG node and complemented-edge illustration.
2. Stuck-at fault injection model.
3. SAT miter: good circuit vs faulty circuit.
4. Algorithm evolution timeline from Alg1 to Alg10.
5. Proof-tier pipeline: TFI -> window -> cone -> global/TFO.
6. Exact TFO-slice construction diagram.
7. Dynamic worker/coordinator architecture.
8. Checkpoint/resume state machine.
9. Bar chart: removed gates by circuit for SAT/TFO.
10. Bar chart: ABC only vs SAT/TFO then ABC.
11. Timeout/unresolved distribution for hard circuits.
12. Solver matrix heatmap or grouped bars.

## Claims That Are Safe

These are defensible:

- The tool performs SAT-based stuck-at redundancy removal on AIG/AAG circuits.
- UNSAT is the only acceptance condition.
- SAT and simulation are rejection-only.
- Timeouts remain unresolved.
- Every reported optimized output is checked by ABC CEC.
- Checkpointing enables safe continuation of hard circuits.
- Exact TFO decomposition can reduce CNF size compared with global/full-cone
  encodings for candidate-local queries.
- SAT/TFO can complement ABC, as shown by ordering and residual experiments.
- Hard arithmetic circuits are dominated by deep UNSAT proof cost.
- The experiments are reproducible in the research sense: commands, input
  directories, checkpoint paths, solver budgets, worker counts, source hashes,
  CEC results, and generated CSV/JSON summaries are recorded with each run.

## Claims To Avoid Or Qualify

Avoid:

- "The tool beats ABC."
- "The tool is a complete industrial ATPG replacement."
- "Timeout means non-redundant."
- "Simulation proves redundancy."
- "Exact TFO always improves runtime."
- "CaDiCaL is always the best solver."
- "The full benchmark suite was solved completely."
- "Gate-by-gate overlap with ABC can be directly measured after rewriting."
- "ABC outputs are valid just because ABC wrote a file."
- "The GPU accelerates the current PySAT proof engine."

Better wording:

- "The tool complements structural synthesis."
- "The method exposes semantically redundant stuck-at replacements under strict
  CEC validation."
- "The final system is a research prototype with production-style safeguards."
- "The bottleneck is proof cost on timeout-heavy hard frontiers."

## Limitations Section

Important limitations to discuss honestly:

- Python overhead and process startup cost.
- Candidate-local TFO instances do not safely share learned clauses across
  structurally different CNFs.
- Sequential recheck and CEC barriers reduce parallel utilization.
- Hard circuits such as `hyp`, `div`, and `sqrt` can consume many CPU hours.
- ABC baselines perform broader transformations than the SAT tool.
- Some CEC checks can timeout on very large ABC outputs.
- Benchmark conclusions depend on timeout budgets and solver choice.
- PySAT/CDCL solving is CPU-oriented and branch-heavy; the current tool does
  not use GPU acceleration for exact SAT proofs.

## Future Work

Good future work topics:

1. Solver portfolio scheduling: choose `g4`, `m22`, `cadical153`, or
   `cadical195` by budget tier and circuit class.
2. Yield-based cross-circuit scheduling: prioritize circuits with high
   classification rate.
3. Cooldown for hard timeout candidates: defer deep retry candidates until
   shallow work is exhausted.
4. Safe root-set grouping: reuse a solver only for candidates with identical
   affected observable root sets and identical TFO structure.
5. C/C++ implementation of hot SAT encoding and simulation paths.
6. Better integration with ABC or AIG rewriting before and after SAT passes.
7. More formal proof of the exact TFO encoding and complete-cut window audit.
8. More extensive benchmark study with fixed hardware and reproducible scripts.
9. GPU-assisted rejection-only simulation or candidate screening. An RTX 3060
   12GB could help with massively parallel random/fault simulation or feature
   extraction, but it should not be claimed as an accelerator for PySAT/CDCL
   UNSAT proofs unless a dedicated GPU SAT backend is added and validated.

## Suggested Chapter 1 Draft Skeleton

```latex
\chapter{Introduction}

\section{Background and Motivation}
Digital circuit optimization aims to reduce implementation cost while
preserving observable behavior. And-Inverter Graphs provide a compact
representation for this task, and structural synthesis tools such as ABC are
highly effective at rewriting, balancing, and merging logic. However,
structural similarity is not the same as semantic redundancy. A gate may be
structurally unique but still replaceable by a constant if the resulting fault
cannot be observed at any output.

\section{Problem Statement}
This thesis studies the problem of identifying such stuck-at redundant gates in
AIG circuits. For each internal AND gate, the tool considers stuck-at-0 and
stuck-at-1 replacements and asks whether the modified circuit can be
distinguished from the original. If no distinguishing assignment exists, the
replacement is safe and can reduce the circuit.

\section{Research Gap}
SAT-based ATPG provides a formal mechanism for proving redundancy, but naive
per-candidate miters do not scale to hard benchmark circuits. A practical
optimization framework must handle timeouts, repeated circuit mutation,
checkpoint recovery, proof-tier escalation, and independent equivalence
checking. This thesis addresses that gap by developing a sound, resumable, and
auditable SAT-based reduction pipeline.

\section{Contributions}
The contributions of this thesis are ...

\section{Scope}
The work is restricted to combinational reasoning over AIG/AAG circuits. Latch
outputs and latch inputs, when present, are treated as cut boundaries. The tool
does not claim sequential redundancy removal.

\section{Thesis Organization}
Chapter 2 introduces AIGs, SAT, ATPG, and CEC. Chapter 3 formalizes the
redundancy problem and correctness boundary. Chapter 4 describes the algorithmic
development. Chapter 5 presents the final architecture. Chapter 6 describes the
experimental methodology. Chapter 7 evaluates the implementation. Chapter 8
discusses limitations and future work.
```

## VS Code LaTeX Setup

Closest Overleaf-like local extension:

- **LaTeX Workshop** by James Yu.

It provides:

- build on save;
- internal PDF preview;
- SyncTeX source/PDF navigation;
- citation and reference autocomplete;
- LaTeX error parsing;
- snippets and outline view.

You still need a LaTeX distribution installed:

- Linux: TeX Live is the cleanest choice.
- Windows: TeX Live or MiKTeX.
- Lightweight option: TinyTeX, but it may require installing missing packages.

Useful install commands on Ubuntu/Debian if needed:

```bash
sudo apt update
sudo apt install texlive-full latexmk chktex
```

If disk space is a concern, install a smaller TeX Live set first and add
packages as needed.

## Files In This Repo To Use While Writing

- `THESIS_EXPERIMENT_HISTORY.md`: best high-level history and decisions.
- `FEEDBACK_VALIDATION_RESULTS_2026-06-15.md`: validation and ABC comparison
  notes.
- `ABC_SAT_ORDERING_COMPARISON_2026-06-15.csv`: ordering comparison table.
- `COMMANDS.md`: reproducible commands.
- `Readme.md`: concise tool overview.
- `alg10_dynamic_tfo_pool_campaign.py`: dynamic final architecture.
- `alg10_parallel_commit_coordinator.py`: transactional commit logic.
- `alg10_frontier_shard_probe.py`: exact TFO worker logic.
- `optimizer_alg10_tiered.py`: main checkpointed SAT engine.
- `abc_baseline_runner.py`: ABC baseline generation.
- `post_abc_residual_tfo_experiment.py`: residual SAT/TFO after ABC.
- `abc_then_tfo_whole_suite_experiment.py`: ABC baseline plus CEC-pass filter
  plus per-flow post-ABC SAT/TFO residual wrapper.

## Open TODOs Before Final Thesis Tables

1. Decide the final benchmark set for thesis tables.
2. Freeze the final best SAT/TFO run data.
3. Regenerate ABC baselines on the same exact inputs.
4. Build clean tables for:
   - SAT/TFO only;
   - ABC only;
   - SAT/TFO then ABC;
   - ABC then SAT/TFO.
5. Mark any CEC timeout as not comparable.
6. Do not include ongoing campaign results until they finish and pass audit.
7. Generate plots from stable CSV/JSON result files.
8. Write the limitations section before the conclusion, not as an afterthought.
9. Add a Yosys baseline wrapper for AIGER inputs and CEC-filtered outputs.
10. Add a related-work comparison table for ABC, Yosys, Atalanta/HOPE, Fault,
    mockturtle, and SAT-based ATPG papers.
11. Select the 3-4 strongest favorable comparisons for the main results:
    ABC ordering/residual, Yosys structural baseline, SAT/TFO proof-tier
    ablation, and solver/scheduling study.
12. Include 1-2 honest negative or boundary comparisons, such as ABC broad
    area wins and timeout-heavy hard circuits, to keep the thesis empirically
    credible.
