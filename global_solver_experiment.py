#!/usr/bin/env python3
"""Compare SAT backends on an Algorithm 10 global frontier.

This is an experiment-only runner.  It builds the same configurable-fault global
miter used by Algorithm 10 and solves candidate assumptions, but it never commits
rewrites and never modifies checkpoints.
"""

import argparse
import csv
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from pysat.solvers import Solver

import optimizer_alg10_tiered as alg10
from optimizer_alg8_hybrid import _build_fault_sweep_cnf, parse_aag


REPO_ROOT = Path(__file__).resolve().parent

DETAIL_FIELDS = [
    "Circuit",
    "Solver",
    "Budget",
    "Candidate_Index",
    "Gate",
    "SA",
    "Result",
    "Solve_s",
    "Audit",
    "Note",
]

SUMMARY_FIELDS = [
    "Circuit",
    "Solver",
    "Budget",
    "Candidates_Tried",
    "SAT",
    "UNSAT",
    "TIMEOUT",
    "ERROR",
    "Audit_Fail",
    "Total_Solve_s",
    "Encode_s",
]


def resolve_path(path):
    path = Path(path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def parse_int_list(raw):
    values = []
    for part in str(raw).split(","):
        part = part.strip()
        if part:
            values.append(int(part))
    return values


def parse_str_list(raw):
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def observable_roots(outputs, latches):
    roots = list(outputs)
    roots.extend(alg10._parse_latch(latch)[1] for latch in latches)
    return roots


def load_checkpoint(path, frontier):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    phase = data.get("phase_resume") or {}
    raw_items = []
    if frontier in {"all", "pending"}:
        raw_items.extend(phase.get("pending", []))
    if frontier in {"all", "escalated"}:
        raw_items.extend(phase.get("escalated", []))
    if frontier in {"all", "candidates"}:
        raw_items.extend(phase.get("candidates", []))

    candidates = []
    seen = set()
    for item in raw_items:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        idx, stuck_value = item[0], item[1]
        if not isinstance(idx, int) or not isinstance(stuck_value, int):
            continue
        if stuck_value not in (0, 1):
            continue
        cand = (idx, stuck_value)
        if cand in seen:
            continue
        seen.add(cand)
        candidates.append(cand)
    return candidates, data.get("work_aag", "")


def collect_inputs(args):
    candidates = None
    circuit = args.circuit
    if args.checkpoint_json:
        candidates, work_aag = load_checkpoint(args.checkpoint_json, args.checkpoint_frontier)
        if not circuit and work_aag:
            circuit = work_aag
    if not circuit:
        raise SystemExit("--circuit or --checkpoint-json with work_aag is required")
    return resolve_path(circuit), candidates


def build_candidate_assumptions(gate_count, f0_lits, f1_lits, candidate, miter_lit):
    idx, stuck_value = candidate
    control_state = [-lit for lit in f0_lits] + [-lit for lit in f1_lits]
    pos, lit, opposite_pos, opposite_lit = alg10._control_position(
        gate_count, idx, stuck_value, f0_lits, f1_lits
    )
    assumptions = control_state.copy()
    assumptions[pos] = lit
    assumptions[opposite_pos] = -opposite_lit
    assumptions.append(miter_lit)
    alg10._audit_global_assumptions(
        assumptions,
        gate_count,
        f0_lits=f0_lits,
        f1_lits=f1_lits,
        candidate=candidate,
        accepted={},
        miter_lit=miter_lit,
    )
    return assumptions


def solve_candidate(solver, assumptions, budget):
    started = time.time()
    if budget > 0:
        solver.conf_budget(budget)
        raw = solver.solve_limited(assumptions=assumptions)
    else:
        raw = solver.solve(assumptions=assumptions)
    elapsed = time.time() - started
    if raw is None:
        return "TIMEOUT", elapsed
    if raw is False:
        return "UNSAT", elapsed
    return "SAT", elapsed


def run_solver(circuit_name, solver_name, budget, clauses, A, f0_lits, f1_lits, miter_lit, candidates, args, detail_writer):
    summary = Counter()
    summary["Circuit"] = circuit_name
    summary["Solver"] = solver_name
    summary["Budget"] = budget
    started = time.time()
    with Solver(name=solver_name, bootstrap_with=clauses) as solver:
        for pos, candidate in enumerate(candidates, start=1):
            if args.seconds > 0 and time.time() - started >= args.seconds:
                break
            idx, stuck_value = candidate
            audit = "PASS"
            note = ""
            try:
                assumptions = build_candidate_assumptions(
                    A, f0_lits, f1_lits, candidate, miter_lit
                )
                result, elapsed = solve_candidate(solver, assumptions, budget)
            except Exception as exc:
                result = "ERROR"
                elapsed = 0.0
                audit = "FAIL"
                note = str(exc)[:200]

            summary["Candidates_Tried"] += 1
            summary[result] += 1
            if audit != "PASS":
                summary["Audit_Fail"] += 1
            summary["Total_Solve_s"] += elapsed
            detail_writer.writerow(
                {
                    "Circuit": circuit_name,
                    "Solver": solver_name,
                    "Budget": budget,
                    "Candidate_Index": pos,
                    "Gate": idx,
                    "SA": stuck_value,
                    "Result": result,
                    "Solve_s": f"{elapsed:.6f}",
                    "Audit": audit,
                    "Note": note,
                }
            )
    return summary


def main():
    parser = argparse.ArgumentParser(description="Compare SAT solvers on Alg10 global assumptions.")
    parser.add_argument("--circuit", default="")
    parser.add_argument("--checkpoint-json", default="")
    parser.add_argument(
        "--checkpoint-frontier",
        choices=["all", "pending", "escalated", "candidates"],
        default="all",
    )
    parser.add_argument("--solvers", default="glucose4,cadical153,cadical195,maplechrono,maplecm")
    parser.add_argument("--budgets", default="1000,5000")
    parser.add_argument("--max-candidates", type=int, default=200)
    parser.add_argument("--seconds", type=float, default=120.0, help="Per solver/budget cap.")
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()

    circuit_path, candidates = collect_inputs(args)
    M, I, L, O, A, inputs, latches, outputs, gates_raw, _symbols = parse_aag(str(circuit_path))
    del M, I, L, O
    roots = observable_roots(outputs, latches)
    if candidates is None:
        candidates = alg10._candidate_order(gates_raw, roots=roots)
    candidates = [
        cand
        for cand in candidates
        if 0 <= cand[0] < len(gates_raw) and cand[1] in (0, 1)
    ]
    if args.max_candidates > 0:
        candidates = candidates[: args.max_candidates]

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_dir = Path(args.output_dir) if args.output_dir else (
        REPO_ROOT / "results_optimized" / "global_solver_experiments" / timestamp
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    detail_path = output_dir / f"global_solver_detail_{timestamp}.csv"
    summary_path = output_dir / f"global_solver_summary_{timestamp}.csv"

    print("Global solver experiment")
    print(f"  circuit={circuit_path}")
    print(f"  candidates={len(candidates)}")
    print(f"  output_dir={output_dir}")

    encode_started = time.time()
    clauses, miter_lit, f0_lits, f1_lits = _build_fault_sweep_cnf(
        inputs, latches, roots, gates_raw
    )
    encode_s = time.time() - encode_started
    print(f"  encoded clauses={len(clauses)} gates={A} roots={len(roots)} encode={encode_s:.2f}s")

    summaries = []
    solvers = parse_str_list(args.solvers)
    budgets = parse_int_list(args.budgets)
    with detail_path.open("w", newline="", encoding="utf-8") as f:
        detail_writer = csv.DictWriter(f, fieldnames=DETAIL_FIELDS)
        detail_writer.writeheader()
        for solver_name in solvers:
            for budget in budgets:
                print(f"  solver={solver_name} budget={budget}")
                summary = run_solver(
                    circuit_path.name,
                    solver_name,
                    budget,
                    clauses,
                    A,
                    f0_lits,
                    f1_lits,
                    miter_lit,
                    candidates,
                    args,
                    detail_writer,
                )
                summary["Encode_s"] = encode_s
                summaries.append(summary)
                print(
                    f"    tried={summary['Candidates_Tried']} sat={summary['SAT']} "
                    f"unsat={summary['UNSAT']} timeout={summary['TIMEOUT']} "
                    f"time={summary['Total_Solve_s']:.2f}s"
                )
                f.flush()

    with summary_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for summary in summaries:
            row = {field: summary.get(field, 0) for field in SUMMARY_FIELDS}
            row["Total_Solve_s"] = f"{summary.get('Total_Solve_s', 0.0):.6f}"
            row["Encode_s"] = f"{summary.get('Encode_s', 0.0):.6f}"
            writer.writerow(row)

    print(f"  detail={detail_path}")
    print(f"  summary={summary_path}")
    if any(summary.get("Audit_Fail", 0) for summary in summaries):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
