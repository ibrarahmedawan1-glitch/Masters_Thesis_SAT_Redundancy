#!/usr/bin/env python3
"""Experiment-only pair stuck-at redundancy checks.

This script does not rewrite circuits and does not modify Algorithm 10.  It
uses the existing global configurable-fault miter and changes only the
assumption vector: exactly two new stuck-at controls are activated atomically.
"""

import argparse
import csv
import itertools
import json
import random
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pysat.solvers import Glucose4

import optimizer_alg10_tiered as alg10
from optimizer_alg8_hybrid import _build_fault_sweep_cnf, parse_aag


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_CIRCUITS = [
    "benchmarks/c17.aag",
    "benchmarks/c432.aag",
    "benchmarks/c880.aag",
]


DETAIL_FIELDS = [
    "Circuit",
    "Gate_Count",
    "Root_Count",
    "Pair_Index",
    "Gate1",
    "SA1",
    "Gate2",
    "SA2",
    "Affected_Roots1",
    "Affected_Roots2",
    "Affected_Roots_Union",
    "Single1_Result",
    "Single2_Result",
    "Pair_Result",
    "Pair_Class",
    "Pair_Sim_Result",
    "Pair_Sim_s",
    "Budget",
    "Pair_Solve_s",
    "Single_Solve_s",
    "Audit",
    "Note",
]

SUMMARY_FIELDS = [
    "Circuit",
    "Pairs_Tried",
    "Pair_UNSAT",
    "Pair_SAT",
    "Pair_TIMEOUT",
    "Pair_SIM_REJECT",
    "Pair_Only_UNSAT",
    "Pair_With_Single_UNSAT",
    "Pair_UNSAT_Unclassified",
    "Audit_Fail",
    "Single_UNSAT",
    "Single_SAT",
    "Single_TIMEOUT",
    "Total_Pair_Solve_s",
    "Total_Pair_Sim_s",
    "Total_Single_Solve_s",
]


@dataclass(frozen=True)
class Candidate:
    idx: int
    stuck_value: int


@dataclass
class SolveStats:
    status: str
    elapsed_s: float
    note: str = ""


def parse_int_list(raw):
    return [int(part.strip()) for part in str(raw).split(",") if part.strip()]


def resolve_path(path):
    path = Path(path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def collect_circuits(items):
    if not items:
        items = DEFAULT_CIRCUITS
    circuits = []
    seen = set()
    for item in items:
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
            continue
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
        candidate = Candidate(idx, stuck_value)
        if candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
    return result, data.get("work_aag", "")


def observable_roots(outputs, latches):
    roots = list(outputs)
    roots.extend(alg10._parse_latch(latch)[1] for latch in latches)
    return roots


def primary_bases(inputs, latches):
    bases = [lit & ~1 for lit in inputs]
    bases.extend(alg10._parse_latch(latch)[0] & ~1 for latch in latches)
    return bases


def simulation_patterns(inputs, latches, pattern_count, seed):
    bases = primary_bases(inputs, latches)
    if pattern_count <= 0 or not bases:
        return []

    patterns = []

    def add(bits):
        if len(patterns) < pattern_count:
            patterns.append({base: bool(bit) for base, bit in zip(bases, bits)})

    n = len(bases)
    add([0] * n)
    add([1] * n)
    add([idx & 1 for idx in range(n)])
    add([(idx + 1) & 1 for idx in range(n)])

    walk = min(n, max(0, pattern_count - len(patterns)) // 2)
    for idx in range(walk):
        bits = [0] * n
        bits[idx] = 1
        add(bits)
    for idx in range(walk):
        bits = [1] * n
        bits[idx] = 0
        add(bits)

    rng = random.Random(seed + len(bases) * 131 + pattern_count)
    while len(patterns) < pattern_count:
        add([rng.getrandbits(1) for _ in range(n)])
    return patterns


def build_sim_context(inputs, latches, roots, gates_raw, pattern_count, seed):
    patterns = simulation_patterns(inputs, latches, pattern_count, seed)
    if not patterns:
        return None

    bases = primary_bases(inputs, latches)
    full_mask = (1 << len(patterns)) - 1
    primary_masks = {}
    for base in bases:
        mask = 0
        for bit, pattern in enumerate(patterns):
            if pattern.get(base, False):
                mask |= 1 << bit
        primary_masks[base] = mask

    by_lhs = {lhs & ~1: idx for idx, (lhs, _, _) in enumerate(gates_raw)}
    good_roots = simulate_root_masks(gates_raw, roots, {}, primary_masks, by_lhs, full_mask)
    return {
        "patterns": len(patterns),
        "full_mask": full_mask,
        "primary_masks": primary_masks,
        "by_lhs": by_lhs,
        "good_roots": good_roots,
        "roots": roots,
    }


def lit_mask(aig_lit, primary_masks, gate_masks, by_lhs, full_mask):
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


def simulate_root_masks(gates_raw, roots, faults, primary_masks, by_lhs, full_mask):
    gate_masks = [0 for _ in gates_raw]
    for idx, (_, r0, r1) in enumerate(gates_raw):
        if idx in faults:
            mask = full_mask if faults[idx] else 0
        else:
            mask = lit_mask(r0, primary_masks, gate_masks, by_lhs, full_mask) & lit_mask(
                r1, primary_masks, gate_masks, by_lhs, full_mask
            )
        gate_masks[idx] = mask
    return tuple(lit_mask(root, primary_masks, gate_masks, by_lhs, full_mask) for root in roots)


def pair_simulation_reject(gates_raw, pair, sim_context):
    if sim_context is None:
        return False
    faults = {candidate.idx: candidate.stuck_value for candidate in pair}
    faulty_roots = simulate_root_masks(
        gates_raw,
        sim_context["roots"],
        faults,
        sim_context["primary_masks"],
        sim_context["by_lhs"],
        sim_context["full_mask"],
    )
    return any(
        good_mask != faulty_mask
        for good_mask, faulty_mask in zip(sim_context["good_roots"], faulty_roots)
    )


def _stuck_lits(idx, stuck_value, f0_lits, f1_lits):
    if stuck_value == 0:
        return f0_lits[idx], -f1_lits[idx]
    if stuck_value == 1:
        return -f0_lits[idx], f1_lits[idx]
    raise AssertionError(f"invalid stuck value {stuck_value}")


def _fault_map(pair, accepted=None):
    accepted = dict(accepted or {})
    result = dict(accepted)
    for candidate in pair:
        if candidate.idx in result and result[candidate.idx] != candidate.stuck_value:
            raise AssertionError(
                f"contradictory stuck values for gate {candidate.idx}: "
                f"{result[candidate.idx]} and {candidate.stuck_value}"
            )
        if candidate.idx in result:
            raise AssertionError(f"candidate gate {candidate.idx} already appears in context")
        result[candidate.idx] = candidate.stuck_value
    return result


def build_pair_assumptions(gate_count, f0_lits, f1_lits, pair, miter_lit, accepted=None):
    if len(pair) != 2:
        raise AssertionError(f"pair assumption builder needs exactly two candidates, got {len(pair)}")
    if pair[0].idx == pair[1].idx:
        raise AssertionError("pair candidates must target two distinct gates")

    fault_map = _fault_map(pair, accepted=accepted)
    assumptions = []
    for idx in range(gate_count):
        stuck_value = fault_map.get(idx)
        if stuck_value is None:
            assumptions.append(-f0_lits[idx])
        else:
            f0_assumption, _f1_assumption = _stuck_lits(idx, stuck_value, f0_lits, f1_lits)
            assumptions.append(f0_assumption)
    for idx in range(gate_count):
        stuck_value = fault_map.get(idx)
        if stuck_value is None:
            assumptions.append(-f1_lits[idx])
        else:
            _f0_assumption, f1_assumption = _stuck_lits(idx, stuck_value, f0_lits, f1_lits)
            assumptions.append(f1_assumption)
    assumptions.append(miter_lit)
    return assumptions


def audit_pair_assumptions(
    assumptions,
    gate_count,
    f0_lits,
    f1_lits,
    pair,
    miter_lit,
    accepted=None,
):
    if len(pair) != 2:
        raise AssertionError("pair audit requires exactly two candidates")
    if pair[0].idx == pair[1].idx:
        raise AssertionError("same-gate pair is invalid")
    for candidate in pair:
        if candidate.idx < 0 or candidate.idx >= gate_count:
            raise AssertionError(f"candidate gate {candidate.idx} is out of range")
        if candidate.stuck_value not in (0, 1):
            raise AssertionError(f"invalid stuck value {candidate.stuck_value}")

    expected_len = 2 * gate_count + 1
    if len(assumptions) != expected_len:
        raise AssertionError(f"pair assumption count {len(assumptions)} != {expected_len}")
    if assumptions[-1] != miter_lit:
        raise AssertionError("pair assumption vector must end with the output miter literal")

    seen = set()
    for lit in assumptions:
        if lit in seen:
            raise AssertionError(f"duplicate pair assumption literal {lit}")
        if -lit in seen:
            raise AssertionError(f"contradictory pair assumption literals {lit} and {-lit}")
        seen.add(lit)

    expected = build_pair_assumptions(
        gate_count, f0_lits, f1_lits, pair, miter_lit, accepted=accepted
    )
    if assumptions != expected:
        missing = sorted(set(expected) - set(assumptions), key=abs)
        extra = sorted(set(assumptions) - set(expected), key=abs)
        raise AssertionError(
            f"pair assumption content mismatch; missing={missing[:10]}, extra={extra[:10]}"
        )

    accepted = accepted or {}
    active_new = 0
    for candidate in pair:
        if candidate.idx not in accepted:
            active_new += 1
    if active_new != 2:
        raise AssertionError(f"expected exactly two active new candidate controls, got {active_new}")


def build_single_assumptions(gate_count, f0_lits, f1_lits, candidate, miter_lit):
    assumptions = [-lit for lit in f0_lits] + [-lit for lit in f1_lits]
    f0_assumption, f1_assumption = _stuck_lits(
        candidate.idx, candidate.stuck_value, f0_lits, f1_lits
    )
    assumptions[candidate.idx] = f0_assumption
    assumptions[gate_count + candidate.idx] = f1_assumption
    assumptions.append(miter_lit)
    alg10._audit_global_assumptions(
        assumptions,
        gate_count,
        f0_lits=f0_lits,
        f1_lits=f1_lits,
        candidate=(candidate.idx, candidate.stuck_value),
        accepted={},
        miter_lit=miter_lit,
    )
    return assumptions


def solve_assumptions(solver, assumptions, budget):
    started = time.time()
    if budget > 0:
        solver.conf_budget(budget)
        raw = solver.solve_limited(assumptions=assumptions)
    else:
        raw = solver.solve(assumptions=assumptions)
    elapsed = time.time() - started
    if raw is None:
        return SolveStats("TIMEOUT", elapsed)
    if raw is False:
        return SolveStats("UNSAT", elapsed)
    return SolveStats("SAT", elapsed)


def pair_class(pair_result, single1_result, single2_result):
    if pair_result == "UNSAT":
        single_statuses = {single1_result, single2_result}
        if not single_statuses <= {"SAT", "UNSAT"}:
            return "PAIR_UNSAT_UNCLASSIFIED"
        if "UNSAT" in single_statuses:
            return "PAIR_WITH_SINGLE_UNSAT"
        return "PAIR_ONLY_UNSAT"
    if pair_result == "SAT":
        return "NONREDUNDANT_PAIR"
    if pair_result == "TIMEOUT":
        return "PAIR_TIMEOUT"
    if pair_result == "SIM_REJECT":
        return "SIM_REJECT"
    return "PAIR_ERROR"


def candidate_pool(gates_raw, roots, args):
    if args.checkpoint_json:
        candidates, _work_aag = load_checkpoint_candidates(
            args.checkpoint_json, args.checkpoint_frontier
        )
        candidates = [
            candidate
            for candidate in candidates
            if 0 <= candidate.idx < len(gates_raw) and candidate.stuck_value in args.stuck_values
        ]
    else:
        candidates = [
            Candidate(idx, stuck_value)
            for idx, stuck_value in alg10._candidate_order(gates_raw, roots=roots)
            if stuck_value in args.stuck_values
        ]
    if args.max_candidates > 0:
        candidates = candidates[: args.max_candidates]
    return candidates


def affected_sets(gates_raw, roots, candidates):
    if not roots:
        return {}
    by_lhs, fanout = alg10._fanout_graph(gates_raw)
    result = {}
    for candidate in candidates:
        affected = alg10._affected_roots_from_graph(by_lhs, fanout, roots, candidate.idx)
        result[candidate] = frozenset(affected)
    return result


def pair_iter(candidates, affected, args):
    yielded = 0
    for left, right in itertools.combinations(candidates, 2):
        if left.idx == right.idx:
            continue
        if args.min_affected_roots > 0:
            if len(affected.get(left, ())) < args.min_affected_roots:
                continue
            if len(affected.get(right, ())) < args.min_affected_roots:
                continue
        if args.pair_filter == "same_roots" and affected.get(left) != affected.get(right):
            continue
        if args.pair_filter == "overlap_roots" and not (
            affected.get(left, frozenset()) & affected.get(right, frozenset())
        ):
            continue
        yield left, right
        yielded += 1
        if args.max_pairs > 0 and yielded >= args.max_pairs:
            return


def update_summary(summary, row):
    summary["Pairs_Tried"] += 1
    summary[f"Pair_{row['Pair_Result']}"] += 1
    class_key = {
        "PAIR_ONLY_UNSAT": "Pair_Only_UNSAT",
        "PAIR_WITH_SINGLE_UNSAT": "Pair_With_Single_UNSAT",
        "PAIR_UNSAT_UNCLASSIFIED": "Pair_UNSAT_Unclassified",
    }.get(row["Pair_Class"])
    if class_key:
        summary[class_key] += 1
    if row["Audit"] != "PASS":
        summary["Audit_Fail"] += 1
    for key in ("Single1_Result", "Single2_Result"):
        status = row[key]
        if status in {"UNSAT", "SAT", "TIMEOUT"}:
            summary[f"Single_{status}"] += 1
    summary["Total_Pair_Solve_s"] += float(row["Pair_Solve_s"])
    summary["Total_Pair_Sim_s"] += float(row["Pair_Sim_s"])
    summary["Total_Single_Solve_s"] += float(row["Single_Solve_s"])


def run_circuit(path, args, detail_writer):
    M, I, L, O, A, inputs, latches, outputs, gates_raw, _symbols = parse_aag(str(path))
    del M, I, L, O
    roots = observable_roots(outputs, latches)
    if not roots or A == 0:
        return None

    started = time.time()
    encode_started = time.time()
    clauses, miter_lit, f0_lits, f1_lits = _build_fault_sweep_cnf(
        inputs, latches, roots, gates_raw
    )
    encode_s = time.time() - encode_started
    candidates = candidate_pool(gates_raw, roots, args)
    affected = affected_sets(gates_raw, roots, candidates)
    sim_context = build_sim_context(
        inputs, latches, roots, gates_raw, args.sim_patterns, args.sim_seed
    )
    summary = Counter()
    summary["Circuit"] = path.name
    single_cache = {}
    pair_index = 0
    print(
        f"  {path.name}: gates={A} roots={len(roots)} candidates={len(candidates)} "
        f"budget={args.budget} sim_patterns={args.sim_patterns} "
        f"filter={args.pair_filter} encode={encode_s:.2f}s"
    )

    with Glucose4(bootstrap_with=clauses) as solver:
        for left, right in pair_iter(candidates, affected, args):
            if args.seconds > 0 and time.time() - started >= args.seconds:
                break
            pair_index += 1
            pair = (left, right)
            audit = "PASS"
            note = ""
            try:
                assumptions = build_pair_assumptions(
                    A, f0_lits, f1_lits, pair, miter_lit, accepted={}
                )
                audit_pair_assumptions(
                    assumptions, A, f0_lits, f1_lits, pair, miter_lit, accepted={}
                )
            except AssertionError as exc:
                audit = "FAIL"
                note = str(exc)[:200]
                pair_stats = SolveStats("ERROR", 0.0, note=note)
            else:
                sim_started = time.time()
                sim_rejected = pair_simulation_reject(gates_raw, pair, sim_context)
                sim_elapsed = time.time() - sim_started
                if sim_rejected:
                    pair_stats = SolveStats("SIM_REJECT", 0.0)
                else:
                    pair_stats = solve_assumptions(solver, assumptions, args.budget)

            if audit != "PASS":
                sim_elapsed = 0.0
                sim_rejected = False

            single_elapsed = 0.0
            single_results = []
            should_solve_singles = (
                pair_stats.status == "UNSAT"
                or (args.solve_singles and pair_stats.status != "SIM_REJECT")
            )
            if should_solve_singles:
                for candidate in pair:
                    stats = single_cache.get(candidate)
                    if stats is None:
                        single_assumptions = build_single_assumptions(
                            A, f0_lits, f1_lits, candidate, miter_lit
                        )
                        stats = solve_assumptions(solver, single_assumptions, args.budget)
                        single_cache[candidate] = stats
                    single_elapsed += stats.elapsed_s
                    single_results.append(stats.status)
            else:
                single_results = ["NOT_RUN", "NOT_RUN"]

            row = {
                "Circuit": path.name,
                "Gate_Count": A,
                "Root_Count": len(roots),
                "Pair_Index": pair_index,
                "Gate1": left.idx,
                "SA1": left.stuck_value,
                "Gate2": right.idx,
                "SA2": right.stuck_value,
                "Affected_Roots1": len(affected.get(left, ())),
                "Affected_Roots2": len(affected.get(right, ())),
                "Affected_Roots_Union": len(affected.get(left, frozenset()) | affected.get(right, frozenset())),
                "Single1_Result": single_results[0],
                "Single2_Result": single_results[1],
                "Pair_Result": pair_stats.status,
                "Pair_Class": pair_class(pair_stats.status, single_results[0], single_results[1]),
                "Pair_Sim_Result": "REJECT" if sim_rejected else "PASS",
                "Pair_Sim_s": f"{sim_elapsed:.6f}",
                "Budget": args.budget,
                "Pair_Solve_s": f"{pair_stats.elapsed_s:.6f}",
                "Single_Solve_s": f"{single_elapsed:.6f}",
                "Audit": audit,
                "Note": note or pair_stats.note,
            }
            detail_writer.writerow(row)
            update_summary(summary, row)

            if args.stop_after_pair_only and row["Pair_Class"] == "PAIR_ONLY_UNSAT":
                break

    print(
        f"    pairs={summary['Pairs_Tried']} pair_unsat={summary['Pair_UNSAT']} "
        f"pair_only={summary['Pair_Only_UNSAT']} sim_reject={summary['Pair_SIM_REJECT']} "
        f"timeouts={summary['Pair_TIMEOUT']}"
    )
    return summary


def write_summary(path, summaries):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for summary in summaries:
            row = {field: summary.get(field, 0) for field in SUMMARY_FIELDS}
            row["Circuit"] = summary.get("Circuit", "")
            row["Total_Pair_Solve_s"] = f"{summary.get('Total_Pair_Solve_s', 0.0):.6f}"
            row["Total_Pair_Sim_s"] = f"{summary.get('Total_Pair_Sim_s', 0.0):.6f}"
            row["Total_Single_Solve_s"] = f"{summary.get('Total_Single_Solve_s', 0.0):.6f}"
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description="Experiment-only pair stuck-at miter runner.")
    parser.add_argument("--circuits", nargs="*", default=None)
    parser.add_argument("--budget", type=int, default=5000, help="0 means unlimited.")
    parser.add_argument("--seconds", type=float, default=30.0, help="Per-circuit wall cap.")
    parser.add_argument("--max-candidates", type=int, default=80)
    parser.add_argument("--max-pairs", type=int, default=500)
    parser.add_argument("--min-affected-roots", type=int, default=1)
    parser.add_argument("--pair-filter", choices=["all", "same_roots", "overlap_roots"], default="all")
    parser.add_argument("--sim-patterns", type=int, default=32)
    parser.add_argument("--sim-seed", type=int, default=20260609)
    parser.add_argument("--solve-singles", action="store_true")
    parser.add_argument("--stuck-values", default="0,1")
    parser.add_argument("--checkpoint-json", default="")
    parser.add_argument(
        "--checkpoint-frontier",
        choices=["all", "pending", "escalated", "candidates"],
        default="all",
    )
    parser.add_argument("--stop-after-pair-only", action="store_true")
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()
    args.stuck_values = set(parse_int_list(args.stuck_values))
    if not args.stuck_values or any(value not in {0, 1} for value in args.stuck_values):
        raise SystemExit("--stuck-values must contain 0, 1, or both")

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
        REPO_ROOT / "results_optimized" / "pair_stuckat_experiments" / timestamp
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    detail_path = output_dir / f"pair_stuckat_detail_{timestamp}.csv"
    summary_path = output_dir / f"pair_stuckat_summary_{timestamp}.csv"

    print("Pair stuck-at experiment")
    print(f"  circuits={len(circuits)}")
    print(f"  output_dir={output_dir}")

    summaries = []
    with detail_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DETAIL_FIELDS)
        writer.writeheader()
        for circuit in circuits:
            summary = run_circuit(circuit, args, writer)
            if summary is not None:
                summaries.append(summary)
            f.flush()

    write_summary(summary_path, summaries)
    print(f"  detail={detail_path}")
    print(f"  summary={summary_path}")

    audit_failures = sum(summary.get("Audit_Fail", 0) for summary in summaries)
    if audit_failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
