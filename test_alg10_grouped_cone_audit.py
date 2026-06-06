#!/usr/bin/env python3
"""Focused grouped-cone assumption audits for Algorithm 10.

These checks deliberately corrupt the per-control assumption vector. A passing
test means the production audit catches the exact faults that could otherwise
leave an inactive stuck-at control free inside the grouped cone miter.
"""

import os

os.environ.setdefault("ALG10_AUDIT_ASSUMPTIONS", "1")
os.environ.setdefault("ALG10_CONE_ENGINE", "grouped")
os.environ.setdefault("ALG10_CONE_GROUP_MIN_SIZE", "1")
os.environ.setdefault("ALG10_CONE_SOLVER", "glucose4")

import optimizer_alg10_tiered as alg10


def _small_cone_state(accepted=None):
    inputs = [2, 4]
    gates = [
        [6, 2, 4],
        [8, 6, 2],
    ]
    outputs = [8]
    by_lhs, fanout = alg10._fanout_graph(gates)
    roots, cone = alg10._cone_group_key(gates, outputs, 0, by_lhs, fanout)
    assert roots == (8,)
    assert cone == {0, 1}
    timings = {"Encode": 0.0, "SAT": 0.0}
    state = alg10._make_cone_group_solver(inputs, [], roots, gates, cone, accepted or {}, timings)
    return inputs, gates, outputs, state


def _expect_audit_failure(fn):
    try:
        fn()
    except AssertionError as exc:
        return str(exc)
    raise AssertionError("expected grouped-cone assumption audit failure")


def test_grouped_cone_assumption_audit_accepts_valid_vector():
    _, _, _, state = _small_cone_state()
    try:
        assumptions = state.assumptions_for(0, 0)
        alg10._audit_cone_group_assumptions(
            assumptions,
            state,
            (0, 0),
            accepted={},
        )
        sat = state.solver.solve(assumptions=assumptions)
        assert isinstance(sat, bool)
    finally:
        state.delete()


def test_grouped_cone_assumption_audit_catches_missing_control():
    _, _, _, state = _small_cone_state()
    try:
        assumptions = state.assumptions_for(0, 0)
        bad = assumptions[:-2] + assumptions[-1:]
        message = _expect_audit_failure(
            lambda: alg10._audit_cone_group_assumptions(
                bad,
                state,
                (0, 0),
                accepted={},
            )
        )
        assert "assumption count" in message
    finally:
        state.delete()


def test_grouped_cone_assumption_audit_catches_free_inactive_control():
    _, _, _, state = _small_cone_state()
    try:
        assumptions = state.assumptions_for(0, 0)
        bad = assumptions.copy()
        inactive_gate_f0_pos = state.positions[(1, 0)]
        bad[inactive_gate_f0_pos] = -bad[inactive_gate_f0_pos]
        message = _expect_audit_failure(
            lambda: alg10._audit_cone_group_assumptions(
                bad,
                state,
                (0, 0),
                accepted={},
            )
        )
        assert "content mismatch" in message
    finally:
        state.delete()


def test_grouped_cone_assumption_audit_catches_candidate_opposite_fault():
    _, _, _, state = _small_cone_state()
    try:
        assumptions = state.assumptions_for(0, 0)
        bad = assumptions.copy()
        candidate_f1_pos = state.positions[(0, 1)]
        bad[candidate_f1_pos] = -bad[candidate_f1_pos]
        message = _expect_audit_failure(
            lambda: alg10._audit_cone_group_assumptions(
                bad,
                state,
                (0, 0),
                accepted={},
            )
        )
        assert "content mismatch" in message
    finally:
        state.delete()


def test_grouped_cone_assumption_audit_catches_committed_control_tamper():
    _, _, _, state = _small_cone_state(accepted={1: 1})
    try:
        assumptions = state.assumptions_for(0, 0)
        alg10._audit_cone_group_assumptions(
            assumptions,
            state,
            (0, 0),
            accepted={1: 1},
        )
        bad = assumptions.copy()
        accepted_f1_pos = state.positions[(1, 1)]
        bad[accepted_f1_pos] = -bad[accepted_f1_pos]
        message = _expect_audit_failure(
            lambda: alg10._audit_cone_group_assumptions(
                bad,
                state,
                (0, 0),
                accepted={1: 1},
            )
        )
        assert "content mismatch" in message
    finally:
        state.delete()


def test_grouped_cone_tier_runs_with_production_audit_enabled():
    inputs, gates, outputs, probe_state = _small_cone_state()
    probe_state.delete()
    old_engine = alg10.CONE_ENGINE
    old_min_size = alg10.CONE_GROUP_MIN_SIZE
    old_audit = alg10.AUDIT_ASSUMPTIONS
    old_budget = alg10.CONE_BUDGET
    try:
        alg10.CONE_ENGINE = "grouped"
        alg10.CONE_GROUP_MIN_SIZE = 1
        alg10.AUDIT_ASSUMPTIONS = True
        alg10.CONE_BUDGET = 100000
        timings = {"Encode": 0.0, "SAT": 0.0}
        accepted, telemetry = alg10._run_cone_miter_tier(
            inputs,
            [],
            outputs,
            gates,
            timings,
            deadline=None,
            initial_pruned=None,
        )
        assert isinstance(accepted, dict)
        assert telemetry["cone_checks"] > 0
    finally:
        alg10.CONE_ENGINE = old_engine
        alg10.CONE_GROUP_MIN_SIZE = old_min_size
        alg10.AUDIT_ASSUMPTIONS = old_audit
        alg10.CONE_BUDGET = old_budget


def run_all():
    test_grouped_cone_assumption_audit_accepts_valid_vector()
    test_grouped_cone_assumption_audit_catches_missing_control()
    test_grouped_cone_assumption_audit_catches_free_inactive_control()
    test_grouped_cone_assumption_audit_catches_candidate_opposite_fault()
    test_grouped_cone_assumption_audit_catches_committed_control_tamper()
    test_grouped_cone_tier_runs_with_production_audit_enabled()


if __name__ == "__main__":
    run_all()
