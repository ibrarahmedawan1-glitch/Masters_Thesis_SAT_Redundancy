#!/usr/bin/env python3
"""Run ABC-only baseline flows on project benchmarks.

This script intentionally does not call any optimizer_alg*.py module.  It uses
the project ABC/AIGER bridge only for format conversion and final CEC.
"""

import argparse
import csv
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

from aag_metrics import compute_aag_metrics
from abc_utils import run_abc_cec, to_ascii_aag, to_binary_aig


REPO_ROOT = Path(__file__).resolve().parent
ABC_PATH = REPO_ROOT / "abc" / "abc"

RESYN2_SCRIPT = (
    "balance; rewrite; refactor; balance; rewrite; rewrite -z; "
    "balance; refactor -z; rewrite -z; balance"
)

FLOW_SCRIPTS = {
    "strash": "strash",
    "balance": "strash; balance",
    "rewrite": "strash; rewrite",
    "refactor": "strash; refactor",
    "dc2": "strash; dc2",
    "dch": "strash; dch",
    "fraig": "strash; fraig",
    "resyn2": f"strash; {RESYN2_SCRIPT}",
    "resyn2x2": f"strash; {RESYN2_SCRIPT}; {RESYN2_SCRIPT}",
    "dc2_fraig": "strash; dc2; fraig",
    "dch_resyn2": f"strash; dch; {RESYN2_SCRIPT}",
}

DEFAULT_FLOWS = ["strash", "dc2", "dch", "fraig", "resyn2", "resyn2x2"]


def pct(saved, before):
    if before <= 0:
        return "0.00%"
    return f"{100.0 * saved / before:.2f}%"


def numeric(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def latest_alg10_csv():
    files = sorted(
        (REPO_ROOT / "results_optimized").glob("thesis_results_ALG10*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def timestamp_from_result_csv(path):
    match = re.search(r"_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.csv$", path.name)
    return match.group(1) if match else None


def dataset_for_result_csv(path):
    stamp = timestamp_from_result_csv(path)
    if not stamp:
        return None
    candidate = REPO_ROOT / "results_optimized" / "datasets" / f"dataset_{stamp}"
    return candidate if candidate.exists() else None


def default_input_paths():
    latest = latest_alg10_csv()
    if latest:
        dataset = dataset_for_result_csv(latest)
        if dataset:
            return [dataset], latest
    fallback = []
    for path in [REPO_ROOT / "benchmarks", REPO_ROOT / "benchmark_suites" / "epfl"]:
        if path.exists():
            fallback.append(path)
    return fallback, latest


def collect_circuits(paths):
    circuits = []
    seen = set()
    for raw in paths:
        path = Path(raw)
        if not path.is_absolute():
            path = REPO_ROOT / path
        if path.is_file() and path.suffix.lower() in {".aag", ".aig"}:
            candidates = [path]
        elif path.is_dir():
            candidates = sorted(
                item
                for item in path.rglob("*")
                if item.is_file() and item.suffix.lower() in {".aag", ".aig"}
            )
        else:
            continue
        for item in candidates:
            key = item.resolve()
            if key not in seen:
                seen.add(key)
                circuits.append(item)
    return circuits


def classify_circuit(path):
    parts = set(path.parts)
    name = path.name
    if name.startswith("planted_live_"):
        return "Planted_Live"
    if name.startswith("epfl_") or "epfl" in parts:
        return "EPFL"
    if "custom_circuits" in parts:
        return "Custom"
    return "Benchmark"


def load_reference_rows(reference_csv):
    if not reference_csv:
        return {}
    if reference_csv == "latest":
        path = latest_alg10_csv()
    else:
        path = Path(reference_csv)
        if not path.is_absolute():
            path = REPO_ROOT / path
    if not path or not path.exists():
        return {}

    rows = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            circuit = row.get("Circuit")
            if circuit:
                rows[circuit] = row
                rows[Path(circuit).name] = row
    return rows


def normalize_input_to_aag(circuit, tmp_dir):
    if circuit.suffix.lower() == ".aag":
        return circuit
    normalized = Path(tmp_dir) / f"{circuit.stem}.input.aag"
    if not to_ascii_aag(str(circuit), str(normalized), comment="ABC baseline input normalization"):
        raise RuntimeError(f"failed to normalize binary AIG input: {circuit}")
    return normalized


def run_abc_flow(input_aag, output_aag, flow_name, flow_script, timeout):
    start = time.time()
    output_aag.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"abc_baseline_{flow_name}_") as tmp:
        tmp_path = Path(tmp)
        in_aig = tmp_path / "input.aig"
        out_aig = tmp_path / "output.aig"
        out_aag_tmp = tmp_path / "output.aag"

        convert_start = time.time()
        if not to_binary_aig(str(input_aag), str(in_aig)):
            return {
                "status": "ERROR",
                "abc_time": 0.0,
                "convert_time": time.time() - convert_start,
                "total_time": time.time() - start,
                "log": f"failed to convert {input_aag} to binary AIG",
            }
        convert_time = time.time() - convert_start

        abc_cmd = f"read_aiger {in_aig}; {flow_script}; write_aiger {out_aig}; quit"
        abc_start = time.time()
        try:
            result = subprocess.run(
                [str(ABC_PATH), "-c", abc_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "TIMEOUT",
                "abc_time": timeout,
                "convert_time": convert_time,
                "total_time": time.time() - start,
                "log": "ABC flow timed out",
            }
        abc_time = time.time() - abc_start
        log = (result.stdout + result.stderr).decode("utf-8", errors="ignore")
        if result.returncode != 0 or not out_aig.exists() or out_aig.stat().st_size == 0:
            return {
                "status": "ERROR",
                "abc_time": abc_time,
                "convert_time": convert_time,
                "total_time": time.time() - start,
                "log": log.strip()[-1000:],
            }

        convert_back_start = time.time()
        if not to_ascii_aag(str(out_aig), str(out_aag_tmp), comment=f"ABC baseline {flow_name}"):
            return {
                "status": "ERROR",
                "abc_time": abc_time,
                "convert_time": convert_time + (time.time() - convert_back_start),
                "total_time": time.time() - start,
                "log": "failed to convert ABC output to ASCII AAG",
            }
        shutil.copy(out_aag_tmp, output_aag)
        convert_time += time.time() - convert_back_start

    return {
        "status": "OK",
        "abc_time": abc_time,
        "convert_time": convert_time,
        "total_time": time.time() - start,
        "log": "",
    }


DETAIL_FIELDS = [
    "Timestamp",
    "Circuit",
    "Type",
    "Source_Path",
    "Flow",
    "Flow_Script",
    "Status",
    "Verify",
    "Original_Gates",
    "Final_Gates",
    "Gates_Removed",
    "Total_Red%",
    "Area_Before_AND2",
    "Area_After_AND2",
    "Area_Saved_AND2",
    "Area_Red%",
    "Depth_Before",
    "Depth_After",
    "Depth_Red%",
    "Reference_Final_Gates",
    "Reference_Gates_Removed",
    "Reference_SAT_Unresolved",
    "Area_Saved_Delta_vs_Reference",
    "T_ABC(s)",
    "T_Convert(s)",
    "T_CEC(s)",
    "T_Total(s)",
    "Output_Path",
    "Error",
]


def make_error_row(stamp, circuit, flow_name, flow_script, before, status, error, source_type):
    return {
        "Timestamp": stamp,
        "Circuit": circuit.name,
        "Type": source_type,
        "Source_Path": str(circuit),
        "Flow": flow_name,
        "Flow_Script": flow_script,
        "Status": status,
        "Verify": "",
        "Original_Gates": before.get("Gates", 0),
        "Final_Gates": "",
        "Gates_Removed": "",
        "Total_Red%": "",
        "Area_Before_AND2": before.get("Area_AND2", 0),
        "Area_After_AND2": "",
        "Area_Saved_AND2": "",
        "Area_Red%": "",
        "Depth_Before": before.get("Depth", 0),
        "Depth_After": "",
        "Depth_Red%": "",
        "Reference_Final_Gates": "",
        "Reference_Gates_Removed": "",
        "Reference_SAT_Unresolved": "",
        "Area_Saved_Delta_vs_Reference": "",
        "T_ABC(s)": "",
        "T_Convert(s)": "",
        "T_CEC(s)": "",
        "T_Total(s)": "",
        "Output_Path": "",
        "Error": error,
    }


def summarize_by_flow(rows):
    summary = []
    flows = sorted({row["Flow"] for row in rows})
    for flow in flows:
        flow_rows = [row for row in rows if row["Flow"] == flow]
        ok_rows = [row for row in flow_rows if row["Status"] == "OK"]
        pass_rows = [row for row in ok_rows if row["Verify"] == "PASS"]
        before = sum(numeric(row["Area_Before_AND2"]) for row in pass_rows)
        after = sum(numeric(row["Area_After_AND2"]) for row in pass_rows)
        saved = before - after
        ref_delta_values = [
            numeric(row["Area_Saved_Delta_vs_Reference"])
            for row in pass_rows
            if row["Area_Saved_Delta_vs_Reference"] != ""
        ]
        summary.append(
            {
                "Flow": flow,
                "Rows": len(flow_rows),
                "OK": len(ok_rows),
                "CEC_PASS": len(pass_rows),
                "CEC_FAIL_OR_OTHER": len(ok_rows) - len(pass_rows),
                "Timeout_or_Error": len(flow_rows) - len(ok_rows),
                "Area_Before_AND2": before,
                "Area_After_AND2": after,
                "Area_Saved_AND2": saved,
                "Area_Red%": pct(saved, before),
                "Depth_Saved_Total": sum(
                    numeric(row["Depth_Before"]) - numeric(row["Depth_After"])
                    for row in pass_rows
                ),
                "T_ABC_Total(s)": f"{sum(float(row['T_ABC(s)'] or 0) for row in ok_rows):.4f}",
                "T_Total(s)": f"{sum(float(row['T_Total(s)'] or 0) for row in ok_rows):.4f}",
                "Area_Saved_Delta_vs_Reference_Total": sum(ref_delta_values),
            }
        )
    return summary


def best_by_circuit(rows):
    best = []
    circuits = sorted({row["Circuit"] for row in rows})
    for circuit in circuits:
        pass_rows = [
            row for row in rows if row["Circuit"] == circuit and row["Status"] == "OK" and row["Verify"] == "PASS"
        ]
        if not pass_rows:
            continue
        best_area = min(pass_rows, key=lambda row: (numeric(row["Area_After_AND2"]), float(row["T_Total(s)"] or 0)))
        best_depth = min(pass_rows, key=lambda row: (numeric(row["Depth_After"]), numeric(row["Area_After_AND2"])))
        best.append(
            {
                "Circuit": circuit,
                "Type": best_area["Type"],
                "Original_Gates": best_area["Original_Gates"],
                "Best_Area_Flow": best_area["Flow"],
                "Best_Area_AND2": best_area["Area_After_AND2"],
                "Best_Area_Saved_AND2": best_area["Area_Saved_AND2"],
                "Best_Area_Red%": best_area["Area_Red%"],
                "Best_Depth_Flow": best_depth["Flow"],
                "Best_Depth": best_depth["Depth_After"],
                "Reference_Gates_Removed": best_area["Reference_Gates_Removed"],
                "Best_Area_Delta_vs_Reference": best_area["Area_Saved_Delta_vs_Reference"],
            }
        )
    return best


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run ABC baseline flows on AAG/AIG benchmarks and verify each output with ABC CEC."
    )
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        help="Input .aag/.aig file or directory. Repeatable. Defaults to the latest Alg10 dataset if available.",
    )
    parser.add_argument(
        "--flows",
        default=",".join(DEFAULT_FLOWS),
        help=f"Comma-separated flows. Available: {', '.join(sorted(FLOW_SCRIPTS))}",
    )
    parser.add_argument("--output-dir", default=None, help="Output directory for CSVs and generated AAGs.")
    parser.add_argument("--timeout", type=float, default=600, help="ABC timeout per circuit/flow in seconds.")
    parser.add_argument("--cec-timeout", type=float, default=60, help="ABC CEC timeout per output in seconds.")
    parser.add_argument("--max-circuits", type=int, default=0, help="Limit number of circuits for smoke tests.")
    parser.add_argument("--filter", default="", help="Regex filter applied to circuit filename.")
    parser.add_argument(
        "--reference-csv",
        default="latest",
        help="Optional Alg10 CSV for comparison columns. Use 'latest' or 'none'.",
    )
    parser.add_argument(
        "--list-flows",
        action="store_true",
        help="Print available flow names and scripts, then exit.",
    )
    return parser.parse_args()


def main():
    os.chdir(REPO_ROOT)
    args = parse_args()

    if args.list_flows:
        for name in sorted(FLOW_SCRIPTS):
            print(f"{name}: {FLOW_SCRIPTS[name]}")
        return 0

    if not ABC_PATH.exists():
        raise SystemExit(f"ABC binary not found: {ABC_PATH}")

    input_paths = [Path(path) for path in args.input]
    default_reference = None
    if not input_paths:
        input_paths, default_reference = default_input_paths()
    if args.reference_csv == "latest":
        reference_rows = load_reference_rows(str(default_reference) if default_reference else "latest")
    elif args.reference_csv.lower() in {"", "none", "off"}:
        reference_rows = {}
    else:
        reference_rows = load_reference_rows(args.reference_csv)

    circuits = collect_circuits(input_paths)
    if args.filter:
        pattern = re.compile(args.filter)
        circuits = [path for path in circuits if pattern.search(path.name)]
    if args.max_circuits > 0:
        circuits = circuits[: args.max_circuits]
    if not circuits:
        raise SystemExit("No .aag/.aig circuits found.")

    flow_names = [name.strip() for name in args.flows.split(",") if name.strip()]
    unknown = [name for name in flow_names if name not in FLOW_SCRIPTS]
    if unknown:
        raise SystemExit(f"Unknown flow(s): {', '.join(unknown)}. Use --list-flows.")

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_dir = Path(args.output_dir) if args.output_dir else REPO_ROOT / "results_optimized" / "abc_baselines" / stamp
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    aag_dir = out_dir / "aag_outputs"
    detail_csv = out_dir / f"abc_baseline_{stamp}.csv"
    summary_csv = out_dir / f"abc_baseline_summary_by_flow_{stamp}.csv"
    best_csv = out_dir / f"abc_baseline_best_by_circuit_{stamp}.csv"

    print(f"[ABC baseline] circuits={len(circuits)} flows={','.join(flow_names)}")
    print(f"[ABC baseline] output_dir={out_dir}")
    if reference_rows:
        print("[ABC baseline] reference comparison enabled")

    rows = []
    for circuit_idx, circuit in enumerate(circuits, start=1):
        source_type = classify_circuit(circuit)
        with tempfile.TemporaryDirectory(prefix="abc_baseline_input_") as tmp:
            try:
                input_aag = normalize_input_to_aag(circuit, tmp)
                before = compute_aag_metrics(str(input_aag))
            except Exception as exc:
                for flow_name in flow_names:
                    rows.append(
                        make_error_row(
                            stamp,
                            circuit,
                            flow_name,
                            FLOW_SCRIPTS[flow_name],
                            {},
                            "ERROR",
                            str(exc),
                            source_type,
                        )
                    )
                continue

            ref = reference_rows.get(circuit.name, {})
            for flow_idx, flow_name in enumerate(flow_names, start=1):
                flow_script = FLOW_SCRIPTS[flow_name]
                safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", circuit.stem)
                output_aag = aag_dir / flow_name / f"{safe_stem}.aag"
                print(f"  [{circuit_idx}/{len(circuits)} {flow_idx}/{len(flow_names)}] {circuit.name} :: {flow_name}")

                result = run_abc_flow(input_aag, output_aag, flow_name, flow_script, timeout=args.timeout)
                if result["status"] != "OK":
                    rows.append(
                        make_error_row(
                            stamp,
                            circuit,
                            flow_name,
                            flow_script,
                            before,
                            result["status"],
                            result["log"],
                            source_type,
                        )
                    )
                    continue

                try:
                    after = compute_aag_metrics(str(output_aag))
                except Exception as exc:
                    rows.append(
                        make_error_row(
                            stamp,
                            circuit,
                            flow_name,
                            flow_script,
                            before,
                            "ERROR",
                            str(exc),
                            source_type,
                        )
                    )
                    continue

                verify, cec_time, _ = run_abc_cec(str(input_aag), str(output_aag), timeout=args.cec_timeout)

                gates_saved = before["Gates"] - after["Gates"]
                area_saved = before["Area_AND2"] - after["Area_AND2"]
                depth_saved = before["Depth"] - after["Depth"]
                reference_removed = ref.get("Gates_Removed", "")
                delta_vs_ref = ""
                if reference_removed != "":
                    delta_vs_ref = area_saved - numeric(reference_removed)

                rows.append(
                    {
                        "Timestamp": stamp,
                        "Circuit": circuit.name,
                        "Type": source_type,
                        "Source_Path": str(circuit),
                        "Flow": flow_name,
                        "Flow_Script": flow_script,
                        "Status": result["status"],
                        "Verify": verify,
                        "Original_Gates": before["Gates"],
                        "Final_Gates": after["Gates"],
                        "Gates_Removed": gates_saved,
                        "Total_Red%": pct(gates_saved, before["Gates"]),
                        "Area_Before_AND2": before["Area_AND2"],
                        "Area_After_AND2": after["Area_AND2"],
                        "Area_Saved_AND2": area_saved,
                        "Area_Red%": pct(area_saved, before["Area_AND2"]),
                        "Depth_Before": before["Depth"],
                        "Depth_After": after["Depth"],
                        "Depth_Red%": pct(depth_saved, before["Depth"]),
                        "Reference_Final_Gates": ref.get("Final_Gates", ""),
                        "Reference_Gates_Removed": reference_removed,
                        "Reference_SAT_Unresolved": ref.get("SAT_Unresolved", ""),
                        "Area_Saved_Delta_vs_Reference": delta_vs_ref,
                        "T_ABC(s)": f"{result['abc_time']:.4f}",
                        "T_Convert(s)": f"{result['convert_time']:.4f}",
                        "T_CEC(s)": f"{cec_time:.4f}",
                        "T_Total(s)": f"{(result['total_time'] + cec_time):.4f}",
                        "Output_Path": str(output_aag),
                        "Error": "",
                    }
                )

    write_csv(detail_csv, rows, DETAIL_FIELDS)

    summary_rows = summarize_by_flow(rows)
    write_csv(summary_csv, summary_rows, list(summary_rows[0].keys()) if summary_rows else ["Flow"])

    best_rows = best_by_circuit(rows)
    write_csv(best_csv, best_rows, list(best_rows[0].keys()) if best_rows else ["Circuit"])

    print("\n[ABC baseline] done")
    print(f"  Detail:  {detail_csv}")
    print(f"  Summary: {summary_csv}")
    print(f"  Best:    {best_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
