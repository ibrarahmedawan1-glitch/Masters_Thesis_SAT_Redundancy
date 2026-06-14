#!/usr/bin/env python3
"""Bounded truth-table checks for pair stuck-at assumptions."""

import argparse
import itertools
import os
import time

os.environ.setdefault("ALG10_MODE", "fast_save")
os.environ.setdefault("ALG10_BUDGETS", "100000")

from pysat.solvers import Glucose4  # noqa: E402

import optimizer_alg10_tiered as alg10  # noqa: E402
from optimizer_alg8_hybrid import _build_fault_sweep_cnf  # noqa: E402
from pair_stuckat_experiment import (  # noqa: E402
    Candidate,
    audit_pair_assumptions,
    build_sim_context,
    build_pair_assumptions,
    build_single_assumptions,
    pair_simulation_reject,
    solve_assumptions,
)
from test_encoding_soundness_bounded import (  # noqa: E402
    gate_lists,
    output_literals,
    simulate,
)


def truth_redundant_pair(inputs, gates, outputs, pair):
    faults = {candidate.idx: candidate.stuck_value for candidate in pair}
    for mask in range(1 << len(inputs)):
        assignment = [(mask >> bit) & 1 for bit in range(len(inputs))]
        good, _ = simulate(inputs, gates, outputs, assignment)
        faulty, _ = simulate(inputs, gates, outputs, assignment, faults=faults)
        if good != faulty:
            return False
    return True


def truth_redundant_single(inputs, gates, outputs, candidate):
    return truth_redundant_pair(inputs, gates, outputs, [candidate])


def normalized_status(status):
    if status in {"SAT", "UNSAT"}:
        return status
    raise AssertionError(f"unexpected pair solver status in bounded check: {status}")


def solve_pair(inputs, gates, outputs, pair, budget):
    clauses, miter_lit, f0_lits, f1_lits = _build_fault_sweep_cnf(inputs, [], outputs, gates)
    with Glucose4(bootstrap_with=clauses) as solver:
        assumptions = build_pair_assumptions(
            len(gates), f0_lits, f1_lits, pair, miter_lit, accepted={}
        )
        audit_pair_assumptions(
            assumptions, len(gates), f0_lits, f1_lits, pair, miter_lit, accepted={}
        )
        return solve_assumptions(solver, assumptions, budget).status


def solve_single(inputs, gates, outputs, candidate, budget):
    clauses, miter_lit, f0_lits, f1_lits = _build_fault_sweep_cnf(inputs, [], outputs, gates)
    with Glucose4(bootstrap_with=clauses) as solver:
        assumptions = build_single_assumptions(len(gates), f0_lits, f1_lits, candidate, miter_lit)
        return solve_assumptions(solver, assumptions, budget).status


def candidate_pairs(gate_count):
    candidates = [Candidate(idx, value) for idx in range(gate_count) for value in (0, 1)]
    for left, right in itertools.combinations(candidates, 2):
        if left.idx == right.idx:
            continue
        yield left, right


def output_sets(inputs, gates, output_count, max_sets):
    literals = output_literals(inputs, gates, "all")
    count = min(output_count, len(literals))
    yielded = 0
    for combo in itertools.combinations(literals, count):
        yield list(combo)
        yielded += 1
        if max_sets > 0 and yielded >= max_sets:
            break


def fail(kind, inputs, gates, outputs, pair, status, expected):
    print("\nPAIR STUCK-AT SOUNDNESS FAILURE")
    print(f"kind={kind}")
    print(f"inputs={len(inputs)} outputs={outputs}")
    print(f"pair={[(candidate.idx, candidate.stuck_value) for candidate in pair]}")
    print(f"status={status} expected_redundant={expected}")
    print("gates:")
    for gate in gates:
        print(" ", gate)
    raise SystemExit(1)


def check_case(inputs, gates, outputs, pair, budget, sim_patterns, sim_seed):
    expected = truth_redundant_pair(inputs, gates, outputs, pair)
    sim_context = build_sim_context(inputs, [], outputs, gates, sim_patterns, sim_seed)
    if pair_simulation_reject(gates, pair, sim_context) and expected:
        fail("pair_simulation_reject", inputs, gates, outputs, pair, "SIM_REJECT", expected)
    status = normalized_status(solve_pair(inputs, gates, outputs, pair, budget))
    if status != ("UNSAT" if expected else "SAT"):
        fail("pair_global_miter", inputs, gates, outputs, pair, status, expected)
    return expected


def run_space(input_count, gate_count, output_count, max_output_sets, budget, sim_patterns, sim_seed):
    inputs = [2 * (idx + 1) for idx in range(input_count)]
    stats = {
        "circuits": 0,
        "output_sets": 0,
        "pairs": 0,
        "redundant_pairs": 0,
        "pair_only_redundant": 0,
    }
    for gates in gate_lists(input_count, gate_count):
        stats["circuits"] += 1
        for outputs in output_sets(inputs, gates, output_count, max_output_sets):
            stats["output_sets"] += 1
            for pair in candidate_pairs(gate_count):
                expected = check_case(inputs, gates, outputs, pair, budget, sim_patterns, sim_seed)
                stats["pairs"] += 1
                if expected:
                    stats["redundant_pairs"] += 1
                    left_single = truth_redundant_single(inputs, gates, outputs, pair[0])
                    right_single = truth_redundant_single(inputs, gates, outputs, pair[1])
                    if not left_single and not right_single:
                        stats["pair_only_redundant"] += 1
    return stats


def handcrafted_pair_only_case(budget):
    inputs = [2]
    # g1 = x & 1, g2 = x & 1, output = XNOR(g1, g2).
    gates = [
        [4, 2, 1],
        [6, 2, 1],
        [8, 4, 7],
        [10, 5, 6],
        [12, 9, 11],
    ]
    outputs = [12]
    pair = (Candidate(0, 0), Candidate(1, 0))
    pair_status = normalized_status(solve_pair(inputs, gates, outputs, pair, budget))
    single0 = normalized_status(solve_single(inputs, gates, outputs, pair[0], budget))
    single1 = normalized_status(solve_single(inputs, gates, outputs, pair[1], budget))
    sim_context = build_sim_context(inputs, [], outputs, gates, 32, 20260609)
    if pair_simulation_reject(gates, pair, sim_context):
        fail("handcrafted_pair_only_sim", inputs, gates, outputs, pair, "SIM_REJECT", True)
    if pair_status != "UNSAT" or single0 != "SAT" or single1 != "SAT":
        fail("handcrafted_pair_only", inputs, gates, outputs, pair, pair_status, True)
    return {
        "handcrafted_pair_status": pair_status,
        "handcrafted_single0": single0,
        "handcrafted_single1": single1,
    }


def negative_audit_checks():
    inputs = [2]
    gates = [[4, 2, 1], [6, 2, 1]]
    outputs = [4]
    clauses, miter_lit, f0_lits, f1_lits = _build_fault_sweep_cnf(inputs, [], outputs, gates)
    del clauses
    pair = (Candidate(0, 0), Candidate(1, 1))
    assumptions = build_pair_assumptions(len(gates), f0_lits, f1_lits, pair, miter_lit)

    failures = 0
    for corrupt in (
        assumptions[:-1],
        assumptions[:-1] + [-miter_lit],
        assumptions.copy() + [assumptions[0]],
    ):
        try:
            audit_pair_assumptions(corrupt, len(gates), f0_lits, f1_lits, pair, miter_lit)
        except AssertionError:
            failures += 1
        else:
            raise SystemExit("negative audit check unexpectedly passed")

    try:
        bad_pair = (Candidate(0, 0), Candidate(0, 1))
        build_pair_assumptions(len(gates), f0_lits, f1_lits, bad_pair, miter_lit)
    except AssertionError:
        failures += 1
    else:
        raise SystemExit("same-gate opposite stuck pair unexpectedly passed")
    return failures


def merge_stats(total, stats):
    for key, value in stats.items():
        total[key] = total.get(key, 0) + value


def main():
    parser = argparse.ArgumentParser(description="Bounded pair stuck-at soundness checker.")
    parser.add_argument("--max-inputs", type=int, default=2)
    parser.add_argument("--max-gates", type=int, default=2)
    parser.add_argument("--output-count", type=int, default=2)
    parser.add_argument("--max-output-sets", type=int, default=24)
    parser.add_argument("--budget", type=int, default=0, help="0 means unlimited.")
    parser.add_argument("--sim-patterns", type=int, default=32)
    parser.add_argument("--sim-seed", type=int, default=20260609)
    args = parser.parse_args()

    started = time.time()
    total = {}
    print("Bounded pair stuck-at soundness check")
    print(
        f"max_inputs={args.max_inputs} max_gates={args.max_gates} "
        f"output_count={args.output_count}"
    )
    hand = handcrafted_pair_only_case(args.budget)
    print(f"PASS handcrafted pair-only: {hand}")
    print(f"PASS negative audit failures caught: {negative_audit_checks()}")

    for input_count in range(1, args.max_inputs + 1):
        for gate_count in range(2, args.max_gates + 1):
            stats = run_space(
                input_count,
                gate_count,
                args.output_count,
                args.max_output_sets,
                args.budget,
                args.sim_patterns,
                args.sim_seed,
            )
            merge_stats(total, stats)
            print(f"PASS inputs={input_count} gates={gate_count}: {stats}")

    print("\nPAIR STUCK-AT SOUNDNESS PASS")
    print(f"elapsed={time.time() - started:.2f}s")
    for key in sorted(total):
        print(f"{key}={total[key]}")


if __name__ == "__main__":
    main()
