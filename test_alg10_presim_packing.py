#!/usr/bin/env python3
"""Bounded checks for packed Alg10 pre-SAT simulation pruning."""

import argparse
import itertools
import time

from alg10_presim_packing_experiment import packed_presim_prune
from test_encoding_soundness_bounded import gate_lists, output_literals, simulate


def all_patterns(inputs):
    bases = [lit & ~1 for lit in inputs]
    patterns = []
    for mask in range(1 << len(bases)):
        values = {
            base: bool((mask >> bit) & 1)
            for bit, base in enumerate(bases)
        }
        patterns.append(("truth", values))
    return patterns


def candidate_list(gate_count):
    return [(idx, stuck_value) for idx in range(gate_count) for stuck_value in (0, 1)]


def truth_observable(inputs, gates, outputs, candidate):
    idx, stuck_value = candidate
    for mask in range(1 << len(inputs)):
        assignment = [(mask >> bit) & 1 for bit in range(len(inputs))]
        good, _ = simulate(inputs, gates, outputs, assignment)
        faulty, _ = simulate(inputs, gates, outputs, assignment, faults={idx: stuck_value})
        if good != faulty:
            return True
    return False


def output_sets(inputs, gates, output_count, max_sets):
    literals = output_literals(inputs, gates, "all")
    count = min(output_count, len(literals))
    yielded = 0
    for combo in itertools.combinations(literals, count):
        yield list(combo)
        yielded += 1
        if max_sets > 0 and yielded >= max_sets:
            break


def fail(kind, inputs, gates, outputs, candidate, expected, observed):
    print("\nPACKED PRE-SIM SOUNDNESS FAILURE")
    print(f"kind={kind}")
    print(f"inputs={len(inputs)} outputs={outputs}")
    print(f"candidate={candidate}")
    print(f"expected={expected} observed={observed}")
    print("gates:")
    for gate in gates:
        print(" ", gate)
    raise SystemExit(1)


def run_space(input_count, gate_count, output_count, max_output_sets, max_pack_bits):
    inputs = [2 * (idx + 1) for idx in range(input_count)]
    patterns = all_patterns(inputs)
    stats = {
        "circuits": 0,
        "output_sets": 0,
        "candidates": 0,
        "observable": 0,
        "packed_pruned": 0,
    }
    for gates in gate_lists(input_count, gate_count):
        stats["circuits"] += 1
        candidates = candidate_list(gate_count)
        for outputs in output_sets(inputs, gates, output_count, max_output_sets):
            stats["output_sets"] += 1
            pruned, _packed_stats = packed_presim_prune(
                inputs,
                [],
                outputs,
                gates,
                candidates,
                patterns,
                max_pack_bits=max_pack_bits,
            )
            for candidate in candidates:
                expected = truth_observable(inputs, gates, outputs, candidate)
                observed = candidate in pruned
                stats["candidates"] += 1
                if expected:
                    stats["observable"] += 1
                if observed:
                    stats["packed_pruned"] += 1
                if observed and not expected:
                    fail("false_rejection", inputs, gates, outputs, candidate, expected, observed)
                if expected and not observed:
                    fail("missed_full_truth_pattern", inputs, gates, outputs, candidate, expected, observed)
    return stats


def merge_stats(total, stats):
    for key, value in stats.items():
        total[key] = total.get(key, 0) + value


def main():
    parser = argparse.ArgumentParser(description="Bounded packed pre-sim soundness checker.")
    parser.add_argument("--max-inputs", type=int, default=2)
    parser.add_argument("--max-gates", type=int, default=2)
    parser.add_argument("--output-count", type=int, default=2)
    parser.add_argument("--max-output-sets", type=int, default=24)
    parser.add_argument("--max-pack-bits", type=int, default=128)
    args = parser.parse_args()

    started = time.time()
    total = {}
    print("Bounded packed pre-SAT simulation check")
    print(
        f"max_inputs={args.max_inputs} max_gates={args.max_gates} "
        f"output_count={args.output_count}"
    )
    for input_count in range(1, args.max_inputs + 1):
        for gate_count in range(1, args.max_gates + 1):
            stats = run_space(
                input_count,
                gate_count,
                args.output_count,
                args.max_output_sets,
                args.max_pack_bits,
            )
            merge_stats(total, stats)
            print(f"PASS inputs={input_count} gates={gate_count}: {stats}")

    print("\nPACKED PRE-SIM SOUNDNESS PASS")
    print(f"elapsed={time.time() - started:.2f}s")
    for key in sorted(total):
        print(f"{key}={total[key]}")


if __name__ == "__main__":
    main()
