#!/usr/bin/env python3
"""Focused professor-defense checks for Alg10 encoding and commit safety.

These tests cover the small remaining soundness questions raised during the
thesis review: committed-state side inputs, latch-cut roots, TFO worker results
rechecked by a different global encoding, false worker proposals, and long
reconvergent fanout.
"""

import os
import tempfile

from pysat.solvers import Solver

import alg10_parallel_commit_coordinator as coordinator
import optimizer_alg10_tiered as alg10
from verifier import verify_equivalence


def _lit_value(lit, values):
    if lit == 0:
        return False
    if lit == 1:
        return True
    value = values[lit & ~1]
    return not value if lit & 1 else value


def _fault_is_observable(inputs, latches, gates, roots, target_idx, stuck_value):
    primary = list(inputs) + [alg10._parse_latch(latch)[0] for latch in latches]
    for mask in range(1 << len(primary)):
        good = {}
        faulty = {}
        for bit, lit in enumerate(primary):
            value = bool((mask >> bit) & 1)
            good[lit & ~1] = value
            faulty[lit & ~1] = value
        for idx, (lhs, r0, r1) in enumerate(gates):
            good[lhs & ~1] = _lit_value(r0, good) and _lit_value(r1, good)
            if idx == target_idx:
                faulty[lhs & ~1] = bool(stuck_value)
            else:
                faulty[lhs & ~1] = _lit_value(r0, faulty) and _lit_value(r1, faulty)
        if any(_lit_value(root, good) != _lit_value(root, faulty) for root in roots):
            return True
    return False


def _tfo_miter_sat(inputs, latches, gates, roots, target_idx, stuck_value):
    by_lhs, fanout = alg10._fanout_graph(gates)
    affected = alg10._affected_roots_from_graph(by_lhs, fanout, roots, target_idx)
    good_cone = alg10._fanin_indices_for_roots(gates, affected, by_lhs=by_lhs)
    tfo_slice = alg10._observable_tfo_slice(fanout, target_idx, good_cone)
    alg10._audit_tfo_slice(
        by_lhs,
        fanout,
        affected,
        target_idx,
        good_cone,
        tfo_slice,
        gates,
    )
    clauses, miter_lit, _ = alg10._build_single_fault_tfo_miter(
        inputs,
        latches,
        affected,
        gates,
        target_idx,
        stuck_value,
        good_cone,
        tfo_slice,
    )
    with Solver(name="glucose4", bootstrap_with=clauses) as solver:
        return solver.solve(assumptions=[miter_lit]), affected, tfo_slice


def _write_odc(path):
    with open(path, "w", encoding="ascii") as f:
        f.write("aag 4 2 0 1 2\n")
        f.write("2\n")
        f.write("4\n")
        f.write("9\n")
        f.write("6 2 4\n")
        f.write("8 7 3\n")
        f.write("c\n")
        f.write("out = x OR (x AND y) = x\n")


def _write_observable_and(path):
    with open(path, "w", encoding="ascii") as f:
        f.write("aag 3 2 0 1 1\n")
        f.write("2\n")
        f.write("4\n")
        f.write("6\n")
        f.write("6 2 4\n")
        f.write("c\n")
        f.write("out = a AND b\n")


def test_committed_side_input_uses_current_working_graph():
    inputs = [2, 4, 6]
    latches = []
    roots = [14]
    original = [
        [8, 2, 4],    # accepted earlier as stuck-at-0 in the working graph
        [10, 8, 6],   # side input for the later candidate's TFO slice
        [12, 2, 6],   # current candidate
        [14, 10, 12],
    ]
    committed = [list(gate) for gate in original]
    committed[0] = [8, 0, 0]

    assert _fault_is_observable(inputs, latches, original, roots, 2, 0)
    assert not _fault_is_observable(inputs, latches, committed, roots, 2, 0)

    original_sat, _affected, _slice = _tfo_miter_sat(inputs, latches, original, roots, 2, 0)
    committed_sat, affected, tfo_slice = _tfo_miter_sat(
        inputs,
        latches,
        committed,
        roots,
        2,
        0,
    )

    assert original_sat is True
    assert committed_sat is False
    assert affected == roots
    assert tfo_slice == {2, 3}


def test_two_latch_cut_roots_are_observable_boundaries():
    inputs = [2]
    latches = ["4 10", "6 12"]
    outputs = [2]
    roots = outputs + [alg10._parse_latch(latch)[1] for latch in latches]
    gates = [
        [8, 2, 4],
        [10, 8, 6],
        [12, 8, 2],
    ]
    by_lhs, fanout = alg10._fanout_graph(gates)
    affected = alg10._affected_roots_from_graph(by_lhs, fanout, roots, 0)
    assert set(affected) == {10, 12}

    for stuck_value in (0, 1):
        sat, _affected, tfo_slice = _tfo_miter_sat(
            inputs,
            latches,
            gates,
            roots,
            0,
            stuck_value,
        )
        expected_sat = _fault_is_observable(inputs, latches, gates, roots, 0, stuck_value)
        assert sat == expected_sat
        assert tfo_slice == {0, 1, 2}


def test_tfo_worker_with_global_recheck_commits_and_cec_passes():
    with tempfile.TemporaryDirectory(prefix="prof_tfo_global_recheck_") as tmp:
        source = os.path.join(tmp, "odc.aag")
        output = os.path.join(tmp, "odc_out.aag")
        _write_odc(source)

        config = coordinator.CoordinatorConfig(
            checkpoint_dir=os.path.join(tmp, "checkpoints"),
            jobs=2,
            budgets=(1000,),
            batch_size=4,
            max_seconds=20,
            max_generations=8,
            solver="glucose4",
            frontier_order="current",
            worker_engine="tfo",
            recheck_engine="global",
        )
        summary = coordinator.run_coordinator(source, output, config)

        verify, _ = verify_equivalence(source, output)
        assert verify == "PASS"
        assert summary["final_verify"] == "PASS"
        assert summary["totals"]["worker_unsat_proposed"] > 0
        assert summary["totals"]["coordinator_unsat_accept"] > 0
        assert summary["totals"]["cec_failed_commits"] == 0
        assert all(
            record["worker_engine"] == "tfo" and record["recheck_engine"] == "global"
            for record in summary["records"]
        )


def test_false_worker_unsat_proposal_is_rejected_by_global_recheck():
    with tempfile.TemporaryDirectory(prefix="prof_false_worker_unsat_") as tmp:
        source = os.path.join(tmp, "observable_and.aag")
        _write_observable_and(source)
        proposal = {
            "ordinal": 0,
            "idx": 0,
            "stuck_value": 0,
            "status": "UNSAT_PROPOSED_ACCEPT",
        }
        config = coordinator.CoordinatorConfig(
            checkpoint_dir=os.path.join(tmp, "checkpoints"),
            solver="glucose4",
            recheck_engine="global",
        )
        recheck = coordinator._serial_recheck(source, [proposal], config)
        assert recheck["accepted"] == {}
        assert recheck["results"][0]["status"] == "SAT_REJECT"


def test_long_reconvergent_tfo_path_matches_truth():
    inputs = [2, 4, 6]
    latches = []
    gates = [[8, 2, 4]]
    previous = 8
    for offset in range(64):
        lhs = 10 + 2 * offset
        gates.append([lhs, previous, 6])
        previous = lhs
    root = previous + 2
    gates.append([root, 8, previous])
    roots = [root]

    sat, affected, tfo_slice = _tfo_miter_sat(inputs, latches, gates, roots, 0, 0)
    expected_sat = _fault_is_observable(inputs, latches, gates, roots, 0, 0)
    assert sat == expected_sat
    assert affected == roots
    assert len(tfo_slice) == len(gates)


if __name__ == "__main__":
    test_committed_side_input_uses_current_working_graph()
    test_two_latch_cut_roots_are_observable_boundaries()
    test_tfo_worker_with_global_recheck_commits_and_cec_passes()
    test_false_worker_unsat_proposal_is_rejected_by_global_recheck()
    test_long_reconvergent_tfo_path_matches_truth()
    print("professor encoding control tests passed")
