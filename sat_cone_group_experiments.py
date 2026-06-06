#!/usr/bin/env python3
"""Validate grouped exact-cone SAT reuse against the current single-cone miter.

This script is measurement-only. It compares two encodings for Algorithm 10's
exact affected-output cone tier:

- single: build one hardcoded single-fault cone miter per candidate;
- grouped: group candidates by identical affected observable roots and reuse one
  configurable-fault cone solver per root set.

Only UNSAT would be an optimizer acceptance proof, but this script does not
rewrite circuits. A decisive SAT/UNSAT mismatch is an encoding bug.
"""

import argparse
import csv
import os
import sys
import time
from collections import defaultdict
from datetime import datetime

from pysat.solvers import Solver

from optimizer_alg8_hybrid import _CNFBuilder, parse_aag, pure_python_forward_strash
from optimizer_alg10_tiered import (
    _affected_roots_from_graph,
    _candidate_order,
    _fanout_graph,
    _fanin_indices_for_roots,
    _parse_latch,
)


DEFAULT_SOLVERS = ["glucose4", "cadical153"]


def _load_circuit(path, pre_strash=True):
    M, I, L, O, A, inputs, latches, outputs, gates_raw, symbols = parse_aag(path)
    if not pre_strash:
        return M, I, L, O, A, inputs, latches, outputs, gates_raw, symbols

    result = pure_python_forward_strash(M, I, L, O, A, inputs, latches, outputs, gates_raw)
    M_f, I_f, L_f, O_f, A_f, in_f, la_f, out_f, gates_f = result
    return M_f, I_f, L_f, O_f, A_f, in_f, la_f, out_f, gates_f, symbols


def _solve_limited(solver, assumptions, budget):
    if budget > 0:
        solver.conf_budget(budget)
        return solver.solve_limited(assumptions=assumptions)
    return solver.solve(assumptions=assumptions)


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
            chosen.append(candidates[round(pos * (n - 1) / (limit - 1))])
        return chosen
    if strategy == "random":
        import random

        rng = random.Random(seed + len(candidates))
        sample = list(candidates)
        rng.shuffle(sample)
        return sample[:limit]
    raise ValueError(f"unknown candidate strategy: {strategy}")


def _build_single_fault_cone_miter(inputs, latches, roots, gates_raw, target_idx, stuck_value, cone):
    cnf = _CNFBuilder()
    shared = {}
    good = {}
    faulty = {}

    for lit in inputs:
        shared[lit >> 1] = cnf.new_var()
    for latch in latches:
        shared[_parse_latch(latch)[0] >> 1] = cnf.new_var()

    def lit_from(mapping, aig_lit):
        if aig_lit == 0:
            return cnf.const(False)
        if aig_lit == 1:
            return cnf.const(True)
        var = aig_lit >> 1
        if var in mapping:
            sat_lit = mapping[var]
        elif var in shared:
            sat_lit = shared[var]
        else:
            raise ValueError(f"undefined literal in cone SAT encoding: {aig_lit}")
        return -sat_lit if (aig_lit & 1) else sat_lit

    for idx in sorted(cone):
        lhs, r0, r1 = gates_raw[idx]

        good_out = cnf.new_var()
        good[lhs >> 1] = good_out
        cnf.and2(good_out, lit_from(good, r0), lit_from(good, r1))

        if idx == target_idx:
            faulty[lhs >> 1] = cnf.const(bool(stuck_value))
            continue

        faulty_out = cnf.new_var()
        faulty[lhs >> 1] = faulty_out
        cnf.and2(faulty_out, lit_from(faulty, r0), lit_from(faulty, r1))

    xors = []
    for root in roots:
        xor = cnf.new_var()
        cnf.xor2(xor, lit_from(good, root), lit_from(faulty, root))
        xors.append(xor)

    return cnf.clauses, cnf.or_many(xors)


def _build_grouped_cone_miter(inputs, latches, roots, gates_raw, cone):
    cnf = _CNFBuilder()
    shared = {}
    good = {}
    faulty = {}
    controls = {}

    for lit in inputs:
        shared[lit >> 1] = cnf.new_var()
    for latch in latches:
        shared[_parse_latch(latch)[0] >> 1] = cnf.new_var()

    def lit_from(mapping, aig_lit):
        if aig_lit == 0:
            return cnf.const(False)
        if aig_lit == 1:
            return cnf.const(True)
        var = aig_lit >> 1
        if var in mapping:
            sat_lit = mapping[var]
        elif var in shared:
            sat_lit = shared[var]
        else:
            raise ValueError(f"undefined literal in grouped cone SAT encoding: {aig_lit}")
        return -sat_lit if (aig_lit & 1) else sat_lit

    for idx in sorted(cone):
        lhs, r0, r1 = gates_raw[idx]
        out = cnf.new_var()
        good[lhs >> 1] = out
        cnf.and2(out, lit_from(good, r0), lit_from(good, r1))

    for idx in sorted(cone):
        lhs, r0, r1 = gates_raw[idx]
        normal = cnf.new_var()
        cnf.and2(normal, lit_from(faulty, r0), lit_from(faulty, r1))

        f0 = cnf.new_var()
        f1 = cnf.new_var()
        controls[idx] = (f0, f1)
        cnf.clauses.append([-f0, -f1])

        not_forced_zero = cnf.new_var()
        cnf.and2(not_forced_zero, normal, -f0)
        out = cnf.new_var()
        cnf.or2(out, not_forced_zero, f1)
        faulty[lhs >> 1] = out

    xors = []
    for root in roots:
        xor = cnf.new_var()
        cnf.xor2(xor, lit_from(good, root), lit_from(faulty, root))
        xors.append(xor)

    return cnf.clauses, cnf.or_many(xors), controls


def _group_key_for_candidate(gates_raw, roots, by_lhs, fanout, candidate, max_cone_gates):
    idx, _ = candidate
    affected = tuple(_affected_roots_from_graph(by_lhs, fanout, roots, idx))
    if not affected:
        return "SKIP", None, None
    cone = _fanin_indices_for_roots(gates_raw, affected, by_lhs=by_lhs)
    if idx not in cone:
        return "SKIP", None, None
    if max_cone_gates > 0 and len(cone) > max_cone_gates:
        return "SKIP", None, None
    return "CHECK", affected, frozenset(cone)


def _single_cone_reference(
    solver_name, inputs, latches, roots, gates_raw, candidates, budget, max_cone_gates, deadline
):
    by_lhs, fanout = _fanout_graph(gates_raw)
    statuses = {}
    checked = sat = unsat = timeouts = skipped = errors = 0
    build_s = solve_s = 0.0
    clauses_total = 0
    error_text = ""

    for candidate in candidates:
        if deadline is not None and time.time() >= deadline:
            break
        idx, stuck_value = candidate
        state, affected, cone = _group_key_for_candidate(
            gates_raw, roots, by_lhs, fanout, candidate, max_cone_gates
        )
        if state == "SKIP":
            statuses[candidate] = "SKIP"
            skipped += 1
            continue

        t_build = time.time()
        clauses, miter_lit = _build_single_fault_cone_miter(
            inputs, latches, affected, gates_raw, idx, stuck_value, cone
        )
        build_s += time.time() - t_build
        clauses_total += len(clauses)

        try:
            with Solver(name=solver_name, bootstrap_with=clauses) as solver:
                t_solve = time.time()
                result = _solve_limited(solver, [miter_lit], budget)
                solve_s += time.time() - t_solve
        except Exception as exc:
            errors += 1
            error_text = str(exc)
            break

        status = _status_name(result)
        statuses[candidate] = status
        checked += 1
        if status == "SAT":
            sat += 1
        elif status == "UNSAT":
            unsat += 1
        else:
            timeouts += 1

    return {
        "mode": "single",
        "solver": solver_name,
        "statuses": statuses,
        "checked": checked,
        "sat": sat,
        "unsat": unsat,
        "timeouts": timeouts,
        "skipped": skipped,
        "errors": errors,
        "groups": checked,
        "max_group": 1,
        "build_s": build_s,
        "solve_s": solve_s,
        "clauses": int(clauses_total / checked) if checked else 0,
        "error": error_text,
    }


def _grouped_cone_run(
    solver_name, inputs, latches, roots, gates_raw, candidates, budget, max_cone_gates, deadline
):
    by_lhs, fanout = _fanout_graph(gates_raw)
    statuses = {}
    groups = defaultdict(list)
    group_cones = {}
    checked = sat = unsat = timeouts = skipped = errors = 0
    build_s = solve_s = 0.0
    clauses_total = 0
    error_text = ""

    for candidate in candidates:
        state, affected, cone = _group_key_for_candidate(
            gates_raw, roots, by_lhs, fanout, candidate, max_cone_gates
        )
        if state == "SKIP":
            statuses[candidate] = "SKIP"
            skipped += 1
            continue
        groups[affected].append(candidate)
        group_cones[affected] = set(cone)

    max_group = max((len(items) for items in groups.values()), default=0)

    for affected, group_candidates in groups.items():
        if deadline is not None and time.time() >= deadline:
            break

        cone = group_cones[affected]
        t_build = time.time()
        clauses, miter_lit, controls = _build_grouped_cone_miter(
            inputs, latches, affected, gates_raw, cone
        )
        build_s += time.time() - t_build
        clauses_total += len(clauses)

        base = []
        control_positions = {}
        for gate_idx, (f0, f1) in controls.items():
            control_positions[(gate_idx, 0)] = len(base)
            base.append(-f0)
            control_positions[(gate_idx, 1)] = len(base)
            base.append(-f1)

        try:
            with Solver(name=solver_name, bootstrap_with=clauses) as solver:
                for candidate in group_candidates:
                    if deadline is not None and time.time() >= deadline:
                        break
                    idx, stuck_value = candidate
                    f0, f1 = controls[idx]
                    assumptions = base.copy()
                    if stuck_value == 0:
                        assumptions[control_positions[(idx, 0)]] = f0
                        assumptions[control_positions[(idx, 1)]] = -f1
                    else:
                        assumptions[control_positions[(idx, 1)]] = f1
                        assumptions[control_positions[(idx, 0)]] = -f0
                    assumptions.append(miter_lit)

                    t_solve = time.time()
                    result = _solve_limited(solver, assumptions, budget)
                    solve_s += time.time() - t_solve

                    status = _status_name(result)
                    statuses[candidate] = status
                    checked += 1
                    if status == "SAT":
                        sat += 1
                    elif status == "UNSAT":
                        unsat += 1
                    else:
                        timeouts += 1
        except Exception as exc:
            errors += 1
            error_text = str(exc)
            break

    return {
        "mode": "grouped",
        "solver": solver_name,
        "statuses": statuses,
        "checked": checked,
        "sat": sat,
        "unsat": unsat,
        "timeouts": timeouts,
        "skipped": skipped,
        "errors": errors,
        "groups": len(groups),
        "max_group": max_group,
        "build_s": build_s,
        "solve_s": solve_s,
        "clauses": int(clauses_total / len(groups)) if groups else 0,
        "error": error_text,
    }


def _decisive_mismatches(statuses, reference):
    compared = mismatches = 0
    for candidate, status in statuses.items():
        ref = reference.get(candidate)
        if status in {"SAT", "UNSAT"} and ref in {"SAT", "UNSAT"}:
            compared += 1
            if status != ref:
                mismatches += 1
    return compared, mismatches


def _row(path, gates, total_candidates, selected, budget, result, reference=None):
    compared = mismatches = ""
    if reference is not None:
        compared, mismatches = _decisive_mismatches(result["statuses"], reference)
    total_s = result["build_s"] + result["solve_s"]
    checked = result["checked"]
    return {
        "Circuit": path,
        "Gates": gates,
        "Total_Candidates": total_candidates,
        "Selected_Candidates": len(selected),
        "Budget": budget if budget > 0 else "unlimited",
        "Mode": result["mode"],
        "Solver": result["solver"],
        "Groups": result["groups"],
        "Max_Group": result["max_group"],
        "Checks": checked,
        "SAT": result["sat"],
        "UNSAT": result["unsat"],
        "Timeouts": result["timeouts"],
        "Skipped": result["skipped"],
        "Errors": result["errors"],
        "Build_s": f"{result['build_s']:.6f}",
        "Solve_s": f"{result['solve_s']:.6f}",
        "Total_s": f"{total_s:.6f}",
        "Avg_ms_per_Check": f"{(1000.0 * total_s / checked) if checked else 0.0:.6f}",
        "Clauses": result["clauses"],
        "Compared_Decisive": compared,
        "Decisive_Mismatches": mismatches,
        "Error": result["error"],
    }


def _experiment_one(path, args):
    M, I, L, O, A, inputs, latches, outputs, gates_raw, _ = _load_circuit(
        path, pre_strash=not args.no_pre_strash
    )
    del M, I, L, O
    roots = list(outputs)
    roots.extend(_parse_latch(latch)[1] for latch in latches)
    all_candidates = _candidate_order(gates_raw, roots=roots)
    selected = _select_candidates(all_candidates, args.max_candidates, args.candidate_strategy, args.seed)
    circuit_deadline = time.time() + args.seconds_per_circuit if args.seconds_per_circuit > 0 else None

    print(f"[probe]   reference {args.reference_solver}", file=sys.stderr, flush=True)
    reference = _single_cone_reference(
        args.reference_solver,
        inputs,
        latches,
        roots,
        gates_raw,
        selected,
        args.budget,
        args.max_cone_gates,
        circuit_deadline,
    )
    rows = [_row(path, A, len(all_candidates), selected, args.budget, reference)]

    for solver_name in args.solvers:
        print(f"[probe]   grouped {solver_name}", file=sys.stderr, flush=True)
        grouped = _grouped_cone_run(
            solver_name,
            inputs,
            latches,
            roots,
            gates_raw,
            selected,
            args.budget,
            args.max_cone_gates,
            circuit_deadline,
        )
        rows.append(_row(path, A, len(all_candidates), selected, args.budget, grouped, reference["statuses"]))

    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("circuits", nargs="+", help="AAG circuits to test.")
    parser.add_argument("--solvers", default=",".join(DEFAULT_SOLVERS))
    parser.add_argument("--reference-solver", default="glucose4")
    parser.add_argument("--budget", type=int, default=1000)
    parser.add_argument("--max-cone-gates", type=int, default=20000)
    parser.add_argument("--max-candidates", type=int, default=500)
    parser.add_argument("--candidate-strategy", choices=["first", "spread", "random"], default="spread")
    parser.add_argument("--seed", type=int, default=20260527)
    parser.add_argument("--seconds-per-circuit", type=float, default=0.0)
    parser.add_argument("--no-pre-strash", action="store_true")
    parser.add_argument("--csv", default="")
    args = parser.parse_args(argv)
    args.solvers = [part.strip() for part in args.solvers.split(",") if part.strip()]

    fieldnames = [
        "Circuit",
        "Gates",
        "Total_Candidates",
        "Selected_Candidates",
        "Budget",
        "Mode",
        "Solver",
        "Groups",
        "Max_Group",
        "Checks",
        "SAT",
        "UNSAT",
        "Timeouts",
        "Skipped",
        "Errors",
        "Build_s",
        "Solve_s",
        "Total_s",
        "Avg_ms_per_Check",
        "Clauses",
        "Compared_Decisive",
        "Decisive_Mismatches",
        "Error",
    ]

    if not args.csv:
        out_dir = os.path.join("results_optimized", "sat_cone_group_experiments")
        os.makedirs(out_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        args.csv = os.path.join(out_dir, f"sat_cone_group_experiments_{stamp}.csv")

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
