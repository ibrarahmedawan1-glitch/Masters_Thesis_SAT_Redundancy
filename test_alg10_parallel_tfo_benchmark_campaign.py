#!/usr/bin/env python3
"""Focused tests for smart TFO benchmark campaign policy."""

import json
import os
import tempfile

import alg10_parallel_tfo_benchmark_campaign as campaign
import alg10_ranked_frontier_campaign as ranked


def _target(path, gates, unresolved, timestamp):
    return ranked.FrontierTarget(
        key="epfl_arithmetic_log2",
        json_path=path,
        work_path=path + ".work.aag",
        source_path="benchmark_suites/epfl/epfl_arithmetic_log2.aag",
        unresolved=unresolved,
        phase_count=unresolved,
        telemetry_unresolved=unresolved,
        removed=100000 - gates,
        source_gates=100000,
        current_gates=gates,
        phase_tier="global",
        status="TIME_BUDGET_CHECKPOINT",
        timestamp=timestamp,
    )


def test_checkpoint_selection_keeps_the_lowest_gate_count():
    weaker_frontier = _target("older-small-frontier.json", 1000, 3, 1.0)
    stronger_circuit = _target("newer-lower-gates.json", 990, 1800, 2.0)

    selected = campaign._choose_best_checkpoint_targets(
        [weaker_frontier, stronger_circuit],
        max_targets=1,
    )
    assert selected == [stronger_circuit]


def test_cec_commit_without_frontier_is_discoverable_for_regeneration():
    with tempfile.TemporaryDirectory(prefix="alg10_campaign_commit_") as tmp:
        source = os.path.join(tmp, "source.aag")
        work = os.path.join(tmp, "work.aag")
        checkpoint = os.path.join(tmp, "checkpoint.json")
        with open(source, "w", encoding="ascii") as f:
            f.write("aag 2 1 0 1 1\n2\n4\n4 2 2\n")
        with open(work, "w", encoding="ascii") as f:
            f.write("aag 1 1 0 1 0\n2\n2\n")
        with open(checkpoint, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "status": "TIME_BUDGET_CHECKPOINT",
                    "timestamp": 10,
                    "source_path": source,
                    "source_sha256": ranked.sha256_file(source),
                    "work_aag": work,
                    "current_gates": 0,
                    "phase_resume": None,
                    "telemetry": {"parallel_cec_pass_commits": 1},
                },
                f,
            )

        assert campaign._parse_campaign_checkpoint_target(checkpoint) is None

        with open(work, "w", encoding="ascii") as f:
            f.write("aag 2 1 0 1 1\n2\n4\n4 2 2\n")
        with open(checkpoint, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["current_gates"] = 1
        with open(checkpoint, "w", encoding="utf-8") as f:
            json.dump(data, f)

        target = campaign._parse_campaign_checkpoint_target(checkpoint)
        assert target is not None
        assert target.phase_tier == "regenerate"
        assert target.unresolved == 2


def test_verified_campaign_output_is_a_restart_seed():
    with tempfile.TemporaryDirectory(prefix="alg10_campaign_output_") as tmp:
        source = os.path.join(tmp, "source.aag")
        output = os.path.join(tmp, "output.aag")
        summary = os.path.join(tmp, "visit_001_summary.json")
        with open(source, "w", encoding="ascii") as f:
            f.write("aag 2 1 0 1 1\n2\n4\n4 2 2\n")
        with open(output, "w", encoding="ascii") as f:
            f.write("aag 2 1 0 1 1\n2\n4\n4 2 2\n")
        with open(summary, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "source": source,
                    "output": output,
                    "status": "TIME_BUDGET_CHECKPOINT",
                    "final_verify": "PASS",
                    "final_gates": 1,
                    "finished": 20,
                },
                f,
            )

        target = campaign._parse_verified_output_summary(summary)
        assert target is not None
        assert target.phase_tier == "verified_output"
        assert target.work_path == output
        assert target.unresolved == 2

        state = campaign.TargetState(
            key=target.key,
            source_path=target.source_path,
            seed_checkpoint=target.json_path,
            seed_work_path=target.work_path,
            seed_unresolved=target.unresolved,
            seed_removed=target.removed,
            phase_tier=target.phase_tier,
            last_unresolved=target.unresolved,
            last_gates=target.current_gates,
        )
        seed = campaign._materialize_verified_output_seed(
            state,
            os.path.join(tmp, "checkpoints"),
            cec_timeout=10,
        )
        with open(seed, "r", encoding="utf-8") as f:
            seed_data = json.load(f)
        assert seed_data["source_sha256"] == ranked.sha256_file(source)
        assert seed_data["current_gates"] == 1


def test_worker_count_uses_physical_cores_and_rejects_oversubscription():
    auto = campaign.resolve_worker_count(
        0,
        logical_cores=12,
        physical_cores=6,
        available_memory=32 * 1024**3,
    )
    assert auto["selected"] == 6
    assert auto["recommended"] == 6

    explicit = campaign.resolve_worker_count(
        8,
        logical_cores=12,
        physical_cores=6,
        available_memory=32 * 1024**3,
    )
    assert explicit["selected"] == 8

    try:
        campaign.resolve_worker_count(
            24,
            logical_cores=12,
            physical_cores=6,
            available_memory=32 * 1024**3,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("oversubscribed worker request was accepted")


def test_abort_reason_policy():
    assert campaign.next_action_for_result({"status": "COMPLETE"}) == "COMPLETE"
    assert campaign.next_action_for_result(
        {"status": "CEC_FAILED_ROLLBACK"}
    ) == "STOP_AND_AUDIT"
    assert campaign.next_action_for_result(
        {
            "status": "TIME_BUDGET_CHECKPOINT",
            "records": [{"transaction": {"committed": True}}],
        }
    ) == "REGENERATE_FRONTIER"
    assert campaign.next_action_for_result(
        {
            "status": "TIME_BUDGET_CHECKPOINT",
            "records": [{"worker_counts": {"TIMEOUT": 4}}],
        }
    ) == "INCREASE_BUDGET"
    assert campaign.next_action_for_result(
        {
            "status": "TIME_BUDGET_CHECKPOINT",
            "records": [{"worker_counts": {"SAT_REJECT": 4}}],
        }
    ) == "CONTINUE_FRONTIER"
    assert campaign.next_action_for_result(
        {
            "status": "TIME_BUDGET_CHECKPOINT",
            "records": [
                {"transaction": {"committed": True}},
                {"worker_counts": {"TIMEOUT": 2}},
            ],
        }
    ) == "INCREASE_BUDGET"


if __name__ == "__main__":
    test_checkpoint_selection_keeps_the_lowest_gate_count()
    test_cec_commit_without_frontier_is_discoverable_for_regeneration()
    test_verified_campaign_output_is_a_restart_seed()
    test_worker_count_uses_physical_cores_and_rejects_oversubscription()
    test_abort_reason_policy()
    print("Alg10 smart benchmark campaign tests passed")
