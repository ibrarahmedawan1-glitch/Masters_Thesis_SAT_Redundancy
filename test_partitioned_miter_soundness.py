#!/usr/bin/env python3
"""Bounded truth-table checks for affected-root partitioned exact miters."""

import argparse
import itertools
import os
import time

os.environ.setdefault("ALG10_MODE", "fast_save")
os.environ.setdefault("ALG10_BUDGETS", "100000")
os.environ.setdefault("ALG10_CONE_BUDGET", "100000")
os.environ.setdefault("ALG10_CONE_MAX_GATES", "100000")

from partitioned_miter_experiment import (  # noqa: E402
    result_family,
    solve_exact_roots,
    solve_partitioned_roots,
)
from test_encoding_soundness_bounded import (  # noqa: E402
    gate_lists,
    output_literals,
    simulate,
)

import optimizer_alg10_tiered as alg10  # noqa: E402


def truth_redundant_multi(inputs, gates, outputs, idx, stuck_value):
    for mask in range(1 << len(inputs)):
        assignment = [(mask >> bit) & 1 for bit in range(len(inputs))]
        good, _ = simulate(inputs, gates, outputs, assignment)
        faulty, _ = simulate(inputs, gates, outputs, assignment, faults={idx: stuck_value})
        if good != faulty:
            return False
    return True


def output_sets(inputs, gates, output_count, max_sets):
    literals = output_literals(inputs, gates, "all")
    count = min(output_count, len(literals))
    yielded = 0
    for combo in itertools.combinations(literals, count):
        yield list(combo)
        yielded += 1
        if max_sets > 0 and yielded >= max_sets:
            break


def normalized_status(status):
    family = result_family(status)
    if family in {"SAT", "UNSAT"}:
        return family
    raise AssertionError(f"unexpected unresolved/error status in bounded check: {status}")


def check_case(inputs, gates, outputs, idx, stuck_value, partition_sizes, budget):
    expected = truth_redundant_multi(inputs, gates, outputs, idx, stuck_value)
    by_lhs, fanout = alg10._fanout_graph(gates)
    affected = alg10._affected_roots_from_graph(by_lhs, fanout, outputs, idx)
    mono = solve_exact_roots(inputs, [], affected, gates, idx, stuck_value, by_lhs, budget)
    mono_status = normalized_status(mono.status)
    if mono_status != ("UNSAT" if expected else "SAT"):
        return False, "monolithic", mono.status, expected, affected

    for partition_size in partition_sizes:
        partition = solve_partitioned_roots(
            inputs,
            [],
            affected,
            gates,
            idx,
            stuck_value,
            by_lhs,
            budget,
            partition_size,
        )
        partition_status = normalized_status(partition.status)
        if partition_status != mono_status:
            return False, f"partition_size_{partition_size}", partition.status, expected, affected
    return True, "", "", expected, affected


def fail(kind, input_count, gates, outputs, idx, stuck_value, status, expected, affected):
    print("\nPARTITIONED MITER SOUNDNESS FAILURE")
    print(f"kind={kind}")
    print(f"inputs={input_count} outputs={outputs} candidate=gate_index:{idx} SA{stuck_value}")
    print(f"status={status} expected_redundant={expected} affected_roots={affected}")
    print("gates:")
    for gate in gates:
        print(" ", gate)
    raise SystemExit(1)


def run_space(input_count, gate_count, output_count, max_output_sets, partition_sizes, budget):
    inputs = [2 * (idx + 1) for idx in range(input_count)]
    stats = {
        "circuits": 0,
        "output_sets": 0,
        "candidates": 0,
        "redundant": 0,
    }
    for gates in gate_lists(input_count, gate_count):
        stats["circuits"] += 1
        for outputs in output_sets(inputs, gates, output_count, max_output_sets):
            stats["output_sets"] += 1
            for idx in range(gate_count):
                for stuck_value in (0, 1):
                    ok, kind, status, expected, affected = check_case(
                        inputs, gates, outputs, idx, stuck_value, partition_sizes, budget
                    )
                    stats["candidates"] += 1
                    if expected:
                        stats["redundant"] += 1
                    if not ok:
                        fail(kind, input_count, gates, outputs, idx, stuck_value, status, expected, affected)
    return stats


def merge_stats(total, stats):
    for key, value in stats.items():
        total[key] = total.get(key, 0) + value


def parse_sizes(raw):
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


def main():
    parser = argparse.ArgumentParser(description="Bounded partitioned miter soundness checker.")
    parser.add_argument("--max-inputs", type=int, default=2)
    parser.add_argument("--max-gates", type=int, default=2)
    parser.add_argument("--output-count", type=int, default=2)
    parser.add_argument("--max-output-sets", type=int, default=32)
    parser.add_argument("--partition-sizes", default="1,2")
    parser.add_argument("--budget", type=int, default=0, help="0 means unlimited.")
    args = parser.parse_args()

    partition_sizes = parse_sizes(args.partition_sizes)
    total = {}
    started = time.time()
    print("Bounded partitioned miter soundness check")
    print(
        f"max_inputs={args.max_inputs} max_gates={args.max_gates} "
        f"output_count={args.output_count} partition_sizes={partition_sizes}"
    )

    for input_count in range(1, args.max_inputs + 1):
        for gate_count in range(1, args.max_gates + 1):
            stats = run_space(
                input_count,
                gate_count,
                args.output_count,
                args.max_output_sets,
                partition_sizes,
                args.budget,
            )
            merge_stats(total, stats)
            print(f"PASS inputs={input_count} gates={gate_count}: {stats}")

    print("\nPARTITIONED MITER SOUNDNESS PASS")
    print(f"elapsed={time.time() - started:.2f}s")
    for key in sorted(total):
        print(f"{key}={total[key]}")


if __name__ == "__main__":
    main()
