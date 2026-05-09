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

The full run generates synthetic circuits, copies `.aag` files from `benchmarks/`, optimizes every dataset circuit, verifies each output, and writes a CSV report to:

```text
results_optimized/thesis_results_ALG<id>_<timestamp>.csv
```

Algorithm 9 reports include the selected mode and profile in both the filename and CSV columns.

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
```

These files are script-style checks with `if __name__ == "__main__"` blocks, not a fully standardized pytest suite.

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
