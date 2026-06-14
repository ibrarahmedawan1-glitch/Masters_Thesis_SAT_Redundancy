#!/usr/bin/env python3
"""Compare Algorithm 10 pre-SAT simulation with packed pattern simulation.

This script is experiment-only.  It never accepts a redundancy and never
rewrites a circuit.  It checks whether a stronger packed simulation stage can
reject globally observable stuck-at candidates before they reach expensive SAT.
"""

import argparse
import csv
import json
import os
import random
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault("ALG10_PRE_SIM_REJECTION", "1")

import optimizer_alg10_tiered as alg10  # noqa: E402
from optimizer_alg8_hybrid import parse_aag  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parent

SUMMARY_FIELDS = [
    "Circuit",
    "Gate_Count",
    "Root_Count",
    "Candidate_Count",
    "Pattern_Count",
    "Packed_Prunes",
    "Scalar_Prunes",
    "Packed_Checked",
    "Scalar_Checked",
    "Packed_s",
    "Scalar_s",
    "Speedup_vs_Scalar",
    "Match_Scalar",
    "Packed_Only",
    "Scalar_Only",
    "Structured_Prunes",
    "Random_Prunes",
    "Max_Pack_Bits",
    "Batch_Candidates",
]


def resolve_path(path):
    path = Path(path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def collect_circuits(items):
    circuits = []
    seen = set()
    for item in items or []:
        path = resolve_path(item)
        if path.is_file() and path.suffix.lower() in {".aag", ".aig"}:
            candidates = [path]
        elif path.is_dir():
            candidates = sorted(
                child
                for child in path.rglob("*")
                if child.is_file() and child.suffix.lower() in {".aag", ".aig"}
            )
        else:
            candidates = []
        for candidate in candidates:
            key = candidate.resolve()
            if key not in seen:
                seen.add(key)
                circuits.append(candidate)
    return circuits


def load_checkpoint_candidates(path, frontier):
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

    result = []
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
        result.append(cand)
    return result, data.get("work_aag", "")


def observable_roots(outputs, latches):
    roots = list(outputs)
    roots.extend(alg10._parse_latch(latch)[1] for latch in latches)
    return roots


def pattern_stream(inputs, latches, walk_patterns, random_patterns, seed):
    bases = alg10._primary_bases(inputs, latches)
    n = len(bases)
    if n == 0:
        yield "structured", {}
        return

    def assignment(bits):
        return {base: bool(bit) for base, bit in zip(bases, bits)}

    yield "structured", assignment([0] * n)
    yield "structured", assignment([1] * n)
    yield "structured", assignment([idx & 1 for idx in range(n)])
    yield "structured", assignment([(idx + 1) & 1 for idx in range(n)])

    walk_count = min(n, max(0, walk_patterns))
    for idx in range(walk_count):
        bits = [0] * n
        bits[idx] = 1
        yield "structured", assignment(bits)
    for idx in range(walk_count):
        bits = [1] * n
        bits[idx] = 0
        yield "structured", assignment(bits)

    rng = random.Random(seed + n)
    for _ in range(max(0, random_patterns)):
        yield "random", {base: bool(rng.getrandbits(1)) for base in bases}


def limited_patterns(inputs, latches, args):
    patterns = list(
        pattern_stream(inputs, latches, args.walk_patterns, args.random_patterns, args.seed)
    )
    if args.pattern_limit > 0:
        patterns = patterns[: args.pattern_limit]
    return patterns


def candidate_pool(gates_raw, roots, args):
    if args.checkpoint_json:
        candidates, _work_aag = load_checkpoint_candidates(
            args.checkpoint_json, args.checkpoint_frontier
        )
        candidates = [
            cand
            for cand in candidates
            if 0 <= cand[0] < len(gates_raw) and cand[1] in args.stuck_values
        ]
    else:
        candidates = [
            cand
            for cand in alg10._candidate_order(gates_raw, roots=roots)
            if cand[1] in args.stuck_values
        ]
    if args.max_candidates > 0:
        candidates = candidates[: args.max_candidates]
    return candidates


def _pattern_lit_mask(aig_lit, primary_masks, gate_masks, by_lhs, full_mask):
    if aig_lit == 0:
        return 0
    if aig_lit == 1:
        return full_mask
    base = aig_lit & ~1
    idx = by_lhs.get(base)
    if idx is not None:
        mask = gate_masks[idx]
    else:
        mask = primary_masks.get(base, 0)
    return mask ^ full_mask if (aig_lit & 1) else mask


def _repeat_pattern_mask(mask, pattern_count, repeat_count):
    result = 0
    shift = 0
    for _ in range(repeat_count):
        result |= mask << shift
        shift += pattern_count
    return result


def _primary_pattern_masks(inputs, latches, patterns):
    bases = alg10._primary_bases(inputs, latches)
    masks = {base: 0 for base in bases}
    for bit, (_kind, primary_values) in enumerate(patterns):
        for base in bases:
            if primary_values.get(base, False):
                masks[base] |= 1 << bit
    return masks


def _good_root_pattern_masks(gates_raw, roots, accepted, primary_masks, by_lhs, pattern_mask):
    gate_masks = [0 for _ in gates_raw]
    for idx, (_lhs, r0, r1) in enumerate(gates_raw):
        if idx in accepted:
            mask = pattern_mask if accepted[idx] else 0
        else:
            mask = _pattern_lit_mask(r0, primary_masks, gate_masks, by_lhs, pattern_mask)
            mask &= _pattern_lit_mask(r1, primary_masks, gate_masks, by_lhs, pattern_mask)
        gate_masks[idx] = mask
    return [
        _pattern_lit_mask(root, primary_masks, gate_masks, by_lhs, pattern_mask)
        for root in roots
    ]


def packed_presim_prune(
    inputs,
    latches,
    roots,
    gates_raw,
    candidates,
    patterns,
    accepted=None,
    already_pruned=None,
    max_pack_bits=4096,
):
    """Return candidates rejected by concrete packed simulation patterns."""
    accepted = dict(accepted or {})
    already_pruned = set(already_pruned or set())
    candidates = [
        cand
        for cand in candidates
        if cand not in already_pruned and cand[0] not in accepted
    ]
    if not candidates or not patterns or not roots:
        return set(), {
            "checked": 0,
            "structured_pruned": 0,
            "random_pruned": 0,
            "batch_candidates": 0,
        }

    pattern_count = len(patterns)
    if pattern_count <= 0:
        return set(), {
            "checked": 0,
            "structured_pruned": 0,
            "random_pruned": 0,
            "batch_candidates": 0,
        }

    by_lhs = {lhs & ~1: idx for idx, (lhs, _, _) in enumerate(gates_raw)}
    pattern_mask = (1 << pattern_count) - 1
    primary_patterns = _primary_pattern_masks(inputs, latches, patterns)
    good_roots = _good_root_pattern_masks(
        gates_raw, roots, accepted, primary_patterns, by_lhs, pattern_mask
    )

    structured_mask = 0
    for bit, (kind, _primary_values) in enumerate(patterns):
        if kind == "structured":
            structured_mask |= 1 << bit
    random_mask = pattern_mask ^ structured_mask

    batch_candidates = max(1, max_pack_bits // pattern_count)
    pruned = set()
    structured_pruned = 0
    random_pruned = 0
    checked = 0

    for start in range(0, len(candidates), batch_candidates):
        batch = candidates[start : start + batch_candidates]
        batch_len = len(batch)
        full_mask = (1 << (batch_len * pattern_count)) - 1

        primary_masks = {
            base: _repeat_pattern_mask(mask, pattern_count, batch_len)
            for base, mask in primary_patterns.items()
        }
        good_batch_roots = [
            _repeat_pattern_mask(mask, pattern_count, batch_len)
            for mask in good_roots
        ]

        force_zero = {}
        force_one = {}
        for slot, (idx, stuck_value) in enumerate(batch):
            lane_mask = pattern_mask << (slot * pattern_count)
            if stuck_value == 0:
                force_zero[idx] = force_zero.get(idx, 0) | lane_mask
            else:
                force_one[idx] = force_one.get(idx, 0) | lane_mask

        gate_masks = [0 for _ in gates_raw]
        for idx, (_lhs, r0, r1) in enumerate(gates_raw):
            if idx in accepted:
                mask = full_mask if accepted[idx] else 0
            else:
                mask = _pattern_lit_mask(r0, primary_masks, gate_masks, by_lhs, full_mask)
                mask &= _pattern_lit_mask(r1, primary_masks, gate_masks, by_lhs, full_mask)
            if idx in force_zero:
                mask &= full_mask ^ force_zero[idx]
            if idx in force_one:
                mask |= force_one[idx]
            gate_masks[idx] = mask

        diff_mask = 0
        for root, good_mask in zip(roots, good_batch_roots):
            root_mask = _pattern_lit_mask(root, primary_masks, gate_masks, by_lhs, full_mask)
            diff_mask |= root_mask ^ good_mask

        checked += len(batch) * pattern_count
        for slot, cand in enumerate(batch):
            lane_diff = (diff_mask >> (slot * pattern_count)) & pattern_mask
            if lane_diff:
                pruned.add(cand)
                if lane_diff & structured_mask:
                    structured_pruned += 1
                elif lane_diff & random_mask:
                    random_pruned += 1

    return pruned, {
        "checked": checked,
        "structured_pruned": structured_pruned,
        "random_pruned": random_pruned,
        "batch_candidates": batch_candidates,
    }


def scalar_presim_prune(inputs, latches, roots, gates_raw, candidates, patterns):
    pruned = set()
    checked = 0
    started = time.time()
    for _kind, primary_values in patterns:
        c_checked, _newly_pruned = alg10._cex_prune_from_primary_values(
            inputs,
            latches,
            roots,
            gates_raw,
            primary_values,
            {},
            candidates,
            pruned,
            None,
            None,
            deadline=None,
        )
        checked += c_checked
    return pruned, checked, time.time() - started


def run_circuit(path, args):
    M, I, L, O, A, inputs, latches, outputs, gates_raw, _symbols = parse_aag(str(path))
    del M, I, L, O
    roots = observable_roots(outputs, latches)
    patterns = limited_patterns(inputs, latches, args)
    candidates = candidate_pool(gates_raw, roots, args)

    packed_started = time.time()
    packed_pruned, packed_stats = packed_presim_prune(
        inputs,
        latches,
        roots,
        gates_raw,
        candidates,
        patterns,
        max_pack_bits=args.max_pack_bits,
    )
    packed_s = time.time() - packed_started

    scalar_pruned = set()
    scalar_checked = 0
    scalar_s = 0.0
    if args.compare_scalar:
        scalar_pruned, scalar_checked, scalar_s = scalar_presim_prune(
            inputs, latches, roots, gates_raw, candidates, patterns
        )

    packed_only = sorted(packed_pruned - scalar_pruned) if args.compare_scalar else []
    scalar_only = sorted(scalar_pruned - packed_pruned) if args.compare_scalar else []
    match_scalar = not args.compare_scalar or (not packed_only and not scalar_only)
    speedup = (scalar_s / packed_s) if scalar_s > 0 and packed_s > 0 else 0.0

    print(
        f"  {path.name}: gates={A} roots={len(roots)} candidates={len(candidates)} "
        f"patterns={len(patterns)} packed_pruned={len(packed_pruned)} "
        f"scalar_pruned={len(scalar_pruned) if args.compare_scalar else 'NA'} "
        f"match={int(match_scalar)} packed={packed_s:.3f}s scalar={scalar_s:.3f}s"
    )

    return {
        "Circuit": path.name,
        "Gate_Count": A,
        "Root_Count": len(roots),
        "Candidate_Count": len(candidates),
        "Pattern_Count": len(patterns),
        "Packed_Prunes": len(packed_pruned),
        "Scalar_Prunes": len(scalar_pruned) if args.compare_scalar else "",
        "Packed_Checked": packed_stats["checked"],
        "Scalar_Checked": scalar_checked if args.compare_scalar else "",
        "Packed_s": f"{packed_s:.6f}",
        "Scalar_s": f"{scalar_s:.6f}" if args.compare_scalar else "",
        "Speedup_vs_Scalar": f"{speedup:.3f}" if args.compare_scalar else "",
        "Match_Scalar": int(match_scalar),
        "Packed_Only": len(packed_only),
        "Scalar_Only": len(scalar_only),
        "Structured_Prunes": packed_stats["structured_pruned"],
        "Random_Prunes": packed_stats["random_pruned"],
        "Max_Pack_Bits": args.max_pack_bits,
        "Batch_Candidates": packed_stats["batch_candidates"],
    }


def parse_int_set(raw):
    values = set()
    for part in str(raw).split(","):
        part = part.strip()
        if part:
            values.add(int(part))
    return values


def main():
    parser = argparse.ArgumentParser(description="Experiment with packed Alg10 pre-SAT simulation.")
    parser.add_argument("--circuits", nargs="*", default=None)
    parser.add_argument("--checkpoint-json", default="")
    parser.add_argument(
        "--checkpoint-frontier",
        choices=["all", "pending", "escalated", "candidates"],
        default="all",
    )
    parser.add_argument("--max-candidates", type=int, default=200)
    parser.add_argument("--walk-patterns", type=int, default=16)
    parser.add_argument("--random-patterns", type=int, default=64)
    parser.add_argument("--pattern-limit", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260609)
    parser.add_argument("--max-pack-bits", type=int, default=4096)
    parser.add_argument("--stuck-values", default="0,1")
    parser.add_argument("--compare-scalar", action="store_true")
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()

    args.stuck_values = parse_int_set(args.stuck_values)
    if not args.stuck_values or any(value not in {0, 1} for value in args.stuck_values):
        raise SystemExit("--stuck-values must contain 0, 1, or both")
    if args.max_pack_bits <= 0:
        raise SystemExit("--max-pack-bits must be positive")

    if args.checkpoint_json and not args.circuits:
        _candidates, work_aag = load_checkpoint_candidates(
            args.checkpoint_json, args.checkpoint_frontier
        )
        if work_aag:
            args.circuits = [work_aag]

    circuits = collect_circuits(args.circuits)
    if not circuits:
        raise SystemExit("no circuits found")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_dir = Path(args.output_dir) if args.output_dir else (
        REPO_ROOT / "results_optimized" / "alg10_presim_packing" / timestamp
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / f"alg10_presim_packing_summary_{timestamp}.csv"

    print("Alg10 packed pre-SAT simulation experiment")
    print(f"  circuits={len(circuits)}")
    print(f"  output_dir={output_dir}")

    rows = []
    for circuit in circuits:
        rows.append(run_circuit(circuit, args))

    with summary_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  summary={summary_path}")

    if any(row["Match_Scalar"] == 0 for row in rows):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
