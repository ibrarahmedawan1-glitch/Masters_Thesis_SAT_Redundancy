#!/usr/bin/env python3
"""Experiment with a lean single-fault global miter assumption layout.

Algorithm 10's production global tier disables every inactive f0/f1 fault
control by assumption for each candidate.  On large circuits this can mean
hundreds of thousands of assumptions per solve.  This runner keeps the same
good-vs-faulty configurable-fault miter, but adds an at-most-one constraint over
all fault controls to the CNF.  A single-candidate query can then assume only:

    candidate_fault_control AND output_miter

This is experiment-only and does not commit rewrites or modify checkpoints.
It is sound only for a zero-accepted-controls single-fault query context.  A
production integration would need to rebuild after accepted global commits, or
use a different encoding for the accepted-control context.
"""

import argparse
import csv
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from pysat.card import CardEnc, EncType
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
    "Full_Result",
    "Full_s",
    "Full_Assumptions",
    "Lean_Result",
    "Lean_s",
    "Lean_Assumptions",
    "Match",
    "Audit",
    "Note",
]

SUMMARY_FIELDS = [
    "Circuit",
    "Solver",
    "Budget",
    "Candidates_Tried",
    "Lean_SAT",
    "Lean_UNSAT",
    "Lean_TIMEOUT",
    "Lean_ERROR",
    "Full_SAT",
    "Full_UNSAT",
    "Full_TIMEOUT",
    "Full_ERROR",
    "Mismatches",
    "Audit_Fail",
    "Total_Lean_s",
    "Total_Full_s",
    "Base_Clauses",
    "AMO_Clauses",
    "Encode_s",
    "AMO_Encode_s",
]


CARD_ENCODINGS = {
    "seqcounter": EncType.seqcounter,
    "sortnetwrk": EncType.sortnetwrk,
    "cardnetwrk": EncType.cardnetwrk,
    "ladder": EncType.ladder,
    "totalizer": EncType.totalizer,
}


def resolve_path(path):
    path = Path(path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


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


def max_var_id(clauses, *lit_groups):
    max_var = 0
    for clause in clauses:
        for lit in clause:
            var = abs(lit)
            if var > max_var:
                max_var = var
    for group in lit_groups:
        for lit in group:
            var = abs(lit)
            if var > max_var:
                max_var = var
    return max_var


def add_single_fault_amo(clauses, f0_lits, f1_lits, encoding="seqcounter"):
    """Return clauses plus AMO(f0_0..f0_n, f1_0..f1_n).

    The original builder already adds per-gate mutexes.  This global AMO is
    stronger: at most one fault control in the whole faulty copy may be true.
    With one candidate control assumed true, every inactive control is forced
    false by propagation/CNF instead of by a huge assumption vector.
    """
    if encoding not in CARD_ENCODINGS:
        raise ValueError(f"unknown cardinality encoding: {encoding}")
    controls = list(f0_lits) + list(f1_lits)
    top_id = max_var_id(clauses, controls)
    amo = CardEnc.atmost(
        lits=controls,
        bound=1,
        top_id=top_id,
        encoding=CARD_ENCODINGS[encoding],
    )
    return list(clauses) + list(amo.clauses), len(amo.clauses), amo.nv


def full_candidate_assumptions(gate_count, f0_lits, f1_lits, candidate, miter_lit):
    idx, stuck_value = candidate
    if not (0 <= idx < gate_count) or stuck_value not in (0, 1):
        raise AssertionError(f"invalid candidate: {candidate}")
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


def lean_candidate_assumptions(gate_count, f0_lits, f1_lits, candidate, miter_lit):
    idx, stuck_value = candidate
    if not (0 <= idx < gate_count) or stuck_value not in (0, 1):
        raise AssertionError(f"invalid candidate: {candidate}")
    _pos, lit, _opposite_pos, _opposite_lit = alg10._control_position(
        gate_count, idx, stuck_value, f0_lits, f1_lits
    )
    assumptions = [lit, miter_lit]
    audit_lean_assumptions(
        assumptions,
        gate_count,
        f0_lits=f0_lits,
        f1_lits=f1_lits,
        candidate=candidate,
        miter_lit=miter_lit,
    )
    return assumptions


def audit_lean_assumptions(assumptions, gate_count, f0_lits, f1_lits, candidate, miter_lit):
    if len(f0_lits) != gate_count or len(f1_lits) != gate_count:
        raise AssertionError("fault-control literal count does not match gate count")
    if len(assumptions) != 2:
        raise AssertionError(f"lean assumption count {len(assumptions)} != 2")
    if assumptions[1] != miter_lit:
        raise AssertionError("lean assumptions must end with the miter literal")
    if assumptions[0] == miter_lit or assumptions[0] == -miter_lit:
        raise AssertionError("candidate literal overlaps the miter literal")
    if assumptions[0] == -assumptions[1]:
        raise AssertionError("contradictory lean assumptions")

    idx, stuck_value = candidate
    if not (0 <= idx < gate_count) or stuck_value not in (0, 1):
        raise AssertionError(f"invalid candidate: {candidate}")
    expected = f0_lits[idx] if stuck_value == 0 else f1_lits[idx]
    if assumptions[0] != expected:
        raise AssertionError(
            f"lean candidate literal mismatch: got {assumptions[0]}, expected {expected}"
        )


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


def run_experiment(
    circuit_name,
    solver_name,
    budget,
    full_clauses,
    lean_clauses,
    gate_count,
    f0_lits,
    f1_lits,
    miter_lit,
    candidates,
    args,
    detail_writer,
):
    summary = Counter()
    summary["Circuit"] = circuit_name
    summary["Solver"] = solver_name
    summary["Budget"] = budget
    started = time.time()

    full_solver = None
    try:
        if args.compare_full:
            full_solver = Solver(name=solver_name, bootstrap_with=full_clauses)
        with Solver(name=solver_name, bootstrap_with=lean_clauses) as lean_solver:
            for pos, candidate in enumerate(candidates, start=1):
                if args.seconds > 0 and time.time() - started >= args.seconds:
                    break
                idx, stuck_value = candidate
                audit = "PASS"
                note = ""
                full_result = ""
                full_elapsed = 0.0
                full_len = 0
                lean_result = "ERROR"
                lean_elapsed = 0.0
                lean_len = 0
                match = ""
                try:
                    if args.compare_full:
                        full_assumptions = full_candidate_assumptions(
                            gate_count, f0_lits, f1_lits, candidate, miter_lit
                        )
                        full_len = len(full_assumptions)
                        full_result, full_elapsed = solve_candidate(
                            full_solver, full_assumptions, budget
                        )
                    lean_assumptions = lean_candidate_assumptions(
                        gate_count, f0_lits, f1_lits, candidate, miter_lit
                    )
                    lean_len = len(lean_assumptions)
                    lean_result, lean_elapsed = solve_candidate(
                        lean_solver, lean_assumptions, budget
                    )
                    if args.compare_full:
                        match = "1" if full_result == lean_result else "0"
                except Exception as exc:
                    audit = "FAIL"
                    note = str(exc)[:200]
                    if lean_result == "ERROR":
                        lean_elapsed = 0.0

                summary["Candidates_Tried"] += 1
                summary[f"Lean_{lean_result}"] += 1
                summary["Total_Lean_s"] += lean_elapsed
                if args.compare_full:
                    summary[f"Full_{full_result}"] += 1
                    summary["Total_Full_s"] += full_elapsed
                    if match == "0":
                        summary["Mismatches"] += 1
                if audit != "PASS":
                    summary["Audit_Fail"] += 1

                detail_writer.writerow(
                    {
                        "Circuit": circuit_name,
                        "Solver": solver_name,
                        "Budget": budget,
                        "Candidate_Index": pos,
                        "Gate": idx,
                        "SA": stuck_value,
                        "Full_Result": full_result,
                        "Full_s": f"{full_elapsed:.6f}",
                        "Full_Assumptions": full_len,
                        "Lean_Result": lean_result,
                        "Lean_s": f"{lean_elapsed:.6f}",
                        "Lean_Assumptions": lean_len,
                        "Match": match,
                        "Audit": audit,
                        "Note": note,
                    }
                )
    finally:
        if full_solver is not None:
            full_solver.delete()

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Compare full-assumption vs AMO lean global miter queries."
    )
    parser.add_argument("--circuit", default="")
    parser.add_argument("--checkpoint-json", default="")
    parser.add_argument(
        "--checkpoint-frontier",
        choices=["all", "pending", "escalated", "candidates"],
        default="all",
    )
    parser.add_argument("--solver", default="cadical153")
    parser.add_argument("--budget", type=int, default=1000)
    parser.add_argument("--max-candidates", type=int, default=200)
    parser.add_argument("--seconds", type=float, default=120.0, help="Per run cap.")
    parser.add_argument("--card-encoding", choices=sorted(CARD_ENCODINGS), default="seqcounter")
    parser.add_argument("--compare-full", action="store_true")
    parser.add_argument(
        "--fail-on-mismatch",
        action="store_true",
        help="Treat full-vs-lean result differences as errors. Use only with non-budgeted checks.",
    )
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
        REPO_ROOT / "results_optimized" / "lean_global_miter_experiments" / timestamp
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    detail_path = output_dir / f"lean_global_miter_detail_{timestamp}.csv"
    summary_path = output_dir / f"lean_global_miter_summary_{timestamp}.csv"

    print("Lean global miter experiment")
    print(f"  circuit={circuit_path}")
    print(f"  candidates={len(candidates)}")
    print(f"  solver={args.solver} budget={args.budget} compare_full={int(args.compare_full)}")
    print(f"  output_dir={output_dir}")

    encode_started = time.time()
    clauses, miter_lit, f0_lits, f1_lits = _build_fault_sweep_cnf(
        inputs, latches, roots, gates_raw
    )
    encode_s = time.time() - encode_started

    amo_started = time.time()
    lean_clauses, amo_clause_count, _top_id = add_single_fault_amo(
        clauses, f0_lits, f1_lits, encoding=args.card_encoding
    )
    amo_encode_s = time.time() - amo_started
    print(
        f"  encoded gates={A} roots={len(roots)} base_clauses={len(clauses)} "
        f"amo_clauses={amo_clause_count} encode={encode_s:.2f}s amo={amo_encode_s:.2f}s"
    )
    print(f"  assumptions: full={2 * A + 1} lean=2")

    with detail_path.open("w", newline="", encoding="utf-8") as f:
        detail_writer = csv.DictWriter(f, fieldnames=DETAIL_FIELDS)
        detail_writer.writeheader()
        summary = run_experiment(
            circuit_path.name,
            args.solver,
            args.budget,
            clauses,
            lean_clauses,
            A,
            f0_lits,
            f1_lits,
            miter_lit,
            candidates,
            args,
            detail_writer,
        )

    summary["Base_Clauses"] = len(clauses)
    summary["AMO_Clauses"] = amo_clause_count
    summary["Encode_s"] = encode_s
    summary["AMO_Encode_s"] = amo_encode_s

    with summary_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        row = {field: summary.get(field, 0) for field in SUMMARY_FIELDS}
        row["Total_Lean_s"] = f"{summary.get('Total_Lean_s', 0.0):.6f}"
        row["Total_Full_s"] = f"{summary.get('Total_Full_s', 0.0):.6f}"
        row["Encode_s"] = f"{summary.get('Encode_s', 0.0):.6f}"
        row["AMO_Encode_s"] = f"{summary.get('AMO_Encode_s', 0.0):.6f}"
        writer.writerow(row)

    print(
        f"  tried={summary['Candidates_Tried']} "
        f"lean_sat={summary['Lean_SAT']} lean_unsat={summary['Lean_UNSAT']} "
        f"lean_timeout={summary['Lean_TIMEOUT']} lean_time={summary['Total_Lean_s']:.2f}s"
    )
    if args.compare_full:
        print(
            f"  full_sat={summary['Full_SAT']} full_unsat={summary['Full_UNSAT']} "
            f"full_timeout={summary['Full_TIMEOUT']} full_time={summary['Total_Full_s']:.2f}s "
            f"mismatches={summary['Mismatches']}"
        )
    print(f"  detail={detail_path}")
    print(f"  summary={summary_path}")
    if summary.get("Audit_Fail", 0) or (
        args.fail_on_mismatch and summary.get("Mismatches", 0)
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
