Act as a strict SAT/ATPG/AIG optimization researcher and thesis examiner.
Do not recommend unrelated optimizer families as the main path. The next work
must remain SAT-engine focused: faster, more concrete proof search for
single-gate stuck-at constant redundancy removal in combinational AIG/AAG
circuits.

Correctness boundary:

- Circuit model: combinational AIG/AAG.
- Latches, if present, are treated only as combinational cut boundaries.
- Optimization action: greedy single internal AND-gate replacement by stuck-at
  constant 0 or 1.
- A replacement may be accepted only when a sound SAT proof tier returns UNSAT.
- SAT/simulation counterexamples are rejection-only. They may prune a candidate
  only after replay gives a concrete mismatch at a real output/latch-next root.
- Timeout means unresolved. Timeout is never nonredundancy.
- Final ABC CEC is mandatory for every reported optimized AAG.
- The thesis must not claim optimality, completeness, sequential reasoning, or
  general superiority over ABC.

Current Algorithm 10 proof tiers:

1. TFI constancy SAT.
   - Old engine: per-candidate complete TFI cone.
   - New engine: phase-local persistent good-circuit solver.
   - Query SA0 by assuming target=1; UNSAT proves constant 0.
   - Query SA1 by assuming target=0; UNSAT proves constant 1.
   - SAT/timeout escalates.

2. Audited bounded TFO window miter.
   - UNSAT accepts only if the window roots form a complete observable cut.
   - SAT/timeout/failed audit escalates.

3. Exact affected-output cone miter.
   - Old engine: one hardcoded single-fault cone miter per candidate.
   - New experimental/integrated engine: hybrid grouped cone.
   - Candidates with identical affected observable roots may share one
     configurable-fault cone solver.
   - Assumptions disable inactive controls, activate previously accepted
     replacements, activate only the current candidate, disable the opposite
     stuck value, and assert the cone miter.
   - Hybrid mode groups only root sets with at least 8 candidates; otherwise it
     falls back to the old single-candidate cone encoder.

4. Global configurable-fault miter fallback.
   - Same UNSAT-only acceptance rule.

Recent implemented SAT-engine changes:

- Added `ALG10_TFI_ENGINE=persistent|local`.
- Added `ALG10_TFI_SOLVER`, default tested as `cadical153`.
- Added `ALG10_CONE_ENGINE=single|grouped|hybrid`.
- Added `ALG10_CONE_SOLVER`, default tested as `cadical153`.
- Added `ALG10_CONE_GROUP_MIN_SIZE`, default 8.
- Kept old local TFI and single-cone paths as fallbacks.
- Did not change CEX pruning into acceptance because CEXs cannot prove
  universal redundancy.

TFI experiment evidence:

- Script: `sat_tfi_solver_experiments.py`.
- Validation compared old local TFI against persistent full-good-circuit TFI.
- Zero decisive SAT/UNSAT mismatches on:
  - all 250 `c432` candidates;
  - 500 sampled candidates from `c7552`;
  - 500 sampled candidates from EPFL `sin`;
  - 500 sampled candidates from EPFL `sqrt`;
  - 500 sampled candidates from EPFL `log2`.
- CaDiCaL153 was usually faster than Glucose4 for persistent TFI:
  - `sqrt`: Glucose4 6.17s, CaDiCaL153 2.88s on 1000 candidates.
  - `div`: Glucose4 12.42s, CaDiCaL153 5.09s.
  - `log2`: Glucose4 9.38s, CaDiCaL153 5.73s.
  - `mem_ctrl`: Glucose4 3.28s, CaDiCaL153 2.01s.

Grouped exact-cone experiment evidence:

- Script: `sat_cone_group_experiments.py`.
- Validation compared old single-cone miter against grouped configurable cone.
- Zero decisive mismatches on the tested slices:
  - all 250 `c432` candidates;
  - 500 sampled candidates from `c7552`;
  - 500 sampled candidates from `c6288`;
  - 500 sampled candidates from EPFL `sin`;
  - sampled eligible candidates from EPFL `div`;
  - sampled eligible candidates from EPFL `mem_ctrl`.
- Some arithmetic samples skipped exact-cone checks because affected cones
  exceeded `ALG10_CONE_MAX_GATES=20000`, matching production behavior.
- Performance was mixed:
  - `c432`: grouped 0.09s vs single 0.21s.
  - `c6288`: grouped CaDiCaL153 3.19s vs single Glucose4 5.75s.
  - `sin`: grouped CaDiCaL153 17.96s vs single Glucose4 21.55s, but grouped
    Glucose4 was slower.
  - `mem_ctrl`: grouped was slower on the sampled slice because groups were
    small and numerous.
- Therefore integration used hybrid grouping with a minimum group size instead
  of replacing the single-cone path globally.

Integrated smoke/ablation evidence:

- `test_alg10_checkpoint.py`: PASS with persistent TFI and with
  `ALG10_TFI_ENGINE=local`.
- `test_algorithms_1_to_10.py`: all tested rows PASS.
- `sat_ablation_experiments.py` on `c432`, 10s:
  - current: 125->121, PASS, SAT 0.40s.
  - hybrid cone: 125->121, PASS, SAT 0.17s.
- `sat_ablation_experiments.py` on `c7552`, window off, 10s:
  - current: 1693->1689, 4 removed, PASS.
  - hybrid cone: 1693->1683, 10 removed, PASS.
- `c6288`, 10s: both removed 0, PASS; hybrid checked slightly more.
- EPFL `sin`, 10s: both removed 39, PASS; TFI dominated.

Questions:

1. Is the persistent full-good-circuit TFI constancy proof sound as stated?
   If not, identify the exact missing constraint or counterexample.

2. Is the grouped exact-cone configurable-fault miter sound when assumptions
   disable inactive controls, activate committed controls, activate only one
   current candidate, and assert the miter?

3. Is comparing original good roots against a faulty copy with previously
   accepted controls active sound in a greedy SAT optimizer, given accepted
   replacements were already proved output-equivalent?

4. Is hybrid grouping by identical affected observable root set sufficient, or
   should grouping key also include cone hash, committed-control set, or another
   phase-local context hash?

5. What SAT-engine improvement should come next if the goal is to find more
   stuck-at redundancies under fixed time without pre-filtering candidates?
   Keep suggestions focused on:
   - exact unresolved queue persistence;
   - per-candidate tier/budget history;
   - adaptive tier scheduling;
   - cone/window solver reuse;
   - global miter assumption reduction without freeing inactive controls;
   - UNSAT-core use only as advisory scheduling data;
   - solver selection by tier/circuit features.

6. Are the current redundancy counts enough for a defensible thesis contribution
   if framed as a correctness-gated SAT architecture rather than as a general
   optimizer beating ABC?

7. If more redundancies are needed, what should be changed in the SAT engine
   first? Avoid suggesting unsafe simulation acceptance, timeout-as-rejection,
   MaxSAT as the main path, sequential reasoning, or broad non-SAT rewriting.

Required answer:

- Classify each current change as sound/suspicious/unsound.
- Identify the highest-risk implementation detail.
- Recommend the next 2-4 day SAT-engine patch.
- Recommend an experiment matrix for `div`, `sqrt`, `log2`, `mem_ctrl`,
  `voter`, `sin`, `c7552`, and `c6288`.
- State whether the thesis claim is already good enough, and what extra result
  would most strengthen it.
