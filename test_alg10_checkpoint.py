#!/usr/bin/env python3
"""
Focused checks for Algorithm 10's safe checkpoint/resume behavior.

These are script-style smoke tests:
- fast-save mode should fully reduce a tiny ODC circuit and pass CEC;
- a tiny time budget should checkpoint c432 safely;
- deep-resume mode should resume that checkpoint and still produce CEC PASS.
"""

import importlib
import os
import sys
import tempfile

from verifier import verify_equivalence


def write_odc_redundant_circuit(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="ascii") as f:
        f.write("aag 4 2 0 1 2\n")
        f.write("2\n")
        f.write("4\n")
        f.write("9\n")
        f.write("6 2 4\n")
        f.write("8 7 3\n")
        f.write("i0 x\n")
        f.write("i1 y\n")
        f.write("o0 out\n")
        f.write("c\n")
        f.write("ODC redundant: out = x OR (x AND y) = x\n")


def write_tfi_constant_circuit(path):
    """Write out = (a & b) & (a & ~b), functionally constant 0."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="ascii") as f:
        f.write("aag 5 2 0 1 3\n")
        f.write("2\n")
        f.write("4\n")
        f.write("10\n")
        f.write("6 2 4\n")
        f.write("8 2 5\n")
        f.write("10 6 8\n")
        f.write("i0 a\n")
        f.write("i1 b\n")
        f.write("o0 out\n")
        f.write("c\n")
        f.write("TFI constant: (a & b) & (a & ~b) = 0\n")


def load_alg10(mode, checkpoint_dir, seconds, budgets, reset=False, tfi=True):
    sys.modules.pop("optimizer_alg10_tiered", None)
    os.environ["ALG10_MODE"] = mode
    os.environ["ALG10_CHECKPOINT_DIR"] = checkpoint_dir
    os.environ["ALG10_MAX_CIRCUIT_SECONDS"] = str(seconds)
    os.environ["ALG10_BUDGETS"] = budgets
    os.environ["ALG10_RESET_CHECKPOINT"] = "1" if reset else "0"
    os.environ["ALG10_TFI_CONSTANCY"] = "1" if tfi else "0"
    return importlib.import_module("optimizer_alg10_tiered")


def run_case(src, out, mode, checkpoint_dir, seconds, budgets, reset=False, tfi=True):
    optimizer = load_alg10(mode, checkpoint_dir, seconds, budgets, reset=reset, tfi=tfi)
    orig, _, final, removed, timings = optimizer.solve_circuit(src, out)
    status, _ = verify_equivalence(src, out)
    return {
        "orig": orig,
        "final": final,
        "removed": removed,
        "status": status,
        "abort": timings.get("SAT_Abort_Reason", ""),
        "checks": timings.get("SAT_Checks", 0),
        "resumed": timings.get("Checkpoint_Resume", 0),
        "unresolved": timings.get("SAT_Unresolved", 0),
        "tfi_unsat": timings.get("TFI_Query_UNSAT", 0),
        "global_unsat": timings.get("Global_Query_UNSAT", 0),
    }


def test_alg10_checkpoint_resume():
    with tempfile.TemporaryDirectory(prefix="alg10_ckpt_") as tmp:
        checkpoint_dir = os.path.join(tmp, "checkpoints")
        odc = os.path.join(tmp, "odc.aag")
        odc_out = os.path.join(tmp, "odc_out.aag")
        write_odc_redundant_circuit(odc)

        fast = run_case(
            odc,
            odc_out,
            mode="fast_save",
            checkpoint_dir=checkpoint_dir,
            seconds=10,
            budgets="100,1000,5000",
            reset=True,
        )
        print(f"alg10 fast-save ODC: {fast}")
        assert fast["status"] == "PASS"
        assert fast["final"] < fast["orig"]

        tfi_const = os.path.join(tmp, "tfi_const.aag")
        tfi_out = os.path.join(tmp, "tfi_const_out.aag")
        write_tfi_constant_circuit(tfi_const)
        tfi = run_case(
            tfi_const,
            tfi_out,
            mode="fast_save",
            checkpoint_dir=checkpoint_dir,
            seconds=10,
            budgets="100,1000",
            reset=True,
            tfi=True,
        )
        print(f"alg10 TFI-constant: {tfi}")
        assert tfi["status"] == "PASS"
        assert tfi["final"] < tfi["orig"]
        assert tfi["tfi_unsat"] > 0

        c432 = "benchmarks/c432.aag"
        partial_out = os.path.join(tmp, "c432_partial.aag")
        partial = run_case(
            c432,
            partial_out,
            mode="fast_save",
            checkpoint_dir=checkpoint_dir,
            seconds=0.001,
            budgets="1",
            reset=True,
        )
        print(f"alg10 fast-save c432 checkpoint: {partial}")
        assert partial["status"] == "PASS"
        assert partial["abort"] in {"TIME_BUDGET_CHECKPOINT", "UNRESOLVED_TIMEOUTS"}

        resumed_out = os.path.join(tmp, "c432_resumed.aag")
        resumed = run_case(
            c432,
            resumed_out,
            mode="deep_resume",
            checkpoint_dir=checkpoint_dir,
            seconds=20,
            budgets="1000,5000,20000",
            reset=False,
        )
        print(f"alg10 deep-resume c432: {resumed}")
        assert resumed["status"] == "PASS"
        assert resumed["resumed"] == 1
        assert resumed["final"] <= partial["final"]


if __name__ == "__main__":
    test_alg10_checkpoint_resume()
