#!/usr/bin/env python3
"""Focused tests for the dynamic cross-circuit TFO worker pool."""

import argparse
import json
import os
import tempfile
from unittest import mock

import alg10_dynamic_tfo_pool_campaign as dynamic
import alg10_parallel_commit_coordinator as coordinator
import alg10_parallel_tfo_benchmark_campaign as benchmark
import alg10_frontier_shard_probe as probe
from verifier import verify_equivalence


def _write_odc_redundant_circuit(path):
    with open(path, "w", encoding="ascii") as f:
        f.write("aag 4 2 0 1 2\n")
        f.write("2\n")
        f.write("4\n")
        f.write("9\n")
        f.write("6 2 4\n")
        f.write("8 7 3\n")


def _fake_state(key, candidates, history=None, inflight=None, last_dispatch=0):
    config = coordinator.CoordinatorConfig(
        checkpoint_dir="/tmp/" + key,
        budgets=(10, 50, 250),
        budget_growth=2.0,
        max_generated_budget=1000,
    )
    return dynamic.PoolCircuitState(
        key=key,
        source_path="",
        seed_checkpoint="",
        seed_work_path="",
        phase_tier="global",
        root="",
        checkpoint_dir="",
        work_path="",
        output_path="",
        events_path="",
        config=config,
        alg_config=probe.Alg10Config(),
        candidates=list(candidates),
        history=dict(history or {}),
        initial_gates=1,
        current_gates=1,
        inflight=set(inflight or ()),
        last_dispatch_seq=last_dispatch,
    )


def test_timeout_candidate_returns_at_the_next_budget():
    candidates = [(3, 0), (4, 0), (5, 0)]
    state = _fake_state(
        "one",
        candidates,
        history={candidate: 10 for candidate in candidates},
    )
    budget, batch, reason = dynamic.select_candidate_batch(state, 16, 6)
    assert budget == 50
    assert batch == [candidates[0]]
    assert reason == "TIMEOUT_RETRY"

    budget, batch, reason = dynamic.select_candidate_batch(state, 16, 6, 2)
    assert budget == 50
    assert batch == candidates[:2]
    assert reason == "TIMEOUT_RETRY"

    targets = dynamic._retry_budget_targets(state, budget, [candidates[0]], reason, 3)
    assert targets == (50, 250, 500)


def test_untried_work_precedes_timeout_retry_and_pool_balances_circuits():
    retried = (3, 0)
    new = (4, 1)
    first = _fake_state(
        "first",
        [retried, new],
        history={retried: 10},
        inflight={(9, 0)},
        last_dispatch=1,
    )
    second = _fake_state("second", [(5, 0)], last_dispatch=2)

    budget, batch, reason = dynamic.select_candidate_batch(first, 16, 6)
    assert budget == 10
    assert batch == [new]
    assert reason == "UNTRIED"

    selected = dynamic.select_ready_circuit([first, second], 16, 6)
    assert selected is second


def test_deadline_admission_scales_history_and_blocks_unknown_tail_work():
    known = (3, 0)
    another = (4, 0)
    state = _fake_state("timed", [known, another])
    state.timing[known] = (10, 2.0)

    fitted = dynamic._fit_batch_to_deadline(
        state,
        50,
        [known, another],
        remaining_seconds=25.0,
        reserve_seconds=1.0,
        unknown_guard_seconds=0.0,
    )
    assert fitted == [known, another]

    fitted = dynamic._fit_batch_to_deadline(
        state,
        50,
        [known, another],
        remaining_seconds=15.0,
        reserve_seconds=1.0,
        unknown_guard_seconds=0.0,
    )
    assert fitted == [known]

    unknown_state = _fake_state("unknown", [known])
    assert dynamic._fit_batch_to_deadline(
        unknown_state,
        10,
        [known],
        remaining_seconds=899.0,
        reserve_seconds=0.0,
        unknown_guard_seconds=900.0,
    ) == []


def _dynamic_args(tmp, seconds=20, jobs=1, budgets="10,50,250"):
    return argparse.Namespace(
        output_dir=os.path.join(tmp, "out"),
        seconds=seconds,
        jobs=jobs,
        budgets=budgets,
        budget_growth=2.0,
        max_generated_budget=1000,
        microbatch_size=1,
        retry_microbatch_size=1,
        persistent_retry_tiers=3,
        worker_cache_entries=1,
        checkpoint_interval=0.0,
        max_targets=1,
        target_filter="",
        checkpoint_dir=[],
        solver="glucose4",
        order="current",
        cec_timeout=10.0,
    )


def test_timeout_history_survives_checkpoint_resume():
    with tempfile.TemporaryDirectory(prefix="alg10_dynamic_retry_resume_") as tmp:
        source = os.path.join(tmp, "source.aag")
        _write_odc_redundant_circuit(source)
        target = benchmark.TargetState(
            key="retry_resume",
            source_path=source,
            seed_checkpoint="",
            seed_work_path=source,
            seed_unresolved=4,
            seed_removed=0,
            phase_tier="fresh",
            last_unresolved=4,
            last_gates=2,
        )
        args = _dynamic_args(tmp)
        state = dynamic._initialize_state(target, args.output_dir, args)
        candidate = state.candidates[0]
        state.candidates = [candidate]
        state.history = {candidate: 10}
        checkpoint = dynamic._persist_state(state, "SAT_TIMEOUT")

        with open(checkpoint, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["phase_resume"]["candidates"] == [
            [candidate[0], candidate[1], 10]
        ]

        resumed_target = benchmark.TargetState(
            key="retry_resume_again",
            source_path=source,
            seed_checkpoint=checkpoint,
            seed_work_path=state.output_path,
            seed_unresolved=1,
            seed_removed=0,
            phase_tier="global",
            last_unresolved=1,
            last_gates=2,
        )
        resumed = dynamic._initialize_state(
            resumed_target,
            os.path.join(tmp, "resumed"),
            args,
        )
        assert resumed.history == {candidate: 10}
        budget, batch, reason = dynamic.select_candidate_batch(resumed, 16, 1)
        assert budget == 50
        assert batch == [candidate]
        assert reason == "TIMEOUT_RETRY"


def test_deferred_unsat_proposal_resumes_serial_recheck_before_dispatch():
    with tempfile.TemporaryDirectory(prefix="alg10_dynamic_deferred_resume_") as tmp:
        source = os.path.join(tmp, "source.aag")
        _write_odc_redundant_circuit(source)
        target = benchmark.TargetState(
            key="deferred_resume",
            source_path=source,
            seed_checkpoint="",
            seed_work_path=source,
            seed_unresolved=4,
            seed_removed=0,
            phase_tier="fresh",
            last_unresolved=4,
            last_gates=2,
        )
        args = _dynamic_args(tmp)
        state = dynamic._initialize_state(target, args.output_dir, args)
        candidate = (0, 0)
        state.candidates = [candidate]
        state.proposals = [
            {
                "ordinal": 0,
                "idx": candidate[0],
                "stuck_value": candidate[1],
                "status": probe.STATUS_UNSAT_PROPOSED,
                "budget": 10,
                "engine": "tfo",
            }
        ]
        checkpoint = dynamic._persist_state(state, "PROPOSAL_DEFERRED_DEADLINE")

        with open(checkpoint, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["phase_resume"]["deferred_proposals"][0]["idx"] == candidate[0]

        resumed_target = benchmark.TargetState(
            key="deferred_resume_again",
            source_path=source,
            seed_checkpoint=checkpoint,
            seed_work_path=state.output_path,
            seed_unresolved=1,
            seed_removed=0,
            phase_tier="global",
            last_unresolved=1,
            last_gates=2,
        )
        resumed = dynamic._initialize_state(
            resumed_target,
            os.path.join(tmp, "resumed"),
            args,
        )
        assert resumed.next_action == "RESUME_SERIAL_RECHECK"
        assert len(resumed.proposals) == 1
        assert dynamic.select_candidate_batch(resumed, 16, 1) == (0, [], "")

        dynamic._finalize_proposals(resumed)
        assert resumed.totals["cec_pass_commits"] == 1
        assert resumed.totals["coordinator_unsat_accept"] == 1
        verify, _ = verify_equivalence(source, resumed.output_path)
        assert verify == "PASS"


def test_dynamic_pool_runs_two_circuits_through_one_shared_executor():
    with tempfile.TemporaryDirectory(prefix="alg10_dynamic_pool_") as tmp:
        sources = []
        targets = []
        for key in ("left", "right"):
            source = os.path.join(tmp, key + ".aag")
            _write_odc_redundant_circuit(source)
            sources.append(source)
            targets.append(
                benchmark.TargetState(
                    key=key,
                    source_path=source,
                    seed_checkpoint="",
                    seed_work_path=source,
                    seed_unresolved=4,
                    seed_removed=0,
                    phase_tier="fresh",
                    last_unresolved=4,
                    last_gates=2,
                )
            )

        args = argparse.Namespace(
            output_dir=os.path.join(tmp, "out"),
            seconds=20,
            jobs=2,
            budgets="1000",
            budget_growth=2.0,
            max_generated_budget=1000,
            microbatch_size=1,
            retry_microbatch_size=1,
            persistent_retry_tiers=1,
            worker_cache_entries=1,
            checkpoint_interval=0.0,
            max_targets=2,
            target_filter="",
            checkpoint_dir=[],
            solver="glucose4",
            order="current",
            cec_timeout=10.0,
        )
        summary = dynamic.run_dynamic_campaign(args, targets=targets)
        by_key = {target["key"]: target for target in summary["targets"]}
        assert set(by_key) == {"left", "right"}
        assert summary["dispatches"] >= 2
        assert summary["pool_metrics"]["max_active_workers"] == 2
        assert summary["pool_metrics"]["tasks_completed"] == summary["dispatches"]
        assert summary["pool_metrics"]["proposal_barriers_completed"] == 2
        assert summary["pool_metrics"]["worker_utilization"] > 0
        for source, key in zip(sources, ("left", "right")):
            output = by_key[key]["output"]
            verify, _ = verify_equivalence(source, output)
            assert verify == "PASS"
            assert by_key[key]["totals"]["worker_errors"] == 0
            assert os.path.exists(
                os.path.join(args.output_dir, key, "pool_events.jsonl")
            )


def test_source_change_stops_dispatch_and_preserves_a_verified_checkpoint():
    with tempfile.TemporaryDirectory(prefix="alg10_dynamic_source_change_") as tmp:
        source = os.path.join(tmp, "source.aag")
        _write_odc_redundant_circuit(source)
        target = benchmark.TargetState(
            key="source_change",
            source_path=source,
            seed_checkpoint="",
            seed_work_path=source,
            seed_unresolved=4,
            seed_removed=0,
            phase_tier="fresh",
            last_unresolved=4,
            last_gates=2,
        )
        args = argparse.Namespace(
            output_dir=os.path.join(tmp, "out"),
            seconds=20,
            jobs=2,
            budgets="1000",
            budget_growth=2.0,
            max_generated_budget=1000,
            microbatch_size=1,
            retry_microbatch_size=1,
            persistent_retry_tiers=1,
            worker_cache_entries=1,
            checkpoint_interval=0.0,
            max_targets=1,
            target_filter="",
            checkpoint_dir=[],
            solver="glucose4",
            order="current",
            cec_timeout=10.0,
        )
        with mock.patch.object(
            dynamic,
            "_source_manifest",
            side_effect=[{"source": "before"}, {"source": "after"}],
        ):
            summary = dynamic.run_dynamic_campaign(args, targets=[target])

        assert summary["status"] == "SOURCE_CHANGED_CHECKPOINT"
        assert summary["dispatches"] == 0
        assert summary["source_manifest"] == {"source": "before"}
        result = summary["targets"][0]
        assert result["status"] == "TIME_BUDGET_CHECKPOINT"
        assert result["totals"]["worker_errors"] == 0
        verify, _ = verify_equivalence(source, result["output"])
        assert verify == "PASS"


if __name__ == "__main__":
    test_timeout_candidate_returns_at_the_next_budget()
    test_untried_work_precedes_timeout_retry_and_pool_balances_circuits()
    test_deadline_admission_scales_history_and_blocks_unknown_tail_work()
    test_timeout_history_survives_checkpoint_resume()
    test_deferred_unsat_proposal_resumes_serial_recheck_before_dispatch()
    test_dynamic_pool_runs_two_circuits_through_one_shared_executor()
    test_source_change_stops_dispatch_and_preserves_a_verified_checkpoint()
    print("Alg10 dynamic TFO pool tests passed")
