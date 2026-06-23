#!/usr/bin/env python3
"""Focused checks for exact strategy ordering and persistent SAT budgets."""

from hard_candidate_strategy_experiment import (
    evaluate_strategy,
    parse_orders,
    replay_order,
    result_family,
    solve_budget_ladder,
    validate_resolved_agreement,
)

import optimizer_alg10_tiered as alg10
from pysat.examples.genhard import PHP


def test_all_orders_are_complete_permutations():
    strategies = ["tfo", "partition_tfo", "cone"]
    orders = parse_orders("all", strategies)
    assert len(orders) == 6
    assert all(len(order) == 3 and set(order) == set(strategies) for order in orders)


def test_persistent_budget_ladder_reuses_one_solver():
    clauses = PHP(nof_holes=6).clauses
    persistent = solve_budget_ladder(
        clauses,
        1,
        "cadical153",
        [1, 10, 100, 10000],
        persistent=True,
    )
    fresh = solve_budget_ladder(
        clauses,
        1,
        "cadical153",
        [1, 10, 100, 10000],
        persistent=False,
    )
    assert persistent.solver_instances == 1
    assert fresh.solver_instances > 1
    assert len(persistent.attempts) > 1
    assert result_family(persistent.status) == result_family(fresh.status)
    assert result_family(persistent.status) in {"SAT", "UNSAT"}


def _evaluate_all(inputs, outputs, gates, target_idx, stuck_value):
    roots = list(outputs)
    by_lhs, fanout = alg10._fanout_graph(gates)
    affected = alg10._affected_roots_from_graph(
        by_lhs,
        fanout,
        roots,
        target_idx,
    )
    results = []
    for mode in ("fresh", "persistent"):
        for strategy in ("tfo", "partition_tfo", "cone", "partition_cone"):
            results.append(
                evaluate_strategy(
                    strategy,
                    mode,
                    inputs,
                    [],
                    affected,
                    gates,
                    target_idx,
                    stuck_value,
                    by_lhs,
                    fanout,
                    [1000],
                    1,
                    "cadical153",
                )
            )
    validate_resolved_agreement(results, (target_idx, stuck_value))
    return results


def test_exact_strategies_agree_on_sat_fault():
    inputs = [2, 4]
    gates = [
        [6, 2, 4],
        [8, 6, 0],
    ]
    results = _evaluate_all(inputs, [6, 8], gates, 0, 0)
    assert {result_family(result.status) for result in results} == {"SAT"}


def test_exact_strategies_agree_on_redundant_fault():
    inputs = [2, 4]
    gates = [
        [6, 2, 4],
        [8, 6, 0],
    ]
    results = _evaluate_all(inputs, [8], gates, 0, 0)
    assert {result_family(result.status) for result in results} == {"UNSAT"}


def test_replay_stops_at_first_resolved_strategy():
    class Result:
        def __init__(self, status, encode_s, solve_s, conflicts, instances):
            self.status = status
            self.encode_s = encode_s
            self.solve_s = solve_s
            self.conflicts = conflicts
            self.solver_instances = instances

    measured = {
        "tfo": Result("TIMEOUT", 1.0, 2.0, 10, 1),
        "partition_tfo": Result("UNSAT", 3.0, 4.0, 20, 1),
        "cone": Result("SAT", 100.0, 100.0, 1000, 1),
    }
    replay = replay_order(("tfo", "partition_tfo", "cone"), measured)
    assert replay["Status"] == "UNSAT"
    assert replay["Winner"] == "partition_tfo"
    assert replay["Strategies_Used"] == 2
    assert replay["Total_s"] == 10.0
    assert replay["Conflicts"] == 30


if __name__ == "__main__":
    test_all_orders_are_complete_permutations()
    test_persistent_budget_ladder_reuses_one_solver()
    test_exact_strategies_agree_on_sat_fault()
    test_exact_strategies_agree_on_redundant_fault()
    test_replay_stops_at_first_resolved_strategy()
    print("Hard candidate strategy experiment tests passed")
