#!/usr/bin/env python3
"""
Focused smoke/comparison runner for committed in-memory incremental SAT.

The default run is intentionally small:
- a deterministic observability-don't-care circuit that should shrink;
- c17;
- c432.

It writes optimized circuits and a timestamped CSV under
results_optimized/incremental_sat_test/ so the outputs can be compared later.
"""

import argparse
import csv
import importlib
import os
import shutil
from datetime import datetime

from abc_utils import to_ascii_aag
from aag_metrics import compute_aag_metrics
from verifier import verify_equivalence


RESULT_ROOT = "results_optimized/incremental_sat_test"


def write_odc_redundant_circuit(path):
    """Write out = x OR (x AND y), encoded as AIG with a redundant AND gate."""
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


def prepare_inputs(run_dir, include_large=False, include_epfl=False):
    input_dir = os.path.join(run_dir, "inputs")
    os.makedirs(input_dir, exist_ok=True)

    circuits = []
    odc = os.path.join(input_dir, "odc_redundant.aag")
    write_odc_redundant_circuit(odc)
    circuits.append(("ODC_Redundant", odc))

    for name in ["c17.aag", "c432.aag"]:
        src = os.path.join("benchmarks", name)
        if os.path.exists(src):
            dst = os.path.join(input_dir, name)
            shutil.copy(src, dst)
            circuits.append(("ISCAS", dst))

    if include_large:
        for name in ["c880.aag", "c1355.aag", "c1908.aag"]:
            src = os.path.join("benchmarks", name)
            if os.path.exists(src):
                dst = os.path.join(input_dir, name)
                shutil.copy(src, dst)
                circuits.append(("ISCAS_Large", dst))

    if include_epfl:
        epfl_sources = [
            "epfl_benchmarks/random_control/dec.aig",
            "epfl_benchmarks/random_control/priority.aig",
            "epfl_benchmarks/random_control/router.aig",
        ]
        for src in epfl_sources:
            if not os.path.exists(src):
                continue
            name = os.path.splitext(os.path.basename(src))[0] + ".aag"
            dst = os.path.join(input_dir, "epfl_" + name)
            if to_ascii_aag(src, dst, comment="EPFL converted for incremental SAT test"):
                circuits.append(("EPFL", dst))

    return circuits


def run_optimizer(module_name, label, circuit_path, out_dir):
    optimizer = importlib.import_module(module_name)
    os.makedirs(out_dir, exist_ok=True)
    output_path = os.path.join(out_dir, os.path.basename(circuit_path))

    result = optimizer.solve_circuit(circuit_path, output_path)
    if len(result) == 5:
        orig, _, final, removed, timings = result
    else:
        orig, _, final, _, _, removed, total = result
        timings = {"Parse": 0.0, "Filter": 0.0, "Encode": 0.0, "SAT": 0.0, "Total": total}

    status, cec_time = verify_equivalence(circuit_path, output_path)
    in_bytes = os.path.getsize(circuit_path)
    out_bytes = os.path.getsize(output_path)
    before_metrics = compute_aag_metrics(circuit_path)
    after_metrics = compute_aag_metrics(output_path)

    gate_delta = max(0, orig - final)
    depth_before = before_metrics["Depth"]
    depth_after = after_metrics["Depth"]
    depth_red = ((depth_before - depth_after) / depth_before * 100) if depth_before > 0 else 0.0

    return {
        "Algorithm": label,
        "Circuit": os.path.basename(circuit_path),
        "Original_Gates": orig,
        "Final_Gates": final,
        "Gates_Removed": gate_delta,
        "Reported_Removed": removed,
        "Area_Before_AND2": orig,
        "Area_After_AND2": final,
        "Area_Saved_AND2": gate_delta,
        "Area_Red%": f"{((gate_delta / orig) * 100) if orig > 0 else 0.0:.2f}%",
        "Depth_Before": depth_before,
        "Depth_After": depth_after,
        "Depth_Red%": f"{depth_red:.2f}%",
        "Input_Bytes": in_bytes,
        "Output_Bytes": out_bytes,
        "Bytes_Reduced": in_bytes - out_bytes,
        "T_Parse(s)": timings.get("Parse", 0.0),
        "T_Filter(s)": timings.get("Filter", 0.0),
        "T_Encode(s)": timings.get("Encode", 0.0),
        "T_SAT(s)": timings.get("SAT", 0.0),
        "T_CEC(s)": cec_time,
        "T_Total(s)": timings.get("Total", 0.0),
        "SAT_Checks": timings.get("SAT_Checks", ""),
        "SAT_Candidates": timings.get("SAT_Candidates", ""),
        "SAT_Query_SAT": timings.get("SAT_Query_SAT", ""),
        "SAT_Query_UNSAT": timings.get("SAT_Query_UNSAT", ""),
        "SAT_Timeouts": timings.get("SAT_Timeouts", ""),
        "SAT_Abort_Reason": timings.get("SAT_Abort_Reason", ""),
        "Initial_AND2": timings.get("Initial_AND2", ""),
        "After_Structural_AND2": timings.get("After_Structural_AND2", ""),
        "After_SAT_AND2": timings.get("After_SAT_AND2", ""),
        "Structural_Removed_AND2": timings.get("Structural_Removed_AND2", ""),
        "SAT_Induced_Removed_AND2": timings.get("SAT_Induced_Removed_AND2", ""),
        "SAT_Accepted_SA0": timings.get("SAT_Accepted_SA0", ""),
        "SAT_Accepted_SA1": timings.get("SAT_Accepted_SA1", ""),
        "Rebuilds": timings.get("Rebuilds", ""),
        "Passes": timings.get("Passes", ""),
        "Verify": status,
        "Output": output_path,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-alg7", action="store_true", help="also run Algorithm 7")
    parser.add_argument("--large", action="store_true", help="include larger ISCAS circuits")
    parser.add_argument("--epfl", action="store_true", help="include a few converted EPFL AIGs")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = os.path.join(RESULT_ROOT, timestamp)
    circuits = prepare_inputs(run_dir, include_large=args.large, include_epfl=args.epfl)

    algorithms = [
        ("ALG8_Hybrid", "optimizer_alg8_hybrid"),
        ("ALG9_Incremental", "optimizer_alg9_incremental"),
    ]
    if args.with_alg7:
        algorithms.insert(0, ("ALG7_Iterative", "optimizer_alg7_iterative"))

    rows = []
    for category, circuit_path in circuits:
        for label, module_name in algorithms:
            print(f"[RUN] {label:<18} {os.path.basename(circuit_path):<24}", end=" ", flush=True)
            out_dir = os.path.join(run_dir, label)
            try:
                row = run_optimizer(module_name, label, circuit_path, out_dir)
                row["Type"] = category
                rows.append(row)
                print(
                    f"gates {row['Original_Gates']}->{row['Final_Gates']} "
                    f"bytes {row['Input_Bytes']}->{row['Output_Bytes']} "
                    f"CEC {row['Verify']} total {float(row['T_Total(s)']):.4f}s"
                )
            except Exception as exc:
                print(f"ERROR {exc}")
                rows.append(
                    {
                        "Algorithm": label,
                        "Circuit": os.path.basename(circuit_path),
                        "Type": category,
                        "Original_Gates": 0,
                        "Final_Gates": 0,
                        "Gates_Removed": 0,
                        "Reported_Removed": 0,
                        "Area_Before_AND2": 0,
                        "Area_After_AND2": 0,
                        "Area_Saved_AND2": 0,
                        "Area_Red%": "ERR",
                        "Depth_Before": 0,
                        "Depth_After": 0,
                        "Depth_Red%": "ERR",
                        "Input_Bytes": os.path.getsize(circuit_path),
                        "Output_Bytes": 0,
                        "Bytes_Reduced": 0,
                        "T_Parse(s)": 0.0,
                        "T_Filter(s)": 0.0,
                        "T_Encode(s)": 0.0,
                        "T_SAT(s)": 0.0,
                        "T_CEC(s)": 0.0,
                        "T_Total(s)": 0.0,
                        "SAT_Checks": "",
                        "SAT_Candidates": "",
                        "SAT_Query_SAT": "",
                        "SAT_Query_UNSAT": "",
                        "SAT_Timeouts": "",
                        "SAT_Abort_Reason": "",
                        "Initial_AND2": "",
                        "After_Structural_AND2": "",
                        "After_SAT_AND2": "",
                        "Structural_Removed_AND2": "",
                        "SAT_Induced_Removed_AND2": "",
                        "SAT_Accepted_SA0": "",
                        "SAT_Accepted_SA1": "",
                        "Rebuilds": "",
                        "Passes": "",
                        "Verify": "ERROR",
                        "Output": "",
                    }
                )

    csv_path = os.path.join(run_dir, f"incremental_sat_comparison_{timestamp}.csv")
    fieldnames = [
        "Algorithm",
        "Circuit",
        "Type",
        "Original_Gates",
        "Final_Gates",
        "Gates_Removed",
        "Reported_Removed",
        "Area_Before_AND2",
        "Area_After_AND2",
        "Area_Saved_AND2",
        "Area_Red%",
        "Depth_Before",
        "Depth_After",
        "Depth_Red%",
        "Input_Bytes",
        "Output_Bytes",
        "Bytes_Reduced",
        "T_Parse(s)",
        "T_Filter(s)",
        "T_Encode(s)",
        "T_SAT(s)",
        "T_CEC(s)",
        "T_Total(s)",
        "SAT_Checks",
        "SAT_Candidates",
        "SAT_Query_SAT",
        "SAT_Query_UNSAT",
        "SAT_Timeouts",
        "SAT_Abort_Reason",
        "Initial_AND2",
        "After_Structural_AND2",
        "After_SAT_AND2",
        "Structural_Removed_AND2",
        "SAT_Induced_Removed_AND2",
        "SAT_Accepted_SA0",
        "SAT_Accepted_SA1",
        "Rebuilds",
        "Passes",
        "Verify",
        "Output",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n[DONE] Wrote comparison CSV: {csv_path}")


if __name__ == "__main__":
    main()
