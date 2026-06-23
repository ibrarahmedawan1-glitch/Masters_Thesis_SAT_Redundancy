#!/usr/bin/env python3
"""Read-only exact SAT strategy and persistent-budget experiment.

The runner evaluates exact candidate-local encodings on one frozen circuit
generation. It never rewrites the circuit. Each encoding is measured once per
candidate and solver-state mode; all requested portfolio orders are then
replayed from those measurements with stop-on-first-resolution semantics.
"""

import argparse
import csv
import itertools
import json
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pysat.solvers import Solver

import optimizer_alg10_tiered as alg10
from optimizer_alg8_hybrid import parse_aag
from partitioned_miter_experiment import (
    audit_partitions,
    load_checkpoint_frontier,
    observable_roots,
    partition_roots,
    resolve_path,
)


REPO_ROOT = Path(__file__).resolve().parent
SUPPORTED_STRATEGIES = ("tfo", "partition_tfo", "cone", "partition_cone")
SUPPORTED_MODES = ("fresh", "persistent")

STRATEGY_FIELDS = [
    "Circuit",
    "Candidate_Position",
    "Gate",
    "SA",
    "Mode",
    "Strategy",
    "Measurement_Position",
    "Status",
    "Affected_Roots",
    "Groups",
    "Good_Cone_Gates",
    "Faulty_TFO_Gates",
    "Clauses",
    "Encode_s",
    "Solve_s",
    "Total_s",
    "Conflicts",
    "Solver_Instances",
    "Attempts",
    "Note",
]

PORTFOLIO_FIELDS = [
    "Circuit",
    "Candidate_Position",
    "Gate",
    "SA",
    "Mode",
    "Order",
    "Status",
    "Winner",
    "Strategies_Used",
    "Encode_s",
    "Solve_s",
    "Total_s",
    "Conflicts",
    "Solver_Instances",
]

SUMMARY_FIELDS = [
    "Circuit",
    "Mode",
    "Order",
    "Candidates",
    "Resolved",
    "SAT",
    "UNSAT",
    "TIMEOUT",
    "ERROR",
    "Total_s",
    "Mean_s",
    "Conflicts",
    "Solver_Instances",
    "Winner_Counts",
]


@dataclass
class EncodedProblem:
    clauses: list
    miter_lit: int
    good_cone_gates: int
    faulty_tfo_gates: int = 0


@dataclass
class LadderResult:
    status: str
    solve_s: float = 0.0
    conflicts: int = 0
    solver_instances: int = 0
    attempts: list = field(default_factory=list)
    note: str = ""


@dataclass
class StrategyResult:
    strategy: str
    mode: str
    status: str
    affected_roots: int = 0
    groups: int = 0
    good_cone_gates: int = 0
    faulty_tfo_gates: int = 0
    clauses: int = 0
    encode_s: float = 0.0
    solve_s: float = 0.0
    conflicts: int = 0
    solver_instances: int = 0
    attempts: list = field(default_factory=list)
    note: str = ""

    @property
    def total_s(self):
        return self.encode_s + self.solve_s


def parse_csv_ints(raw):
    return [int(part.strip()) for part in str(raw).split(",") if part.strip()]


def parse_csv_words(raw):
    return [part.strip().lower() for part in str(raw).split(",") if part.strip()]


def result_family(status):
    for family in ("SAT", "UNSAT", "TIMEOUT", "ERROR"):
        if status.startswith(family):
            return family
    return status


def _conflicts(solver):
    try:
        return int(solver.accum_stats().get("conflicts", 0))
    except Exception:
        return 0


def _raw_status(raw):
    if raw is None:
        return "TIMEOUT"
    return "SAT" if raw else "UNSAT"


def solve_budget_ladder(clauses, miter_lit, solver_name, budgets, persistent):
    """Solve at increasing conflict targets, optionally retaining one solver.

    CaDiCaL and the other PySAT budget APIs apply a relative conflict allowance
    to each call. In persistent mode the granted allowance is therefore the
    remaining distance to the next cumulative target.
    """

    attempts = []
    total_s = 0.0
    total_conflicts = 0
    instances = 0

    def solve_once(solver, target, granted, conflict_base, cumulative_before):
        nonlocal total_s
        if granted <= 0:
            attempts.append(
                {
                    "target": target,
                    "granted": 0,
                    "status": "TIMEOUT",
                    "seconds": 0.0,
                    "conflicts_delta": 0,
                    "conflicts_total": cumulative_before,
                }
            )
            return "TIMEOUT", 0

        before = _conflicts(solver)
        started = time.perf_counter()
        solver.conf_budget(granted)
        raw = solver.solve_limited(assumptions=[miter_lit])
        elapsed = time.perf_counter() - started
        after = _conflicts(solver)
        delta = max(0, after - before)
        status = _raw_status(raw)
        total_s += elapsed
        attempts.append(
            {
                "target": target,
                "granted": granted,
                "status": status,
                "seconds": round(elapsed, 9),
                "conflicts_delta": delta,
                "conflicts_total": max(0, after - conflict_base)
                if conflict_base is not None
                else cumulative_before + delta,
            }
        )
        return status, delta

    try:
        if persistent:
            bootstrap_started = time.perf_counter()
            with Solver(name=solver_name, bootstrap_with=clauses) as solver:
                total_s += time.perf_counter() - bootstrap_started
                instances = 1
                conflict_base = _conflicts(solver)
                for target in budgets:
                    consumed = max(0, _conflicts(solver) - conflict_base)
                    status, delta = solve_once(
                        solver,
                        target,
                        max(0, target - consumed),
                        conflict_base,
                        consumed,
                    )
                    total_conflicts += delta
                    if status in {"SAT", "UNSAT"}:
                        return LadderResult(
                            status,
                            total_s,
                            total_conflicts,
                            instances,
                            attempts,
                        )
        else:
            for target in budgets:
                bootstrap_started = time.perf_counter()
                with Solver(name=solver_name, bootstrap_with=clauses) as solver:
                    total_s += time.perf_counter() - bootstrap_started
                    instances += 1
                    status, delta = solve_once(
                        solver,
                        target,
                        target,
                        None,
                        total_conflicts,
                    )
                total_conflicts += delta
                if status in {"SAT", "UNSAT"}:
                    return LadderResult(
                        status,
                        total_s,
                        total_conflicts,
                        instances,
                        attempts,
                    )
    except Exception as exc:
        return LadderResult(
            "ERROR_SOLVE",
            total_s,
            total_conflicts,
            instances,
            attempts,
            str(exc)[:300],
        )

    return LadderResult(
        "TIMEOUT",
        total_s,
        total_conflicts,
        instances,
        attempts,
    )


def build_problem(
    strategy,
    inputs,
    latches,
    roots,
    gates_raw,
    target_idx,
    stuck_value,
    by_lhs,
    fanout,
):
    good_cone = alg10._fanin_indices_for_roots(
        gates_raw,
        roots,
        by_lhs=by_lhs,
    )
    if target_idx not in good_cone:
        raise AssertionError("target is outside its affected observable cone")

    if strategy in {"tfo", "partition_tfo"}:
        tfo_slice = alg10._observable_tfo_slice(fanout, target_idx, good_cone)
        alg10._audit_tfo_slice(
            by_lhs,
            fanout,
            roots,
            target_idx,
            good_cone,
            tfo_slice,
            gates_raw,
        )
        clauses, miter_lit, _shared = alg10._build_single_fault_tfo_miter(
            inputs,
            latches,
            roots,
            gates_raw,
            target_idx,
            stuck_value,
            good_cone,
            tfo_slice,
        )
        return EncodedProblem(
            clauses,
            miter_lit,
            len(good_cone),
            len(tfo_slice),
        )

    clauses, miter_lit, _shared = alg10._build_single_fault_cone_miter(
        inputs,
        latches,
        roots,
        gates_raw,
        target_idx,
        stuck_value,
        good_cone,
    )
    return EncodedProblem(clauses, miter_lit, len(good_cone))


def evaluate_strategy(
    strategy,
    mode,
    inputs,
    latches,
    affected_roots,
    gates_raw,
    target_idx,
    stuck_value,
    by_lhs,
    fanout,
    budgets,
    partition_size,
    solver_name,
):
    result = StrategyResult(
        strategy=strategy,
        mode=mode,
        status="TIMEOUT",
        affected_roots=len(affected_roots),
    )
    if not affected_roots:
        result.status = "UNSAT_NO_AFFECTED_ROOTS"
        return result

    if strategy.startswith("partition_"):
        groups = partition_roots(affected_roots, partition_size)
        audit_partitions(affected_roots, groups)
    else:
        groups = [list(affected_roots)]
    result.groups = len(groups)

    saw_timeout = False
    for group_pos, roots in enumerate(groups):
        encode_started = time.perf_counter()
        try:
            problem = build_problem(
                strategy,
                inputs,
                latches,
                roots,
                gates_raw,
                target_idx,
                stuck_value,
                by_lhs,
                fanout,
            )
        except Exception as exc:
            result.encode_s += time.perf_counter() - encode_started
            result.status = "ERROR_ENCODE"
            result.note = str(exc)[:300]
            return result
        result.encode_s += time.perf_counter() - encode_started
        result.good_cone_gates += problem.good_cone_gates
        result.faulty_tfo_gates += problem.faulty_tfo_gates
        result.clauses += len(problem.clauses)

        ladder = solve_budget_ladder(
            problem.clauses,
            problem.miter_lit,
            solver_name,
            budgets,
            persistent=(mode == "persistent"),
        )
        result.solve_s += ladder.solve_s
        result.conflicts += ladder.conflicts
        result.solver_instances += ladder.solver_instances
        result.attempts.extend(
            {"group": group_pos, **attempt} for attempt in ladder.attempts
        )
        family = result_family(ladder.status)
        if family == "SAT":
            result.status = "SAT"
            return result
        if family == "UNSAT":
            continue
        if family == "TIMEOUT":
            saw_timeout = True
            continue
        result.status = ladder.status
        result.note = ladder.note
        return result

    result.status = "TIMEOUT" if saw_timeout else "UNSAT"
    return result


def parse_orders(raw, strategies):
    if raw.strip().lower() == "all":
        return list(itertools.permutations(strategies))

    orders = []
    for item in raw.split(";"):
        order = tuple(part.strip().lower() for part in item.split(">") if part.strip())
        if not order:
            continue
        if len(order) != len(strategies) or set(order) != set(strategies):
            raise ValueError(
                "each custom order must contain every configured strategy exactly once"
            )
        if order not in orders:
            orders.append(order)
    if not orders:
        raise ValueError("no portfolio orders configured")
    return orders


def replay_order(order, measured):
    encode_s = 0.0
    solve_s = 0.0
    conflicts = 0
    instances = 0
    used = []
    status = "TIMEOUT"
    winner = ""

    for strategy in order:
        result = measured[strategy]
        used.append(strategy)
        encode_s += result.encode_s
        solve_s += result.solve_s
        conflicts += result.conflicts
        instances += result.solver_instances
        family = result_family(result.status)
        if family in {"SAT", "UNSAT"}:
            status = family
            winner = strategy
            break
        if family == "ERROR":
            status = result.status
            winner = strategy
            break

    return {
        "Status": status,
        "Winner": winner,
        "Strategies_Used": len(used),
        "Encode_s": encode_s,
        "Solve_s": solve_s,
        "Total_s": encode_s + solve_s,
        "Conflicts": conflicts,
        "Solver_Instances": instances,
    }


def _strategy_row(
    circuit,
    candidate_pos,
    idx,
    stuck_value,
    measurement_pos,
    result,
):
    return {
        "Circuit": circuit,
        "Candidate_Position": candidate_pos,
        "Gate": idx,
        "SA": stuck_value,
        "Mode": result.mode,
        "Strategy": result.strategy,
        "Measurement_Position": measurement_pos,
        "Status": result.status,
        "Affected_Roots": result.affected_roots,
        "Groups": result.groups,
        "Good_Cone_Gates": result.good_cone_gates,
        "Faulty_TFO_Gates": result.faulty_tfo_gates,
        "Clauses": result.clauses,
        "Encode_s": f"{result.encode_s:.9f}",
        "Solve_s": f"{result.solve_s:.9f}",
        "Total_s": f"{result.total_s:.9f}",
        "Conflicts": result.conflicts,
        "Solver_Instances": result.solver_instances,
        "Attempts": json.dumps(result.attempts, separators=(",", ":")),
        "Note": result.note,
    }


def _portfolio_row(circuit, candidate_pos, idx, stuck_value, mode, order, replay):
    return {
        "Circuit": circuit,
        "Candidate_Position": candidate_pos,
        "Gate": idx,
        "SA": stuck_value,
        "Mode": mode,
        "Order": ">".join(order),
        "Status": replay["Status"],
        "Winner": replay["Winner"],
        "Strategies_Used": replay["Strategies_Used"],
        "Encode_s": f"{replay['Encode_s']:.9f}",
        "Solve_s": f"{replay['Solve_s']:.9f}",
        "Total_s": f"{replay['Total_s']:.9f}",
        "Conflicts": replay["Conflicts"],
        "Solver_Instances": replay["Solver_Instances"],
    }


def update_summary(summary, row):
    key = (row["Circuit"], row["Mode"], row["Order"])
    item = summary.setdefault(
        key,
        {
            "Circuit": row["Circuit"],
            "Mode": row["Mode"],
            "Order": row["Order"],
            "Candidates": 0,
            "Resolved": 0,
            "SAT": 0,
            "UNSAT": 0,
            "TIMEOUT": 0,
            "ERROR": 0,
            "Total_s": 0.0,
            "Conflicts": 0,
            "Solver_Instances": 0,
            "Winner_Counts": Counter(),
        },
    )
    item["Candidates"] += 1
    family = result_family(row["Status"])
    if family in {"SAT", "UNSAT"}:
        item["Resolved"] += 1
    if family in item:
        item[family] += 1
    else:
        item["ERROR"] += 1
    item["Total_s"] += float(row["Total_s"])
    item["Conflicts"] += int(row["Conflicts"])
    item["Solver_Instances"] += int(row["Solver_Instances"])
    if row["Winner"]:
        item["Winner_Counts"][row["Winner"]] += 1


def write_summary(path, summary):
    rows = []
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for key in sorted(summary):
            item = dict(summary[key])
            candidates = item["Candidates"]
            item["Mean_s"] = item["Total_s"] / candidates if candidates else 0.0
            item["Total_s"] = f"{item['Total_s']:.9f}"
            item["Mean_s"] = f"{item['Mean_s']:.9f}"
            item["Winner_Counts"] = json.dumps(
                dict(sorted(item["Winner_Counts"].items())),
                separators=(",", ":"),
            )
            writer.writerow(item)
            rows.append(item)
    return rows


def validate_resolved_agreement(results, candidate):
    resolved = {
        result_family(result.status)
        for result in results
        if result_family(result.status) in {"SAT", "UNSAT"}
    }
    if len(resolved) > 1:
        detail = ", ".join(
            f"{result.mode}/{result.strategy}={result.status}" for result in results
        )
        raise AssertionError(
            f"exact encoding disagreement for candidate {candidate}: {detail}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Compare exact encoding order and persistent SAT budgets."
    )
    parser.add_argument("--circuit", default="")
    parser.add_argument("--checkpoint-json", default="")
    parser.add_argument(
        "--checkpoint-frontier",
        choices=["all", "pending", "escalated"],
        default="all",
    )
    parser.add_argument(
        "--candidate-order",
        choices=[
            "current",
            "reverse",
            "proof_cost",
            "proof_cost_untried",
            "proof_reverse_portfolio",
            "history_desc",
        ],
        default="proof_reverse_portfolio",
    )
    parser.add_argument(
        "--strategies",
        default="tfo,partition_tfo,cone",
        help="Comma-separated exact encodings.",
    )
    parser.add_argument(
        "--modes",
        default="fresh,persistent",
        help="Comma-separated solver-state modes.",
    )
    parser.add_argument(
        "--orders",
        default="all",
        help="'all' or semicolon-separated orders such as tfo>partition_tfo>cone.",
    )
    parser.add_argument("--budgets", default="1000,5000,20000")
    parser.add_argument("--partition-size", type=int, default=1)
    parser.add_argument("--solver", default="cadical153")
    parser.add_argument("--scan-limit", type=int, default=5000)
    parser.add_argument("--max-candidates", type=int, default=20)
    parser.add_argument("--min-affected-roots", type=int, default=1)
    parser.add_argument("--seconds", type=float, default=120.0)
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()

    strategies = parse_csv_words(args.strategies)
    modes = parse_csv_words(args.modes)
    budgets = parse_csv_ints(args.budgets)
    if not strategies or len(set(strategies)) != len(strategies):
        raise SystemExit("--strategies must contain unique values")
    if any(strategy not in SUPPORTED_STRATEGIES for strategy in strategies):
        raise SystemExit(f"supported strategies: {','.join(SUPPORTED_STRATEGIES)}")
    if not modes or len(set(modes)) != len(modes):
        raise SystemExit("--modes must contain unique values")
    if any(mode not in SUPPORTED_MODES for mode in modes):
        raise SystemExit(f"supported modes: {','.join(SUPPORTED_MODES)}")
    if not budgets or any(budget <= 0 for budget in budgets):
        raise SystemExit("--budgets must contain positive integers")
    if budgets != sorted(set(budgets)):
        raise SystemExit("--budgets must be unique and strictly increasing")
    if args.partition_size <= 0:
        raise SystemExit("--partition-size must be positive")
    try:
        orders = parse_orders(args.orders, strategies)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    history = {}
    checkpoint_tier = ""
    if args.checkpoint_json:
        circuit, candidates, history, checkpoint_tier = load_checkpoint_frontier(
            args.checkpoint_json,
            args.checkpoint_frontier,
        )
    else:
        if not args.circuit:
            raise SystemExit("--circuit or --checkpoint-json is required")
        circuit = resolve_path(args.circuit)
        candidates = None
    if not circuit.exists():
        raise SystemExit(f"circuit does not exist: {circuit}")

    parsed = parse_aag(str(circuit))
    _, _, _, _, gate_count, inputs, latches, outputs, gates_raw, _symbols = parsed
    roots = observable_roots(outputs, latches)
    if candidates is None:
        candidates = alg10._candidate_order(gates_raw, roots=roots)
    if args.candidate_order == "history_desc":
        candidates = sorted(
            candidates,
            key=lambda candidate: (
                -int(history.get(candidate, 0)),
                -int(candidate[0]),
                int(candidate[1]),
            ),
        )
    else:
        candidates = alg10._order_global_frontier(
            candidates,
            gates_raw,
            history,
            roots=roots,
            order=args.candidate_order,
        )
    by_lhs, fanout = alg10._fanout_graph(gates_raw)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else REPO_ROOT
        / "results_optimized"
        / "hard_candidate_strategy_experiments"
        / timestamp
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    strategy_path = output_dir / f"strategy_detail_{timestamp}.csv"
    portfolio_path = output_dir / f"portfolio_detail_{timestamp}.csv"
    summary_path = output_dir / f"portfolio_summary_{timestamp}.csv"
    metadata_path = output_dir / f"experiment_{timestamp}.json"

    print("Exact hard-candidate strategy experiment")
    print(
        f"  circuit={circuit} gates={gate_count} roots={len(roots)} "
        f"frontier={len(candidates)} tier={checkpoint_tier or 'fresh'}"
    )
    print(
        f"  strategies={','.join(strategies)} modes={','.join(modes)} "
        f"orders={len(orders)}"
    )
    print(
        f"  solver={args.solver} budgets={','.join(map(str, budgets))} "
        f"partition_size={args.partition_size}"
    )
    print(f"  output_dir={output_dir}")

    summary = {}
    started = time.perf_counter()
    scanned = 0
    evaluated = 0

    with strategy_path.open("w", newline="", encoding="utf-8") as strategy_file, (
        portfolio_path.open("w", newline="", encoding="utf-8")
    ) as portfolio_file:
        strategy_writer = csv.DictWriter(strategy_file, fieldnames=STRATEGY_FIELDS)
        portfolio_writer = csv.DictWriter(portfolio_file, fieldnames=PORTFOLIO_FIELDS)
        strategy_writer.writeheader()
        portfolio_writer.writeheader()

        for idx, stuck_value in candidates:
            if args.scan_limit > 0 and scanned >= args.scan_limit:
                break
            if args.seconds > 0 and time.perf_counter() - started >= args.seconds:
                break
            scanned += 1
            affected = alg10._affected_roots_from_graph(
                by_lhs,
                fanout,
                roots,
                idx,
            )
            if len(affected) < args.min_affected_roots:
                continue

            candidate_pos = evaluated + 1
            measured_by_mode = {}
            all_results = []
            for mode_pos, mode in enumerate(modes):
                rotation = (candidate_pos + mode_pos - 1) % len(strategies)
                measurement_order = strategies[rotation:] + strategies[:rotation]
                measured = {}
                for measurement_pos, strategy in enumerate(measurement_order, start=1):
                    result = evaluate_strategy(
                        strategy,
                        mode,
                        inputs,
                        latches,
                        affected,
                        gates_raw,
                        idx,
                        stuck_value,
                        by_lhs,
                        fanout,
                        budgets,
                        args.partition_size,
                        args.solver,
                    )
                    measured[strategy] = result
                    all_results.append(result)
                    strategy_writer.writerow(
                        _strategy_row(
                            circuit.name,
                            candidate_pos,
                            idx,
                            stuck_value,
                            measurement_pos,
                            result,
                        )
                    )
                    strategy_file.flush()
                measured_by_mode[mode] = measured

            validate_resolved_agreement(all_results, (idx, stuck_value))
            for mode in modes:
                for order in orders:
                    replay = replay_order(order, measured_by_mode[mode])
                    row = _portfolio_row(
                        circuit.name,
                        candidate_pos,
                        idx,
                        stuck_value,
                        mode,
                        order,
                        replay,
                    )
                    portfolio_writer.writerow(row)
                    update_summary(summary, row)
            portfolio_file.flush()

            evaluated += 1
            families = Counter(result_family(result.status) for result in all_results)
            print(
                f"  candidate={candidate_pos} gate={idx} SA{stuck_value} "
                f"roots={len(affected)} outcomes={dict(families)}"
            )
            if args.max_candidates > 0 and evaluated >= args.max_candidates:
                break

    summary_rows = write_summary(summary_path, summary)
    elapsed = time.perf_counter() - started
    metadata = {
        "schema": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "circuit": str(circuit.resolve()),
        "gate_count": gate_count,
        "observable_roots": len(roots),
        "checkpoint_json": str(resolve_path(args.checkpoint_json))
        if args.checkpoint_json
        else "",
        "checkpoint_tier": checkpoint_tier,
        "candidate_order": args.candidate_order,
        "strategies": strategies,
        "modes": modes,
        "orders": [list(order) for order in orders],
        "budgets": budgets,
        "partition_size": args.partition_size,
        "solver": args.solver,
        "scanned": scanned,
        "evaluated": evaluated,
        "elapsed_s": elapsed,
        "strategy_detail": str(strategy_path),
        "portfolio_detail": str(portfolio_path),
        "portfolio_summary": str(summary_path),
        "summary": summary_rows,
    }
    with metadata_path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
        f.write("\n")

    best = sorted(
        summary_rows,
        key=lambda row: (
            -int(row["Resolved"]),
            float(row["Total_s"]),
            int(row["Conflicts"]),
        ),
    )
    print("\nExperiment complete")
    print(f"  elapsed={elapsed:.3f}s scanned={scanned} evaluated={evaluated}")
    for row in best[: min(6, len(best))]:
        print(
            f"  {row['Mode']:10s} {row['Order']:35s} "
            f"resolved={row['Resolved']}/{row['Candidates']} "
            f"time={row['Total_s']} conflicts={row['Conflicts']}"
        )
    print(f"  summary={summary_path}")
    print(f"  metadata={metadata_path}")


if __name__ == "__main__":
    main()
