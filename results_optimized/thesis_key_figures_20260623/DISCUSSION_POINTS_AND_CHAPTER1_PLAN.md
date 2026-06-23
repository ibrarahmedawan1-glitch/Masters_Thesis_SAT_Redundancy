# Thesis Figure Pack and Discussion Notes

## Latest Run Status

The current native `sqrt` continuation is finished. It ended at the 5-hour time budget with `removed=66`, `unresolved=7255`, `cec_pass_commits=1`, `cec_failed_commits=0`, `worker_errors=0`, and worker utilization around 0.868.

This is a good correctness result and a modest optimization result: the run accepted a CEC-passed rewrite and increased the removed count from 56 to 66. The unresolved count increased because the commit regenerated the candidate frontier on the new graph. In the thesis, unresolved should be described as a current frontier size, not as a monotone progress counter.

## Near-Zero Targets to Continue While Writing

Already at zero or marked complete in the native summaries: adder (removed 0), alu_8bit (removed 0), arbiter (removed 0), arbiter_8bit (removed 0), bar (removed 0), c1355 (removed 0), c17 (removed 0), c1908 (removed 0), c2670 (removed 0), c3540 (removed 4).

Best historical frontier states by recorded unresolved count: sqrt (unres 362, removed 56), hyp (unres 923, removed 4), voter (unres 17097, removed 696), mem_ctrl (unres 34003, removed 131), log2 (unres 39927, removed 422), div (unres 66679, removed 21).

Current continuation order from the latest native summaries: sqrt (latest unres 7255, removed 66), voter (latest unres 17097, removed 696), log2 (latest unres 62335, removed 145), div (latest unres 66679, removed 21), mem_ctrl (latest unres 81192, removed 56), hyp (latest unres 427204, removed 0).

For background runs while writing, `sqrt` is the cleanest next target from the current checkpoint. `voter` is second if the goal is visible removals. `log2`, `div`, `mem_ctrl`, and especially current `hyp` belong in the hard-frontier discussion rather than in a promise to reach zero soon.

For writing, the honest position is that small and medium circuits can be driven to zero, while large EPFL arithmetic circuits are dominated by a hard SAT tail. The tool is not near impossible as a research contribution, but reaching zero for every large circuit with the current Python/PySAT implementation is not a realistic deadline claim. The defensible claim is exact CEC-checked redundancy removal with explicit unresolved accounting.

## ABC Baseline Discussion

The strongest ABC baseline by whole-suite area saved in the recorded run is `dc2_fraig`, with `62111` AND2 gates saved and CEC pass count `32/33`. This should be presented as the industrial structural/resynthesis baseline, not as the same problem as SAT-based stuck-at redundancy classification.

The post-ABC residual experiment shows the largest extra native reduction after `dch` with `131495` additional gates and `32` CEC-passed commits. This `dch` case must be presented carefully, because the ABC `dch` output increased the gate count before the residual run. It is useful as a stress case showing recovery from a bloated but CEC-passed output, not as the cleanest comparison point.

The cleaner residual comparison points are `strash`: 9 gates, `balance`: 9 gates, `fraig`: 5 gates, `dch_resyn2`: 3 gates. These are smaller but easier to defend as complementary SAT-based removals after normal CEC-passed ABC flows.

## Figures Generated

1. `01_latest_native_unresolved_frontier.png`: latest native unresolved frontier by circuit.
2. `02_near_zero_native_targets.png`: best recorded historical frontiers for context.
3. `03_latest_sqrt_continuation.png`: seed checkpoint versus latest 5-hour `sqrt` continuation.
4. `04_latest_sqrt_worker_outcomes.png`: SAT rejects, timeouts, UNSAT proposals, and commits.
5. `05_abc_baseline_area_saved_by_flow.png`: ABC whole-suite baseline area savings.
6. `06_post_abc_residual_native_tfo.png`: additional native exact-TFO removals after ABC outputs.
7. `07_correctness_validation_evidence.png`: bounded exhaustive and stress-test evidence.

## Chapter 1 Proposal

Open Chapter 1 with the practical problem: AIG optimization normally uses fast structural transformations, but structural similarity is not the same as semantic observability. A gate can be structurally present while its stuck-at replacement is unobservable at every primary output or latch-next cut boundary. This motivates SAT-based ATPG as an exact proof mechanism for candidate redundancy.

Then define the gap: ABC-style optimization is strong and fast for synthesis, but it does not provide a candidate-by-candidate stuck-at classification trace with SAT/UNSAT/TIMEOUT accounting, checkpoint resume, and transactional proof logs. Existing structural flows can also leave residual semantic redundancy, while exact SAT engines can become impractical on hard arithmetic frontiers without careful slicing, scheduling, and audit rules.

State the research questions around exactness and practicality: whether candidate-local exact TFO miters agree with full observable-root miters, whether side-input reuse remains sound under closure audits, whether parallel SAT proposals can be committed safely, and how much residual redundancy remains after established ABC baselines.

List the contributions as the audited exact-TFO encoding, the transactional coordinator with sequential recheck and CEC-gated commits, checkpointed budget laddering with explicit unresolved accounting, the validation methodology, and the empirical comparison against ABC baselines.

Close the introduction scope carefully: the thesis is not claiming a universal replacement for ABC or complete classification of all large EPFL circuits within fixed time. It claims a sound, audited, reproducible SAT proof framework for exact stuck-at redundancy removal in AIG/AAG circuits, with independent CEC verification of every reported optimized output.

## Presentation Points

The validation run checked `536376` bounded candidates over `92628` small circuits, plus `36` required stress rows. This belongs in the main evaluation as correctness evidence, with detailed logs in an appendix.

The large-circuit discussion should be framed as a hard-frontier result. SAT rejects are cheap and common, while UNSAT commits are rare and valuable. The latest `sqrt` run classified many SAT candidates and found a small number of accepted UNSAT proposals, but the remaining frontier is still large.

Do not present unresolved count alone as quality. Pair it with removed gates, CEC commits, worker errors, timeouts, and the generation number.
