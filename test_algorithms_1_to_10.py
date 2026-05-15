#!/usr/bin/env python3
"""
Smoke all optimizer engines on small real circuits.

This is intentionally focused rather than exhaustive:
- algorithms 1-10 must all produce CEC-PASS output on c17;
- algorithms 8-10 are also checked on c432, where the current SAT engines
  are expected to reduce 125 AND gates to 121.
"""

import importlib
import os
import sys
import tempfile

from verifier import verify_equivalence


ALGORITHMS = [
    ("ALG1", "optimizer_alg1"),
    ("ALG2", "optimizer_alg2"),
    ("ALG3", "optimizer_alg3"),
    ("ALG4", "optimizer_alg3_saf"),
    ("ALG5", "optimizer_alg3_sim"),
    ("ALG6", "optimizer_alg3_timeout_cadical"),
    ("ALG7", "optimizer_alg7_iterative"),
    ("ALG8", "optimizer_alg8_hybrid"),
    ("ALG9", "optimizer_alg9_incremental"),
    ("ALG10", "optimizer_alg10_tiered"),
]


def load_optimizer(module_name, tmp):
    sys.modules.pop(module_name, None)
    if module_name == "optimizer_alg9_incremental":
        os.environ["ALG9_EXHAUSTIVE"] = "1"
        os.environ["ALG9_ALLOW_VERY_LARGE_SAT"] = "1"
        os.environ["ALG9_MAX_CANDIDATES"] = "0"
        os.environ["ALG9_MAX_SAT_SECONDS"] = "20"
    if module_name == "optimizer_alg10_tiered":
        os.environ["ALG10_MODE"] = "deep_resume"
        os.environ["ALG10_BUDGETS"] = "1000,5000,20000"
        os.environ["ALG10_MAX_CIRCUIT_SECONDS"] = "30"
        os.environ["ALG10_CHECKPOINT_DIR"] = os.path.join(tmp, "alg10_checkpoints")
        os.environ["ALG10_RESET_CHECKPOINT"] = "1"
    return importlib.import_module(module_name)


def run_optimizer(label, module_name, src, out_dir, tmp):
    optimizer = load_optimizer(module_name, tmp)
    out = os.path.join(out_dir, f"{label}_{os.path.basename(src)}")
    result = optimizer.solve_circuit(src, out)

    if len(result) == 5:
        orig, _, final, removed, timings = result
    else:
        orig, _, final, _, _, removed, dur = result
        timings = {"Total": dur}

    status, _ = verify_equivalence(src, out)
    return {
        "label": label,
        "src": os.path.basename(src),
        "orig": orig,
        "final": final,
        "removed": removed,
        "status": status,
        "total": timings.get("Total", 0.0),
    }


def test_algorithms_1_to_10():
    with tempfile.TemporaryDirectory(prefix="alg_smoke_") as tmp:
        out_dir = os.path.join(tmp, "outs")
        os.makedirs(out_dir, exist_ok=True)

        rows = []
        for label, module_name in ALGORITHMS:
            row = run_optimizer(label, module_name, "benchmarks/c17.aag", out_dir, tmp)
            rows.append(row)
            print(
                f"{label:<5} c17  {row['orig']:>4}->{row['final']:<4} "
                f"removed={row['removed']:<3} CEC={row['status']} "
                f"total={row['total']:.4f}s"
            )
            assert row["status"] == "PASS"

        for label, module_name in ALGORITHMS[-3:]:
            row = run_optimizer(label, module_name, "benchmarks/c432.aag", out_dir, tmp)
            rows.append(row)
            print(
                f"{label:<5} c432 {row['orig']:>4}->{row['final']:<4} "
                f"removed={row['removed']:<3} CEC={row['status']} "
                f"total={row['total']:.4f}s"
            )
            assert row["status"] == "PASS"
            assert row["final"] <= row["orig"]


if __name__ == "__main__":
    test_algorithms_1_to_10()
