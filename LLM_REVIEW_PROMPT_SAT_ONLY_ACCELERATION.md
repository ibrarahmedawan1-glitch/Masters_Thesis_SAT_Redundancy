Act as a strict SAT/ATPG/AIG optimization researcher and thesis examiner.
Do not give generic advice. Do not recommend making simulation the main
algorithm. I need SAT-side improvements for reducing SAT_Unresolved faster while
keeping the current formal acceptance boundary unchanged.

Core correctness boundary:

- Circuit model: combinational AIG/AAG.
- Latches, if present, are treated only as combinational cut boundaries.
- Optimization action: greedy single-gate stuck-at constant replacement of
  internal AND gates.
- A candidate may be accepted only when a sound SAT proof tier returns UNSAT.
- SAT or simulation counterexamples may reject/non-detect a candidate only when
  replay gives a concrete observable output/latch-next mismatch.
- Timeout means unresolved. Timeout must never be treated as nonredundant.
- Every reported optimized AAG must pass independent final ABC CEC.
- Do not claim full AIG optimization, sequential reasoning, optimality, or
  superiority over ABC as a general optimizer.

Current Algorithm 10 proof tiers:

1. TFI constancy SAT:
   - encode complete transitive fanin of target gate;
   - query whether the opposite stuck value is reachable;
   - UNSAT means the gate is functionally constant and can be committed;
   - SAT/timeout/skip escalates.

2. Audited bounded TFO window miter:
   - encode complete fanin cones of bounded fanout window roots;
   - accept UNSAT only if a runtime audit proves the window roots form a
     complete observable cut from the candidate to all real output/latch-next
     roots;
   - SAT/timeout/skip escalates.

3. Exact affected-output cone miter:
   - find all real output/latch-next roots in candidate fanout;
   - encode complete fanin cones for those affected roots;
   - UNSAT commits;
   - SAT rejects;
   - timeout/skip escalates.

4. Full global configurable-fault miter:
   - good and faulty circuit copies share PI/latch-current variables;
   - two controls per AND gate: f0_i and f1_i;
   - mutex: not f0_i OR not f1_i;
   - faulty behavior: (normal AND not f0_i) OR f1_i;
   - assumptions disable inactive controls, activate committed replacements,
     activate current candidate, disable opposite stuck value, and assert the
     output miter;
   - UNSAT commits;
   - SAT rejects;
   - timeout remains unresolved.

Current acceleration features, which are allowed but must stay secondary:

- CEX pruning/replay is rejection-only.
- Persistent CEX pool is rejection-only.
- Deterministic pre-SAT simulation rejection is opt-in and rejection-only.
- These may reduce SAT workload, but they must not accept redundancy.

Latest enhanced run facts:

- Mode: alg10_resume_pool_presim_deep_current.
- Checkpoint dir: results_optimized/alg10_checkpoints_resume_pool_presim.
- Features enabled: CEX pool, pre-SAT rejection, phase-local resume.
- Every optimized output in the latest completed enhanced run passed ABC CEC.
- The first enhanced run started fresh in this checkpoint directory.

Key latest results:

div:
- previous enhanced checkpoint: 173 total gates removed, SAT_Unresolved 12149;
- after resume run: 227 total gates removed, SAT_Unresolved 424;
- this means +54 total gate removals in the second run;
- CEX pool loaded 229 vectors;
- SAT UNSAT proofs in second run: 19, all from audited window UNSAT;
- still slow: one 600s session was needed.

sqrt:
- latest enhanced completed run: 56 removed, SAT_Unresolved 9110.

log2:
- latest enhanced completed run: 23 removed, SAT_Unresolved 13793.

sin:
- latest enhanced completed run: 41 removed, SAT_Unresolved 137.

mem_ctrl:
- latest enhanced completed run: 2 removed, SAT_Unresolved 73291.

voter:
- latest enhanced completed run: 605 removed, SAT_Unresolved 1908.

Problem:

The checkpoint/resume strategy works and can reduce unresolved dramatically, but
large circuits still require many long sessions. I need SAT-side design changes
that reduce unresolved faster and/or prove more UNSAT redundancies per session
without changing the acceptance boundary.

Your task:

Give a strict SAT-focused review and patch plan. Avoid broad advice. Every
recommendation must connect directly to one of these:

- SAT encoding size;
- SAT assumption design;
- proof-tier scheduling;
- incremental SAT use;
- learned-clause reuse within a sound context;
- exact cone/window/global miter efficiency;
- candidate ordering for SAT proof/search;
- unresolved queue checkpoint/resume;
- per-candidate budget history;
- UNSAT core use;
- dominator/cut selection with audit;
- final ABC CEC methodology.

Do not make pre-SAT simulation the main recommendation. It may appear only as a
supporting rejection filter.

Questions to answer:

1. In the current tier order, where is SAT time most likely being wasted for
   hard circuits such as div, sqrt, log2, and mem_ctrl?

2. Should the system persist an exact unresolved queue after each tier, not just
   the safe AAG and CEX pool? If yes, what fields are needed and how do we avoid
   stale candidate IDs after strash/rebuild?

3. Is phase-local gate index plus work-AAG SHA enough for exact resume within a
   phase? When should we invalidate it?

4. What per-candidate SAT history should be stored?
   Consider:
   - last tier reached;
   - budgets already tried per tier;
   - timeout count;
   - SAT-rejected proof source;
   - UNSAT proof source;
   - affected output-root set;
   - cone size;
   - window audit result;
   - last context hash.

5. How should the next run schedule candidates?
   Options:
   - process never-seen candidates first;
   - process timed-out candidates with larger budgets;
   - prioritize candidates sharing small affected-output cones;
   - prioritize candidates whose window audit passed previously;
   - defer candidates that repeatedly time out in global miter;
   - sort by fanout cone size or affected output count.

6. Can exact cone SAT be made faster and more complete?
   Evaluate:
   - caching cone CNF by affected output-root set;
   - grouping candidates by identical affected root set;
   - building one incremental cone solver per root-set group;
   - reusing assumptions for candidate stuck-at controls;
   - splitting large output-cone groups;
   - using dominator roots as audited cut points.

7. Can audited window SAT be improved without unsoundness?
   Evaluate:
   - adaptive window levels;
   - widening only until the cut audit passes;
   - preferring dominator cuts;
   - caching cut audits;
   - grouping candidates by window root set;
   - storing previous window SAT/UNSAT/timeout history.

8. Can the global configurable-fault miter be more incremental?
   Explain exactly what is sound:
   - one solver per unchanged work-AAG phase;
   - learned clauses reused only while the CNF circuit and committed context are
     unchanged;
   - rebuild solver after any strash/rebuild or committed replacement if unit
     clauses change the circuit semantics;
   - assumptions for candidate controls and miter activation.

9. Can UNSAT cores help?
   Evaluate whether PySAT/Glucose failed assumptions can:
   - remove irrelevant committed controls from future assumptions;
   - identify output roots not needed for a proof;
   - improve candidate ordering;
   - reduce global assumption lists.
   Be realistic about implementation risk.

10. How should budgets be changed?
    Recommend a concrete budget policy for a 600s session:
    - small budget for first-pass TFI/window;
    - larger budget only for candidates that survived filters;
    - per-candidate timeout history;
    - no repeated equal-budget retries after timeout;
    - deadline-aware scheduling.

11. Which single SAT-side patch should be implemented next in 2-4 days?
    Provide:
    - exact data structures;
    - functions to add/change;
    - checkpoint JSON schema;
    - CSV telemetry;
    - tests;
    - experiment matrix.

12. Which ideas should be postponed or avoided?
    Avoid:
    - unsafe simulation acceptance;
    - treating repeated timeout as nonredundant;
    - MaxSAT unless framed as future work;
    - full FRAIG or broad rewriting;
    - sequential reasoning;
    - parallel portfolios that break greedy committed-context semantics.

Required answer format:

1. Correctness invariants that must not change.
2. Diagnosis of current bottleneck from the provided telemetry.
3. Ranked SAT-side changes to reduce SAT_Unresolved faster.
4. For each change: soundness classification, expected impact, risk, and
   implementation complexity.
5. Best 2-4 day patch plan with concrete data structures and functions.
6. Exact checkpoint/resume schema for unresolved queue and per-candidate SAT
   history.
7. Candidate identity scheme recommendation.
8. Incremental SAT recommendation with sound/unsound boundaries.
9. Experiment matrix for div, sqrt, log2, sin, mem_ctrl, and voter.
10. CSV metrics to prove progress across repeated sessions.
11. Thesis-safe wording that keeps the work SAT-centered.
12. Final verdict: implement first, postpone, avoid.
