#!/usr/bin/env python3
"""Focused safety checks for Alg10 proof-cost frontier ordering."""

import optimizer_alg10_tiered as alg10


def _fixture():
    inputs = [2, 4]
    gates = [
        [6, 2, 4],   # g0 feeds g1
        [8, 6, 2],   # g1 is observable
        [10, 4, 4],  # g2 is a smaller independent observable cone
        [12, 2, 2],  # g3 is unobservable
    ]
    roots = [8, 10]
    candidates = [(idx, value) for idx in range(len(gates)) for value in (0, 1)]
    return inputs, gates, roots, candidates


def test_proof_cost_preserves_complete_frontier():
    _inputs, gates, roots, candidates = _fixture()
    ordered = alg10._order_global_frontier(
        candidates,
        gates,
        {},
        roots=roots,
        order="proof_cost",
    )
    assert len(ordered) == len(candidates)
    assert len(set(ordered)) == len(candidates)
    assert set(ordered) == set(candidates)


def test_proof_cost_prefers_smaller_exact_observable_obligations():
    _inputs, gates, roots, candidates = _fixture()
    ordered = alg10._order_global_frontier(
        candidates,
        gates,
        {},
        roots=roots,
        order="proof_cost",
    )
    gate_order = []
    for idx, _value in ordered:
        if idx not in gate_order:
            gate_order.append(idx)
    assert gate_order == [3, 2, 1, 0], gate_order


def test_proof_cost_untried_keeps_history_as_primary_partition():
    _inputs, gates, roots, candidates = _fixture()
    history = {(3, 0): 100, (3, 1): 100}
    ordered = alg10._order_global_frontier(
        candidates,
        gates,
        history,
        roots=roots,
        order="proof_cost_untried",
    )
    first_tried = min(pos for pos, cand in enumerate(ordered) if history.get(cand, 0) > 0)
    assert all(history.get(cand, 0) == 0 for cand in ordered[:first_tried])
    assert set(ordered) == set(candidates)


def test_proof_cost_without_roots_is_deterministic_and_complete():
    _inputs, gates, _roots, candidates = _fixture()
    first = alg10._order_global_frontier(
        candidates,
        gates,
        {},
        roots=None,
        order="proof_cost",
    )
    second = alg10._order_global_frontier(
        candidates,
        gates,
        {},
        roots=None,
        order="proof_cost",
    )
    assert first == second
    assert set(first) == set(candidates)


def test_proof_reverse_portfolio_is_deterministic_and_complete():
    _inputs, gates, roots, candidates = _fixture()
    first = alg10._order_global_frontier(
        candidates,
        gates,
        {},
        roots=roots,
        order="proof_reverse_portfolio",
    )
    second = alg10._order_global_frontier(
        candidates,
        gates,
        {},
        roots=roots,
        order="proof_reverse_portfolio",
    )
    assert first == second
    assert len(first) == len(candidates)
    assert len(set(first)) == len(candidates)
    assert set(first) == set(candidates)
    assert first[0][0] == 3


if __name__ == "__main__":
    test_proof_cost_preserves_complete_frontier()
    test_proof_cost_prefers_smaller_exact_observable_obligations()
    test_proof_cost_untried_keeps_history_as_primary_partition()
    test_proof_cost_without_roots_is_deterministic_and_complete()
    test_proof_reverse_portfolio_is_deterministic_and_complete()
    print("Alg10 proof-cost candidate strategy tests passed")
