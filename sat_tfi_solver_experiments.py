#!/usr/bin/env python3
"""Compare Alg10 TFI constancy encodings and SAT solver backends.

This is an experiment harness, not an optimizer. It checks the SAT-side
recommendation that TFI constancy can be tested with one phase-local
good-circuit solver instead of rebuilding a local TFI cone solver for every
candidate.

Acceptance semantics are unchanged: a stuck-at replacement is only suggested
when the opposite target value is UNSAT.
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime

from pysat.solvers import Solver

from optimizer_alg10_tiered import _candidate_order, _parse_latch
from optimizer_alg8_hybrid import parse_aag, pure_python_forward_strash


DEFAULT_SOLVERS = [
    "glucose4",
    "cadical195",
    "cadical153",
    "maplechrono",
    "maplecm",
    "minisat22",
]


def _load_circuit(path, pre_strash=True):
    M, I, L, O, A, inputs, latches, outputs, gates_raw, symbols = parse_aag(path)
    if not pre_strash:
        return M, I, L, O, A, inputs, latches, outputs, gates_raw, symbols

    result = pure_python_forward_strash(M, I, L, O, A, inputs, latches, outputs, gates_raw)
    M_f, I_f, L_f, O_f, A_f, in_f, la_f, out_f, gates_f = result
    return M_f, I_f, L_f, O_f, A_f, in_f, la_f, out_f, gates_f, symbols


def _primary_bases(inputs, latches):
    bases = {lit & ~1 for lit in inputs}
    bases.update(_parse_latch(latch)[0] & ~1 for latch in latches)
    return bases


def _fanin_cone_indices(gates_raw, target_idx):
    by_lhs = {lhs & ~1: idx for idx, (lhs, _, _) in enumerate(gates_raw)}
    cone = set()
    stack = [gates_raw[target_idx][0] & ~1]

    while stack:
        lhs = stack.pop()
        idx = by_lhs.get(lhs)
        if idx is None or idx in cone:
            continue
        cone.add(idx)
        _, r0, r1 = gates_raw[idx]
        if r0 > 1:
            stack.append(r0 & ~1)
        if r1 > 1:
            stack.append(r1 & ~1)

    return cone


def _add_and_clauses(clauses, out, a, b):
    """Append clauses for out = a AND b. Constants are represented by None/True/False."""
    if a is False or b is False:
        clauses.append([-out])
    elif a is True and b is True:
        clauses.append([out])
    elif a is True:
        clauses.append([-b, out])
        clauses.append([b, -out])
    elif b is True:
        clauses.append([-a, out])
        clauses.append([a, -out])
    else:
        clauses.append([-a, -b, out])
        clauses.append([a, -out])
        clauses.append([b, -out])


def _build_good_circuit_cnf(inputs, latches, gates_raw, cone=None):
    """Build good-circuit Tseitin CNF and return (clauses, var_for_base)."""
    var_for_base = {}
    next_var = 1

    def sat_var(base):
        nonlocal next_var
        if base not in var_for_base:
            var_for_base[base] = next_var
            next_var += 1
        return var_for_base[base]

    def lit_to_sat(aig_lit):
        if aig_lit == 0:
            return False
        if aig_lit == 1:
            return True
        var = sat_var(aig_lit & ~1)
        return -var if (aig_lit & 1) else var

    for base in _primary_bases(inputs, latches):
        sat_var(base)

    indices = range(len(gates_raw)) if cone is None else sorted(cone)
    clauses = []
    for idx in indices:
        lhs, r0, r1 = gates_raw[idx]
        out = sat_var(lhs & ~1)
        _add_and_clauses(clauses, out, lit_to_sat(r0), lit_to_sat(r1))

    return clauses, var_for_base


def _target_assumption(gates_raw, var_for_base, candidate):
    idx, stuck_value = candidate
    target = gates_raw[idx][0] & ~1
    lit = var_for_base[target]
    return lit if stuck_value == 0 else -lit


def _solve_limited(solver, assumption, budget):
    if budget > 0:
        solver.conf_budget(budget)
        return solver.solve_limited(assumptions=[assumption])
    return solver.solve(assumptions=[assumption])


def _status_name(result):
    if result is True:
        return "SAT"
    if result is False:
        return "UNSAT"
    return "TIMEOUT"


def _select_candidates(candidates, limit, strategy, seed):
    if limit <= 0 or limit >= len(candidates):
        return list(candidates)
    if strategy == "first":
        return list(candidates[:limit])
    if strategy == "spread":
        if limit == 1:
            return [candidates[0]]
        chosen = []
        n = len(candidates)
        for pos in range(limit):
            idx = round(pos * (n - 1) / (limit - 1))
            chosen.append(candidates[idx])
        return chosen
    if strategy == "random":
        import random

        rng = random.Random(seed + len(candidates))
        sample = list(candidates)
        rng.shuffle(sample)
        return sample[:limit]
    raise ValueError(f"unknown candidate strategy: {strategy}")


def _run_full_persistent_solver(solver_name, inputs, latches, gates_raw, candidates, budget, deadline):
    t_build = time.time()
    clauses, var_for_base = _build_good_circuit_cnf(inputs, latches, gates_raw)
    build_s = time.time() - t_build

    statuses = {}
    checks = sat = unsat = timeouts = errors = 0
    solve_s = 0.0
    stats_before = {}
    stats_after = {}
    error_text = ""

    try:
        with Solver(name=solver_name, bootstrap_with=clauses) as solver:
            try:
                stats_before = solver.accum_stats() or {}
            except Exception:
                stats_before = {}
            for cand in candidates:
                if deadline is not None and time.time() >= deadline:
                    break
                assumption = _target_assumption(gates_raw, var_for_base, cand)
                t_solve = time.time()
                try:
                    result = _solve_limited(solver, assumption, budget)
                except NotImplementedError as exc:
                    error_text = str(exc)
                    errors += 1
                    break
                solve_s += time.time() - t_solve
                status = _status_name(result)
                statuses[cand] = status
                checks += 1
                if status == "SAT":
                    sat += 1
                elif status == "UNSAT":
                    unsat += 1
                else:
                    timeouts += 1
            try:
                stats_after = solver.accum_stats() or {}
            except Exception:
                stats_after = {}
    except Exception as exc:
        errors += 1
        error_text = str(exc)

    return {
        "mode": "full_persistent",
        "solver": solver_name,
        "clauses": len(clauses),
        "build_s": build_s,
        "solve_s": solve_s,
        "checks": checks,
        "sat": sat,
        "unsat": unsat,
        "timeouts": timeouts,
        "errors": errors,
        "error": error_text,
        "statuses": statuses,
        "conflicts": int(stats_after.get("conflicts", 0) - stats_before.get("conflicts", 0)),
        "decisions": int(stats_after.get("decisions", 0) - stats_before.get("decisions", 0)),
        "propagations": int(stats_after.get("propagations", 0) - stats_before.get("propagations", 0)),
    }


def _run_local_per_candidate_solver(solver_name, inputs, latches, gates_raw, candidates, budget, deadline):
    statuses = {}
    checks = sat = unsat = timeouts = errors = 0
    build_s = solve_s = 0.0
    clause_total = 0
    error_text = ""
    conflicts = decisions = propagations = 0

    for cand in candidates:
        if deadline is not None and time.time() >= deadline:
            break
        idx, _ = cand
        t_build = time.time()
        cone = _fanin_cone_indices(gates_raw, idx)
        clauses, var_for_base = _build_good_circuit_cnf(inputs, latches, gates_raw, cone=cone)
        build_s += time.time() - t_build
        clause_total += len(clauses)
        assumption = _target_assumption(gates_raw, var_for_base, cand)

        try:
            with Solver(name=solver_name, bootstrap_with=clauses) as solver:
                t_solve = time.time()
                try:
                    result = _solve_limited(solver, assumption, budget)
                except NotImplementedError as exc:
                    error_text = str(exc)
                    errors += 1
                    break
                solve_s += time.time() - t_solve
                try:
                    stats = solver.accum_stats() or {}
                    conflicts += int(stats.get("conflicts", 0))
                    decisions += int(stats.get("decisions", 0))
                    propagations += int(stats.get("propagations", 0))
                except Exception:
                    pass
        except Exception as exc:
            error_text = str(exc)
            errors += 1
            break

        status = _status_name(result)
        statuses[cand] = status
        checks += 1
        if status == "SAT":
            sat += 1
        elif status == "UNSAT":
            unsat += 1
        else:
            timeouts += 1

    avg_clauses = int(clause_total / checks) if checks else 0
    return {
        "mode": "local_per_candidate",
        "solver": solver_name,
        "clauses": avg_clauses,
        "build_s": build_s,
        "solve_s": solve_s,
        "checks": checks,
        "sat": sat,
        "unsat": unsat,
        "timeouts": timeouts,
        "errors": errors,
        "error": error_text,
        "statuses": statuses,
        "conflicts": conflicts,
        "decisions": decisions,
        "propagations": propagations,
    }


def _decisive_mismatches(statuses, reference):
    mismatches = 0
    compared = 0
    for cand, status in statuses.items():
        ref = reference.get(cand)
        if status in {"SAT", "UNSAT"} and ref in {"SAT", "UNSAT"}:
            compared += 1
            if status != ref:
                mismatches += 1
    return compared, mismatches


def _row_for_result(path, gates, candidates_total, selected, budget, result, reference=None):
    compared = mismatches = ""
    if reference is not None:
        compared, mismatches = _decisive_mismatches(result["statuses"], reference)

    checks = result["checks"]
    total_s = result["build_s"] + result["solve_s"]
    return {
        "Circuit": path,
        "Gates": gates,
        "Total_Candidates": candidates_total,
        "Selected_Candidates": len(selected),
        "Budget": budget if budget > 0 else "unlimited",
        "Mode": result["mode"],
        "Solver": result["solver"],
        "Checks": checks,
        "SAT": result["sat"],
        "UNSAT": result["unsat"],
        "Timeouts": result["timeouts"],
        "Errors": result["errors"],
        "Build_s": f"{result['build_s']:.6f}",
        "Solve_s": f"{result['solve_s']:.6f}",
        "Total_s": f"{total_s:.6f}",
        "Avg_ms_per_Check": f"{(1000.0 * total_s / checks) if checks else 0.0:.6f}",
        "Clauses": result["clauses"],
        "Conflicts": result["conflicts"],
        "Decisions": result["decisions"],
        "Propagations": result["propagations"],
        "Compared_Decisive": compared,
        "Decisive_Mismatches": mismatches,
        "Error": result["error"],
    }


def _experiment_one(path, args):
    M, I, L, O, A, inputs, latches, outputs, gates_raw, _ = _load_circuit(
        path, pre_strash=not args.no_pre_strash
    )
    del M, I, L, O, outputs
    all_candidates = _candidate_order(gates_raw)
    selected = _select_candidates(all_candidates, args.max_candidates, args.candidate_strategy, args.seed)

    rows = []
    local_reference_by_solver = {}
    circuit_deadline = time.time() + args.seconds_per_circuit if args.seconds_per_circuit > 0 else None

    for solver_name in args.solvers:
        solver_deadline = circuit_deadline
        if "local" in args.modes:
            print(f"[probe]   {solver_name} local", file=sys.stderr, flush=True)
            result = _run_local_per_candidate_solver(
                solver_name, inputs, latches, gates_raw, selected, args.budget, solver_deadline
            )
            local_reference_by_solver[solver_name] = result["statuses"]
            rows.append(_row_for_result(path, A, len(all_candidates), selected, args.budget, result))

        if "full" in args.modes:
            print(f"[probe]   {solver_name} full", file=sys.stderr, flush=True)
            result = _run_full_persistent_solver(
                solver_name, inputs, latches, gates_raw, selected, args.budget, solver_deadline
            )
            reference = local_reference_by_solver.get(solver_name)
            rows.append(_row_for_result(path, A, len(all_candidates), selected, args.budget, result, reference))

    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("circuits", nargs="+", help="AAG circuits to test.")
    parser.add_argument("--solvers", default=",".join(DEFAULT_SOLVERS))
    parser.add_argument("--modes", default="local,full", help="Comma list: local,full")
    parser.add_argument("--budget", type=int, default=5000, help="Conflict budget; <=0 means unlimited solve().")
    parser.add_argument("--max-candidates", type=int, default=2000)
    parser.add_argument("--candidate-strategy", choices=["first", "spread", "random"], default="spread")
    parser.add_argument("--seed", type=int, default=20260527)
    parser.add_argument("--seconds-per-circuit", type=float, default=0.0)
    parser.add_argument("--no-pre-strash", action="store_true")
    parser.add_argument("--csv", default="")
    args = parser.parse_args(argv)

    args.solvers = [part.strip() for part in args.solvers.split(",") if part.strip()]
    args.modes = {part.strip() for part in args.modes.split(",") if part.strip()}
    if not args.modes <= {"local", "full"}:
        raise SystemExit("--modes must contain only local and/or full")

    fieldnames = [
        "Circuit",
        "Gates",
        "Total_Candidates",
        "Selected_Candidates",
        "Budget",
        "Mode",
        "Solver",
        "Checks",
        "SAT",
        "UNSAT",
        "Timeouts",
        "Errors",
        "Build_s",
        "Solve_s",
        "Total_s",
        "Avg_ms_per_Check",
        "Clauses",
        "Conflicts",
        "Decisions",
        "Propagations",
        "Compared_Decisive",
        "Decisive_Mismatches",
        "Error",
    ]

    if not args.csv:
        out_dir = os.path.join("results_optimized", "sat_tfi_solver_experiments")
        os.makedirs(out_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        args.csv = os.path.join(out_dir, f"sat_tfi_solver_experiments_{stamp}.csv")

    os.makedirs(os.path.dirname(args.csv) or ".", exist_ok=True)
    with open(args.csv, "w", encoding="ascii", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        stdout_writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
        stdout_writer.writeheader()

        for circuit in args.circuits:
            print(f"[probe] {circuit}", file=sys.stderr, flush=True)
            rows = _experiment_one(circuit, args)
            writer.writerows(rows)
            f.flush()
            stdout_writer.writerows(rows)
            sys.stdout.flush()

    print(f"\n[wrote] {args.csv}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
