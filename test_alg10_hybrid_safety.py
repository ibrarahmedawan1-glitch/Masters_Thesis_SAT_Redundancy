#!/usr/bin/env python3
"""Hybrid safety regression for the next Alg10 SAT-side work.

This test intentionally combines the current thesis-critical mechanisms before
adding more SAT-side state:
- enhanced resume loads the safe checkpoint and reports per-session progress;
- persistent CEX pools remain rejection-only and replayable;
- phase-local queues are used only under a matching work-AAG SHA;
- stale phase-local state falls back safely;
- every produced AAG still passes independent ABC CEC.
"""

import json
import os
import tempfile

from test_alg10_resume_pool import (
    checkpoint_json,
    load_checkpoint_json,
    run_case,
)


def _assert_progress_columns(result):
    assert result["checkpoint_status"] != ""
    assert isinstance(result["checkpoint_start_and2"], int)
    assert isinstance(result["checkpoint_start_removed"], int)
    assert isinstance(result["new_removed"], int)
    assert isinstance(result["checkpoint_start_unresolved"], int)
    assert isinstance(result["checkpoint_unresolved_delta"], int)


def test_enhanced_resume_progress_and_pool_are_safe():
    with tempfile.TemporaryDirectory(prefix="alg10_hybrid_pool_") as tmp:
        ckpt = os.path.join(tmp, "ckpt")
        src = "benchmarks/c432.aag"

        first = run_case(
            src,
            os.path.join(tmp, "first.aag"),
            ckpt,
            ALG10_RESET_CHECKPOINT="1",
            ALG10_MODE="deep_resume",
            ALG10_BUDGETS="1000,5000,20000",
            ALG10_MAX_CIRCUIT_SECONDS="20",
            ALG10_CEX_POOL="1",
            ALG10_PHASE_LOCAL_RESUME="1",
            ALG10_PRE_SIM_REJECTION="1",
            ALG10_PRE_SIM_RANDOM_PATTERNS="16",
            ALG10_PRE_SIM_WALK_PATTERNS="8",
            ALG10_PRE_SIM_MAX_SECONDS="5",
            ALG10_PRE_SIM_MAX_FRACTION="0.25",
        )
        print(f"hybrid enhanced first: {first}")
        assert first["status"] == "PASS"
        assert first["removed"] == 4
        assert first["pool_saved"] > 0
        assert first["presim_pruned"] > 0

        second = run_case(
            src,
            os.path.join(tmp, "second.aag"),
            ckpt,
            ALG10_RESET_CHECKPOINT="0",
            ALG10_MODE="deep_resume",
            ALG10_BUDGETS="1000,5000,20000",
            ALG10_MAX_CIRCUIT_SECONDS="20",
            ALG10_CEX_POOL="1",
            ALG10_PHASE_LOCAL_RESUME="1",
            ALG10_PRE_SIM_REJECTION="1",
            ALG10_PRE_SIM_RANDOM_PATTERNS="16",
            ALG10_PRE_SIM_WALK_PATTERNS="8",
            ALG10_PRE_SIM_MAX_SECONDS="5",
            ALG10_PRE_SIM_MAX_FRACTION="0.25",
        )
        print(f"hybrid enhanced resume: {second}")
        assert second["status"] == "PASS"
        assert second["resumed"] == 1
        assert second["pool_loaded"] > 0
        if first["unresolved"] > 0:
            assert second["pool_replay_patterns"] > 0
            assert second["pool_replay_pruned"] > 0
        else:
            assert second["checks"] == 0
            assert second["pool_replay_patterns"] == 0
        assert second["final"] <= first["final"]
        assert second["removed"] >= first["removed"]
        _assert_progress_columns(second)
        assert second["checkpoint_start_removed"] == first["removed"]
        assert second["new_removed"] == second["removed"] - first["removed"]


def test_phase_queue_resume_and_stale_fallback_are_safe():
    with tempfile.TemporaryDirectory(prefix="alg10_hybrid_phase_") as tmp:
        ckpt = os.path.join(tmp, "ckpt")
        src = "benchmarks/c432.aag"

        partial = run_case(
            src,
            os.path.join(tmp, "partial.aag"),
            ckpt,
            ALG10_RESET_CHECKPOINT="1",
            ALG10_TFI_CONSTANCY="0",
            ALG10_WINDOW_MITER="0",
            ALG10_CONE_MITER="0",
            ALG10_GLOBAL_MITER="1",
            ALG10_PHASE_LOCAL_RESUME="1",
            ALG10_CEX_POOL="1",
            ALG10_CEX_PRUNING="0",
            ALG10_PRE_SIM_REJECTION="0",
            ALG10_MAX_CIRCUIT_SECONDS="0.01",
            ALG10_BUDGETS="1",
        )
        print(f"hybrid phase partial: {partial}")
        assert partial["status"] == "PASS"
        assert partial["phase_saved"] == 1
        assert partial["phase_candidates"] > 0
        assert partial["unresolved"] > 0
        checkpoint = load_checkpoint_json(ckpt)
        assert checkpoint.get("phase_resume")

        resumed = run_case(
            src,
            os.path.join(tmp, "resumed.aag"),
            ckpt,
            ALG10_RESET_CHECKPOINT="0",
            ALG10_TFI_CONSTANCY="0",
            ALG10_WINDOW_MITER="0",
            ALG10_CONE_MITER="0",
            ALG10_GLOBAL_MITER="1",
            ALG10_PHASE_LOCAL_RESUME="1",
            ALG10_CEX_POOL="1",
            ALG10_CEX_PRUNING="1",
            ALG10_PRE_SIM_REJECTION="0",
            ALG10_MAX_CIRCUIT_SECONDS="10",
            ALG10_BUDGETS="100,1000",
        )
        print(f"hybrid phase resume: {resumed}")
        assert resumed["status"] == "PASS"
        assert resumed["resumed"] == 1
        assert resumed["phase_used"] == 1
        _assert_progress_columns(resumed)
        assert resumed["checkpoint_start_unresolved"] == partial["unresolved"]

        stale = load_checkpoint_json(ckpt)
        stale["phase_resume"] = stale.get("phase_resume") or {}
        stale["phase_resume"]["work_sha256"] = "stale"
        with open(checkpoint_json(ckpt), "w", encoding="utf-8") as f:
            json.dump(stale, f, indent=2, sort_keys=True)

        fallback = run_case(
            src,
            os.path.join(tmp, "fallback.aag"),
            ckpt,
            ALG10_RESET_CHECKPOINT="0",
            ALG10_TFI_CONSTANCY="0",
            ALG10_WINDOW_MITER="0",
            ALG10_CONE_MITER="0",
            ALG10_GLOBAL_MITER="1",
            ALG10_PHASE_LOCAL_RESUME="1",
            ALG10_CEX_POOL="1",
            ALG10_CEX_PRUNING="1",
            ALG10_PRE_SIM_REJECTION="0",
            ALG10_MAX_CIRCUIT_SECONDS="10",
            ALG10_BUDGETS="100,1000",
        )
        print(f"hybrid stale fallback: {fallback}")
        assert fallback["status"] == "PASS"
        assert fallback["resumed"] == 1
        assert fallback["phase_used"] == 0


def test_phase_budget_history_skips_repeated_equal_budget():
    with tempfile.TemporaryDirectory(prefix="alg10_hybrid_budget_") as tmp:
        ckpt = os.path.join(tmp, "ckpt")
        src = "benchmarks/c432.aag"

        partial = run_case(
            src,
            os.path.join(tmp, "partial.aag"),
            ckpt,
            ALG10_RESET_CHECKPOINT="1",
            ALG10_TFI_CONSTANCY="0",
            ALG10_WINDOW_MITER="0",
            ALG10_CONE_MITER="0",
            ALG10_GLOBAL_MITER="1",
            ALG10_PHASE_LOCAL_RESUME="1",
            ALG10_CEX_POOL="0",
            ALG10_CEX_PRUNING="0",
            ALG10_PRE_SIM_REJECTION="0",
            ALG10_MAX_CIRCUIT_SECONDS="0.01",
            ALG10_BUDGETS="1",
        )
        print(f"hybrid budget-history partial: {partial}")
        assert partial["status"] == "PASS"
        assert partial["phase_saved"] == 1

        checkpoint = load_checkpoint_json(ckpt)
        entries = checkpoint["phase_resume"]["candidates"]
        tried = [entry[2] for entry in entries if len(entry) == 3 and entry[2] > 0]
        assert tried, "partial checkpoint did not persist per-candidate budget history"

        resumed = run_case(
            src,
            os.path.join(tmp, "resumed.aag"),
            ckpt,
            ALG10_RESET_CHECKPOINT="0",
            ALG10_TFI_CONSTANCY="0",
            ALG10_WINDOW_MITER="0",
            ALG10_CONE_MITER="0",
            ALG10_GLOBAL_MITER="1",
            ALG10_PHASE_LOCAL_RESUME="1",
            ALG10_CEX_POOL="0",
            ALG10_CEX_PRUNING="0",
            ALG10_PRE_SIM_REJECTION="0",
            ALG10_MAX_CIRCUIT_SECONDS="1",
            ALG10_BUDGETS="1",
        )
        print(f"hybrid budget-history resume: {resumed}")
        assert resumed["status"] == "PASS"
        assert resumed["resumed"] == 1
        assert resumed["phase_used"] == 1
        assert resumed["budget_history_loaded"] > 0
        assert resumed["budget_history_skipped"] > 0


def test_grouped_cone_full_pipeline_assumption_audit_is_safe():
    with tempfile.TemporaryDirectory(prefix="alg10_grouped_audit_") as tmp:
        ckpt = os.path.join(tmp, "ckpt")
        result = run_case(
            "benchmarks/c432.aag",
            os.path.join(tmp, "grouped_audit.aag"),
            ckpt,
            ALG10_RESET_CHECKPOINT="1",
            ALG10_TFI_CONSTANCY="0",
            ALG10_WINDOW_MITER="0",
            ALG10_CONE_MITER="1",
            ALG10_CONE_ENGINE="grouped",
            ALG10_CONE_SOLVER="glucose4",
            ALG10_CONE_GROUP_MIN_SIZE="1",
            ALG10_GLOBAL_MITER="1",
            ALG10_CEX_PRUNING="0",
            ALG10_PRE_SIM_REJECTION="0",
            ALG10_AUDIT_ASSUMPTIONS="1",
            ALG10_MAX_CIRCUIT_SECONDS="20",
            ALG10_BUDGETS="1000,5000",
        )
        print(f"grouped cone full-pipeline audit: {result}")
        assert result["status"] == "PASS"
        assert result["removed"] == 4
        assert result["unresolved"] == 0


def run_all():
    test_enhanced_resume_progress_and_pool_are_safe()
    test_phase_queue_resume_and_stale_fallback_are_safe()
    test_phase_budget_history_skips_repeated_equal_budget()
    test_grouped_cone_full_pipeline_assumption_audit_is_safe()


if __name__ == "__main__":
    run_all()
