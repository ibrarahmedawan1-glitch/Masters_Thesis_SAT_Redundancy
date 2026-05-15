# SAT-Based Redundancy Removal for AIG Logic Circuits

This repository contains the implementation and experiment pipeline for a thesis project on SAT-based stuck-at redundancy removal in combinational AIG/AAG circuits.

The current workflow is centered on verified optimization: an optimizer proposes safe stuck-at replacements, writes a smaller ASCII AIGER `.aag` circuit, and the pipeline verifies the result with ABC combinational equivalence checking before reporting it.

## Current Main Engines

The interactive entry point is:

```bash
python3 main.py
```

The menu exposes algorithms `1-10`. The two current research engines are:

- **Algorithm 9**: committed in-memory incremental SAT with candidate filtering and final ABC CEC.
- **Algorithm 10**: checkpointed budget-cycling SAT engine with a sound TFI constancy tier, global miter fallback, safe partial outputs, and resume support.

Algorithm 10 is the preferred engine when a large circuit might take too long. It writes a latest safe `.aag` and checkpoint when the per-circuit time limit is reached, allowing a later deep-resume run.

## Correctness Policy

For thesis claims, a result is useful only when:

```text
Verify = PASS
```

Algorithm 9 and Algorithm 10 use SAT to prove accepted stuck-at replacements. The final report still relies on ABC CEC through `verifier.py` and `abc_utils.py`.

Important distinction:

- SAT `UNSAT` for an accepted stuck-at replacement is a proof step.
- Random simulation and structural scoring are ranking/filtering aids, not acceptance proofs.
- Timeouts are reported as unresolved/checkpointed work, not as proof of non-redundancy.

## Setup

Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

The repository expects bundled/local tools at:

```text
./abc/abc
./aiger/aigtoaig
```

`abc_utils.py` handles the local ABC/AIGER quirk: this ABC build accepts binary `.aig` but rejects ASCII `.aag` through direct `read_aiger`, so the wrapper converts and verifies safely.

## Running Experiments

Run the interactive pipeline:

```bash
python3 main.py
```

Recommended choices:

- `9` for the committed in-memory SAT thesis engine.
- `10` for checkpointed long-running SAT experiments.

Algorithm 10 modes:

- `1`: fast-save/checkpoint mode.
- `2`: deep-resume mode.

Useful non-interactive Algorithm 10 knobs:

```bash
ALG10_MODE=fast_save \
ALG10_MAX_CIRCUIT_SECONDS=60 \
ALG10_BUDGETS=100,1000,5000 \
python3 main.py

ALG10_MODE=deep_resume \
ALG10_MAX_CIRCUIT_SECONDS=600 \
ALG10_BUDGETS=1000,5000,20000,100000 \
python3 main.py
```

Algorithm 10 checkpoints are written to:

```text
results_optimized/alg10_checkpoints/
```

Set `ALG10_RESET_CHECKPOINT=1` to ignore an existing checkpoint.

## Benchmarks

The project currently uses:

- `benchmarks/`: ISCAS-style `.aag` files.
- `benchmark_suites/epfl/`: prepared EPFL combinational benchmarks.
- generated fuzz and planted-live ATPG benchmarks.
- `custom_circuits/`: drop folder for professor-supplied `.aag`/`.aig` circuits.

The thesis scope is **combinational** circuits. Imported circuits should have:

```text
Latches = 0
```

Prepare external `.aag`, `.aig`, or Verilog `.v` benchmarks with:

```bash
python3 prepare_benchmark_suites.py --extra-src external_raw/my_suite --force
```

Then check the manifest:

```bash
python3 - <<'PY'
import csv
with open("benchmark_suites/manifest.csv", newline="") as f:
    for row in csv.DictReader(f):
        if row["Status"] == "OK" and row["Latches"] != "0":
            print("NON-COMB:", row["Target"], "Latches=", row["Latches"])
PY
```

Use only `Latches = 0` circuits for professor-facing combinational results.

## Results And Plots

Reports are written under:

```text
results_optimized/
```

The latest optimized circuit files for a `main.py` run are under:

```text
results_optimized/latest_run/
```

Generate plots with:

```bash
python3 thesis_plots.py
```

## Focused Checks

Useful smoke checks:

```bash
venv/bin/python test_alg10_checkpoint.py
venv/bin/python test_algorithms_1_to_10.py
venv/bin/python test_incremental_sat_pipeline.py
venv/bin/python test_alg9_random_observability.py
```

Recent expected behavior:

- Algorithms `1-10` pass ABC CEC on `c17`.
- Algorithms `8-10` pass ABC CEC on `c432`.
- Algorithm 10 fast-save can checkpoint hard circuits safely.
- Algorithm 10 deep-resume can continue from saved checkpoints.

## Key Files

- `main.py`: interactive experiment pipeline and CSV reporting.
- `optimizer_alg9_incremental.py`: committed in-memory incremental SAT engine.
- `optimizer_alg10_tiered.py`: checkpointed budget-cycling SAT engine with TFI constancy tier.
- `optimizer_alg8_hybrid.py`: shared AAG parsing, writing, strashing, and CNF helpers.
- `verifier.py`: ABC CEC first, Python SAT fallback.
- `abc_utils.py`: AAG/AIG conversion, ABC CEC, ABC strash wrapper.
- `generators.py`: synthetic and planted-live benchmark generation.
- `prepare_benchmark_suites.py`: one-time benchmark import/conversion.
- `COMMANDS.md`: common commands.
- `SESSION.md`: detailed working session notes and latest checkpoint.

## Author

- **Name:** Ibrar Ahmed Awan
- **Institution:** University of Freiburg
- **Year:** 2026
