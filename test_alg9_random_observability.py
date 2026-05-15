#!/usr/bin/env python3
"""
Focused smoke test for Algorithm 9's random-observability candidate filter.

The ODC circuit is out = x OR (x AND y). The internal x AND y node toggles, so
plain random value signatures do not nominate it as a constant-like stuck-at
candidate. Random observability should nominate its stuck-at-0 fault, and SAT
must still prove the replacement before the optimizer commits it.
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


def load_alg9(random_observability):
    sys.modules.pop("optimizer_alg9_incremental", None)
    os.environ["ALG9_FAULT_SIM_MAX_GATES"] = "0"
    os.environ["ALG9_RANDOM_OBS_SIM"] = "1" if random_observability else "0"
    os.environ["ALG9_MAX_CANDIDATES"] = "32"
    os.environ["ALG9_MAX_SAT_SECONDS"] = "10"
    return importlib.import_module("optimizer_alg9_incremental")


def run_case(input_path, output_path, random_observability):
    optimizer = load_alg9(random_observability)
    orig, _, final, removed, timings = optimizer.solve_circuit(input_path, output_path)
    status, _ = verify_equivalence(input_path, output_path)
    return {
        "orig": orig,
        "final": final,
        "removed": removed,
        "status": status,
        "candidates": timings.get("SAT_Candidates", 0),
        "checks": timings.get("SAT_Checks", 0),
        "unsat": timings.get("SAT_Query_UNSAT", 0),
    }


def test_random_observability_filter():
    with tempfile.TemporaryDirectory(prefix="alg9_random_obs_") as tmp:
        input_path = os.path.join(tmp, "odc.aag")
        signature_out = os.path.join(tmp, "signature_only.aag")
        observability_out = os.path.join(tmp, "random_observability.aag")
        write_odc_redundant_circuit(input_path)

        signature = run_case(input_path, signature_out, random_observability=False)
        observability = run_case(input_path, observability_out, random_observability=True)

        print(f"signature-only:      {signature}")
        print(f"random-observability:{observability}")

        assert signature["status"] == "PASS"
        assert observability["status"] == "PASS"
        assert signature["candidates"] == 0
        assert signature["final"] == signature["orig"]
        assert observability["candidates"] > 0
        assert observability["checks"] > 0
        assert observability["unsat"] > 0
        assert observability["final"] < observability["orig"]


if __name__ == "__main__":
    test_random_observability_filter()
