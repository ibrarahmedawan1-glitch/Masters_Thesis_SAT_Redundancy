# Thesis Algorithm Pseudocode

This file collects thesis-facing pseudocode for the SAT-based ATPG redundancy
removal algorithms developed in this project. The goal is clarity for the
report, not a line-by-line copy of the Python implementation.

The common correctness rule for the final thesis is:

- `UNSAT` may prove and accept a stuck-at replacement.
- `SAT` means an observable counterexample exists, so the candidate is rejected
  or used only for rejection/pruning.
- `TIMEOUT` means unresolved, never non-redundant.
- Every reported optimized circuit must pass independent ABC CEC.

## Common Definitions

Let an AIG gate be:

```text
g_i = a_i AND b_i
```

A stuck-at replacement candidate is:

```text
(i, v) where i is the gate index and v in {0, 1}
```

The configurable faulty gate model used by the later algorithms is:

```text
g'_i = (g_i AND NOT f0_i) OR f1_i
```

with the mutex constraint:

```text
NOT (f0_i AND f1_i)
```

Interpretation:

```text
f0_i = 1, f1_i = 0  => stuck-at-0 candidate
f0_i = 0, f1_i = 1  => stuck-at-1 candidate
f0_i = 0, f1_i = 0  => gate remains normal
```

The SAT miter asserts that at least one observable output or latch-next boundary
differs between the good and faulty circuits.

## Algorithm 1: Naive One-Shot SA0 Miter

Implementation: `optimizer_alg1.py`

Role: first baseline. It checks one gate at a time by physically creating a
faulty circuit and solving a full miter.

```text
Algorithm 1: Naive_One_Shot_SA0
Input:
    source AAG circuit C
    output path P
Output:
    optimized circuit P

1. Count reachable gates in C.
2. If the circuit has no gates:
       copy C to P and stop.
3. Parse C into inputs, latches, outputs, and AND gates.
4. Create a temporary working circuit W = C.
5. Define a constant-zero gate encoding using one input x:
       zero := x AND NOT x
6. repeat
7.     changed := false
8.     Parse the current working circuit W.
9.     for each AND gate g_i in W do
10.        if g_i is already the zero encoding:
11.            continue
12.        Create a faulty copy F by replacing g_i with zero.
13.        Build a full miter between W and F.
14.        Convert the miter to CNF.
15.        Solve the SAT query with the miter output asserted.
16.        if the query is UNSAT then
17.            Replace g_i by zero in W.
18.            changed := true
19.            break and restart from the modified circuit.
20. until changed = false
21. Run ABC strash on W to clean dead logic.
22. If ABC fails, keep W as the output.
23. Return the final gate counts and runtime.
```

Main limitation:

- Rebuilds a separate faulty circuit and SAT miter for each candidate.
- Only checks stuck-at-0 in the early implementation.
- Very expensive because each accepted gate restarts the scan.

## Algorithm 2: Structural Universal Fault Machine

Implementation: `optimizer_alg2.py`

Role: early structural sharing attempt. It builds one universal faulty machine
with fault-enable inputs, then collapses the environment for each candidate.

```text
Algorithm 2: Structural_Universal_Machine
Input:
    source AAG circuit C
    output path P
Output:
    optimized circuit P

1. Count reachable gates in C.
2. If the circuit has no gates:
       copy C to P and stop.
3. Parse C and create a temporary working circuit W.
4. Define a constant-zero encoding.
5. repeat
6.     changed := false
7.     Parse W.
8.     Build a universal faulty machine U for W.
       U contains a fault-enable input for each gate.
9.     Build a miter between W and U.
10.    redundant := empty list
11.    for each gate index i do
12.        Fix the fault environment so only fault_en_i is true.
13.        Collapse the miter under this environment.
14.        Convert the collapsed miter to CNF.
15.        Solve with the miter output asserted.
16.        if the query is UNSAT then
17.            append i to redundant.
18.    for each i in redundant do
19.        if gate i is not already zero:
20.            Replace gate i by zero in W.
21.            changed := true.
22.    if changed:
23.        write the modified W.
24. until changed = false
25. Run ABC strash.
26. Return final statistics.
```

Main limitation:

- Shares more structure than Algorithm 1, but still repeatedly specializes and
  solves many candidate instances.
- Early version still focuses on the constant-zero replacement.

## Algorithm 3: Incremental Universal Fault Machine

Implementation: `optimizer_alg3.py`

Role: first true incremental SAT direction. It builds one universal fault
machine and one miter, then uses SAT assumptions to activate candidates.

```text
Algorithm 3: Incremental_Universal_Fault_Machine
Input:
    source AAG circuit C
    output path P
Output:
    optimized circuit P

1. Count reachable gates.
2. Parse C and create working circuit W.
3. If W has no inputs or no gates:
       copy C to P and stop.
4. Define a constant-zero encoding.
5. repeat
6.     changed := false
7.     Parse W.
8.     Build a universal faulty machine U for W.
9.     Build one miter between the good copy W and faulty copy U.
10.    Convert the miter once to CNF.
11.    Create one SAT solver with the CNF.
12.    for each candidate gate i do
13.        Build assumptions:
               all fault controls disabled except candidate i
               candidate i enabled
               miter output asserted
14.        Solve incrementally under assumptions.
15.        if the query is UNSAT then
16.            record i as redundant.
17.    Apply all recorded redundant replacements to W.
18.    if any replacement was applied:
19.        write W and continue.
20. until changed = false
21. Run ABC strash.
22. Return final statistics.
```

Main improvement:

- One solver/CNF can serve many candidate queries through assumptions.

Main limitation:

- Earlier form still lacks the strict modern acceptance and checkpointing
  structure.

## Algorithm 3-SAF: SA0/SA1 Batch Universal Machine

Implementation: `optimizer_alg3_saf.py`

Role: extends the universal fault machine to both stuck-at-0 and stuck-at-1,
then adds a safety fallback if the batch rewrite fails CEC.

```text
Algorithm 3-SAF: Batch_SA0_SA1_Sweep
Input:
    source AAG circuit C
    output path P
Output:
    optimized circuit P

1. Parse C and build a universal faulty machine U.
2. For every gate i, create controls f0_i and f1_i.
3. Build a miter between the original circuit and U.
4. Convert the miter to CNF once.
5. Start an incremental SAT solver.
6. base := assumptions disabling every f0_i and f1_i.
7. redundant := empty list.
8. for each gate i do
9.     Query stuck-at-0:
           assumptions := base with f0_i enabled and miter asserted
10.    if query is UNSAT:
11.        append (i, 0) to redundant.
12.    else:
13.        Query stuck-at-1:
               assumptions := base with f1_i enabled and miter asserted
14.        if query is UNSAT:
15.            append (i, 1) to redundant.
16. Apply all redundant replacements as one batch.
17. Run ABC strash and write P.
18. Verify C versus P with ABC CEC.
19. if CEC passes:
20.     accept the batch.
21. else:
22.     Reset to the original gates.
23.     for each candidate (i, v) from the batch do
24.         Apply only (i, v) to the current safe gates.
25.         Strash and CEC-check the trial circuit.
26.         if CEC passes:
27.             keep the replacement.
28.     If no candidate survives, write the original/strashed circuit.
29. Return accepted count and runtime.
```

Main improvement:

- Handles both SA0 and SA1 candidates.
- Adds a CEC-based safety fallback for batch rewrites.

## Algorithm 3-Sim: Simulation-Filtered Incremental SAT

Implementation: `optimizer_alg3_sim.py`

Role: adds bit-parallel random simulation as a filter before SAT, plus conflict
budgets to avoid solver freezes.

```text
Algorithm 3-Sim: Simulation_Filtered_Sweep
Input:
    source AAG circuit C
    output path P
Output:
    optimized circuit P

1. Optionally precondition C with ABC strash.
2. Parse the processing circuit.
3. If the circuit is combinational:
       run bit-parallel simulation.
       produce candidate sets H0 and H1 for SA0 and SA1.
   else:
       keep all candidates because latch handling is boundary-based.
4. Build the universal faulty machine.
5. Build and CNF-encode the good/faulty miter.
6. Start an incremental SAT solver.
7. Set a fixed conflict budget.
8. for each gate i do
9.     if i is in H0:
10.        solve SA0 under assumptions and miter assertion.
11.        if result is UNSAT:
12.            record (i, 0).
13.        if result is TIMEOUT:
14.            leave unresolved.
15.    if i is in H1:
16.        solve SA1 under assumptions and miter assertion.
17.        if result is UNSAT:
18.            record (i, 1).
19.        if result is TIMEOUT:
20.            leave unresolved.
21. Apply all recorded replacements.
22. Write the candidate circuit and run ABC strash.
23. Return final counts and timing breakdown.
```

Main improvement:

- Simulation reduces the number of SAT calls.
- Conflict budgets prevent very hard candidates from freezing the run.

Important caveat:

- Simulation is only a filter. It does not prove redundancy.

## Algorithm 3-Timeout-CaDiCaL/G4 Variant

Implementation: `optimizer_alg3_timeout_cadical.py`

Role: budgeted universal-machine sweep with ABC preconditioning. Despite the
file name, the implemented limited solving path uses a PySAT backend that
supports `solve_limited`.

```text
Algorithm 3-Timeout: Budgeted_Universal_Sweep
Input:
    source AAG circuit C
    output path P
Output:
    optimized circuit P

1. Run ABC strash on C to create a preconditioned circuit W if possible.
2. Parse W.
3. Build the universal SA0/SA1 faulty machine.
4. Build one good/faulty miter and encode it as CNF.
5. Start a SAT solver.
6. Disable all fault controls in the base assumption vector.
7. Set a per-query conflict budget.
8. for each gate i do
9.     Query SA0 under assumptions.
10.    if UNSAT:
11.        record (i, 0).
12.    Query SA1 under assumptions.
13.    if UNSAT:
14.        record (i, 1).
15.    if either query times out:
16.        do not classify it.
17. Apply all recorded replacements in a batch.
18. Run ABC strash and write output.
19. Return statistics.
```

Main improvement:

- Makes large circuits less likely to hang indefinitely.

## Algorithm 7: Iterative Simulation and Surgery

Implementation: `optimizer_alg7_iterative.py`

Role: commits one SAT-proven replacement at a time, immediately strashes, then
rebuilds the SAT problem on the smaller circuit.

```text
Algorithm 7: Iterative_Surgery
Input:
    source AAG circuit C
    output path P
Output:
    optimized circuit P

1. Create a working circuit W by ABC-strashing C if possible.
2. total_removed := 0.
3. repeat
4.     changed := false.
5.     Parse W.
6.     if W has no AND gates:
7.         break.
8.     Run bit-parallel simulation to produce candidate sets H0 and H1.
9.     Build a universal faulty machine for W.
10.    Build and CNF-encode the good/faulty miter.
11.    Start a SAT solver with a larger conflict budget.
12.    found_fault := false.
13.    for each gate i do
14.        skip gates already replaced by constants.
15.        if i is in H0:
16.            solve SA0.
17.            if UNSAT:
18.                replace gate i by constant 0 in W.
19.                found_fault := true.
20.                break.
21.        if i is in H1:
22.            solve SA1.
23.            if UNSAT:
24.                replace gate i by constant 1 in W.
25.                found_fault := true.
26.                break.
27.    if found_fault:
28.        Write W.
29.        Run ABC strash on W to remove dead logic.
30.        total_removed := total_removed + 1.
31.        changed := true.
32. until changed = false
33. Copy W to P.
34. Return final counts and timings.
```

Main improvement:

- Rebuilds after each accepted replacement, so later SAT queries see the
  current circuit.

Main limitation:

- Rebuilding after every single commit can be expensive.

## Algorithm 8: Hybrid Safe Batch With TFO Conflict Filtering

Implementation: `optimizer_alg8_hybrid.py`

Role: finds all individually redundant candidates, then selects a safer batch
using TFO conflict information before rewriting.

```text
Algorithm 8: Hybrid_TFO_Conflict_Batch
Input:
    source AAG circuit C
    output path P
Output:
    optimized circuit P

1. Parse C.
2. Define observable sweep roots:
       primary outputs plus latch-next boundaries.
3. Run a SAT miter sweep to collect all individually redundant candidates.
4. Build a TFO conflict graph among the redundant candidates.
5. Select a safe batch of non-conflicting replacements.
6. Apply every replacement in the safe batch to a working gate list.
7. Write and strash the candidate output P.
8. Verify C versus P with ABC CEC.
9. if CEC passes:
10.    accept the batch.
11. else:
12.    Reset to the original gate list.
13.    accepted := empty list.
14.    for each candidate in the safe batch do
15.        Apply the candidate tentatively.
16.        Write and strash a trial circuit.
17.        if ABC CEC passes:
18.            permanently keep the candidate.
19.            append candidate to accepted.
20.    Write the final safe fallback output.
21. if no output exists:
22.    copy the original circuit.
23. Return final gates, accepted count, and timings.
```

Main improvement:

- Avoids blindly applying all individually redundant candidates when their
  simultaneous interaction may matter.
- Uses final CEC as the decisive safety boundary.

## Algorithm 9: Committed In-Memory Incremental SAT

Implementation: `optimizer_alg9_incremental.py`

Role: mature incremental engine. It keeps accepted replacements active in
later SAT assumptions and rebuilds periodically.

```text
Algorithm 9: Committed_Incremental_SAT
Input:
    source AAG circuit C
    output path P
Output:
    optimized circuit P

1. Parse C.
2. Create a temporary working circuit W.
3. Optionally run initial structural strash if the circuit is below the
   configured size threshold.
4. for rebuild_round from 1 to REBUILD_ROUNDS do
5.     Parse W.
6.     Define observable roots:
           primary outputs plus latch-next boundaries.
7.     Build a global configurable-fault miter:
           good copy,
           faulty copy,
           f0_i/f1_i controls for every gate,
           mutex clauses,
           output-difference miter.
8.     Start an incremental SAT solver.
9.     accepted := empty map from gate index to stuck value.
10.    for each candidate (i, v) in the configured order do
11.        Build assumptions:
               all inactive controls disabled,
               previously accepted controls active,
               candidate control active,
               opposite candidate control disabled,
               miter output asserted.
12.        Optionally apply conflict budget.
13.        result := SAT solve under assumptions.
14.        if result is SAT:
15.            count candidate as rejected.
16.        else if result is UNSAT:
17.            accepted[i] := v.
18.            Add permanent unit clauses for the accepted controls if enabled.
19.        else if result is TIMEOUT:
20.            count timeout.
21.            if timeout policy is exceeded:
22.                stop this phase.
23.    Merge phase telemetry.
24.    if accepted is empty:
25.        break.
26.    Apply accepted replacements to W.
27.    Strash W and continue the next rebuild round.
28. Copy W to P.
29. Return final gates and SAT telemetry.
```

Main contribution:

- Tests candidates in the context of already accepted replacements.
- Tracks SAT, UNSAT, timeout, and accepted SA0/SA1 counts.
- Provides a stable SAT engine before the checkpointed Algorithm 10.

## Algorithm 10: Checkpointed Tiered SAT Engine

Implementation: `optimizer_alg10_tiered.py`

Role: main checkpointed long-running engine. It adds proof tiers, budget
cycling, CEX pruning, checkpoint/resume, and detailed telemetry.

```text
Algorithm 10: Checkpointed_Tiered_SAT
Input:
    source AAG circuit C
    output path P
Output:
    optimized circuit P
    checkpoint containing unresolved frontier and budget history

1. Parse C and initialize telemetry.
2. Set a wall-clock deadline if configured.
3. Try to load a valid checkpoint for C:
       source hash must match,
       work AAG must exist,
       phase-resume frontier must match work hash and gate count.
4. if a valid checkpoint exists:
       copy its work AAG to W and restore phase-resume state.
   else:
       create W from C, optionally with initial strash.
5. repeat for at most MAX_PHASES:
6.     Parse W.
7.     Build or restore the current candidate frontier.
8.     Run tiered SAT search on the frontier:
9.         a. Optional CEX pool replay or pre-SAT simulation:
               reject only candidates with concrete observable mismatches.
10.        b. TFI constancy tier:
               prove target is constant by complete fanin SAT query.
               UNSAT accepts; SAT/timeout escalates.
11.        c. Audited bounded TFO window tier:
               build bounded observable window.
               require complete-cut audit.
               UNSAT accepts; SAT/timeout/skip escalates.
12.        d. Exact affected-output cone tier:
               build complete fanin cones for affected observable roots.
               UNSAT accepts; SAT/timeout/skip escalates.
13.        e. Optional exact cone-TFO or partitioned cone variants:
               use only if audit conditions hold.
14.        f. Global configurable-fault miter:
               use budget ladder and saved budget history.
               SAT rejects; UNSAT accepts; timeout remains unresolved.
15.        g. Optional CEX pruning:
               convert SAT models to concrete patterns and simulate the full
               circuit; prune only candidates whose own stuck-at fault causes
               a real output mismatch.
16.    accepted := all UNSAT-proven replacements from the phase.
17.    Save unresolved frontier and maximum tried budgets in phase-resume state.
18.    if accepted is non-empty:
19.        Apply accepted replacements to W.
20.        Strash W.
21.        Save checkpoint immediately.
22.    if deadline reached, user interrupted, or unresolved timeout policy hit:
23.        save safe checkpoint and break.
24.    if no accepted replacements remain and no unresolved work remains:
25.        status := COMPLETE and break.
26. Copy W to P.
27. Save CEX pool and final checkpoint.
28. Return final gates, unresolved count, budget history, and tier telemetry.
```

Main contribution:

- Safe partial progress on hard circuits.
- Exact checkpoint/resume of unresolved candidate frontiers.
- Clear distinction between accepted, rejected, timed-out, and skipped
  candidates.

## Algorithm 10 TFI Constancy Tier

Role: cheap sufficient proof that a gate is functionally constant.

```text
Algorithm: TFI_Constancy_Check
Input:
    current circuit W
    candidate (i, v)
    conflict budget B
Output:
    ACCEPT, ESCALATE, or TIMEOUT

1. Build the complete transitive fanin cone of gate i.
2. Encode the cone as CNF.
3. Assert the opposite of the proposed stuck value:
       if v = 0, assert gate_i = 1;
       if v = 1, assert gate_i = 0.
4. Solve with budget B.
5. if result is UNSAT:
       return ACCEPT.
6. if result is SAT:
       return ESCALATE.
7. if result is TIMEOUT:
       return TIMEOUT or ESCALATE according to phase policy.
```

Soundness:

- If the opposite value is unreachable, the gate is constant and replacement is
  safe.

## Algorithm 10 Audited Bounded TFO Window Tier

Role: over-observable sufficient proof using a bounded fanout window.

```text
Algorithm: Audited_TFO_Window_Check
Input:
    current circuit W
    candidate (i, v)
    window depth d
    conflict budget B
Output:
    ACCEPT, ESCALATE, or TIMEOUT

1. Starting from gate i, follow fanout edges up to depth d.
2. Select window boundary roots.
3. Audit the boundary:
       every path from gate i to any real observable root must pass through at
       least one selected boundary root.
4. if the audit fails:
       return ESCALATE.
5. Build complete fanin cones for all selected boundary roots.
6. If cone-size limits would require dropping roots:
       return ESCALATE.
7. Build a good/faulty miter over the window roots.
8. Solve the miter with candidate stuck-at value active.
9. if result is UNSAT:
       return ACCEPT.
10. if result is SAT:
       return ESCALATE, because window SAT may be over-observable.
11. if result is TIMEOUT:
       return TIMEOUT or ESCALATE according to phase policy.
```

Soundness:

- UNSAT is safe because the boundary is over-observable and complete.
- SAT is not a global rejection proof unless converted into a concrete full
  circuit CEX for the exact candidate.

## Algorithm 10 Exact Affected-Output Cone Tier

Role: exact candidate proof over all real outputs affected by the target.

```text
Algorithm: Exact_Affected_Output_Cone_Check
Input:
    current circuit W
    candidate (i, v)
    conflict budget B
Output:
    ACCEPT, REJECT, TIMEOUT, or SKIP

1. Build the fanout graph of W.
2. Find all real observable roots affected by gate i.
3. if no observable root is affected:
       return ACCEPT as structurally unobservable.
4. Build the complete fanin cone of all affected roots.
5. if the complete cone exceeds configured limits:
       return SKIP.
6. Encode good and faulty copies of the affected-root cone.
7. Activate candidate stuck-at value v in the faulty copy.
8. Assert that at least one affected root differs.
9. Solve with budget B.
10. if result is UNSAT:
       return ACCEPT.
11. if result is SAT:
       return REJECT.
12. if result is TIMEOUT:
       return TIMEOUT.
```

Soundness:

- The cone is exact only because all affected roots and their full fanin cones
  are encoded.

## Exact Candidate-Local TFO Worker

Implementation: `alg10_frontier_shard_probe.py`

Role: final exact TFO classifier used by parallel native TFO campaigns.

```text
Algorithm: Exact_TFO_Worker_Classify
Input:
    immutable work AAG W
    candidate batch Q
    budget ladder L
    solver configuration S
Output:
    classification record for each candidate

1. Load and parse W.
2. Build fanout graph and observable roots.
3. for each candidate (i, v) in Q do
4.     affected := real observable roots reachable from i.
5.     if affected is empty:
6.         report UNSAT_PROPOSED_ACCEPT with structural-unobservable metadata.
7.         continue.
8.     good_cone := complete fanin of affected roots.
9.     tfo_slice := observable faulty TFO slice from i within good_cone.
10.    Audit the TFO slice closure:
           no missing fanout path,
           no missing side input,
           no incomplete observable boundary.
11.    Build the single-fault exact TFO miter:
           good values for the affected-root cone,
           faulty copy only for the observable TFO slice,
           shared side inputs outside the faulty TFO,
           candidate stuck-at value v,
           affected-root difference miter.
12.    Start SAT solver S with the TFO CNF.
13.    for each budget target b in L do
14.        solve the miter with conflict budget b.
15.        if SAT:
16.            report SAT_REJECT and stop this candidate.
17.        if UNSAT:
18.            report UNSAT_PROPOSED_ACCEPT and stop this candidate.
19.        if TIMEOUT:
20.            continue to next budget target.
21.    if all budgets timeout:
22.        report TIMEOUT with highest tried budget.
23. Return all candidate records.
```

Important boundary:

- Workers do not rewrite the circuit.
- Worker UNSAT is only a proposal, not a commit.

## Transactional Parallel Commit Coordinator

Implementation: `alg10_parallel_commit_coordinator.py`

Role: single-writer coordinator for parallel workers. It rechecks proposals on
the current circuit and requires CEC before committing.

```text
Algorithm: Transactional_Parallel_Coordinator
Input:
    source circuit C
    initial work circuit W
    candidate frontier F
    worker count k
Output:
    CEC-verified optimized circuit and checkpoint

1. Initialize current generation G from W.
2. while time and generation limits remain do
3.     Select a batch of candidates from frontier F according to budget history.
4.     Dispatch read-only worker tasks on immutable snapshot G.
5.     Collect worker results:
6.         SAT_REJECT:
               remove candidate from frontier.
7.         TIMEOUT:
               update candidate budget history.
8.         UNSAT_PROPOSED_ACCEPT:
               queue proposal for coordinator recheck.
9.     When all tasks for the current generation are drained:
10.        if proposals exist:
11.            Sequentially recheck every proposal on the current W.
12.            Build accepted set from recheck UNSAT results.
13.            Reject proposals that become SAT, stale, or timeout.
14.            if accepted set is non-empty:
15.                Apply accepted replacements to W.
16.                Run ABC CEC between source C and modified W.
17.                if CEC PASS:
18.                    Commit W.
19.                    Save checkpoint.
20.                    Regenerate frontier F because gate indices and
                       observability may have changed.
21.                else:
22.                    Roll back and stop for audit.
23.     if no candidates remain:
24.        mark COMPLETE.
25. Return final output and checkpoint.
```

Soundness:

- Parallel workers are read-only.
- Only the coordinator mutates the AAG.
- Final CEC is the commit gate.

## Dynamic Cross-Circuit TFO Pool

Implementation: `alg10_dynamic_tfo_pool_campaign.py`

Role: final multi-circuit scheduler. It lets all benchmark circuits share a
global pool of exact TFO workers.

```text
Algorithm: Dynamic_Cross_Circuit_TFO_Pool
Input:
    target circuits or checkpoints T
    worker count k
    time budget D
Output:
    per-circuit outputs, checkpoints, and campaign summary

1. Discover or load target states.
2. For each target circuit t:
       load source path,
       load best valid checkpoint if available,
       copy work AAG,
       restore candidates and TFO budget history,
       restore deferred proposals if present.
3. Start a global process pool with k worker slots.
4. Start a separate single-slot proposal barrier pool.
5. while time remains do
6.     Stop if source code manifest changed.
7.     Mark circuits complete if their candidate frontier is empty.
8.     For any circuit with proposals and no inflight work:
9.         Estimate proposal recheck time.
10.        if proposal barrier fits before deadline reserve:
11.            submit sequential proposal barrier.
12.        else:
13.            checkpoint deferred proposals and mark resume-needed.
14.    while worker slots are free:
15.        Select the next ready circuit:
               prefer no inflight work,
               prefer untried candidates before timeout retries,
               use budget history to choose the next ladder value.
16.        Select candidate microbatch:
               broad batches for untried candidates,
               singleton or small batches for retries.
17.        If estimated runtime does not fit before deadline reserve:
               temporarily block this circuit.
18.        Dispatch an exact TFO worker task.
19.    Wait for at least one worker or proposal barrier to finish.
20.    Apply worker results to that circuit state.
21.    Apply completed proposal barrier results:
           commit only after sequential recheck and CEC PASS,
           regenerate that circuit frontier after commit.
22.    Periodically write campaign summary and circuit checkpoints.
23. Drain inflight tasks at deadline.
24. Persist unresolved candidates and deferred proposals.
25. Write final campaign summary.
```

Main contribution:

- Prevents one circuit from owning the whole campaign.
- Preserves strict per-circuit transactional commits.
- Gives thesis-quality telemetry for utilization, timeouts, and unresolved
  frontiers.

## Native Exact-TFO Campaign Launcher

Implementation: `alg10_native_tfo_7h_campaign.py`

Role: reproducible wrapper for raw-suite or checkpoint-seeded exact-TFO
campaigns.

```text
Algorithm: Native_TFO_Campaign_Launcher
Input:
    target selection
    optional seed summary/checkpoint JSONs
    runtime budget
    worker count
    solver name
Output:
    manifest, logs, campaign summary, per-circuit checkpoints

1. Parse command-line or menu arguments.
2. Determine target source circuits:
       raw ISCAS + EPFL suite, or
       hard native target set, or
       explicitly selected checkpoints.
3. If a seed summary is given:
       choose valid per-circuit checkpoints from the summary.
4. Build a manifest containing:
       mode,
       budgets,
       solver,
       worker count,
       target list,
       source/checkpoint paths,
       CEC role,
       deadline reserve.
5. Validate seed work AAGs and source hashes.
6. Call Dynamic_Cross_Circuit_TFO_Pool with the selected targets.
7. Write final summary and logs.
```

## ABC Baseline Runner

Implementation: `abc_baseline_runner.py`

Role: not a SAT algorithm, but important for thesis comparison.

```text
Algorithm: ABC_Baseline_Comparison
Input:
    benchmark circuits
    ABC flow list
Output:
    CEC-verified baseline CSV and output AAGs

1. Collect benchmark AAG/AIG files.
2. For each circuit C:
3.     Normalize input to ASCII AAG if needed.
4.     for each ABC flow F do
5.         Convert C to binary AIG.
6.         Run ABC script F:
               examples: strash, dc2, dch, fraig, resyn2, dc2_fraig.
7.         Convert ABC output back to ASCII AAG.
8.         Run ABC CEC between C and the flow output.
9.         Record gate counts, area/depth metrics, runtime, and CEC status.
10. Write detailed and aggregate CSV files.
```

Thesis use:

- Context baseline only.
- ABC is broader than stuck-at constant replacement.

## Post-ABC Residual TFO Experiment

Implementation: `post_abc_residual_tfo_experiment.py`

Role: asks whether exact SAT/TFO can still remove gates after ABC has already
optimized the circuit.

```text
Algorithm: Post_ABC_Residual_TFO
Input:
    CEC-passed ABC output circuits
    exact TFO runtime budget
Output:
    residual TFO reductions after ABC

1. For each selected ABC flow:
2.     Collect the flow's output AAG circuits.
3.     Treat each ABC output as a fresh target circuit.
4.     Build target state with unresolved count = 2 * gate_count.
5.     Run Dynamic_Cross_Circuit_TFO_Pool for a bounded time.
6.     For each target, record:
           starting gates,
           final gates,
           residual gates removed,
           SAT rejects,
           UNSAT proposals,
           timeouts,
           CEC commits,
           remaining obligations.
7. Write detail and aggregate CSV files.
```

Thesis use:

- Demonstrates whether ABC leaves exact stuck-at redundancies behind.
- Supports the claim that SAT/TFO is complementary rather than a replacement.

## Suggested LaTeX Algorithm Mapping

For the main report, do not include every historical variant in full detail.
Use the following split:

1. Main text:
   - Algorithm 1: naive baseline.
   - Algorithm 9: committed incremental SAT.
   - Algorithm 10: checkpointed tiered SAT.
   - Exact TFO worker.
   - Transactional coordinator.
   - Dynamic cross-circuit scheduler.

2. Short table or appendix:
   - Algorithm 2.
   - Algorithm 3.
   - Algorithm 3-SAF.
   - Algorithm 3-Sim.
   - Algorithm 3-Timeout.
   - Algorithm 7.
   - Algorithm 8.
   - ABC baseline runner.
   - Post-ABC residual experiment.

## Recommended Thesis Pseudocode Order

If space is limited, present the algorithms in this order:

1. Generic stuck-at SAT query.
2. Naive one-shot baseline.
3. Incremental configurable-fault miter.
4. Checkpointed tiered SAT engine.
5. Exact TFO worker classification.
6. Transactional parallel commit.
7. Dynamic cross-circuit campaign.

This gives the reader the clearest path from simple theory to the final tool.
