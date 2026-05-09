# Architecture

This project is an experimental SAT-based logic optimization pipeline for AIG/AAG circuits.

## High-Level Flow

```text
generators.py + benchmarks/
        |
        v
dataset_benchmarks/
        |
        v
main.py selects optimizer_alg*.py
        |
        v
results_optimized/latest_run/
        |
        v
verifier.py
        |
        v
results_optimized/thesis_results_ALG<id>_<timestamp>.csv
        |
        v
thesis_plots.py
```

## Orchestration Layer

`main.py` is the main experiment driver. It owns:

- directory setup;
- interactive optimizer selection;
- synthetic circuit generation;
- benchmark copying from `benchmarks/`;
- AAG name normalization;
- per-circuit optimizer execution;
- verification calls;
- CSV report writing.

The script intentionally uses dynamic imports so algorithm modules can be compared behind a shared command-line workflow.
When option `9` is selected, `main.py` also asks for an Algorithm 9 runtime mode and dataset profile.

## Dataset Layer

`generators.py` creates synthetic `.aag` circuits:

- `generate_ladder_circuit(...)` creates a chain of repeated idempotent-style logic.
- `generate_parallel_circuit(...)` creates a small duplicated parallel structure.
- `generate_random_circuit(...)` creates random AIGs and can inject stuck-at or idempotent redundancy patterns.

`main.py` also copies static `.aag` circuits from `benchmarks/` into `dataset_benchmarks/` before running the optimizer.
Prepared benchmark suites under `benchmark_suites/` and custom `.aag`/`.aig` files can also be copied or converted into the run dataset.

## Optimization Layer

The optimizer modules are separate algorithm implementations. They share the `solve_circuit(circuit_path, output_path)` entry point, but their internal strategies differ:

- baseline SAT miter;
- structural and universal-machine approaches;
- incremental ATPG;
- stuck-at fault batch injection;
- simulation filters before SAT;
- solver-budget and timeout strategies;
- iterative circuit surgery;
- pure Python hybrid optimization.
- committed in-memory incremental SAT optimization.

Some optimizer modules use the bundled ABC binary for structural hashing or output cleanup. The hybrid algorithm is described in the menu as ABC-free.

## Verification Layer

`verifier.py` provides strict equivalence checking:

1. If `./abc/abc` and `./aiger/aigtoaig` exist, it converts ASCII `.aag` files to binary `.aig` and runs ABC `cec -n` with a hard timeout.
2. If the ABC wrapper cannot run, it falls back to a deterministic ASCII-AIGER SAT miter.
3. If that cannot handle the input, it falls back to `py-aiger`, `py-aiger-cnf`, and `python-sat`.
4. For large files in the final fallback mode, it returns `TIMEOUT` rather than risking a long pure-Python conversion.

This means the strongest validation path depends on the local ABC binary being built and executable.

## Results Layer

Each processed circuit contributes a row with:

- circuit name and category;
- original and final gate counts;
- removed gate count and reduction percentage;
- parse/filter/encode/SAT/CEC/total timing;
- verification status.

Optimized circuits for the latest full run are written to:

```text
results_optimized/latest_run/
```

Timestamped CSV reports are written directly under:

```text
results_optimized/
```

## External Code And Data

- `abc/`: bundled ABC source/binary tree used for equivalence and structural commands.
- `aiger/`: bundled AIGER C utilities and documentation.
- `epfl_benchmarks/`: EPFL benchmark circuits in several formats.
- `benchmarks/`: active `.aag` benchmark set used by `main.py`.
- `pysat_engine/`: SAT solver experiments and dataset-generation utilities.
- `fuzz_testing/` and `fuzz_benchmarks/`: fuzzing support and generated fuzz circuits.

## Architectural Boundaries

- Keep experiment orchestration in `main.py` or dedicated run scripts.
- Keep circuit generation in `generators.py`.
- Keep formal equivalence logic in `verifier.py`.
- Keep algorithm-specific parsing, encoding, filtering, and surgery inside `optimizer_alg*.py`.
- Keep result visualization in `thesis_plots.py`.

This separation makes it easier to compare algorithms without changing benchmark generation or verification semantics.
