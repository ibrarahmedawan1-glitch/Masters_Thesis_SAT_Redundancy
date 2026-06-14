#!/usr/bin/env python3
"""Focused tests for the single-writer parallel Alg10 coordinator."""

import os
import tempfile

import alg10_frontier_shard_probe as probe
import alg10_parallel_commit_coordinator as coordinator
from verifier import verify_equivalence


def write_odc_redundant_circuit(path):
    with open(path, "w", encoding="ascii") as f:
        f.write("aag 4 2 0 1 2\n")
        f.write("2\n")
        f.write("4\n")
        f.write("9\n")
        f.write("6 2 4\n")
        f.write("8 7 3\n")
        f.write("c\n")
        f.write("out = x OR (x AND y) = x\n")


def test_parallel_coordinator_commits_only_after_serial_recheck_and_cec():
    with tempfile.TemporaryDirectory(prefix="alg10_parallel_commit_") as tmp:
        source = os.path.join(tmp, "odc.aag")
        output = os.path.join(tmp, "odc_out.aag")
        report = os.path.join(tmp, "report.json")
        jsonl = os.path.join(tmp, "waves.jsonl")
        write_odc_redundant_circuit(source)

        config = coordinator.CoordinatorConfig(
            checkpoint_dir=os.path.join(tmp, "checkpoints"),
            jobs=2,
            budgets=(1000,),
            batch_size=4,
            max_seconds=20,
            max_generations=8,
            solver="glucose4",
            frontier_order="current",
        )
        summary = coordinator.run_coordinator(
            source,
            output,
            config,
            report_path=report,
            jsonl_path=jsonl,
        )

        verify, _ = verify_equivalence(source, output)
        assert verify == "PASS"
        assert summary["final_verify"] == "PASS"
        assert summary["final_gates"] < summary["initial_gates"]
        assert summary["totals"]["worker_unsat_proposed"] > 0
        assert summary["totals"]["coordinator_unsat_accept"] > 0
        assert summary["totals"]["cec_pass_commits"] > 0
        assert summary["totals"]["cec_failed_commits"] == 0
        assert os.path.exists(report)
        assert os.path.exists(jsonl)


def test_bound_phase_state_advances_without_repeating_rejected_candidates():
    with tempfile.TemporaryDirectory(prefix="alg10_parallel_state_") as tmp:
        source = os.path.abspath("benchmarks/c432.aag")
        work = os.path.join(tmp, "work.aag")
        with open(source, "rb") as src, open(work, "wb") as dst:
            dst.write(src.read())

        config = coordinator.CoordinatorConfig(
            checkpoint_dir=os.path.join(tmp, "checkpoints"),
            jobs=2,
            budgets=(100,),
            solver="glucose4",
            frontier_order="current",
        )
        opt = probe._load_alg10(coordinator._alg10_config(config))
        assert tuple(opt.SAT_BUDGETS) == config.budgets
        candidates, history = coordinator._frontier_from_state(opt, work, None)
        remaining = candidates[4:]
        state = coordinator._phase_state(
            opt,
            work,
            remaining,
            history,
            "UNIT_TEST_ADVANCE",
        )
        resumed, _ = coordinator._frontier_from_state(opt, work, state)
        assert resumed == remaining
        assert not set(candidates[:4]).intersection(resumed)


def test_failed_cec_rolls_back_candidate_generation():
    with tempfile.TemporaryDirectory(prefix="alg10_parallel_rollback_") as tmp:
        source = os.path.join(tmp, "odc.aag")
        work = os.path.join(tmp, "work.aag")
        write_odc_redundant_circuit(source)
        with open(source, "rb") as src, open(work, "wb") as dst:
            dst.write(src.read())

        config = coordinator.CoordinatorConfig(
            checkpoint_dir=os.path.join(tmp, "checkpoints"),
            solver="glucose4",
        )
        opt = probe._load_alg10(coordinator._alg10_config(config))
        before = opt._sha256_file(work)
        original_cec = coordinator.run_abc_cec
        coordinator.run_abc_cec = lambda *_args, **_kwargs: ("FAIL", 0.0, "forced")
        try:
            result = coordinator._cec_transaction(
                source,
                work,
                {1: 0},
                opt,
                cec_timeout=1.0,
            )
        finally:
            coordinator.run_abc_cec = original_cec

        assert result["committed"] is False
        assert result["verify"] == "FAIL"
        assert opt._sha256_file(work) == before


if __name__ == "__main__":
    test_parallel_coordinator_commits_only_after_serial_recheck_and_cec()
    test_bound_phase_state_advances_without_repeating_rejected_candidates()
    test_failed_cec_rolls_back_candidate_generation()
    print("alg10 parallel commit coordinator tests passed")
