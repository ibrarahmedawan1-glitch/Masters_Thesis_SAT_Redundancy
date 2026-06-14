#!/usr/bin/env python3
"""Experiment-only global SAT scheduling strategies for Algorithm 10.

This runner keeps the production global configurable-fault miter and the
production full assumption vector.  It varies only SAT-side strategy:

* candidate ordering inside an existing global frontier;
* conflict/decision/propagation budget kind;
* solver reuse vs periodic rebuild;
* optional phase hints.

It never commits rewrites and never writes checkpoints.  Every candidate solve
uses the production global-assumption audit.
"""

import argparse
import csv
import json
import random
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
    "Order",
    "Budget_Kind",
    "Budget",
    "Reuse",
    "Phase_Mode",
    "Candidate_Index",
    "Gate",
    "SA",
    "Tried_Before",
    "Depth",
    "Fanout",
    "Result",
    "Solve_s",
    "Conflicts_Delta",
    "Decisions_Delta",
    "Propagations_Delta",
    "Restarts_Delta",
    "Audit",
    "Note",
]

SUMMARY_FIELDS = [
    "Circuit",
    "Solver",
    "Order",
    "Budget_Kind",
    "Budget",
    "Reuse",
    "Phase_Mode",
    "Candidates_Tried",
    "SAT",
    "UNSAT",
    "TIMEOUT",
    "ERROR",
    "Audit_Fail",
    "Total_Solve_s",
    "Encode_s",
    "Assumptions_Per_Query",
    "Clauses",
    "Avg_Conflicts",
    "Avg_Decisions",
    "Avg_Propagations",
    "First_SAT_Position",
    "First_UNSAT_Position",
]


def resolve_path(path):
    path = Path(path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def parse_list(raw):
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
    tried = {}
    seen = set()
    for item in raw_items:
        if not isinstance(item, (list, tuple)) or len(item) not in (2, 3):
            continue
        idx, stuck_value = item[0], item[1]
        tried_before = item[2] if len(item) == 3 else 0
        if not isinstance(idx, int) or not isinstance(stuck_value, int):
            continue
        if not isinstance(tried_before, int):
            tried_before = 0
        if stuck_value not in (0, 1):
            continue
        cand = (idx, stuck_value)
        if cand in seen:
            continue
        seen.add(cand)
        candidates.append(cand)
        tried[cand] = max(0, tried_before)
    return candidates, tried, data.get("work_aag", "")


def collect_inputs(args):
    candidates = None
    tried = {}
    circuit = args.circuit
    if args.checkpoint_json:
        candidates, tried, work_aag = load_checkpoint(
            args.checkpoint_json, args.checkpoint_frontier
        )
        if not circuit and work_aag:
            circuit = work_aag
    if not circuit:
        raise SystemExit("--circuit or --checkpoint-json with work_aag is required")
    return resolve_path(circuit), candidates, tried


def gate_features(gates_raw):
    defined_by_var = {lhs >> 1: idx for idx, (lhs, _, _) in enumerate(gates_raw)}
    fanout = [0 for _ in gates_raw]
    depth = [0 for _ in gates_raw]

    for idx, (_lhs, r0, r1) in enumerate(gates_raw):
        d0 = d1 = 0
        for lit, slot in ((r0, 0), (r1, 1)):
            parent = defined_by_var.get(lit >> 1)
            if parent is not None:
                fanout[parent] += 1
                if slot == 0:
                    d0 = depth[parent] + 1
                else:
                    d1 = depth[parent] + 1
        depth[idx] = max(d0, d1)
    return depth, fanout


def order_candidates(candidates, order, depth, fanout, tried, seed):
    items = list(candidates)
    if order == "current":
        return items
    if order == "random":
        rng = random.Random(seed + len(items))
        rng.shuffle(items)
        return items

    def key(cand):
        idx, stuck_value = cand
        tried_before = tried.get(cand, 0)
        if order == "tried_asc":
            return (tried_before, idx, stuck_value)
        if order == "tried_desc":
            return (-tried_before, idx, stuck_value)
        if order in {"forward", "topo"}:
            return (idx, stuck_value)
        if order in {"reverse", "reverse_topo"}:
            return (-idx, stuck_value)
        if order == "depth_desc":
            return (-depth[idx], idx, stuck_value)
        if order == "depth_asc":
            return (depth[idx], idx, stuck_value)
        if order == "fanout_desc":
            return (-fanout[idx], -depth[idx], idx, stuck_value)
        if order == "fanout_asc":
            return (fanout[idx], depth[idx], idx, stuck_value)
        if order == "stuck0_first":
            return (stuck_value, idx)
        if order == "stuck1_first":
            return (-stuck_value, idx)
        return (idx, stuck_value)

    return sorted(items, key=key)


def candidate_assumptions(gate_count, f0_lits, f1_lits, candidate, miter_lit):
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


def apply_budget(solver, kind, budget):
    if budget <= 0:
        return
    if kind == "conf":
        solver.conf_budget(budget)
    elif kind == "dec":
        solver.dec_budget(budget)
    elif kind == "prop":
        solver.prop_budget(budget)
    else:
        raise ValueError(f"unknown budget kind: {kind}")


def get_stats(solver):
    try:
        stats = solver.accum_stats() or {}
    except Exception:
        return {}
    return {str(k): int(v) for k, v in stats.items()}


def stats_delta(before, after, key):
    return int(after.get(key, 0)) - int(before.get(key, 0))


def apply_initial_phases(solver, phase_mode, f0_lits, f1_lits):
    if phase_mode in {"controls_false", "controls_false_model"}:
        solver.set_phases([-lit for lit in f0_lits])
        solver.set_phases([-lit for lit in f1_lits])


def apply_model_phases(solver, phase_mode, last_model, limit):
    if phase_mode not in {"model", "controls_false_model"} or not last_model:
        return
    if limit > 0:
        solver.set_phases(last_model[:limit])
    else:
        solver.set_phases(last_model)


def parse_reuse(raw):
    raw = str(raw).strip().lower()
    if raw == "incremental":
        return 0
    if raw == "fresh":
        return 1
    if raw.startswith("rebuild"):
        parts = raw.split(":", 1)
        if len(parts) == 2:
            return max(1, int(parts[1]))
    raise ValueError(f"unknown reuse mode: {raw}")


def solve_candidate(solver, assumptions, budget_kind, budget):
    before = get_stats(solver)
    started = time.time()
    if budget > 0:
        apply_budget(solver, budget_kind, budget)
        raw = solver.solve_limited(assumptions=assumptions)
    else:
        raw = solver.solve(assumptions=assumptions)
    elapsed = time.time() - started
    after = get_stats(solver)
    if raw is None:
        result = "TIMEOUT"
    elif raw is False:
        result = "UNSAT"
    else:
        result = "SAT"
    deltas = {
        "conflicts": stats_delta(before, after, "conflicts"),
        "decisions": stats_delta(before, after, "decisions"),
        "propagations": stats_delta(before, after, "propagations"),
        "restarts": stats_delta(before, after, "restarts"),
    }
    return result, elapsed, deltas


def run_config(
    circuit_name,
    solver_name,
    order,
    budget_kind,
    budget,
    reuse,
    phase_mode,
    clauses,
    gate_count,
    f0_lits,
    f1_lits,
    miter_lit,
    candidates,
    tried,
    depth,
    fanout,
    args,
    detail_writer,
):
    ordered = order_candidates(
        candidates, order, depth, fanout, tried, args.random_seed
    )
    if args.max_candidates > 0:
        ordered = ordered[: args.max_candidates]

    rebuild_interval = parse_reuse(reuse)
    summary = Counter()
    summary["Circuit"] = circuit_name
    summary["Solver"] = solver_name
    summary["Order"] = order
    summary["Budget_Kind"] = budget_kind
    summary["Budget"] = budget
    summary["Reuse"] = reuse
    summary["Phase_Mode"] = phase_mode
    summary["Assumptions_Per_Query"] = 2 * gate_count + 1
    summary["Clauses"] = len(clauses)

    solver = None
    last_model = None
    config_started = time.time()

    def new_solver():
        s = Solver(name=solver_name, bootstrap_with=clauses)
        apply_initial_phases(s, phase_mode, f0_lits, f1_lits)
        apply_model_phases(s, phase_mode, last_model, args.phase_model_limit)
        return s

    try:
        if rebuild_interval == 0:
            solver = new_solver()
        for pos, candidate in enumerate(ordered, start=1):
            if args.seconds > 0 and time.time() - config_started >= args.seconds:
                break
            idx, stuck_value = candidate
            audit = "PASS"
            note = ""
            result = "ERROR"
            elapsed = 0.0
            deltas = {"conflicts": 0, "decisions": 0, "propagations": 0, "restarts": 0}
            try:
                if rebuild_interval > 0 and (
                    solver is None or ((pos - 1) % rebuild_interval == 0)
                ):
                    if solver is not None:
                        solver.delete()
                    solver = new_solver()
                assumptions = candidate_assumptions(
                    gate_count, f0_lits, f1_lits, candidate, miter_lit
                )
                apply_model_phases(solver, phase_mode, last_model, args.phase_model_limit)
                result, elapsed, deltas = solve_candidate(
                    solver, assumptions, budget_kind, budget
                )
                if result == "SAT" and phase_mode in {"model", "controls_false_model"}:
                    last_model = solver.get_model()
            except Exception as exc:
                audit = "FAIL"
                note = str(exc)[:200]

            summary["Candidates_Tried"] += 1
            summary[result] += 1
            summary["Total_Solve_s"] += elapsed
            summary["Total_Conflicts"] += deltas["conflicts"]
            summary["Total_Decisions"] += deltas["decisions"]
            summary["Total_Propagations"] += deltas["propagations"]
            if result == "SAT" and not summary.get("First_SAT_Position"):
                summary["First_SAT_Position"] = pos
            if result == "UNSAT" and not summary.get("First_UNSAT_Position"):
                summary["First_UNSAT_Position"] = pos
            if audit != "PASS":
                summary["Audit_Fail"] += 1

            detail_writer.writerow(
                {
                    "Circuit": circuit_name,
                    "Solver": solver_name,
                    "Order": order,
                    "Budget_Kind": budget_kind,
                    "Budget": budget,
                    "Reuse": reuse,
                    "Phase_Mode": phase_mode,
                    "Candidate_Index": pos,
                    "Gate": idx,
                    "SA": stuck_value,
                    "Tried_Before": tried.get(candidate, 0),
                    "Depth": depth[idx],
                    "Fanout": fanout[idx],
                    "Result": result,
                    "Solve_s": f"{elapsed:.6f}",
                    "Conflicts_Delta": deltas["conflicts"],
                    "Decisions_Delta": deltas["decisions"],
                    "Propagations_Delta": deltas["propagations"],
                    "Restarts_Delta": deltas["restarts"],
                    "Audit": audit,
                    "Note": note,
                }
            )
    finally:
        if solver is not None:
            solver.delete()

    tried_count = summary.get("Candidates_Tried", 0)
    if tried_count:
        summary["Avg_Conflicts"] = summary.get("Total_Conflicts", 0) / tried_count
        summary["Avg_Decisions"] = summary.get("Total_Decisions", 0) / tried_count
        summary["Avg_Propagations"] = summary.get("Total_Propagations", 0) / tried_count
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Compare SAT-side global frontier strategies without rewrites."
    )
    parser.add_argument("--circuit", default="")
    parser.add_argument("--checkpoint-json", default="")
    parser.add_argument(
        "--checkpoint-frontier",
        choices=["all", "pending", "escalated", "candidates"],
        default="all",
    )
    parser.add_argument("--solver", default="cadical153")
    parser.add_argument("--orders", default="current,tried_asc,depth_desc,depth_asc,fanout_desc,reverse")
    parser.add_argument("--budget-kinds", default="conf")
    parser.add_argument("--budget", type=int, default=1000)
    parser.add_argument("--reuse-modes", default="incremental,rebuild:20,fresh")
    parser.add_argument("--phase-modes", default="none")
    parser.add_argument("--phase-model-limit", type=int, default=20000)
    parser.add_argument("--max-candidates", type=int, default=80)
    parser.add_argument("--seconds", type=float, default=120.0, help="Per configuration cap.")
    parser.add_argument("--random-seed", type=int, default=20260610)
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()

    circuit_path, candidates, tried = collect_inputs(args)
    M, I, L, O, A, inputs, latches, outputs, gates_raw, _symbols = parse_aag(str(circuit_path))
    del M, I, L, O
    roots = observable_roots(outputs, latches)
    if candidates is None:
        candidates = alg10._candidate_order(gates_raw, roots=roots)
        tried = {}
    candidates = [
        cand for cand in candidates if 0 <= cand[0] < len(gates_raw) and cand[1] in (0, 1)
    ]

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_dir = Path(args.output_dir) if args.output_dir else (
        REPO_ROOT / "results_optimized" / "global_sat_strategy_experiments" / timestamp
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    detail_path = output_dir / f"global_sat_strategy_detail_{timestamp}.csv"
    summary_path = output_dir / f"global_sat_strategy_summary_{timestamp}.csv"

    print("Global SAT strategy experiment")
    print(f"  circuit={circuit_path}")
    print(f"  frontier_candidates={len(candidates)}")
    print(f"  solver={args.solver} budget={args.budget} max_candidates={args.max_candidates}")
    print(f"  output_dir={output_dir}")

    encode_started = time.time()
    clauses, miter_lit, f0_lits, f1_lits = _build_fault_sweep_cnf(
        inputs, latches, roots, gates_raw
    )
    encode_s = time.time() - encode_started
    depth, fanout = gate_features(gates_raw)
    print(
        f"  encoded gates={A} roots={len(roots)} clauses={len(clauses)} "
        f"assumptions={2 * A + 1} encode={encode_s:.2f}s"
    )

    summaries = []
    with detail_path.open("w", newline="", encoding="utf-8") as f:
        detail_writer = csv.DictWriter(f, fieldnames=DETAIL_FIELDS)
        detail_writer.writeheader()
        for order in parse_list(args.orders):
            for budget_kind in parse_list(args.budget_kinds):
                for reuse in parse_list(args.reuse_modes):
                    for phase_mode in parse_list(args.phase_modes):
                        print(
                            f"  order={order} budget_kind={budget_kind} "
                            f"reuse={reuse} phase={phase_mode}"
                        )
                        summary = run_config(
                            circuit_path.name,
                            args.solver,
                            order,
                            budget_kind,
                            args.budget,
                            reuse,
                            phase_mode,
                            clauses,
                            A,
                            f0_lits,
                            f1_lits,
                            miter_lit,
                            candidates,
                            tried,
                            depth,
                            fanout,
                            args,
                            detail_writer,
                        )
                        summary["Encode_s"] = encode_s
                        summaries.append(summary)
                        print(
                            f"    tried={summary['Candidates_Tried']} "
                            f"sat={summary['SAT']} unsat={summary['UNSAT']} "
                            f"timeout={summary['TIMEOUT']} error={summary['ERROR']} "
                            f"time={summary['Total_Solve_s']:.2f}s"
                        )
                        f.flush()

    with summary_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for summary in summaries:
            row = {field: summary.get(field, 0) for field in SUMMARY_FIELDS}
            for key in ("Total_Solve_s", "Encode_s", "Avg_Conflicts", "Avg_Decisions", "Avg_Propagations"):
                row[key] = f"{float(summary.get(key, 0.0)):.6f}"
            writer.writerow(row)

    print(f"  detail={detail_path}")
    print(f"  summary={summary_path}")
    if any(summary.get("Audit_Fail", 0) for summary in summaries):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
