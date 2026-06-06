#!/usr/bin/env python3
"""Probe pre-SAT simulation rejection potential for Algorithm 10.

This is measurement-only. It does not accept redundancies and does not modify
the optimizer. It reuses Algorithm 10's existing rejection-only CEX simulation
primitive with deterministic PI/latch assignments.
"""

import argparse
import csv
import os
import random
import sys
import time

os.environ.setdefault("ALG10_CEX_PRUNING", "1")

from optimizer_alg10_tiered import (  # noqa: E402
    _candidate_order,
    _cex_prune_from_primary_values,
    _parse_latch,
)
from optimizer_alg8_hybrid import parse_aag, pure_python_forward_strash  # noqa: E402


def _load_circuit(path, pre_strash=True):
    M, I, L, O, A, inputs, latches, outputs, gates_raw, symbols = parse_aag(path)
    if not pre_strash:
        return M, I, L, O, A, inputs, latches, outputs, gates_raw, symbols

    result = pure_python_forward_strash(M, I, L, O, A, inputs, latches, outputs, gates_raw)
    M_f, I_f, L_f, O_f, A_f, in_f, la_f, out_f, gates_f = result
    return M_f, I_f, L_f, O_f, A_f, in_f, la_f, out_f, gates_f, symbols


def _primary_bases(inputs, latches):
    bases = [lit & ~1 for lit in inputs]
    bases.extend(_parse_latch(latch)[0] & ~1 for latch in latches)
    return bases


def _assignment_from_bits(bases, bits):
    return {base: bool(bit) for base, bit in zip(bases, bits)}


def _structured_patterns(bases, max_walk):
    n = len(bases)
    if n == 0:
        yield {}
        return

    yield _assignment_from_bits(bases, [0] * n)
    yield _assignment_from_bits(bases, [1] * n)
    yield _assignment_from_bits(bases, [(idx & 1) for idx in range(n)])
    yield _assignment_from_bits(bases, [((idx + 1) & 1) for idx in range(n)])

    walk_count = min(n, max(0, max_walk))
    for idx in range(walk_count):
        bits = [0] * n
        bits[idx] = 1
        yield _assignment_from_bits(bases, bits)

    for idx in range(walk_count):
        bits = [1] * n
        bits[idx] = 0
        yield _assignment_from_bits(bases, bits)


def _random_patterns(bases, count, seed):
    rng = random.Random(seed)
    n = len(bases)
    for _ in range(max(0, count)):
        yield {base: bool(rng.getrandbits(1)) for base in bases}


def _probe_one(path, args):
    t_start = time.time()
    M, I, L, O, A, inputs, latches, outputs, gates_raw, _ = _load_circuit(
        path, pre_strash=not args.no_pre_strash
    )
    roots = list(outputs)
    roots.extend(_parse_latch(latch)[1] for latch in latches)
    candidates = _candidate_order(gates_raw, roots=roots)
    primaries = _primary_bases(inputs, latches)
    pruned = set()
    accepted = {}
    checked_total = 0
    random_pruned = 0
    structured_pruned = 0
    patterns_used = 0
    deadline = time.time() + args.max_seconds if args.max_seconds > 0 else None

    pattern_stream = []
    for primary_values in _structured_patterns(primaries, args.walk_patterns):
        pattern_stream.append(("structured", primary_values))
    for primary_values in _random_patterns(primaries, args.random_patterns, args.seed):
        pattern_stream.append(("random", primary_values))

    for kind, primary_values in pattern_stream:
        if deadline is not None and time.time() >= deadline:
            break
        before = len(pruned)
        checked, newly_pruned = _cex_prune_from_primary_values(
            inputs,
            latches,
            roots,
            gates_raw,
            primary_values,
            accepted,
            candidates,
            pruned,
            telemetry=None,
            timings=None,
            deadline=deadline,
        )
        checked_total += checked
        patterns_used += 1
        if kind == "random":
            random_pruned += newly_pruned
        else:
            structured_pruned += newly_pruned
        if args.stop_when_stale > 0 and len(pruned) == before:
            args._stale_count += 1
            if args._stale_count >= args.stop_when_stale:
                break
        else:
            args._stale_count = 0
        if len(pruned) == len(candidates):
            break

    elapsed = time.time() - t_start
    total = len(candidates)
    rejected = len(pruned)
    unresolved_after_sim = total - rejected
    return {
        "Circuit": path,
        "Primaries": len(primaries),
        "Gates": len(gates_raw),
        "Candidates": total,
        "Patterns_Used": patterns_used,
        "Structured_Pruned": structured_pruned,
        "Random_Pruned": random_pruned,
        "PreSAT_Sim_Pruned": rejected,
        "PreSAT_Sim_Pruned_Pct": f"{(100.0 * rejected / total) if total else 0.0:.2f}",
        "Unresolved_After_PreSAT_Sim": unresolved_after_sim,
        "Checked_Total": checked_total,
        "Time_s": f"{elapsed:.3f}",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("circuits", nargs="+", help="AAG circuits to probe")
    parser.add_argument("--random-patterns", type=int, default=256)
    parser.add_argument("--walk-patterns", type=int, default=64)
    parser.add_argument("--seed", type=int, default=20260525)
    parser.add_argument("--max-seconds", type=float, default=0.0)
    parser.add_argument("--no-pre-strash", action="store_true")
    parser.add_argument("--stop-when-stale", type=int, default=0)
    parser.add_argument("--csv", default="")
    args = parser.parse_args(argv)

    rows = []
    for circuit in args.circuits:
        args._stale_count = 0
        rows.append(_probe_one(circuit, args))

    fieldnames = list(rows[0]) if rows else []
    if args.csv:
        with open(args.csv, "w", encoding="ascii", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
