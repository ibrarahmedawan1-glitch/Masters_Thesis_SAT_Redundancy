# Unresolved-To-Zero Feedback Assessment

## Reviewer Consensus

All reviewed feedback agreed on the core correctness boundary:

- timeout remains unresolved, never nonredundant;
- simulation/CEX can reject only when it gives a concrete observable mismatch;
- simulation/CEX must never accept a replacement;
- accepted replacements still require UNSAT in a sound proof tier;
- final ABC CEC remains mandatory.

The strongest shared implementation idea was deterministic pre-SAT
counterexample rejection. This is sound because each rejection is backed by a
concrete PI/latch assignment that distinguishes the good circuit from the
single-candidate stuck-at faulty circuit.

## Disagreement

The feedback split on checkpointing:

- one side recommended exact unresolved-queue checkpointing with stable
  candidate IDs;
- another side warned that exact gate identity through strash/cleanup is an
  engineering trap and recommended persisting/replaying CEX assignments first.

Current decision: do not implement exact candidate-ID resume first. It is
valuable, but only after the rejection path and per-candidate telemetry are
stable. The first patch should reduce the unresolved set without depending on
fragile gate-lineage mapping.

## First Patch Chosen

Implemented opt-in pre-SAT simulation rejection in Algorithm 10:

- flag: `ALG10_PRE_SIM_REJECTION=1`;
- deterministic structured patterns: all-zero, all-one, alternating, walking
  one, walking zero;
- deterministic random patterns with `ALG10_PRE_SIM_SEED`;
- local cap: `ALG10_PRE_SIM_MAX_SECONDS`;
- telemetry:
  - `PreSAT_Sim_Enabled`;
  - `PreSAT_Sim_Patterns`;
  - `PreSAT_Sim_Checked`;
  - `PreSAT_Sim_Pruned`;
  - `PreSAT_Sim_Structured_Pruned`;
  - `PreSAT_Sim_Random_Pruned`;
  - `PreSAT_Sim_Time`.

The pre-sim pruned set is shared across TFI, window, cone, and global tiers for
the current phase. It is rejection-only and does not change any acceptance
condition.

## Measurement-Only Probe Results

Probe script:

```text
probe_alg10_presat_sim.py
```

Quick full-pattern probe:

| Circuit | Patterns | Pruned | Pruned % | Time |
|---|---:|---:|---:|---:|
| c432 | 196 | 248 / 250 | 99.20% | 0.018s |
| c7552 | 196 | 3190 / 3386 | 94.21% | 0.420s |
| sin | 180 | 9602 / 10832 | 88.64% | 2.478s |

Hard-circuit capped probes with `--no-pre-strash`:

| Circuit | Patterns | Pruned | Pruned % | Time |
|---|---:|---:|---:|---:|
| sqrt | 68 | 36117 / 49236 | 73.35% | 28.205s |
| div | 17 | 38694 / 114494 | 33.80% | 60.151s |
| log2 | 68 | 43630 / 64120 | 68.04% | 48.999s |
| mem_ctrl | 20 | 14550 / 93672 | 15.53% | 60.123s |

Interpretation: pre-sim is high-value, but large circuits need strict pattern
and wall-clock caps.

## Opt-In Ablation Results

Smoke command:

```text
venv/bin/python sat_ablation_experiments.py --circuits benchmarks/c432.aag benchmarks/c7552.aag --variants cex_window_current presim_cex_window_current --seconds 10 --budgets 100,1000 --output-dir /tmp/alg10_presim_ablation_smoke2
```

Results:

| Circuit | Variant | Removed | Verify | SAT_Unresolved | T_SAT | T_Total | PreSAT pruned |
|---|---|---:|---|---:|---:|---:|---:|
| c432 | cex_window_current | 4 | PASS | 0 | 0.0828s | 0.1169s | 0 |
| c432 | presim_cex_window_current | 4 | PASS | 0 | 0.0064s | 0.0413s | 732 |
| c7552 | cex_window_current | 14 | PASS | 2 | 2.8350s | 5.9541s | 0 |
| c7552 | presim_cex_window_current | 14 | PASS | 0 | 1.9327s | 3.6614s | 5829 |

Sin command:

```text
venv/bin/python sat_ablation_experiments.py --circuits benchmark_suites/epfl/epfl_arithmetic_sin.aag --variants cex_window_current presim_cex_window_current --seconds 20 --budgets 100,1000,5000 --output-dir /tmp/alg10_presim_ablation_sin2
```

Results:

| Variant | Removed | Verify | SAT_Unresolved | T_SAT | T_Total | PreSAT pruned |
|---|---:|---|---:|---:|---:|---:|
| cex_window_current | 39 | PASS | 3612 | 11.7239s | 20.0227s | 0 |
| presim_cex_window_current | 39 | PASS | 201 | 8.7659s | 20.0097s | 18075 |

Audit smoke:

```text
venv/bin/python sat_ablation_experiments.py --circuits benchmarks/c432.aag --variants presim_cex_window_audit_capped --seconds 5 --budgets 100,1000 --output-dir /tmp/alg10_presim_audit_smoke
```

Result:

- `c432`: 4 removed, `Verify=PASS`;
- `PreSAT_Sim_Pruned=633`;
- `CEX_Audit_Checked=751`;
- `CEX_Audit_False_Prunes=0`.

## Decision

Keep the pre-SAT simulation rejection patch as the first enhancement, but keep
it opt-in until broader runs on `sqrt`, `div`, `log2`, and `mem_ctrl`.

Next tests:

1. `sin` with 30-60s to see whether `SAT_Unresolved` reaches 0.
2. `sqrt` with deep pre-sim caps to measure unresolved reduction under the same
   wall-clock budget.
3. `div` and `mem_ctrl` with smaller pattern caps, because pre-sim itself can
   consume the run if left too large.

Postpone:

- exact unresolved candidate-ID checkpointing;
- clause reuse across changing committed contexts;
- structural domination rules without separate proof/audit.
