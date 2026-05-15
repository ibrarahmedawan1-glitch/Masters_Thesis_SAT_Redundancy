# Commands

Common commands for working on the thesis project from the repository root.

## Environment

Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

Install Python dependencies:

```bash
pip install -r requirements.txt
```

## Main Experiment

Run the full interactive thesis pipeline:

```bash
python3 main.py
```

Recommended first algorithm choice for the current pipeline is `9`, the committed in-memory incremental SAT optimizer.
After selecting `9`, choose a runtime mode and dataset profile from the prompts.

Algorithm 9 runtime modes:

- `1`: fast filtered thesis mode.
- `2`: exhaustive stuck-at sweep capped at 50k gates per circuit.
- `3`: filtered large-circuit survey with very-large SAT enabled.
- `4`: full exhaustive stuck-at sweep with no dataset gate cap and no SAT wall-clock abort.

Algorithm 10 is the checkpointed budget-cycling SAT engine. It has two modes:

- `1`: fast save/checkpoint mode with bounded per-circuit runtime.
- `2`: deep resume mode with larger budgets and a longer per-circuit runtime.

Useful non-interactive Algorithm 10 knobs:

```bash
ALG10_MODE=fast_save ALG10_MAX_CIRCUIT_SECONDS=60 ALG10_BUDGETS=100,1000,5000 python3 main.py
ALG10_MODE=deep_resume ALG10_MAX_CIRCUIT_SECONDS=600 ALG10_BUDGETS=1000,5000,20000,100000 python3 main.py
```

Checkpoints are written under `results_optimized/alg10_checkpoints/` by default. Set `ALG10_CHECKPOINT_DIR=/path/to/dir` to choose another directory, and `ALG10_RESET_CHECKPOINT=1` to ignore an existing checkpoint.

Algorithm 10 also has a sound TFI constancy tier before the global miter:

```bash
ALG10_TFI_CONSTANCY=1 ALG10_TFI_BUDGET=500 ALG10_TFI_MAX_CONE_GATES=2000 python3 main.py
```

TFI `UNSAT` can commit a stuck-at constant safely. TFI `SAT`, timeout, or skip still escalates to the global miter, so the tier does not remove candidates from coverage.

The full run generates synthetic circuits, copies `.aag` files from `benchmarks/`, optimizes every dataset circuit, verifies each output, and writes a CSV report to:

```text
results_optimized/thesis_results_ALG<id>_<timestamp>.csv
```

Algorithm 9 and Algorithm 10 reports include the selected mode and profile in both the filename and CSV columns.

## Plotting

Generate thesis plots from available CSV results:

```bash
python3 thesis_plots.py
```

Check `thesis_plots/` for generated images.

## Benchmark Preparation And Demos

Prepare benchmark files:

```bash
python3 prepare_benchmarks.py
```

Run demo experiments:

```bash
python3 run_demo_experiment.py
python3 run_bench_demo.py
python3 demos/run_normalization_demo.py
```

## Focused Checks

Run individual validation scripts:

```bash
python3 test_baselines.py
python3 test_miter_integrity.py
python3 test_strict_pipeline.py
python3 test_alg3_sandbox.py
python3 test_encoding_surgery.py
python3 test_alg9_random_observability.py
python3 test_alg10_checkpoint.py
python3 test_algorithms_1_to_10.py
```

These files are script-style checks with `if __name__ == "__main__"` blocks, not a fully standardized pytest suite.

Force Algorithm 9's random-observability filter during the focused comparison smoke:

```bash
ALG9_FAULT_SIM_MAX_GATES=0 ALG9_RANDOM_OBS_SIM=1 python3 test_incremental_sat_pipeline.py --epfl
```

## ABC Checks

The verifier expects ABC at:

```text
./abc/abc
```

Use the Python verifier or ABC wrapper for `.aag` files, because this local ABC build rejects ASCII AIGER when called directly with `read_aiger`:

```bash
python3 -c "from verifier import verify_equivalence; print(verify_equivalence('original.aag', 'optimized.aag'))"
```

Manual binary AIGER check after conversion:

```bash
./aiger/aigtoaig original.aag /tmp/original.aig
./aiger/aigtoaig optimized.aag /tmp/optimized.aig
./abc/abc -c "cec -n /tmp/original.aig /tmp/optimized.aig; quit"
```

## File Discovery

Find Python optimizer entry points:

```bash
rg "def solve_circuit" *.py
```

Find ABC usage:

```bash
rg "ABC_PATH|cec|strash" *.py
```

Find generated result reports:

```bash
find results_optimized -name "*.csv" -maxdepth 2
```
