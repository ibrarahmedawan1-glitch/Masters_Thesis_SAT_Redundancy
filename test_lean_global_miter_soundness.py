#!/usr/bin/env python3
"""Bounded soundness checks for the lean global miter experiment.

The lean encoding adds AMO(all fault controls) to the global fault-sweep CNF and
then solves each single stuck-at candidate with only two assumptions:
candidate-control and miter.  This test exhaustively compares that encoding
against brute-force truth tables and the production full-assumption encoding on
small AIGs.
"""

import argparse
import os
import time

os.environ.setdefault("ALG10_AUDIT_ASSUMPTIONS", "1")
os.environ.setdefault("ALG10_CEX_PRUNING", "0")

from pysat.solvers import Glucose4

import optimizer_alg10_tiered as alg10
from lean_global_miter_experiment import (
    add_single_fault_amo,
    full_candidate_assumptions,
    lean_candidate_assumptions,
)
from test_encoding_soundness_bounded import (
    gate_lists,
    output_literals,
    truth_redundant,
)


def fail(kind, input_count, gates, output, idx, stuck_value, expected, full_sat, lean_sat):
    print("\nLEAN GLOBAL MITER SOUNDNESS FAILURE")
    print(f"kind={kind}")
    print(f"inputs={input_count} output={output} candidate=gate_index:{idx} SA{stuck_value}")
    print(f"expected_redundant={expected} full_sat={full_sat} lean_sat={lean_sat}")
    print("gates:")
    for gate in gates:
        print(" ", gate)
    raise SystemExit(1)


def run_space(input_count, gate_count, output_mode, progress_interval):
    inputs = [2 * (idx + 1) for idx in range(input_count)]
    stats = {
        "circuits": 0,
        "candidates": 0,
        "redundant_candidates": 0,
        "full_sat": 0,
        "full_unsat": 0,
        "lean_sat": 0,
        "lean_unsat": 0,
        "matches": 0,
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

            clauses, miter_lit, f0_lits, f1_lits = alg10._build_fault_sweep_cnf(
                inputs, [], [output], gates
            )
            lean_clauses, _amo_count, _top_id = add_single_fault_amo(
                clauses, f0_lits, f1_lits
            )

            with Glucose4(bootstrap_with=clauses) as full_solver:
                with Glucose4(bootstrap_with=lean_clauses) as lean_solver:
                    for idx in range(gate_count):
                        for stuck_value in (0, 1):
                            expected_redundant = truth_redundant(
                                inputs, gates, output, idx, stuck_value
                            )
                            if expected_redundant:
                                stats["redundant_candidates"] += 1

                            full_assumptions = full_candidate_assumptions(
                                gate_count,
                                f0_lits,
                                f1_lits,
                                (idx, stuck_value),
                                miter_lit,
                            )
                            lean_assumptions = lean_candidate_assumptions(
                                gate_count,
                                f0_lits,
                                f1_lits,
                                (idx, stuck_value),
                                miter_lit,
                            )
                            full_sat = full_solver.solve(assumptions=full_assumptions)
                            lean_sat = lean_solver.solve(assumptions=lean_assumptions)
                            stats["candidates"] += 1
                            stats["full_sat" if full_sat else "full_unsat"] += 1
                            stats["lean_sat" if lean_sat else "lean_unsat"] += 1

                            if full_sat != lean_sat:
                                fail(
                                    "full_vs_lean",
                                    input_count,
                                    gates,
                                    output,
                                    idx,
                                    stuck_value,
                                    expected_redundant,
                                    full_sat,
                                    lean_sat,
                                )
                            stats["matches"] += 1

                            if lean_sat != (not expected_redundant):
                                fail(
                                    "truth_table",
                                    input_count,
                                    gates,
                                    output,
                                    idx,
                                    stuck_value,
                                    expected_redundant,
                                    full_sat,
                                    lean_sat,
                                )

    return stats


def merge_stats(total, stats):
    for key, value in stats.items():
        total[key] = total.get(key, 0) + value


def main():
    parser = argparse.ArgumentParser(
        description="Bounded exhaustive soundness checker for lean global miter."
    )
    parser.add_argument("--max-inputs", type=int, default=2)
    parser.add_argument("--max-gates", type=int, default=2)
    parser.add_argument("--include-depth3", action="store_true")
    parser.add_argument("--progress-interval", type=int, default=10000)
    args = parser.parse_args()

    total = {}
    started = time.time()

    print("Bounded lean global miter soundness check")
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

    print("\nLEAN GLOBAL MITER SOUNDNESS PASS")
    print(f"elapsed={time.time() - started:.2f}s")
    for key in sorted(total):
        print(f"{key}={total[key]}")


if __name__ == "__main__":
    main()
