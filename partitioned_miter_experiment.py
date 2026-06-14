#!/usr/bin/env python3
"""Compare monolithic exact cone miters with affected-root partitions.

This is an experiment-only runner.  It does not rewrite circuits and does not
change Algorithm 10.  The purpose is to test whether splitting one candidate's
affected output/latch-next roots into smaller exact miters can resolve the same
single stuck-at proof obligations faster than one large affected-root miter.
"""

import argparse
import csv
import os
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pysat.solvers import Glucose4

import optimizer_alg10_tiered as alg10
from optimizer_alg8_hybrid import parse_aag


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_CIRCUITS = [
    "benchmarks/c17.aag",
    "benchmarks/c432.aag",
    "benchmarks/c7552.aag",
    "benchmark_suites/epfl/epfl_arithmetic_sin.aag",
    "benchmark_suites/epfl/epfl_random_control_voter.aag",
]


@dataclass
class ExactResult:
    status: str
    encode_s: float = 0.0
    sat_s: float = 0.0
    clauses: int = 0
    cone_gates: int = 0
    roots: int = 0
    note: str = ""

    @property
    def total_s(self):
        return self.encode_s + self.sat_s


@dataclass
class PartitionResult:
    status: str
    encode_s: float = 0.0
    sat_s: float = 0.0
    groups: int = 0
    sat_groups: int = 0
    unsat_groups: int = 0
    timeout_groups: int = 0
    error_groups: int = 0
    clauses_total: int = 0
    cone_gates_total: int = 0
    cone_gates_max: int = 0
    first_sat_group: int = -1
    note: str = ""

    @property
    def total_s(self):
        return self.encode_s + self.sat_s


DETAIL_FIELDS = [
    "Circuit",
    "Gate_Count",
    "Root_Count",
    "Candidate_Index",
    "Stuck_Value",
    "Affected_Roots",
    "Partition_Size",
    "Partitions",
    "Mono_Result",
    "Partition_Result",
    "Result_Match",
    "Comparison",
    "TFI_Result",
    "Exact_Proof_Class",
    "Mono_Encode_s",
    "Mono_SAT_s",
    "Mono_Total_s",
    "Mono_Cone_Gates",
    "Mono_Clauses",
    "Partition_Encode_s",
    "Partition_SAT_s",
    "Partition_Total_s",
    "Partition_Cone_Gates_Total",
    "Partition_Cone_Gates_Max",
    "Partition_Clauses_Total",
    "Partition_SAT_Groups",
    "Partition_UNSAT_Groups",
    "Partition_Timeout_Groups",
    "Partition_Error_Groups",
    "First_SAT_Group",
    "Speedup_Mono_Over_Partition",
    "Note",
]


SUMMARY_FIELDS = [
    "Circuit",
    "Partition_Size",
    "Rows",
    "Resolved_Matches",
    "Mismatches",
    "Mono_Timeout_Partition_Resolved",
    "Partition_Timeout_Mono_Resolved",
    "Both_Timeout",
    "Partition_Faster_Same_Result",
    "Mono_Faster_Same_Result",
    "Partition_UNSAT",
    "Partition_SAT",
    "Partition_TIMEOUT",
    "Exact_ODC_or_Const_UNSAT",
    "TFI_CONST_UNSAT",
    "ODC_UNSAT_Not_TFI_Proved",
    "Mono_Total_s",
    "Partition_Total_s",
]


def parse_csv_ints(raw):
    values = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        values.append(int(part))
    return values


def resolve_path(path):
    path = Path(path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def default_circuits():
    return [resolve_path(path) for path in DEFAULT_CIRCUITS if resolve_path(path).exists()]


def collect_circuits(items):
    if not items:
        return default_circuits()
    circuits = []
    seen = set()
    for item in items:
        path = resolve_path(item)
        if path.is_file() and path.suffix.lower() in {".aag", ".aig"}:
            candidates = [path]
        elif path.is_dir():
            candidates = sorted(
                child
                for child in path.rglob("*")
                if child.is_file() and child.suffix.lower() in {".aag", ".aig"}
            )
        else:
            continue
        for candidate in candidates:
            key = candidate.resolve()
            if key in seen:
                continue
            seen.add(key)
            circuits.append(candidate)
    return circuits


def observable_roots(outputs, latches):
    roots = list(outputs)
    roots.extend(alg10._parse_latch(latch)[1] for latch in latches)
    return roots


def result_family(status):
    if status.startswith("UNSAT"):
        return "UNSAT"
    if status.startswith("SAT"):
        return "SAT"
    if status.startswith("TIMEOUT"):
        return "TIMEOUT"
    if status.startswith("ERROR"):
        return "ERROR"
    if status.startswith("SKIP"):
        return "SKIP"
    return status


def resolved_family(status):
    family = result_family(status)
    return family if family in {"SAT", "UNSAT"} else ""


def solve_exact_roots(inputs, latches, roots, gates_raw, target_idx, stuck_value, by_lhs, budget):
    if not roots:
        return ExactResult("UNSAT_NO_AFFECTED_ROOTS", roots=0, note="no observable affected root")

    cone = alg10._fanin_indices_for_roots(gates_raw, roots, by_lhs=by_lhs)
    if target_idx not in cone:
        return ExactResult("ERROR_TARGET_OUTSIDE_CONE", roots=len(roots), cone_gates=len(cone))

    t_encode = time.time()
    try:
        clauses, miter_lit, _shared = alg10._build_single_fault_cone_miter(
            inputs, latches, roots, gates_raw, target_idx, stuck_value, cone
        )
    except Exception as exc:
        return ExactResult(
            "ERROR_ENCODE",
            roots=len(roots),
            cone_gates=len(cone),
            note=str(exc)[:200],
        )
    encode_s = time.time() - t_encode

    t_sat = time.time()
    try:
        with Glucose4(bootstrap_with=clauses) as solver:
            if budget > 0:
                solver.conf_budget(budget)
                raw_result = solver.solve_limited(assumptions=[miter_lit])
            else:
                raw_result = solver.solve(assumptions=[miter_lit])
    except Exception as exc:
        return ExactResult(
            "ERROR_SOLVE",
            encode_s=encode_s,
            roots=len(roots),
            clauses=len(clauses),
            cone_gates=len(cone),
            note=str(exc)[:200],
        )
    sat_s = time.time() - t_sat

    if raw_result is None:
        status = "TIMEOUT"
    elif raw_result is False:
        status = "UNSAT"
    else:
        status = "SAT"
    return ExactResult(
        status,
        encode_s=encode_s,
        sat_s=sat_s,
        clauses=len(clauses),
        cone_gates=len(cone),
        roots=len(roots),
    )


def partition_roots(roots, partition_size):
    if partition_size <= 0:
        return [list(roots)]
    return [list(roots[pos : pos + partition_size]) for pos in range(0, len(roots), partition_size)]


def audit_partitions(affected_roots, partitions):
    if affected_roots and not partitions:
        raise AssertionError("affected roots are non-empty but partition list is empty")
    if any(not group for group in partitions):
        raise AssertionError("empty affected-root partition")
    flattened = [root for group in partitions for root in group]
    if Counter(flattened) != Counter(affected_roots):
        raise AssertionError("partition root multiset does not exactly match affected roots")


def solve_partitioned_roots(
    inputs,
    latches,
    affected_roots,
    gates_raw,
    target_idx,
    stuck_value,
    by_lhs,
    budget,
    partition_size,
):
    partitions = partition_roots(affected_roots, partition_size)
    try:
        audit_partitions(affected_roots, partitions)
    except AssertionError as exc:
        return PartitionResult("ERROR_PARTITION_AUDIT", note=str(exc))

    if not affected_roots:
        return PartitionResult("UNSAT_NO_AFFECTED_ROOTS", groups=0, note="no observable affected root")

    aggregate = PartitionResult("UNSAT", groups=len(partitions))
    saw_timeout = False

    for group_pos, roots in enumerate(partitions):
        result = solve_exact_roots(inputs, latches, roots, gates_raw, target_idx, stuck_value, by_lhs, budget)
        aggregate.encode_s += result.encode_s
        aggregate.sat_s += result.sat_s
        aggregate.clauses_total += result.clauses
        aggregate.cone_gates_total += result.cone_gates
        aggregate.cone_gates_max = max(aggregate.cone_gates_max, result.cone_gates)

        family = result_family(result.status)
        if family == "SAT":
            aggregate.sat_groups += 1
            aggregate.status = "SAT"
            aggregate.first_sat_group = group_pos
            return aggregate
        if family == "UNSAT":
            aggregate.unsat_groups += 1
            continue
        if family == "TIMEOUT":
            aggregate.timeout_groups += 1
            saw_timeout = True
            continue
        aggregate.error_groups += 1
        aggregate.status = result.status
        aggregate.note = result.note
        return aggregate

    if saw_timeout:
        aggregate.status = "TIMEOUT"
    return aggregate


def classify_exact_proof(partition_status, tfi_status):
    if result_family(partition_status) != "UNSAT":
        return ""
    if tfi_status == "UNSAT":
        return "TFI_CONST"
    if tfi_status:
        return "ODC_NOT_TFI_PROVED"
    return "ODC_OR_CONST_NOT_CLASSIFIED"


def compare_results(mono_status, partition_status, mono_total, partition_total):
    mono_family = resolved_family(mono_status)
    part_family = resolved_family(partition_status)
    if mono_family and part_family:
        if mono_family != part_family:
            return "NO", "RESOLVED_MISMATCH"
        if partition_total < mono_total:
            return "YES", "MATCH_PARTITION_FASTER"
        if mono_total < partition_total:
            return "YES", "MATCH_MONO_FASTER"
        return "YES", "MATCH_EQUAL_TIME"
    if result_family(mono_status) == "TIMEOUT" and part_family:
        return "YES", "MONO_TIMEOUT_PARTITION_RESOLVED"
    if mono_family and result_family(partition_status) == "TIMEOUT":
        return "YES", "PARTITION_TIMEOUT_MONO_RESOLVED"
    if result_family(mono_status) == "TIMEOUT" and result_family(partition_status) == "TIMEOUT":
        return "YES", "BOTH_TIMEOUT"
    if result_family(mono_status) == "ERROR" or result_family(partition_status) == "ERROR":
        return "NO", "ERROR"
    return "YES", "UNRESOLVED_OR_SKIPPED"


def speedup(mono_total, partition_total):
    if partition_total <= 0:
        return ""
    return f"{mono_total / partition_total:.3f}"


def tfi_classification(inputs, latches, gates_raw, idx, stuck_value, enabled):
    if not enabled:
        return ""
    status, _primary_values = alg10._tfi_constancy_check(inputs, latches, gates_raw, idx, stuck_value)
    return status


def update_summary(summary, row):
    key = (row["Circuit"], row["Partition_Size"])
    item = summary.setdefault(
        key,
        {
            "Circuit": row["Circuit"],
            "Partition_Size": row["Partition_Size"],
            "Rows": 0,
            "Resolved_Matches": 0,
            "Mismatches": 0,
            "Mono_Timeout_Partition_Resolved": 0,
            "Partition_Timeout_Mono_Resolved": 0,
            "Both_Timeout": 0,
            "Partition_Faster_Same_Result": 0,
            "Mono_Faster_Same_Result": 0,
            "Partition_UNSAT": 0,
            "Partition_SAT": 0,
            "Partition_TIMEOUT": 0,
            "Exact_ODC_or_Const_UNSAT": 0,
            "TFI_CONST_UNSAT": 0,
            "ODC_UNSAT_Not_TFI_Proved": 0,
            "Mono_Total_s": 0.0,
            "Partition_Total_s": 0.0,
        },
    )
    item["Rows"] += 1
    item["Mono_Total_s"] += float(row["Mono_Total_s"])
    item["Partition_Total_s"] += float(row["Partition_Total_s"])

    comparison = row["Comparison"]
    if row["Result_Match"] == "NO":
        item["Mismatches"] += 1
    elif comparison.startswith("MATCH"):
        item["Resolved_Matches"] += 1

    if comparison == "MONO_TIMEOUT_PARTITION_RESOLVED":
        item["Mono_Timeout_Partition_Resolved"] += 1
    elif comparison == "PARTITION_TIMEOUT_MONO_RESOLVED":
        item["Partition_Timeout_Mono_Resolved"] += 1
    elif comparison == "BOTH_TIMEOUT":
        item["Both_Timeout"] += 1
    elif comparison == "MATCH_PARTITION_FASTER":
        item["Partition_Faster_Same_Result"] += 1
    elif comparison == "MATCH_MONO_FASTER":
        item["Mono_Faster_Same_Result"] += 1

    part_family = result_family(row["Partition_Result"])
    if part_family == "UNSAT":
        item["Partition_UNSAT"] += 1
        item["Exact_ODC_or_Const_UNSAT"] += 1
    elif part_family == "SAT":
        item["Partition_SAT"] += 1
    elif part_family == "TIMEOUT":
        item["Partition_TIMEOUT"] += 1

    if row["Exact_Proof_Class"] == "TFI_CONST":
        item["TFI_CONST_UNSAT"] += 1
    elif row["Exact_Proof_Class"] in {"ODC_NOT_TFI_PROVED", "ODC_OR_CONST_NOT_CLASSIFIED"}:
        item["ODC_UNSAT_Not_TFI_Proved"] += 1


def row_for_result(
    circuit,
    gate_count,
    root_count,
    idx,
    stuck_value,
    affected_count,
    partition_size,
    mono,
    partition,
    tfi_status,
):
    match, comparison = compare_results(
        mono.status, partition.status, mono.total_s, partition.total_s
    )
    proof_class = classify_exact_proof(partition.status, tfi_status)
    note_parts = [part for part in [mono.note, partition.note] if part]
    return {
        "Circuit": circuit,
        "Gate_Count": gate_count,
        "Root_Count": root_count,
        "Candidate_Index": idx,
        "Stuck_Value": stuck_value,
        "Affected_Roots": affected_count,
        "Partition_Size": partition_size,
        "Partitions": partition.groups,
        "Mono_Result": mono.status,
        "Partition_Result": partition.status,
        "Result_Match": match,
        "Comparison": comparison,
        "TFI_Result": tfi_status,
        "Exact_Proof_Class": proof_class,
        "Mono_Encode_s": f"{mono.encode_s:.6f}",
        "Mono_SAT_s": f"{mono.sat_s:.6f}",
        "Mono_Total_s": f"{mono.total_s:.6f}",
        "Mono_Cone_Gates": mono.cone_gates,
        "Mono_Clauses": mono.clauses,
        "Partition_Encode_s": f"{partition.encode_s:.6f}",
        "Partition_SAT_s": f"{partition.sat_s:.6f}",
        "Partition_Total_s": f"{partition.total_s:.6f}",
        "Partition_Cone_Gates_Total": partition.cone_gates_total,
        "Partition_Cone_Gates_Max": partition.cone_gates_max,
        "Partition_Clauses_Total": partition.clauses_total,
        "Partition_SAT_Groups": partition.sat_groups,
        "Partition_UNSAT_Groups": partition.unsat_groups,
        "Partition_Timeout_Groups": partition.timeout_groups,
        "Partition_Error_Groups": partition.error_groups,
        "First_SAT_Group": partition.first_sat_group,
        "Speedup_Mono_Over_Partition": speedup(mono.total_s, partition.total_s),
        "Note": " | ".join(note_parts),
    }


def run_circuit(path, args, detail_writer, summary):
    M, I, L, O, A, inputs, latches, outputs, gates_raw, _symbols = parse_aag(str(path))
    del M, I, L, O

    roots = observable_roots(outputs, latches)
    by_lhs, fanout = alg10._fanout_graph(gates_raw)
    candidates = alg10._candidate_order(gates_raw, roots=roots)
    stuck_values = set(args.stuck_values)
    deadline = time.time() + args.seconds if args.seconds > 0 else None

    scanned = 0
    evaluated = 0
    mismatches = 0
    circuit_name = path.name
    print(
        f"  {circuit_name}: gates={A} roots={len(roots)} "
        f"budget={args.budget} partitions={','.join(map(str, args.partition_sizes))}"
    )

    for idx, stuck_value in candidates:
        if stuck_value not in stuck_values:
            continue
        if args.scan_limit > 0 and scanned >= args.scan_limit:
            break
        if deadline is not None and time.time() >= deadline:
            break
        scanned += 1

        affected = alg10._affected_roots_from_graph(by_lhs, fanout, roots, idx)
        if len(affected) < args.min_affected_roots:
            continue
        if args.max_affected_roots > 0 and len(affected) > args.max_affected_roots:
            continue

        mono = solve_exact_roots(
            inputs, latches, affected, gates_raw, idx, stuck_value, by_lhs, args.budget
        )
        tfi_status = tfi_classification(
            inputs, latches, gates_raw, idx, stuck_value, args.classify_tfi
        )

        for partition_size in args.partition_sizes:
            partition = solve_partitioned_roots(
                inputs,
                latches,
                affected,
                gates_raw,
                idx,
                stuck_value,
                by_lhs,
                args.budget,
                partition_size,
            )
            row = row_for_result(
                circuit_name,
                A,
                len(roots),
                idx,
                stuck_value,
                len(affected),
                partition_size,
                mono,
                partition,
                tfi_status,
            )
            detail_writer.writerow(row)
            update_summary(summary, row)
            if row["Result_Match"] == "NO":
                mismatches += 1

        evaluated += 1
        if args.max_candidates > 0 and evaluated >= args.max_candidates:
            break

    print(f"    scanned={scanned} evaluated={evaluated} mismatches={mismatches}")
    return scanned, evaluated, mismatches


def write_summary(summary_path, summary):
    with summary_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for key in sorted(summary):
            row = dict(summary[key])
            row["Mono_Total_s"] = f"{row['Mono_Total_s']:.6f}"
            row["Partition_Total_s"] = f"{row['Partition_Total_s']:.6f}"
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(
        description="Experiment with affected-root partitioned exact cone miters."
    )
    parser.add_argument("--circuits", nargs="*", default=None)
    parser.add_argument("--partition-sizes", default="1,2,4,8")
    parser.add_argument("--budget", type=int, default=5000)
    parser.add_argument("--seconds", type=float, default=30.0, help="Per-circuit wall time cap.")
    parser.add_argument("--scan-limit", type=int, default=5000)
    parser.add_argument("--max-candidates", type=int, default=200)
    parser.add_argument("--min-affected-roots", type=int, default=2)
    parser.add_argument("--max-affected-roots", type=int, default=0)
    parser.add_argument("--stuck-values", default="0,1")
    parser.add_argument("--classify-tfi", action="store_true")
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()

    args.partition_sizes = parse_csv_ints(args.partition_sizes)
    args.stuck_values = parse_csv_ints(args.stuck_values)
    if not args.partition_sizes:
        raise SystemExit("at least one partition size is required")
    if not args.stuck_values or any(value not in {0, 1} for value in args.stuck_values):
        raise SystemExit("--stuck-values must contain 0, 1, or both")

    circuits = collect_circuits(args.circuits)
    if not circuits:
        raise SystemExit("no circuits found")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_dir = Path(args.output_dir) if args.output_dir else (
        REPO_ROOT / "results_optimized" / "partitioned_miter_experiments" / timestamp
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    detail_path = output_dir / f"partitioned_miter_detail_{timestamp}.csv"
    summary_path = output_dir / f"partitioned_miter_summary_{timestamp}.csv"

    print("Partitioned exact miter experiment")
    print(f"  circuits={len(circuits)}")
    print(f"  output_dir={output_dir}")
    print(f"  detail={detail_path}")

    summary = {}
    total_scanned = 0
    total_evaluated = 0
    total_mismatches = 0
    started = time.time()

    with detail_path.open("w", newline="", encoding="utf-8") as f:
        detail_writer = csv.DictWriter(f, fieldnames=DETAIL_FIELDS)
        detail_writer.writeheader()
        for circuit in circuits:
            scanned, evaluated, mismatches = run_circuit(circuit, args, detail_writer, summary)
            total_scanned += scanned
            total_evaluated += evaluated
            total_mismatches += mismatches
            f.flush()

    write_summary(summary_path, summary)

    print("\nPartitioned miter experiment complete")
    print(f"  elapsed={time.time() - started:.2f}s")
    print(f"  scanned={total_scanned} evaluated={total_evaluated} mismatches={total_mismatches}")
    print(f"  summary={summary_path}")
    if total_mismatches:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
