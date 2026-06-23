#!/usr/bin/env python3
"""Focused closure and end-to-end checks for the exact TFO fault miter."""

import importlib
import itertools
import os
import tempfile

from pysat.solvers import Solver

from verifier import verify_equivalence


def _literal_value(lit, values):
    if lit == 0:
        return False
    if lit == 1:
        return True
    value = values[lit & ~1]
    return not value if lit & 1 else value


def _fault_is_observable(inputs, gates, roots, target_idx, stuck_value):
    for assignment in itertools.product((False, True), repeat=len(inputs)):
        good_values = {
            lit & ~1: value for lit, value in zip(inputs, assignment)
        }
        faulty_values = dict(good_values)
        for idx, (lhs, r0, r1) in enumerate(gates):
            good_values[lhs & ~1] = _literal_value(
                r0,
                good_values,
            ) and _literal_value(r1, good_values)
            if idx == target_idx:
                faulty_values[lhs & ~1] = bool(stuck_value)
            else:
                faulty_values[lhs & ~1] = _literal_value(
                    r0,
                    faulty_values,
                ) and _literal_value(r1, faulty_values)
        if any(
            _literal_value(root, good_values)
            != _literal_value(root, faulty_values)
            for root in roots
        ):
            return True
    return False


def _assert_tfo_matches_truth(
    inputs,
    gates,
    roots,
    target_idx,
    latches=(),
):
    import optimizer_alg10_tiered as alg10

    primary_literals = list(inputs)
    primary_literals.extend(int(latch.split()[0]) for latch in latches)
    by_lhs, fanout = alg10._fanout_graph(gates)
    affected = alg10._affected_roots_from_graph(
        by_lhs,
        fanout,
        roots,
        target_idx,
    )
    good_cone = alg10._fanin_indices_for_roots(
        gates,
        affected,
        by_lhs=by_lhs,
    )
    tfo_slice = alg10._observable_tfo_slice(
        fanout,
        target_idx,
        good_cone,
    )
    alg10._audit_tfo_slice(
        by_lhs,
        fanout,
        affected,
        target_idx,
        good_cone,
        tfo_slice,
        gates,
    )

    for stuck_value in (0, 1):
        clauses, miter_lit, _shared = alg10._build_single_fault_tfo_miter(
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
            sat = solver.solve(assumptions=[miter_lit])
        assert sat == _fault_is_observable(
            primary_literals,
            gates,
            affected,
            target_idx,
            stuck_value,
        )
    return tfo_slice


def test_tfo_slice_audit_rejects_missing_relevant_gate():
    import optimizer_alg10_tiered as alg10

    gates = [
        [6, 2, 4],
        [8, 6, 2],
        [10, 8, 4],
    ]
    roots = [10]
    by_lhs, fanout = alg10._fanout_graph(gates)
    good_cone = alg10._fanin_indices_for_roots(gates, roots, by_lhs=by_lhs)
    complete = alg10._observable_tfo_slice(fanout, 0, good_cone)
    alg10._audit_tfo_slice(
        by_lhs,
        fanout,
        roots,
        0,
        good_cone,
        complete,
        gates,
    )

    corrupt = set(complete)
    corrupt.remove(1)
    try:
        alg10._audit_tfo_slice(
            by_lhs,
            fanout,
            roots,
            0,
            good_cone,
            corrupt,
            gates,
        )
    except AssertionError:
        return
    raise AssertionError("TFO audit accepted a slice with a missing relevant gate")


def test_independent_tfo_audit_rejects_corrupt_fanout():
    import optimizer_alg10_tiered as alg10

    gates = [
        [6, 2, 4],
        [8, 6, 2],
        [10, 8, 4],
    ]
    roots = [10]
    by_lhs, _fanout = alg10._fanout_graph(gates)
    good_cone = alg10._fanin_indices_for_roots(
        gates,
        roots,
        by_lhs=by_lhs,
    )
    corrupt_fanout = [set(), {2}, set()]
    corrupt_slice = alg10._observable_tfo_slice(
        corrupt_fanout,
        0,
        good_cone,
    )
    try:
        alg10._audit_tfo_slice(
            by_lhs,
            corrupt_fanout,
            roots,
            0,
            good_cone,
            corrupt_slice,
            gates,
        )
    except AssertionError as exc:
        assert "fanin-dependency" in str(exc)
        return
    raise AssertionError("independent TFO audit accepted corrupt fanout closure")


def test_tfo_handles_complemented_only_fanout():
    inputs = [2, 4]
    gates = [
        [6, 2, 4],
        [8, 7, 2],
    ]
    tfo_slice = _assert_tfo_matches_truth(inputs, gates, [8], 0)
    assert tfo_slice == {0, 1}


def test_tfo_side_input_reuse_and_reconvergence_match_truth():
    inputs = [2, 4, 6]

    independent_side_input = [
        [8, 2, 4],
        [10, 8, 6],
        [12, 2, 6],
        [14, 10, 12],
    ]
    tfo_slice = _assert_tfo_matches_truth(
        inputs,
        independent_side_input,
        [14],
        0,
    )
    assert tfo_slice == {0, 1, 3}

    reconvergent_side_input = [
        [8, 2, 4],
        [10, 8, 6],
        [12, 9, 6],
        [14, 10, 12],
    ]
    tfo_slice = _assert_tfo_matches_truth(
        inputs,
        reconvergent_side_input,
        [14],
        0,
    )
    assert tfo_slice == {0, 1, 2, 3}


def test_tfo_multiple_outputs_and_latch_next_roots_match_truth():
    inputs = [2, 4]
    latches = ["6 12"]
    gates = [
        [8, 2, 6],
        [10, 9, 4],
        [12, 8, 4],
        [14, 10, 13],
    ]
    outputs = [14, 9]
    roots = outputs + [12]
    tfo_slice = _assert_tfo_matches_truth(
        inputs,
        gates,
        roots,
        0,
        latches=latches,
    )
    assert tfo_slice == {0, 1, 2, 3}


def test_tfo_miter_matches_full_cone_with_latch_cut_boundary():
    import optimizer_alg10_tiered as alg10

    inputs = [2]
    latches = ["4 8"]
    gates = [
        [6, 2, 4],
        [8, 6, 2],
    ]
    roots = [8]
    by_lhs, fanout = alg10._fanout_graph(gates)

    for idx in range(len(gates)):
        for stuck_value in (0, 1):
            affected = alg10._affected_roots_from_graph(
                by_lhs,
                fanout,
                roots,
                idx,
            )
            good_cone = alg10._fanin_indices_for_roots(
                gates,
                affected,
                by_lhs=by_lhs,
            )
            tfo_slice = alg10._observable_tfo_slice(
                fanout,
                idx,
                good_cone,
            )
            alg10._audit_tfo_slice(
                by_lhs,
                fanout,
                affected,
                idx,
                good_cone,
                tfo_slice,
                gates,
            )
            full_clauses, full_miter, _ = alg10._build_single_fault_cone_miter(
                inputs,
                latches,
                affected,
                gates,
                idx,
                stuck_value,
                good_cone,
            )
            tfo_clauses, tfo_miter, _ = alg10._build_single_fault_tfo_miter(
                inputs,
                latches,
                affected,
                gates,
                idx,
                stuck_value,
                good_cone,
                tfo_slice,
            )
            with Solver(name="glucose4", bootstrap_with=full_clauses) as full_solver:
                full_sat = full_solver.solve(assumptions=[full_miter])
            with Solver(name="glucose4", bootstrap_with=tfo_clauses) as tfo_solver:
                tfo_sat = tfo_solver.solve(assumptions=[tfo_miter])
            assert tfo_sat == full_sat


def test_tfo_engine_pipeline_cec():
    env = {
        "ALG10_MODE": "fast_save",
        "ALG10_BUDGETS": "100000",
        "ALG10_MAX_CIRCUIT_SECONDS": "30",
        "ALG10_MAX_PHASES": "10",
        "ALG10_RESET_CHECKPOINT": "1",
        "ALG10_CHECKPOINT_DIR": "/tmp/alg10_tfo_test_checkpoints",
        "ALG10_TFI_CONSTANCY": "0",
        "ALG10_WINDOW_MITER": "0",
        "ALG10_CONE_MITER": "1",
        "ALG10_CONE_ENGINE": "tfo",
        "ALG10_CONE_SOLVER": "glucose4",
        "ALG10_CONE_BUDGET": "100000",
        "ALG10_CONE_TFO_MAX_GOOD_GATES": "100000",
        "ALG10_CONE_TFO_MAX_FAULTY_GATES": "100000",
        "ALG10_GLOBAL_MITER": "0",
        "ALG10_CEX_PRUNING": "0",
        "ALG10_PRE_SIM_REJECTION": "0",
    }
    old = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    try:
        import optimizer_alg10_tiered as alg10

        alg10 = importlib.reload(alg10)
        with tempfile.TemporaryDirectory(prefix="alg10_tfo_") as tmp:
            os.environ["ALG10_CHECKPOINT_DIR"] = os.path.join(tmp, "checkpoints")
            alg10 = importlib.reload(alg10)
            output = os.path.join(tmp, "c432_tfo.aag")
            _orig, _structural, _final, _removed, timings = alg10.solve_circuit(
                "benchmarks/c432.aag",
                output,
            )
            assert verify_equivalence("benchmarks/c432.aag", output)[0] == "PASS"
            assert timings["Cone_TFO_Checks"] > 0
            assert timings["Cone_TFO_Audit_Fail"] == 0
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import optimizer_alg10_tiered as alg10

        importlib.reload(alg10)


if __name__ == "__main__":
    test_tfo_slice_audit_rejects_missing_relevant_gate()
    test_independent_tfo_audit_rejects_corrupt_fanout()
    test_tfo_handles_complemented_only_fanout()
    test_tfo_side_input_reuse_and_reconvergence_match_truth()
    test_tfo_multiple_outputs_and_latch_next_roots_match_truth()
    test_tfo_miter_matches_full_cone_with_latch_cut_boundary()
    test_tfo_engine_pipeline_cec()
    print("Alg10 exact TFO miter tests passed")
