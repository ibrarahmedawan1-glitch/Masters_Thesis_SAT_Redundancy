#!/usr/bin/env python3
"""
SAT-side ablation runner for Algorithm 10.

This script intentionally tests experimental combinations outside the main
interactive pipeline. Every row still runs final ABC CEC through verifier.py.
The goal is to compare SAT proof efficiency, not to declare a new default.
"""

import argparse
import csv
import importlib
import os
import sys
from datetime import datetime

from aag_metrics import compute_aag_metrics
from verifier import verify_equivalence


DEFAULT_CIRCUITS = [
    "benchmarks/c432.aag",
    "benchmarks/c7552.aag",
    "benchmark_suites/epfl/epfl_random_control_router.aag",
    "benchmark_suites/epfl/epfl_arithmetic_sin.aag",
]

HARD_CIRCUITS = [
    "benchmark_suites/epfl/epfl_random_control_arbiter.aag",
    "benchmark_suites/epfl/epfl_arithmetic_sqrt.aag",
]

ENV_KEYS = [
    "ALG10_MODE",
    "ALG10_BUDGETS",
    "ALG10_MAX_CIRCUIT_SECONDS",
    "ALG10_MAX_PHASES",
    "ALG10_REBUILD_AFTER_COMMITS",
    "ALG10_PRE_STRASH",
    "ALG10_PRE_STRASH_MAX_GATES",
    "ALG10_COMMIT_UNITS",
    "ALG10_CHECKPOINT_DIR",
    "ALG10_RESET_CHECKPOINT",
    "ALG10_TFI_CONSTANCY",
    "ALG10_TFI_BUDGET",
    "ALG10_TFI_MAX_CONE_GATES",
    "ALG10_AUDIT_ASSUMPTIONS",
    "ALG10_CANDIDATE_ORDER",
    "ALG10_CANDIDATE_RANDOM_SEED",
    "ALG10_WINDOW_MITER",
    "ALG10_WINDOW_AUDIT",
    "ALG10_WINDOW_LEVELS",
    "ALG10_WINDOW_BUDGET",
    "ALG10_WINDOW_MAX_CONE_GATES",
    "ALG10_CONE_MITER",
    "ALG10_CONE_BUDGET",
    "ALG10_CONE_MAX_GATES",
    "ALG10_CEX_PRUNING",
    "ALG10_CEX_PRUNING_MAX_CANDIDATES",
    "ALG10_CEX_PRUNING_BATCH_SIZE",
    "ALG10_AUDIT_CEX_PRUNING",
    "ALG10_AUDIT_CEX_PRUNING_BUDGET",
    "ALG10_AUDIT_CEX_PRUNING_MAX",
]


VARIANTS = {
    "current": {
        "ALG10_TFI_CONSTANCY": "1",
        "ALG10_WINDOW_MITER": "0",
        "ALG10_CONE_MITER": "1",
        "ALG10_CANDIDATE_ORDER": "current",
        "ALG10_REBUILD_AFTER_COMMITS": "100",
        "ALG10_COMMIT_UNITS": "1",
    },
    "reverse": {
        "ALG10_TFI_CONSTANCY": "1",
        "ALG10_WINDOW_MITER": "0",
        "ALG10_CONE_MITER": "1",
        "ALG10_CANDIDATE_ORDER": "reverse_topo",
        "ALG10_REBUILD_AFTER_COMMITS": "100",
        "ALG10_COMMIT_UNITS": "1",
    },
    "cone_size": {
        "ALG10_TFI_CONSTANCY": "1",
        "ALG10_WINDOW_MITER": "0",
        "ALG10_CONE_MITER": "1",
        "ALG10_CANDIDATE_ORDER": "cone_size",
        "ALG10_REBUILD_AFTER_COMMITS": "100",
        "ALG10_COMMIT_UNITS": "1",
    },
    "window_reverse": {
        "ALG10_TFI_CONSTANCY": "1",
        "ALG10_WINDOW_MITER": "1",
        "ALG10_WINDOW_LEVELS": "5",
        "ALG10_CONE_MITER": "1",
        "ALG10_CANDIDATE_ORDER": "reverse_topo",
        "ALG10_REBUILD_AFTER_COMMITS": "100",
        "ALG10_COMMIT_UNITS": "1",
    },
    "window_current": {
        "ALG10_TFI_CONSTANCY": "1",
        "ALG10_WINDOW_MITER": "1",
        "ALG10_WINDOW_LEVELS": "5",
        "ALG10_CONE_MITER": "1",
        "ALG10_CANDIDATE_ORDER": "current",
        "ALG10_REBUILD_AFTER_COMMITS": "100",
        "ALG10_COMMIT_UNITS": "1",
    },
    "window_cone_size": {
        "ALG10_TFI_CONSTANCY": "1",
        "ALG10_WINDOW_MITER": "1",
        "ALG10_WINDOW_LEVELS": "5",
        "ALG10_CONE_MITER": "1",
        "ALG10_CANDIDATE_ORDER": "cone_size",
        "ALG10_REBUILD_AFTER_COMMITS": "100",
        "ALG10_COMMIT_UNITS": "1",
    },
    "rebuild25_reverse": {
        "ALG10_TFI_CONSTANCY": "1",
        "ALG10_WINDOW_MITER": "0",
        "ALG10_CONE_MITER": "1",
        "ALG10_CANDIDATE_ORDER": "reverse_topo",
        "ALG10_REBUILD_AFTER_COMMITS": "25",
        "ALG10_COMMIT_UNITS": "1",
    },
    "rebuild25_current": {
        "ALG10_TFI_CONSTANCY": "1",
        "ALG10_WINDOW_MITER": "0",
        "ALG10_CONE_MITER": "1",
        "ALG10_CANDIDATE_ORDER": "current",
        "ALG10_REBUILD_AFTER_COMMITS": "25",
        "ALG10_COMMIT_UNITS": "1",
    },
    "no_commit_units_reverse": {
        "ALG10_TFI_CONSTANCY": "1",
        "ALG10_WINDOW_MITER": "0",
        "ALG10_CONE_MITER": "1",
        "ALG10_CANDIDATE_ORDER": "reverse_topo",
        "ALG10_REBUILD_AFTER_COMMITS": "100",
        "ALG10_COMMIT_UNITS": "0",
    },
    "global_only_audit": {
        "ALG10_TFI_CONSTANCY": "0",
        "ALG10_WINDOW_MITER": "0",
        "ALG10_CONE_MITER": "0",
        "ALG10_CANDIDATE_ORDER": "reverse_topo",
        "ALG10_REBUILD_AFTER_COMMITS": "100",
        "ALG10_AUDIT_ASSUMPTIONS": "1",
        "ALG10_COMMIT_UNITS": "1",
    },
    "global_only_current": {
        "ALG10_TFI_CONSTANCY": "0",
        "ALG10_WINDOW_MITER": "0",
        "ALG10_CONE_MITER": "0",
        "ALG10_CANDIDATE_ORDER": "current",
        "ALG10_REBUILD_AFTER_COMMITS": "100",
        "ALG10_AUDIT_ASSUMPTIONS": "1",
        "ALG10_COMMIT_UNITS": "1",
    },
    "cex_current": {
        "ALG10_TFI_CONSTANCY": "1",
        "ALG10_WINDOW_MITER": "0",
        "ALG10_CONE_MITER": "1",
        "ALG10_CANDIDATE_ORDER": "current",
        "ALG10_REBUILD_AFTER_COMMITS": "100",
        "ALG10_COMMIT_UNITS": "1",
        "ALG10_CEX_PRUNING": "1",
    },
    "cex_window_current": {
        "ALG10_TFI_CONSTANCY": "1",
        "ALG10_WINDOW_MITER": "1",
        "ALG10_WINDOW_LEVELS": "5",
        "ALG10_CONE_MITER": "1",
        "ALG10_CANDIDATE_ORDER": "current",
        "ALG10_REBUILD_AFTER_COMMITS": "100",
        "ALG10_COMMIT_UNITS": "1",
        "ALG10_CEX_PRUNING": "1",
    },
    "cex_window_deep_current": {
        "ALG10_MODE": "deep_resume",
        "ALG10_TFI_CONSTANCY": "1",
        "ALG10_TFI_BUDGET": "2000",
        "ALG10_TFI_MAX_CONE_GATES": "10000",
        "ALG10_WINDOW_MITER": "1",
        "ALG10_WINDOW_AUDIT": "1",
        "ALG10_WINDOW_LEVELS": "5",
        "ALG10_WINDOW_BUDGET": "2000",
        "ALG10_WINDOW_MAX_CONE_GATES": "10000",
        "ALG10_CONE_MITER": "1",
        "ALG10_CONE_BUDGET": "5000",
        "ALG10_CONE_MAX_GATES": "20000",
        "ALG10_CANDIDATE_ORDER": "current",
        "ALG10_REBUILD_AFTER_COMMITS": "100",
        "ALG10_AUDIT_ASSUMPTIONS": "1",
        "ALG10_COMMIT_UNITS": "1",
        "ALG10_CEX_PRUNING": "1",
    },
    "cex_window_audit": {
        "ALG10_TFI_CONSTANCY": "1",
        "ALG10_WINDOW_MITER": "1",
        "ALG10_WINDOW_LEVELS": "5",
        "ALG10_CONE_MITER": "1",
        "ALG10_CANDIDATE_ORDER": "current",
        "ALG10_REBUILD_AFTER_COMMITS": "100",
        "ALG10_COMMIT_UNITS": "1",
        "ALG10_CEX_PRUNING": "1",
        "ALG10_AUDIT_CEX_PRUNING": "1",
        "ALG10_AUDIT_CEX_PRUNING_BUDGET": "100000",
    },
    "cex_window_audit_capped": {
        "ALG10_TFI_CONSTANCY": "1",
        "ALG10_WINDOW_MITER": "1",
        "ALG10_WINDOW_LEVELS": "5",
        "ALG10_CONE_MITER": "1",
        "ALG10_CANDIDATE_ORDER": "current",
        "ALG10_REBUILD_AFTER_COMMITS": "100",
        "ALG10_COMMIT_UNITS": "1",
        "ALG10_CEX_PRUNING": "1",
        "ALG10_AUDIT_CEX_PRUNING": "1",
        "ALG10_AUDIT_CEX_PRUNING_BUDGET": "20000",
        "ALG10_AUDIT_CEX_PRUNING_MAX": "5000",
    },
    "global_only_cex_current": {
        "ALG10_TFI_CONSTANCY": "0",
        "ALG10_WINDOW_MITER": "0",
        "ALG10_CONE_MITER": "0",
        "ALG10_CANDIDATE_ORDER": "current",
        "ALG10_REBUILD_AFTER_COMMITS": "100",
        "ALG10_AUDIT_ASSUMPTIONS": "1",
        "ALG10_COMMIT_UNITS": "1",
        "ALG10_CEX_PRUNING": "1",
    },
}


CSV_FIELDS = [
    "Timestamp",
    "Variant",
    "Circuit",
    "Verify",
    "Original_Gates",
    "Final_Gates",
    "Removed",
    "Area_Before_AND2",
    "Area_After_AND2",
    "Area_Saved_AND2",
    "Depth_Before",
    "Depth_After",
    "T_Parse",
    "T_Encode",
    "T_SAT",
    "T_CEC",
    "T_Total",
    "SAT_Candidates",
    "SAT_Checks",
    "SAT_Query_SAT",
    "SAT_Query_UNSAT",
    "SAT_Timeouts",
    "SAT_Abort_Reason",
    "SAT_Unresolved",
    "SAT_Max_Budget",
    "Rebuilds",
    "TFI_Checks",
    "TFI_Query_SAT",
    "TFI_Query_UNSAT",
    "TFI_Timeouts",
    "TFI_Skipped",
    "Window_Checks",
    "Window_Query_SAT",
    "Window_Query_UNSAT",
    "Window_Timeouts",
    "Window_Skipped",
    "Window_Audit_Fail",
    "Cone_Checks",
    "Cone_Query_SAT",
    "Cone_Query_UNSAT",
    "Cone_Timeouts",
    "Cone_Skipped",
    "Global_Checks",
    "Global_Query_SAT",
    "Global_Query_UNSAT",
    "Global_Timeouts",
    "CEX_Prune_Events",
    "CEX_Prune_Checked",
    "CEX_Pruned",
    "CEX_TFI_Prune_Events",
    "CEX_TFI_Prune_Checked",
    "CEX_TFI_Pruned",
    "CEX_Pruning_Enabled",
    "CEX_Audit_Enabled",
    "CEX_Audit_Checked",
    "CEX_Audit_SAT",
    "CEX_Audit_False_Prunes",
    "CEX_Audit_Timeouts",
    "CEX_Audit_Skipped",
    "CEX_Audit_Limit_Hit",
    "Candidate_Order",
    "Window_Enabled",
    "Cone_Enabled",
    "Checkpoint_Resume",
]


def safe_name(path):
    name = os.path.splitext(os.path.basename(path))[0]
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)


def selected_variants(names, include_global_only):
    if names:
        missing = [name for name in names if name not in VARIANTS]
        if missing:
            raise SystemExit(f"unknown variants: {', '.join(missing)}")
        return names

    names = [
        "current",
        "reverse",
        "cone_size",
        "window_reverse",
        "window_current",
        "window_cone_size",
        "rebuild25_reverse",
        "rebuild25_current",
        "no_commit_units_reverse",
    ]
    if include_global_only:
        names.append("global_only_audit")
    return names


def apply_env(variant_env, checkpoint_dir, seconds, budgets):
    for key in ENV_KEYS:
        os.environ.pop(key, None)

    os.environ["ALG10_MODE"] = "fast_save"
    os.environ["ALG10_CHECKPOINT_DIR"] = checkpoint_dir
    os.environ["ALG10_RESET_CHECKPOINT"] = "1"
    os.environ["ALG10_MAX_CIRCUIT_SECONDS"] = str(seconds)
    os.environ["ALG10_BUDGETS"] = budgets
    os.environ["ALG10_PRE_STRASH"] = "1"
    os.environ["ALG10_PRE_STRASH_MAX_GATES"] = "100000"
    os.environ["ALG10_MAX_PHASES"] = "100"
    os.environ["ALG10_TFI_BUDGET"] = "500"
    os.environ["ALG10_TFI_MAX_CONE_GATES"] = "10000"
    os.environ["ALG10_WINDOW_BUDGET"] = "500"
    os.environ["ALG10_WINDOW_AUDIT"] = "1"
    os.environ["ALG10_WINDOW_MAX_CONE_GATES"] = "10000"
    os.environ["ALG10_CONE_BUDGET"] = "1000"
    os.environ["ALG10_CONE_MAX_GATES"] = "20000"
    os.environ["ALG10_CEX_PRUNING_BATCH_SIZE"] = "512"
    os.environ.update(variant_env)


def load_optimizer():
    sys.modules.pop("optimizer_alg10_tiered", None)
    return importlib.import_module("optimizer_alg10_tiered")


def run_one(circuit, variant_name, variant_env, output_dir, seconds, budgets, timestamp):
    circuit_name = safe_name(circuit)
    variant_dir = os.path.join(output_dir, variant_name)
    checkpoint_dir = os.path.join(output_dir, "checkpoints", variant_name, circuit_name)
    os.makedirs(variant_dir, exist_ok=True)
    os.makedirs(checkpoint_dir, exist_ok=True)

    apply_env(variant_env, checkpoint_dir, seconds, budgets)
    optimizer = load_optimizer()

    out_path = os.path.join(variant_dir, f"{circuit_name}.aag")
    before = compute_aag_metrics(circuit)
    orig, _, final, removed, timings = optimizer.solve_circuit(circuit, out_path)
    verify, cec_time = verify_equivalence(circuit, out_path)
    after = compute_aag_metrics(out_path)

    row = {
        "Timestamp": timestamp,
        "Variant": variant_name,
        "Circuit": circuit,
        "Verify": verify,
        "Original_Gates": orig,
        "Final_Gates": final,
        "Removed": removed,
        "Area_Before_AND2": before["Area_AND2"],
        "Area_After_AND2": after["Area_AND2"],
        "Area_Saved_AND2": max(0, before["Area_AND2"] - after["Area_AND2"]),
        "Depth_Before": before["Depth"],
        "Depth_After": after["Depth"],
        "T_CEC": f"{cec_time:.4f}",
    }

    for key in CSV_FIELDS:
        if key in row:
            continue
        if key.startswith("T_"):
            timing_key = key[2:]
            row[key] = f"{timings.get(timing_key, 0.0):.4f}"
        else:
            row[key] = timings.get(key, "")

    return row


def print_row(row):
    def as_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    print(
        f"{row['Variant']:<23} {os.path.basename(row['Circuit']):<34} "
        f"{row['Original_Gates']:>6}->{row['Final_Gates']:<6} "
        f"rm={row['Removed']:<4} pass={row['Verify']:<4} "
        f"sat={as_float(row['T_SAT']):>7.2f}s total={as_float(row['T_Total']):>7.2f}s "
        f"chk={row['SAT_Checks']:<6} "
        f"tfi={row['TFI_Query_UNSAT']:<3} win={row['Window_Query_UNSAT']:<3} "
        f"waudit={row['Window_Audit_Fail']:<3} "
        f"cone={row['Cone_Query_UNSAT']:<3} glob={row['Global_Query_UNSAT']:<3} "
        f"cexpr={row['CEX_Pruned']:<5} tficex={row['CEX_TFI_Pruned']:<5} "
        f"aud={row['CEX_Audit_Checked']:<4}/{row['CEX_Audit_False_Prunes']:<3} "
        f"abort={row['SAT_Abort_Reason']}"
    )


def summarize(rows):
    print("\nSummary by circuit:")
    circuits = sorted({row["Circuit"] for row in rows})
    for circuit in circuits:
        subset = [row for row in rows if row["Circuit"] == circuit and row["Verify"] == "PASS"]
        if not subset:
            print(f"  {circuit}: no PASS rows")
            continue
        best_removed = max(subset, key=lambda row: (int(row["Removed"]), -float(row["T_Total"])))
        best_time = min(subset, key=lambda row: (float(row["T_Total"]), -int(row["Removed"])))
        best_eff = max(
            subset,
            key=lambda row: (
                int(row["Removed"]) / max(0.001, float(row["T_SAT"])),
                int(row["Removed"]),
            ),
        )
        print(f"  {circuit}")
        print(
            f"    max removal: {best_removed['Variant']} "
            f"rm={best_removed['Removed']} total={best_removed['T_Total']}s"
        )
        print(
            f"    fastest:     {best_time['Variant']} "
            f"rm={best_time['Removed']} total={best_time['T_Total']}s"
        )
        print(
            f"    best rm/sat: {best_eff['Variant']} "
            f"rm={best_eff['Removed']} sat={best_eff['T_SAT']}s"
        )


def main():
    parser = argparse.ArgumentParser(description="Run Algorithm 10 SAT-side ablations.")
    parser.add_argument("--circuits", nargs="*", default=None, help="Circuit .aag paths.")
    parser.add_argument("--variants", nargs="*", default=None, help="Variant names to run.")
    parser.add_argument("--seconds", type=float, default=20.0, help="Per-circuit time budget.")
    parser.add_argument("--budgets", default="100,1000,5000", help="SAT conflict budgets.")
    parser.add_argument("--include-hard", action="store_true", help="Also run larger EPFL circuits.")
    parser.add_argument("--include-global-only", action="store_true", help="Include monolithic global-only audit.")
    parser.add_argument("--output-dir", default=None, help="Output directory.")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_dir = args.output_dir or os.path.join("results_optimized", f"sat_ablation_{timestamp}")
    os.makedirs(output_dir, exist_ok=True)

    circuits = args.circuits or list(DEFAULT_CIRCUITS)
    if args.include_hard:
        circuits.extend(HARD_CIRCUITS)
    circuits = [path for path in circuits if os.path.exists(path)]
    variants = selected_variants(args.variants, args.include_global_only)

    if not circuits:
        raise SystemExit("no circuits found")

    csv_path = os.path.join(output_dir, f"sat_ablation_{timestamp}.csv")
    rows = []

    print(f"Output: {csv_path}")
    print(f"Per-circuit budget: {args.seconds}s; budgets={args.budgets}")
    print(f"Circuits: {len(circuits)}; variants: {', '.join(variants)}\n")

    with open(csv_path, "w", newline="", encoding="ascii") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for circuit in circuits:
            for variant in variants:
                try:
                    row = run_one(
                        circuit,
                        variant,
                        VARIANTS[variant],
                        output_dir,
                        args.seconds,
                        args.budgets,
                        timestamp,
                    )
                except Exception as exc:
                    row = {key: "" for key in CSV_FIELDS}
                    row.update(
                        {
                            "Timestamp": timestamp,
                            "Variant": variant,
                            "Circuit": circuit,
                            "Verify": f"ERROR: {exc}",
                        }
                    )
                rows.append(row)
                writer.writerow(row)
                f.flush()
                print_row(row)
                sys.stdout.flush()

    summarize(rows)
    print(f"\nSaved: {csv_path}")


if __name__ == "__main__":
    main()
