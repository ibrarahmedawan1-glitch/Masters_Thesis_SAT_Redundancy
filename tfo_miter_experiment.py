#!/usr/bin/env python3
"""Read-only comparison of monolithic and exact TFO-slice fault miters."""

import argparse
import csv
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from pysat.solvers import Solver

import optimizer_alg10_tiered as alg10
from optimizer_alg8_hybrid import parse_aag
from partitioned_miter_experiment import (
    load_checkpoint_frontier,
    observable_roots,
    resolve_path,
)


REPO_ROOT = Path(__file__).resolve().parent
DETAIL_FIELDS = [
    "Circuit",
    "Candidate_Index",
    "Gate",
    "SA",
    "Affected_Roots",
    "Good_Cone_Gates",
    "Faulty_TFO_Gates",
    "Mono_Clauses",
    "TFO_Clauses",
    "Clause_Reduction%",
    "Mono_Result",
    "TFO_Result",
    "Resolved_Match",
    "Mono_Encode_s",
    "Mono_Solve_s",
    "TFO_Encode_s",
    "TFO_Solve_s",
]


def solve_clauses(clauses, miter_lit, solver_name, budget):
    started = time.perf_counter()
    with Solver(name=solver_name, bootstrap_with=clauses) as solver:
        if budget > 0:
            solver.conf_budget(budget)
            raw = solver.solve_limited(assumptions=[miter_lit])
        else:
            raw = solver.solve(assumptions=[miter_lit])
    elapsed = time.perf_counter() - started
    if raw is None:
        return "TIMEOUT", elapsed
    if raw is False:
        return "UNSAT", elapsed
    return "SAT", elapsed


def resolved(status):
    return status in {"SAT", "UNSAT"}


def main():
    parser = argparse.ArgumentParser(
        description="Compare exact monolithic cones with exact faulty-TFO slices."
    )
    parser.add_argument("--circuit", default="")
    parser.add_argument("--checkpoint-json", default="")
    parser.add_argument(
        "--checkpoint-frontier",
        choices=["all", "pending", "escalated"],
        default="all",
    )
    parser.add_argument(
        "--candidate-order",
        choices=[
            "current",
            "reverse",
            "proof_cost",
            "proof_cost_untried",
            "proof_reverse_portfolio",
        ],
        default="proof_reverse_portfolio",
    )
    parser.add_argument("--solver", default="cadical153")
    parser.add_argument("--budget", type=int, default=5000)
    parser.add_argument("--max-candidates", type=int, default=100)
    parser.add_argument("--seconds", type=float, default=120.0)
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()

    history = {}
    if args.checkpoint_json:
        circuit, candidates, history, tier = load_checkpoint_frontier(
            args.checkpoint_json,
            args.checkpoint_frontier,
        )
    else:
        if not args.circuit:
            raise SystemExit("--circuit or --checkpoint-json is required")
        circuit = resolve_path(args.circuit)
        candidates = None
        tier = ""

    parsed = parse_aag(str(circuit))
    _, _, _, _, gate_count, inputs, latches, outputs, gates_raw, _symbols = parsed
    roots = observable_roots(outputs, latches)
    if candidates is None:
        candidates = alg10._candidate_order(gates_raw, roots=roots)
    candidates = alg10._order_global_frontier(
        candidates,
        gates_raw,
        history,
        roots=roots,
        order=args.candidate_order,
    )
    if args.max_candidates > 0:
        candidates = candidates[: args.max_candidates]

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else REPO_ROOT / "results_optimized" / "tfo_miter_experiments" / timestamp
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    detail_path = output_dir / f"tfo_miter_detail_{timestamp}.csv"
    summary_path = output_dir / f"tfo_miter_summary_{timestamp}.csv"

    print("Exact TFO-slice miter experiment")
    print(
        f"  circuit={circuit} gates={gate_count} roots={len(roots)} "
        f"tier={tier or 'fresh'} candidates={len(candidates)}"
    )
    print(
        f"  solver={args.solver} budget={args.budget} "
        f"candidate_order={args.candidate_order}"
    )

    by_lhs, fanout = alg10._fanout_graph(gates_raw)
    counts = Counter()
    totals = Counter()
    started = time.perf_counter()

    with detail_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DETAIL_FIELDS)
        writer.writeheader()
        for pos, (idx, stuck_value) in enumerate(candidates, start=1):
            if args.seconds > 0 and time.perf_counter() - started >= args.seconds:
                break
            affected = alg10._affected_roots_from_graph(
                by_lhs,
                fanout,
                roots,
                idx,
            )
            if not affected:
                continue
            good_cone = alg10._fanin_indices_for_roots(
                gates_raw,
                affected,
                by_lhs=by_lhs,
            )
            tfo_slice = alg10._observable_tfo_slice(fanout, idx, good_cone)
            alg10._audit_tfo_slice(
                by_lhs,
                fanout,
                affected,
                idx,
                good_cone,
                tfo_slice,
                gates_raw,
            )

            encode_started = time.perf_counter()
            mono_clauses, mono_miter, _mono_shared = alg10._build_single_fault_cone_miter(
                inputs,
                latches,
                affected,
                gates_raw,
                idx,
                stuck_value,
                good_cone,
            )
            mono_encode = time.perf_counter() - encode_started

            encode_started = time.perf_counter()
            tfo_clauses, tfo_miter, _tfo_shared = alg10._build_single_fault_tfo_miter(
                inputs,
                latches,
                affected,
                gates_raw,
                idx,
                stuck_value,
                good_cone,
                tfo_slice,
            )
            tfo_encode = time.perf_counter() - encode_started

            mono_result, mono_solve = solve_clauses(
                mono_clauses,
                mono_miter,
                args.solver,
                args.budget,
            )
            tfo_result, tfo_solve = solve_clauses(
                tfo_clauses,
                tfo_miter,
                args.solver,
                args.budget,
            )
            match = int(
                not (resolved(mono_result) and resolved(tfo_result))
                or mono_result == tfo_result
            )
            if not match:
                raise AssertionError(
                    f"resolved miter mismatch for {(idx, stuck_value)}: "
                    f"mono={mono_result}, tfo={tfo_result}"
                )

            reduction = (
                100.0 * (len(mono_clauses) - len(tfo_clauses)) / len(mono_clauses)
                if mono_clauses
                else 0.0
            )
            writer.writerow(
                {
                    "Circuit": Path(circuit).name,
                    "Candidate_Index": pos,
                    "Gate": idx,
                    "SA": stuck_value,
                    "Affected_Roots": len(affected),
                    "Good_Cone_Gates": len(good_cone),
                    "Faulty_TFO_Gates": len(tfo_slice),
                    "Mono_Clauses": len(mono_clauses),
                    "TFO_Clauses": len(tfo_clauses),
                    "Clause_Reduction%": f"{reduction:.2f}",
                    "Mono_Result": mono_result,
                    "TFO_Result": tfo_result,
                    "Resolved_Match": match,
                    "Mono_Encode_s": f"{mono_encode:.6f}",
                    "Mono_Solve_s": f"{mono_solve:.6f}",
                    "TFO_Encode_s": f"{tfo_encode:.6f}",
                    "TFO_Solve_s": f"{tfo_solve:.6f}",
                }
            )
            counts[f"Mono_{mono_result}"] += 1
            counts[f"TFO_{tfo_result}"] += 1
            counts["Rows"] += 1
            totals["Mono_Clauses"] += len(mono_clauses)
            totals["TFO_Clauses"] += len(tfo_clauses)
            totals["Mono_Time"] += mono_encode + mono_solve
            totals["TFO_Time"] += tfo_encode + tfo_solve
            f.flush()

    summary = {
        "Circuit": Path(circuit).name,
        "Rows": counts["Rows"],
        "Mono_SAT": counts["Mono_SAT"],
        "Mono_UNSAT": counts["Mono_UNSAT"],
        "Mono_TIMEOUT": counts["Mono_TIMEOUT"],
        "TFO_SAT": counts["TFO_SAT"],
        "TFO_UNSAT": counts["TFO_UNSAT"],
        "TFO_TIMEOUT": counts["TFO_TIMEOUT"],
        "Mono_Clauses_Total": totals["Mono_Clauses"],
        "TFO_Clauses_Total": totals["TFO_Clauses"],
        "Mono_Total_s": f"{totals['Mono_Time']:.6f}",
        "TFO_Total_s": f"{totals['TFO_Time']:.6f}",
    }
    with summary_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary))
        writer.writeheader()
        writer.writerow(summary)

    print(
        f"  rows={counts['Rows']} mono_sat={counts['Mono_SAT']} "
        f"mono_unsat={counts['Mono_UNSAT']} mono_timeout={counts['Mono_TIMEOUT']}"
    )
    print(
        f"  tfo_sat={counts['TFO_SAT']} tfo_unsat={counts['TFO_UNSAT']} "
        f"tfo_timeout={counts['TFO_TIMEOUT']}"
    )
    print(
        f"  clauses={totals['Mono_Clauses']}->{totals['TFO_Clauses']} "
        f"time={totals['Mono_Time']:.2f}s->{totals['TFO_Time']:.2f}s"
    )
    print(f"  detail={detail_path}")
    print(f"  summary={summary_path}")


if __name__ == "__main__":
    main()
