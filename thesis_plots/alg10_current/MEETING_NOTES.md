# Algorithm 10 Meeting Notes

## Current Claim

Algorithm 10 is a correctness-gated SAT pipeline for combinational AIG stuck-at constant redundancy removal. Accepted replacements require SAT UNSAT proof in one of the proof tiers and final ABC CEC PASS. Simulation/CEX pruning is rejection-only.

## Deep Run Summary

- Deep rows analyzed: 8; CEC PASS rows: 8/8.
- Total verified AND removals in the clean deep rows: 446.
- ISCAS c432/c7552/c6288 reached SAT_Unresolved=0 in the clean deep run.
- EPFL rows still hit time budgets, so they are not exhaustive completion claims.

## Per-Circuit Deep Results

| Circuit | Removed | TFI UNSAT | Window UNSAT | Unresolved | CEC |
|---|---:|---:|---:|---:|---|
| c432 | 4 | 0 | 2 | 0 | PASS |
| c6288 | 0 | 0 | 0 | 0 | PASS |
| c7552 | 14 | 0 | 7 | 0 | PASS |
| div | 233 | 8 | 74 | 21490 | PASS |
| log2 | 23 | 13 | 0 | 19132 | PASS |
| mem_ctrl | 75 | 1 | 34 | 48193 | PASS |
| sin | 41 | 19 | 1 | 179 | PASS |
| sqrt | 56 | 0 | 22 | 19747 | PASS |

## How To Explain Checkpoints

- `sat_ablation_experiments.py` uses `ALG10_RESET_CHECKPOINT=1`, so each row is a clean run from the benchmark.
- Algorithm 10 checkpoints save the last safe optimized AAG, not an exact unresolved-candidate queue.
- A resume run starts from the last safe optimized circuit and sweeps again; it does not literally continue at candidate 180/179.

## Safe Wording

- Say: fully resolved under the current single-gate stuck-at replacement model when `SAT_Unresolved=0`.
- Do not say: fully optimized circuit, optimal reduction, or no possible redundancy exists.
- Say: EPFL deep rows found more verified reductions but still have unresolved candidates under the time budget.

## Suggested Meeting Ask

Ask whether to prioritize: (1) ABC baseline comparison, (2) adaptive tier routing / CEX scan reduction, or (3) candidate ordering experiments. The SAT encoding itself should stay stable unless a proof audit fails.

## Generated Files

- `thesis_plots/alg10_current/01_removed_fast_short_deep.png`
- `thesis_plots/alg10_current/02_deep_tier_commits.png`
- `thesis_plots/alg10_current/03_deep_unresolved.png`
- `thesis_plots/alg10_current/04_deep_cex_pruning.png`
- `thesis_plots/alg10_current/05_cex_audit_outcomes.png`
- `thesis_plots/alg10_current/summary_cex_audit.csv`
- `thesis_plots/alg10_current/summary_deep_cex_pruning.csv`
- `thesis_plots/alg10_current/summary_deep_tier_commits.csv`
- `thesis_plots/alg10_current/summary_deep_unresolved.csv`
- `thesis_plots/alg10_current/summary_removed_fast_short_deep.csv`
