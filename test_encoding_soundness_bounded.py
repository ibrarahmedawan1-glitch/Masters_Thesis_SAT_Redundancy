#!/usr/bin/env python3
"""Bounded exhaustive soundness checks for Algorithm 10 SAT encodings.

This is not a benchmark test. It enumerates a finite space of small AIGs and
checks production SAT encodings against brute-force truth-table semantics for
every single-gate stuck-at candidate in that space.
"""

import argparse
import itertools
import os
import sys
import time

os.environ.setdefault("ALG10_MODE", "fast_save")
os.environ.setdefault("ALG10_BUDGETS", "100000")
os.environ.setdefault("ALG10_TFI_BUDGET", "100000")
os.environ.setdefault("ALG10_TFI_MAX_CONE_GATES", "100000")
os.environ.setdefault("ALG10_WINDOW_BUDGET", "100000")
os.environ.setdefault("ALG10_WINDOW_MAX_CONE_GATES", "100000")
os.environ.setdefault("ALG10_CONE_BUDGET", "100000")
os.environ.setdefault("ALG10_CONE_MAX_GATES", "100000")
os.environ.setdefault("ALG10_CONE_SOLVER", "glucose4")
os.environ.setdefault("ALG10_WINDOW_AUDIT", "1")
os.environ.setdefault("ALG10_AUDIT_ASSUMPTIONS", "1")
os.environ.setdefault("ALG10_CEX_PRUNING", "0")

from pysat.solvers import Glucose4

import optimizer_alg10_tiered as alg10
from optimizer_alg8_hybrid import pure_python_forward_strash


def lit_value(lit, values):
    if lit == 0:
        return False
    if lit == 1:
        return True
    value = values.get(lit & ~1, False)
    return not value if (lit & 1) else value


def simulate(inputs, gates, outputs, assignment, faults=None):
    faults = faults or {}
    values = {}
    for lit, bit in zip(inputs, assignment):
        values[lit & ~1] = bool(bit)

    gate_values = []
    for idx, (lhs, r0, r1) in enumerate(gates):
        if idx in faults:
            value = bool(faults[idx])
        else:
            value = lit_value(r0, values) and lit_value(r1, values)
        values[lhs & ~1] = value
        gate_values.append(value)

    return tuple(lit_value(out, values) for out in outputs), tuple(gate_values)


def truth_redundant(inputs, gates, output, idx, stuck_value):
    for mask in range(1 << len(inputs)):
        assignment = [(mask >> bit) & 1 for bit in range(len(inputs))]
        good, _ = simulate(inputs, gates, [output], assignment)
        faulty, _ = simulate(inputs, gates, [output], assignment, faults={idx: stuck_value})
        if good != faulty:
            return False
    return True


def truth_tfi_constant(inputs, gates, idx, stuck_value):
    for mask in range(1 << len(inputs)):
        assignment = [(mask >> bit) & 1 for bit in range(len(inputs))]
        _, gate_values = simulate(inputs, gates, [], assignment)
        if gate_values[idx] != bool(stuck_value):
            return False
    return True


def fanin_pairs(available):
    for pos, left in enumerate(available):
        for right in available[pos:]:
            # Keep one representative for commutative AND.
            yield left, right


def gate_lists(input_count, gate_count):
    inputs = [2 * (idx + 1) for idx in range(input_count)]
    first_lhs_var = input_count + 1

    def rec(idx, gates, available):
        if idx == gate_count:
            yield gates
            return
        lhs = 2 * (first_lhs_var + idx)
        for r0, r1 in fanin_pairs(available):
            yield from rec(
                idx + 1,
                gates + [[lhs, r0, r1]],
                available + [lhs, lhs ^ 1],
            )

    base_available = [0, 1]
    for lit in inputs:
        base_available.extend([lit, lit ^ 1])
    yield from rec(0, [], base_available)


def output_literals(inputs, gates, mode):
    available = [0, 1]
    for lit in inputs:
        available.extend([lit, lit ^ 1])
    for lhs, _, _ in gates:
        available.extend([lhs, lhs ^ 1])

    if mode == "last_gate":
        if not gates:
            return available
        lhs = gates[-1][0]
        return [lhs, lhs ^ 1]
    return available


def check_global_encoding(inputs, gates, output, idx, stuck_value, expected_redundant):
    clauses, miter_lit, f0_lits, f1_lits = alg10._build_fault_sweep_cnf(inputs, [], [output], gates)
    gate_count = len(gates)
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
        candidate=(idx, stuck_value),
        accepted={},
        miter_lit=miter_lit,
    )
    with Glucose4(bootstrap_with=clauses) as solver:
        sat = solver.solve(assumptions=assumptions)
    return sat == (not expected_redundant)


def check_tfi_encoding(inputs, gates, idx, stuck_value, expected_constant):
    result, _ = alg10._tfi_constancy_check(inputs, [], gates, idx, stuck_value)
    if result == "UNSAT":
        return expected_constant
    if result == "SAT":
        return not expected_constant
    return False


def check_persistent_tfi_encoding(inputs, gates, idx, stuck_value, expected_constant):
    clauses, var_for_base = alg10._build_full_good_tfi_cnf(inputs, [], gates)
    assumption = alg10._tfi_candidate_assumption(gates, var_for_base, idx, stuck_value)
    if assumption is None:
        return False
    with Glucose4(bootstrap_with=clauses) as solver:
        sat = solver.solve(assumptions=[assumption])
    return sat == (not expected_constant)


def check_cone_encoding(inputs, gates, output, idx, stuck_value, expected_redundant):
    timings = {"Encode": 0.0, "SAT": 0.0}
    by_lhs, fanout = alg10._fanout_graph(gates)
    result, _ = alg10._cone_miter_check(
        inputs, [], [output], gates, idx, stuck_value, timings, by_lhs, fanout
    )
    if result == "SKIP":
        return True
    if result == "UNSAT":
        return expected_redundant
    if result == "SAT":
        return not expected_redundant
    return False


def check_grouped_cone_encoding(inputs, gates, output, idx, stuck_value, expected_redundant):
    timings = {"Encode": 0.0, "SAT": 0.0}
    by_lhs, fanout = alg10._fanout_graph(gates)
    roots, cone = alg10._cone_group_key(gates, [output], idx, by_lhs, fanout)
    if roots is None:
        return True

    state = alg10._make_cone_group_solver(inputs, [], roots, gates, cone, {}, timings)
    try:
        assumptions = state.assumptions_for(idx, stuck_value)
        if assumptions is None:
            return True
        alg10._audit_cone_group_assumptions(
            assumptions,
            state,
            (idx, stuck_value),
            accepted={},
        )
        sat = state.solver.solve(assumptions=assumptions)
    finally:
        state.delete()
    return sat == (not expected_redundant)


def check_window_soundness(inputs, gates, output, idx, stuck_value, expected_redundant):
    timings = {"Encode": 0.0, "SAT": 0.0}
    by_lhs, fanout = alg10._fanout_graph(gates)
    result, _, _ = alg10._window_miter_check(
        inputs, [], [output], gates, idx, stuck_value, timings, by_lhs, fanout
    )
    # The audited window tier may be incomplete and skip/SAT. The soundness
    # obligation is only that every UNSAT acceptance is truly redundant.
    if result == "UNSAT":
        return expected_redundant
    if result in {"SAT", "SKIP", "AUDIT_FAIL"}:
        return True
    return False


def check_rewrite(inputs, gates, output, idx, stuck_value, expected_redundant):
    if not expected_redundant:
        return True

    M = len(inputs) + len(gates)
    working = [[lhs, r0, r1] for lhs, r0, r1 in gates]
    lhs = working[idx][0]
    working[idx] = [lhs, stuck_value, stuck_value]
    result = pure_python_forward_strash(M, len(inputs), 0, 1, len(gates), inputs, [], [output], working)
    _, _, _, _, _, out_inputs, _, out_outputs, out_gates = result

    for mask in range(1 << len(inputs)):
        assignment = [(mask >> bit) & 1 for bit in range(len(inputs))]
        good, _ = simulate(inputs, gates, [output], assignment)
        rewritten, _ = simulate(out_inputs, out_gates, out_outputs, assignment)
        if good != rewritten:
            return False
    return True


def fail(kind, input_count, gates, output, idx, stuck_value, expected):
    print("\nENCODING SOUNDNESS FAILURE")
    print(f"kind={kind}")
    print(f"inputs={input_count} output={output} candidate=gate_index:{idx} SA{stuck_value}")
    print(f"expected={expected}")
    print("gates:")
    for gate in gates:
        print(" ", gate)
    raise SystemExit(1)


def run_space(input_count, gate_count, output_mode, progress_interval):
    inputs = [2 * (idx + 1) for idx in range(input_count)]
    stats = {
        "circuits": 0,
        "candidates": 0,
        "global": 0,
        "tfi": 0,
        "persistent_tfi": 0,
        "cone": 0,
        "grouped_cone": 0,
        "window": 0,
        "rewrite": 0,
        "redundant_candidates": 0,
        "window_unsat_accepts": 0,
    }
    started = time.time()

    for gates in gate_lists(input_count, gate_count):
        for output in output_literals(inputs, gates, output_mode):
            stats["circuits"] += 1
            if progress_interval and stats["circuits"] % progress_interval == 0:
                elapsed = time.time() - started
                print(
                    f"  inputs={input_count} gates={gate_count} "
                    f"circuits={stats['circuits']} candidates={stats['candidates']} "
                    f"elapsed={elapsed:.1f}s"
                )

            for idx in range(gate_count):
                for stuck_value in (0, 1):
                    expected_redundant = truth_redundant(inputs, gates, output, idx, stuck_value)
                    expected_constant = truth_tfi_constant(inputs, gates, idx, stuck_value)
                    stats["candidates"] += 1
                    if expected_redundant:
                        stats["redundant_candidates"] += 1

                    if not check_global_encoding(inputs, gates, output, idx, stuck_value, expected_redundant):
                        fail("global_miter", input_count, gates, output, idx, stuck_value, expected_redundant)
                    stats["global"] += 1

                    if not check_tfi_encoding(inputs, gates, idx, stuck_value, expected_constant):
                        fail("tfi_constancy", input_count, gates, output, idx, stuck_value, expected_constant)
                    stats["tfi"] += 1

                    if not check_persistent_tfi_encoding(
                        inputs, gates, idx, stuck_value, expected_constant
                    ):
                        fail(
                            "persistent_tfi_constancy",
                            input_count,
                            gates,
                            output,
                            idx,
                            stuck_value,
                            expected_constant,
                        )
                    stats["persistent_tfi"] += 1

                    if not check_cone_encoding(inputs, gates, output, idx, stuck_value, expected_redundant):
                        fail("cone_miter", input_count, gates, output, idx, stuck_value, expected_redundant)
                    stats["cone"] += 1

                    if not check_grouped_cone_encoding(
                        inputs, gates, output, idx, stuck_value, expected_redundant
                    ):
                        fail(
                            "grouped_cone_miter",
                            input_count,
                            gates,
                            output,
                            idx,
                            stuck_value,
                            expected_redundant,
                        )
                    stats["grouped_cone"] += 1

                    before_window = stats["window_unsat_accepts"]
                    if not check_window_soundness(inputs, gates, output, idx, stuck_value, expected_redundant):
                        fail("window_miter_unsat", input_count, gates, output, idx, stuck_value, expected_redundant)
                    # Count accepted windows separately for reporting.
                    timings = {"Encode": 0.0, "SAT": 0.0}
                    by_lhs, fanout = alg10._fanout_graph(gates)
                    result, _, _ = alg10._window_miter_check(
                        inputs, [], [output], gates, idx, stuck_value, timings, by_lhs, fanout
                    )
                    if result == "UNSAT":
                        stats["window_unsat_accepts"] = before_window + 1
                    stats["window"] += 1

                    if not check_rewrite(inputs, gates, output, idx, stuck_value, expected_redundant):
                        fail("rewrite_after_true_redundancy", input_count, gates, output, idx, stuck_value, True)
                    stats["rewrite"] += 1

    return stats


def merge_stats(total, stats):
    for key, value in stats.items():
        total[key] = total.get(key, 0) + value


def main():
    parser = argparse.ArgumentParser(description="Bounded exhaustive SAT encoding soundness checker.")
    parser.add_argument("--max-inputs", type=int, default=3)
    parser.add_argument("--max-gates", type=int, default=2)
    parser.add_argument("--include-depth3", action="store_true")
    parser.add_argument("--progress-interval", type=int, default=10000)
    args = parser.parse_args()

    total = {}
    started = time.time()

    print("Bounded exhaustive encoding soundness check")
    print(f"max_inputs={args.max_inputs} max_gates={args.max_gates} include_depth3={args.include_depth3}")

    for input_count in range(1, args.max_inputs + 1):
        for gate_count in range(1, args.max_gates + 1):
            stats = run_space(input_count, gate_count, "all", args.progress_interval)
            merge_stats(total, stats)
            print(f"PASS inputs={input_count} gates={gate_count}: {stats}")

    if args.include_depth3:
        stats = run_space(2, 3, "last_gate", args.progress_interval)
        merge_stats(total, stats)
        print(f"PASS inputs=2 gates=3 last-gate outputs: {stats}")

    print("\nBOUNDED ENCODING SOUNDNESS PASS")
    print(f"elapsed={time.time() - started:.2f}s")
    for key in sorted(total):
        print(f"{key}={total[key]}")


if __name__ == "__main__":
    main()
