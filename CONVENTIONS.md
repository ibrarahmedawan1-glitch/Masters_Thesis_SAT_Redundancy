# Conventions

Project conventions for keeping the thesis code and experiments reproducible.

## Circuit Formats

- Prefer `.aag` for readable AIGER files inside Python experiments.
- `.aig` may appear in benchmark and fuzz directories, but the main pipeline currently collects `benchmarks/*.aag`.
- Keep generated and optimized circuits separate from source benchmarks.

## Optimizer Contract

Every optimizer used by `main.py` must expose:

```python
solve_circuit(circuit_path, output_path)
```

`main.py` currently accepts two return shapes:

```python
# Algorithms 5, 7, 8, and 9
orig, _, final, removed, timings = solve_circuit(circuit_path, output_path)

# Other algorithms
orig, _, final, _, _, removed, dur = solve_circuit(circuit_path, output_path)
```

When adding a new optimizer, either match one of these shapes or update `main.py` deliberately. The output path must be written even when no optimization is possible, because verification expects a circuit file there.

## Timing Dictionary

For detailed optimizer telemetry, use this timing key convention:

```python
{
    "Parse": 0.0,
    "Filter": 0.0,
    "Encode": 0.0,
    "SAT": 0.0,
    "Total": 0.0,
}
```

`main.py` writes these values into the report columns:

- `T_Parse(s)`
- `T_Filter(s)`
- `T_Encode(s)`
- `T_SAT(s)`
- `T_Total(s)`

## Verification Convention

Use `verifier.verify_equivalence(original_path, optimized_path)` for final claims. Its result status is expected to be one of:

- `PASS`
- `FAIL`
- `TIMEOUT`
- `ERROR`

Only `PASS` should be counted as a confirmed equivalent optimization.

## Generated Files

Treat these as generated or disposable unless you intentionally archive them:

- `dataset_benchmarks/`
- `results_optimized/latest_run/`
- `optimized_circuits/`
- temporary files such as `temp_mod.aag`, `current_working.aag`, and `test_*_out.aag`

Thesis evidence should be preserved as timestamped CSV files, plots, and explicitly named benchmark artifacts.
Reusable prepared benchmark inputs can live under `benchmark_suites/`; run outputs should not.

## Naming

- Use `optimizer_alg<number>_<variant>.py` for algorithm variants.
- Use lowercase descriptive benchmark names with underscores.
- Keep report filenames timestamped when produced by a full run.
- Keep plot filenames numbered when they correspond to thesis figures.

## Coding Style

- Keep optimizer modules independent enough to be dynamically imported by name.
- Avoid hidden global changes in optimizer modules; `main.py` should remain the orchestration layer.
- Prefer explicit failure statuses in reports over silent skipping.
- Do not remove verification to make experiments faster unless the run is clearly marked as exploratory.

## Reproducibility

Generated random circuits use Python's `random` module. For a reproducible experiment, set and record a seed near the beginning of `main.py` or in a dedicated experiment script.

If an experiment changes benchmark generation parameters, solver budgets, ABC usage, or verification timeout values, record that change in the result notes or thesis text.
