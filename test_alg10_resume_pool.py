#!/usr/bin/env python3
"""Focused checks for Algorithm 10 CEX pool and phase-local resume.

These tests exercise the conservative resume rules:
- CEX pool vectors are persisted and replayed as rejection-only witnesses.
- Phase-local global unresolved queues are used only when the checkpoint work
  AAG hash still matches.
- Stale phase-resume metadata falls back to a normal safe checkpoint resume.
- Accepted/rebuilt checkpoints do not keep stale phase-local queues.
"""

import glob
import importlib
import json
import os
import shutil
import sys
import tempfile

from test_alg10_checkpoint import write_odc_redundant_circuit
from verifier import verify_equivalence


ALG10_ENV = [
    "ALG10_MODE",
    "ALG10_BUDGETS",
    "ALG10_MAX_CIRCUIT_SECONDS",
    "ALG10_MAX_PHASES",
    "ALG10_REBUILD_AFTER_COMMITS",
    "ALG10_PRE_STRASH",
    "ALG10_PRE_STRASH_MAX_GATES",
    "ALG10_COMMIT_UNITS",
    "ALG10_CHECKPOINT_DIR",
    "ALG10_RESET_CHECKPOINT",
    "ALG10_CHECKPOINT_SELECT",
    "ALG10_EXTRA_CHECKPOINT_DIRS",
    "ALG10_PROTECT_BEST_CHECKPOINT",
    "ALG10_TFI_CONSTANCY",
    "ALG10_TFI_BUDGET",
    "ALG10_TFI_MAX_CONE_GATES",
    "ALG10_TFI_ENGINE",
    "ALG10_TFI_SOLVER",
    "ALG10_AUDIT_ASSUMPTIONS",
    "ALG10_CANDIDATE_ORDER",
    "ALG10_WINDOW_MITER",
    "ALG10_WINDOW_AUDIT",
    "ALG10_WINDOW_LEVELS",
    "ALG10_WINDOW_ROOT_STRATEGY",
    "ALG10_WINDOW_DOMINATOR_MAX_LEVELS",
    "ALG10_WINDOW_DOMINATOR_MAX_ROOTS",
    "ALG10_WINDOW_BUDGET",
    "ALG10_WINDOW_MAX_CONE_GATES",
    "ALG10_CONE_MITER",
    "ALG10_CONE_ENGINE",
    "ALG10_CONE_SOLVER",
    "ALG10_CONE_GROUP_MIN_SIZE",
    "ALG10_CONE_BUDGET",
    "ALG10_CONE_MAX_GATES",
    "ALG10_GLOBAL_MITER",
    "ALG10_PHASE_LOCAL_RESUME",
    "ALG10_EXACT_FRONTIER_RESUME",
    "ALG10_CEX_POOL",
    "ALG10_CEX_POOL_MAX_VECTORS",
    "ALG10_CEX_POOL_REPLAY_MAX_VECTORS",
    "ALG10_PRE_SIM_REJECTION",
    "ALG10_PRE_SIM_RANDOM_PATTERNS",
    "ALG10_PRE_SIM_WALK_PATTERNS",
    "ALG10_PRE_SIM_MAX_SECONDS",
    "ALG10_PRE_SIM_MAX_FRACTION",
    "ALG10_CEX_PRUNING",
    "ALG10_CEX_PRUNING_BATCH_SIZE",
    "ALG10_AUDIT_CEX_PRUNING",
    "ALG10_AUDIT_CEX_PRUNING_BUDGET",
    "ALG10_AUDIT_CEX_PRUNING_MAX",
]


def load_alg10(**env):
    for key in ALG10_ENV:
        os.environ.pop(key, None)
    defaults = {
        "ALG10_MODE": "fast_save",
        "ALG10_MAX_CIRCUIT_SECONDS": "10",
        "ALG10_BUDGETS": "100,1000",
        "ALG10_RESET_CHECKPOINT": "1",
        "ALG10_TFI_CONSTANCY": "1",
        "ALG10_WINDOW_MITER": "1",
        "ALG10_WINDOW_AUDIT": "1",
        "ALG10_WINDOW_LEVELS": "5",
        "ALG10_CONE_MITER": "1",
        "ALG10_GLOBAL_MITER": "1",
        "ALG10_CANDIDATE_ORDER": "current",
        "ALG10_CEX_PRUNING": "1",
        "ALG10_CEX_PRUNING_BATCH_SIZE": "512",
    }
    defaults.update({key: str(value) for key, value in env.items()})
    os.environ.update(defaults)
    sys.modules.pop("optimizer_alg10_tiered", None)
    return importlib.import_module("optimizer_alg10_tiered")


def run_case(src, out, checkpoint_dir, **env):
    optimizer = load_alg10(ALG10_CHECKPOINT_DIR=checkpoint_dir, **env)
    orig, _, final, removed, timings = optimizer.solve_circuit(src, out)
    status, _ = verify_equivalence(src, out)
    assert status == "PASS", f"CEC failed for {out}: {status}"
    return {
        "orig": orig,
        "final": final,
        "removed": removed,
        "status": status,
        "abort": timings.get("SAT_Abort_Reason", ""),
        "unresolved": timings.get("SAT_Unresolved", 0),
        "checks": timings.get("SAT_Checks", 0),
        "resumed": timings.get("Checkpoint_Resume", 0),
        "checkpoint_status": timings.get("Checkpoint_Status_Loaded", ""),
        "checkpoint_source_dir": timings.get("Checkpoint_Source_Dir", ""),
        "checkpoint_imported_external": timings.get("Checkpoint_Imported_External", 0),
        "checkpoint_start_and2": timings.get("Checkpoint_Start_AND2", ""),
        "checkpoint_start_removed": timings.get("Checkpoint_Start_Removed_AND2", ""),
        "new_removed": timings.get("New_Removed_This_Run", ""),
        "checkpoint_start_unresolved": timings.get("Checkpoint_Start_Unresolved", ""),
        "checkpoint_unresolved_delta": timings.get("Checkpoint_Unresolved_Delta", ""),
        "phase_used": timings.get("Phase_Local_Resume_Used", 0),
        "phase_saved": timings.get("Phase_Local_Resume_Saved", 0),
        "phase_candidates": timings.get("Phase_Local_Resume_Candidates", 0),
        "exact_frontier_enabled": timings.get("Exact_Frontier_Resume_Enabled", 0),
        "exact_frontier_used": timings.get("Exact_Frontier_Resume_Used", 0),
        "exact_frontier_candidates": timings.get("Exact_Frontier_Resume_Candidates", 0),
        "exact_frontier_skipped_lower": timings.get("Exact_Frontier_Skipped_Lower_Tiers", 0),
        "exact_frontier_tier": timings.get("Exact_Frontier_Resume_Tier", ""),
        "budget_history_loaded": timings.get("Global_Budget_History_Loaded", 0),
        "budget_history_skipped": timings.get("Global_Budget_History_Skipped", 0),
        "budget_history_exhausted": timings.get("Global_Budget_History_Exhausted", 0),
        "tfi_checks": timings.get("TFI_Checks", 0),
        "window_checks": timings.get("Window_Checks", 0),
        "cone_checks": timings.get("Cone_Checks", 0),
        "pool_loaded": timings.get("CEX_Pool_Loaded", 0),
        "pool_saved": timings.get("CEX_Pool_Saved", 0),
        "pool_size": timings.get("CEX_Pool_Size", 0),
        "pool_added": timings.get("CEX_Pool_Added", 0),
        "pool_replay_patterns": timings.get("CEX_Pool_Replay_Patterns", 0),
        "pool_replay_pruned": timings.get("CEX_Pool_Replay_Pruned", 0),
        "presim_pruned": timings.get("PreSAT_Sim_Pruned", 0),
        "audit_checked": timings.get("CEX_Audit_Checked", 0),
        "audit_false": timings.get("CEX_Audit_False_Prunes", 0),
        "fault_total": timings.get("Faults_Total", 0),
        "fault_unresolved": timings.get("Faults_Unresolved", 0),
        "fault_coverage": timings.get("Fault_Coverage_Lower_Bound%", ""),
    }


def checkpoint_json(checkpoint_dir):
    paths = sorted(glob.glob(os.path.join(checkpoint_dir, "*.json")))
    paths = [path for path in paths if not path.endswith(".cex.json")]
    assert paths, f"no checkpoint json under {checkpoint_dir}"
    return paths[0]


def cex_pool_json(checkpoint_dir):
    paths = sorted(glob.glob(os.path.join(checkpoint_dir, "*.cex.json")))
    assert paths, f"no cex pool json under {checkpoint_dir}"
    return paths[0]


def load_checkpoint_json(checkpoint_dir):
    with open(checkpoint_json(checkpoint_dir), "r", encoding="utf-8") as f:
        return json.load(f)


def write_odc_reduced_circuit(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="ascii") as f:
        f.write("aag 2 2 0 1 0\n")
        f.write("2\n")
        f.write("4\n")
        f.write("2\n")
        f.write("i0 x\n")
        f.write("i1 y\n")
        f.write("o0 out\n")
        f.write("c\n")
        f.write("Reduced ODC equivalent: out = x\n")


def test_checkpoint_save_preserves_best_unresolved_active_branch():
    with tempfile.TemporaryDirectory(prefix="alg10_protect_unres_") as tmp:
        ckpt = os.path.join(tmp, "ckpt")
        src = os.path.join(tmp, "odc.aag")
        reduced = os.path.join(tmp, "odc_reduced.aag")
        write_odc_redundant_circuit(src)
        write_odc_reduced_circuit(reduced)

        optimizer = load_alg10(
            ALG10_CHECKPOINT_DIR=ckpt,
            ALG10_RESET_CHECKPOINT="0",
            ALG10_CHECKPOINT_SELECT="unresolved",
            ALG10_PROTECT_BEST_CHECKPOINT="1",
        )
        optimizer._save_checkpoint(src, src, {"unresolved": 5}, "TIME_BUDGET_CHECKPOINT")
        optimizer._save_checkpoint(src, reduced, {"unresolved": 99}, "TIME_BUDGET_CHECKPOINT")

        data = load_checkpoint_json(ckpt)
        loaded = optimizer._load_checkpoint(src)
        print(f"protected unresolved checkpoint: {data}")
        assert data["current_gates"] == 2
        assert data["telemetry"]["unresolved"] == 5
        assert loaded["current_gates"] == 2
        assert loaded["telemetry"]["unresolved"] == 5


def test_checkpoint_save_allows_lower_gate_branch_under_gate_policy():
    with tempfile.TemporaryDirectory(prefix="alg10_protect_gates_") as tmp:
        ckpt = os.path.join(tmp, "ckpt")
        src = os.path.join(tmp, "odc.aag")
        reduced = os.path.join(tmp, "odc_reduced.aag")
        write_odc_redundant_circuit(src)
        write_odc_reduced_circuit(reduced)

        optimizer = load_alg10(
            ALG10_CHECKPOINT_DIR=ckpt,
            ALG10_RESET_CHECKPOINT="0",
            ALG10_CHECKPOINT_SELECT="gates",
            ALG10_PROTECT_BEST_CHECKPOINT="1",
        )
        optimizer._save_checkpoint(src, src, {"unresolved": 5}, "TIME_BUDGET_CHECKPOINT")
        optimizer._save_checkpoint(src, reduced, {"unresolved": 99}, "TIME_BUDGET_CHECKPOINT")

        data = load_checkpoint_json(ckpt)
        loaded = optimizer._load_checkpoint(src)
        print(f"protected gates checkpoint: {data}")
        assert data["current_gates"] == 0
        assert data["telemetry"]["unresolved"] == 99
        assert loaded["current_gates"] == 0


def test_checkpoint_save_does_not_shadow_better_external_seed():
    with tempfile.TemporaryDirectory(prefix="alg10_protect_external_") as tmp:
        active = os.path.join(tmp, "active")
        external = os.path.join(tmp, "external")
        src = os.path.join(tmp, "odc.aag")
        reduced = os.path.join(tmp, "odc_reduced.aag")
        write_odc_redundant_circuit(src)
        write_odc_reduced_circuit(reduced)

        external_optimizer = load_alg10(
            ALG10_CHECKPOINT_DIR=external,
            ALG10_RESET_CHECKPOINT="0",
            ALG10_CHECKPOINT_SELECT="unresolved",
            ALG10_PROTECT_BEST_CHECKPOINT="1",
        )
        external_optimizer._save_checkpoint(src, src, {"unresolved": 3}, "TIME_BUDGET_CHECKPOINT")

        active_optimizer = load_alg10(
            ALG10_CHECKPOINT_DIR=active,
            ALG10_EXTRA_CHECKPOINT_DIRS=external,
            ALG10_RESET_CHECKPOINT="0",
            ALG10_CHECKPOINT_SELECT="unresolved",
            ALG10_PROTECT_BEST_CHECKPOINT="1",
        )
        returned = active_optimizer._save_checkpoint(
            src, reduced, {"unresolved": 100}, "TIME_BUDGET_CHECKPOINT"
        )
        loaded = active_optimizer._load_checkpoint(src)
        active_jsons = [
            path
            for path in glob.glob(os.path.join(active, "*.json"))
            if not path.endswith(".cex.json")
        ]
        print(f"external protected checkpoint returned={returned} loaded={loaded}")
        assert not active_jsons
        assert loaded["telemetry"]["unresolved"] == 3
        assert loaded["_checkpoint_imported_external"] == 1


def test_cex_pool_persist_and_replay():
    with tempfile.TemporaryDirectory(prefix="alg10_pool_") as tmp:
        ckpt = os.path.join(tmp, "ckpt")
        c432 = "benchmarks/c432.aag"

        seed_out = os.path.join(tmp, "c432_seed.aag")
        seed = run_case(
            c432,
            seed_out,
            ckpt,
            ALG10_RESET_CHECKPOINT="1",
            ALG10_CEX_POOL="1",
            ALG10_PRE_SIM_REJECTION="1",
            ALG10_PRE_SIM_RANDOM_PATTERNS="16",
            ALG10_PRE_SIM_WALK_PATTERNS="8",
            ALG10_PRE_SIM_MAX_SECONDS="5",
        )
        print(f"cex pool seed: {seed}")
        assert seed["pool_saved"] > 0
        assert seed["pool_added"] > 0
        assert seed["presim_pruned"] > 0
        seed_path = checkpoint_json(ckpt)
        with open(seed_path, "r", encoding="utf-8") as f:
            seed_data = json.load(f)
        seed_data["status"] = "TIME_BUDGET_CHECKPOINT"
        seed_data.setdefault("telemetry", {})["unresolved"] = max(1, seed["fault_total"] // 2)
        with open(seed_path, "w", encoding="utf-8") as f:
            json.dump(seed_data, f, indent=2, sort_keys=True)

        replay_out = os.path.join(tmp, "c432_replay.aag")
        replay = run_case(
            c432,
            replay_out,
            ckpt,
            ALG10_RESET_CHECKPOINT="0",
            ALG10_CEX_POOL="1",
            ALG10_PRE_SIM_REJECTION="0",
            ALG10_MAX_CIRCUIT_SECONDS="10",
        )
        print(f"cex pool replay: {replay}")
        assert replay["resumed"] == 1
        assert replay["pool_loaded"] > 0
        assert replay["pool_replay_patterns"] > 0
        assert replay["pool_replay_pruned"] > 0


def test_cex_pool_stale_metadata_is_ignored():
    with tempfile.TemporaryDirectory(prefix="alg10_pool_stale_") as tmp:
        ckpt = os.path.join(tmp, "ckpt")
        c432 = "benchmarks/c432.aag"

        seed_out = os.path.join(tmp, "c432_seed.aag")
        seed = run_case(
            c432,
            seed_out,
            ckpt,
            ALG10_RESET_CHECKPOINT="1",
            ALG10_CEX_POOL="1",
            ALG10_CEX_POOL_MAX_VECTORS="3",
            ALG10_PRE_SIM_REJECTION="1",
            ALG10_PRE_SIM_RANDOM_PATTERNS="16",
            ALG10_PRE_SIM_WALK_PATTERNS="8",
            ALG10_PRE_SIM_MAX_SECONDS="5",
        )
        print(f"cex pool capped seed: {seed}")
        assert seed["pool_saved"] == 3

        pool_path = cex_pool_json(ckpt)
        with open(pool_path, "r", encoding="utf-8") as f:
            pool = json.load(f)
        pool["source_sha256"] = "stale"
        with open(pool_path, "w", encoding="utf-8") as f:
            json.dump(pool, f, indent=2, sort_keys=True)

        stale_out = os.path.join(tmp, "c432_stale_pool.aag")
        stale = run_case(
            c432,
            stale_out,
            ckpt,
            ALG10_RESET_CHECKPOINT="0",
            ALG10_CEX_POOL="1",
            ALG10_PRE_SIM_REJECTION="0",
            ALG10_MAX_CIRCUIT_SECONDS="10",
        )
        print(f"cex pool stale metadata: {stale}")
        assert stale["pool_loaded"] == 0
        assert stale["pool_replay_patterns"] == 0


def test_phase_local_resume_valid_and_stale_fallback():
    with tempfile.TemporaryDirectory(prefix="alg10_phase_") as tmp:
        ckpt = os.path.join(tmp, "ckpt")
        c432 = "benchmarks/c432.aag"

        partial_out = os.path.join(tmp, "c432_partial.aag")
        partial = run_case(
            c432,
            partial_out,
            ckpt,
            ALG10_RESET_CHECKPOINT="1",
            ALG10_TFI_CONSTANCY="0",
            ALG10_WINDOW_MITER="0",
            ALG10_CONE_MITER="0",
            ALG10_GLOBAL_MITER="1",
            ALG10_PHASE_LOCAL_RESUME="1",
            ALG10_MAX_CIRCUIT_SECONDS="0.01",
            ALG10_BUDGETS="1",
            ALG10_CEX_PRUNING="0",
        )
        print(f"phase partial: {partial}")
        assert partial["phase_saved"] == 1
        assert partial["phase_candidates"] > 0
        checkpoint = load_checkpoint_json(ckpt)
        assert checkpoint.get("phase_resume")

        stale = load_checkpoint_json(ckpt)
        stale["phase_resume"]["work_sha256"] = "stale"
        with open(checkpoint_json(ckpt), "w", encoding="utf-8") as f:
            json.dump(stale, f, indent=2, sort_keys=True)

        stale_out = os.path.join(tmp, "c432_stale.aag")
        stale_run = run_case(
            c432,
            stale_out,
            ckpt,
            ALG10_RESET_CHECKPOINT="0",
            ALG10_TFI_CONSTANCY="0",
            ALG10_WINDOW_MITER="0",
            ALG10_CONE_MITER="0",
            ALG10_GLOBAL_MITER="1",
            ALG10_PHASE_LOCAL_RESUME="1",
            ALG10_MAX_CIRCUIT_SECONDS="10",
            ALG10_BUDGETS="100,1000",
            ALG10_CEX_PRUNING="1",
        )
        print(f"phase stale fallback: {stale_run}")
        assert stale_run["resumed"] == 1
        assert stale_run["phase_used"] == 0

        phase_ckpt = os.path.join(tmp, "ckpt_phase")
        partial = run_case(
            c432,
            partial_out,
            phase_ckpt,
            ALG10_RESET_CHECKPOINT="1",
            ALG10_TFI_CONSTANCY="0",
            ALG10_WINDOW_MITER="0",
            ALG10_CONE_MITER="0",
            ALG10_GLOBAL_MITER="1",
            ALG10_PHASE_LOCAL_RESUME="1",
            ALG10_MAX_CIRCUIT_SECONDS="0.01",
            ALG10_BUDGETS="1",
            ALG10_CEX_PRUNING="0",
        )
        assert partial["phase_saved"] == 1

        resumed_out = os.path.join(tmp, "c432_resumed.aag")
        resumed = run_case(
            c432,
            resumed_out,
            phase_ckpt,
            ALG10_RESET_CHECKPOINT="0",
            ALG10_TFI_CONSTANCY="0",
            ALG10_WINDOW_MITER="0",
            ALG10_CONE_MITER="0",
            ALG10_GLOBAL_MITER="1",
            ALG10_PHASE_LOCAL_RESUME="1",
            ALG10_MAX_CIRCUIT_SECONDS="10",
            ALG10_BUDGETS="100,1000",
            ALG10_CEX_PRUNING="1",
        )
        print(f"phase valid resume: {resumed}")
        assert resumed["resumed"] == 1
        assert resumed["phase_used"] == 1


def test_external_checkpoint_preserves_valid_phase_resume():
    with tempfile.TemporaryDirectory(prefix="alg10_external_phase_") as tmp:
        external_ckpt = os.path.join(tmp, "external")
        active_ckpt = os.path.join(tmp, "active")
        c432 = "benchmarks/c432.aag"

        seed = run_case(
            c432,
            os.path.join(tmp, "seed.aag"),
            external_ckpt,
            ALG10_RESET_CHECKPOINT="1",
            ALG10_TFI_CONSTANCY="0",
            ALG10_WINDOW_MITER="0",
            ALG10_CONE_MITER="0",
            ALG10_GLOBAL_MITER="1",
            ALG10_PHASE_LOCAL_RESUME="1",
            ALG10_MAX_CIRCUIT_SECONDS="0.01",
            ALG10_BUDGETS="1",
            ALG10_CEX_PRUNING="0",
        )
        print(f"external phase seed: {seed}")
        assert seed["phase_saved"] == 1

        resumed = run_case(
            c432,
            os.path.join(tmp, "resumed.aag"),
            active_ckpt,
            ALG10_RESET_CHECKPOINT="0",
            ALG10_EXTRA_CHECKPOINT_DIRS=external_ckpt,
            ALG10_TFI_CONSTANCY="1",
            ALG10_WINDOW_MITER="1",
            ALG10_CONE_MITER="1",
            ALG10_GLOBAL_MITER="1",
            ALG10_PHASE_LOCAL_RESUME="1",
            ALG10_EXACT_FRONTIER_RESUME="1",
            ALG10_MAX_PHASES="1",
            ALG10_MAX_CIRCUIT_SECONDS="10",
            ALG10_BUDGETS="100,1000",
            ALG10_CEX_PRUNING="1",
        )
        print(f"external phase resume: {resumed}")
        assert resumed["resumed"] == 1
        assert resumed["checkpoint_imported_external"] == 1
        assert resumed["phase_used"] == 1
        assert resumed["exact_frontier_used"] == 1


def test_checkpoint_rank_counts_tier_pending_and_escalated():
    optimizer = load_alg10(
        ALG10_CHECKPOINT_SELECT="unresolved",
        ALG10_PHASE_LOCAL_RESUME="1",
    )
    data = {
        "current_gates": 0,
        "timestamp": 0,
        "telemetry": {"unresolved": 1},
        "phase_resume": {
            "schema": "alg10_tier_frontier_v1",
            "tier": "cone",
            "pending": [[0, 0]],
            "escalated": [[1, 0], [2, 1]],
        },
    }
    rank = optimizer._checkpoint_rank_from_data(data, "benchmarks/c432.aag")
    assert rank[0] == 3


def test_tier_frontier_overlap_and_duplicates_are_rejected():
    optimizer = load_alg10(ALG10_PHASE_LOCAL_RESUME="1")
    c432 = "benchmarks/c432.aag"
    gate_count = optimizer.parse_aag(c432)[4]
    base = {
        "schema": "alg10_tier_frontier_v1",
        "tier": "window",
        "work_sha256": optimizer._sha256_file(c432),
        "gate_count": gate_count,
        "pending": [[0, 0]],
        "escalated": [[0, 0]],
    }
    assert optimizer._valid_phase_resume_state(base, c432, gate_count) is None

    duplicate = dict(base)
    duplicate["pending"] = [[0, 0], [0, 0]]
    duplicate["escalated"] = []
    assert optimizer._valid_phase_resume_state(duplicate, c432, gate_count) is None

    global_duplicate = {
        "schema": "alg10_global_frontier_v1",
        "tier": "global",
        "work_sha256": optimizer._sha256_file(c432),
        "gate_count": gate_count,
        "candidates": [[0, 0, 1000], [0, 0, 5000]],
    }
    assert optimizer._valid_phase_resume_state(global_duplicate, c432, gate_count) is None


def test_untried_first_global_frontier_order():
    optimizer = load_alg10(ALG10_GLOBAL_FRONTIER_ORDER="untried_first")
    gates_raw = optimizer.parse_aag("benchmarks/c432.aag")[8]
    candidates = [(0, 0), (1, 0), (2, 0), (3, 0)]
    ordered = optimizer._order_global_frontier(
        candidates,
        gates_raw,
        {
            (0, 0): 1000,
            (2, 0): 5000,
        },
    )
    assert ordered == [(1, 0), (3, 0), (0, 0), (2, 0)]


def test_exact_frontier_resume_skips_completed_lower_tiers():
    with tempfile.TemporaryDirectory(prefix="alg10_exact_frontier_") as tmp:
        ckpt = os.path.join(tmp, "ckpt")
        c432 = "benchmarks/c432.aag"

        partial_out = os.path.join(tmp, "c432_partial.aag")
        partial = run_case(
            c432,
            partial_out,
            ckpt,
            ALG10_RESET_CHECKPOINT="1",
            ALG10_TFI_CONSTANCY="0",
            ALG10_WINDOW_MITER="0",
            ALG10_CONE_MITER="0",
            ALG10_GLOBAL_MITER="1",
            ALG10_PHASE_LOCAL_RESUME="1",
            ALG10_MAX_CIRCUIT_SECONDS="0.01",
            ALG10_BUDGETS="1",
            ALG10_CEX_PRUNING="0",
        )
        print(f"exact frontier seed: {partial}")
        assert partial["phase_saved"] == 1
        checkpoint = load_checkpoint_json(ckpt)
        assert checkpoint.get("phase_resume", {}).get("tier") == "global"

        exact_out = os.path.join(tmp, "c432_exact.aag")
        exact = run_case(
            c432,
            exact_out,
            ckpt,
            ALG10_RESET_CHECKPOINT="0",
            ALG10_TFI_CONSTANCY="1",
            ALG10_WINDOW_MITER="1",
            ALG10_CONE_MITER="1",
            ALG10_GLOBAL_MITER="1",
            ALG10_PHASE_LOCAL_RESUME="1",
            ALG10_EXACT_FRONTIER_RESUME="1",
            ALG10_MAX_PHASES="1",
            ALG10_MAX_CIRCUIT_SECONDS="10",
            ALG10_BUDGETS="100,1000",
            ALG10_CEX_PRUNING="1",
        )
        print(f"exact frontier resume: {exact}")
        assert exact["resumed"] == 1
        assert exact["phase_used"] == 1
        assert exact["exact_frontier_used"] == 1
        assert exact["exact_frontier_skipped_lower"] == 1
        assert exact["exact_frontier_candidates"] > 0
        assert exact["tfi_checks"] == 0
        assert exact["window_checks"] == 0
        assert exact["cone_checks"] == 0


def test_exact_frontier_resume_for_tfi_window_and_cone():
    tier_configs = {
        "tfi": {
            "seed": {
                "ALG10_TFI_CONSTANCY": "1",
                "ALG10_WINDOW_MITER": "0",
                "ALG10_CONE_MITER": "0",
                "ALG10_GLOBAL_MITER": "0",
            },
            "skipped_lower": 1,
        },
        "window": {
            "seed": {
                "ALG10_TFI_CONSTANCY": "0",
                "ALG10_WINDOW_MITER": "1",
                "ALG10_CONE_MITER": "0",
                "ALG10_GLOBAL_MITER": "0",
            },
            "skipped_lower": 2,
        },
        "cone": {
            "seed": {
                "ALG10_TFI_CONSTANCY": "0",
                "ALG10_WINDOW_MITER": "0",
                "ALG10_CONE_MITER": "1",
                "ALG10_GLOBAL_MITER": "0",
            },
            "skipped_lower": 3,
        },
    }

    for tier, cfg in tier_configs.items():
        with tempfile.TemporaryDirectory(prefix=f"alg10_{tier}_frontier_") as tmp:
            ckpt = os.path.join(tmp, "ckpt")
            c432 = "benchmarks/c432.aag"
            seed_out = os.path.join(tmp, f"c432_{tier}_seed.aag")
            seed = run_case(
                c432,
                seed_out,
                ckpt,
                ALG10_RESET_CHECKPOINT="1",
                ALG10_PHASE_LOCAL_RESUME="1",
                ALG10_MAX_CIRCUIT_SECONDS="0.002",
                ALG10_BUDGETS="1",
                ALG10_CEX_PRUNING="0",
                ALG10_CEX_POOL="0",
                ALG10_PRE_SIM_REJECTION="0",
                **cfg["seed"],
            )
            checkpoint = load_checkpoint_json(ckpt)
            print(f"{tier} frontier seed: {seed}")
            assert checkpoint.get("phase_resume", {}).get("tier") == tier
            assert checkpoint["phase_resume"].get("schema") == "alg10_tier_frontier_v1"
            assert checkpoint["phase_resume"].get("pending")

            resume_out = os.path.join(tmp, f"c432_{tier}_resume.aag")
            resumed = run_case(
                c432,
                resume_out,
                ckpt,
                ALG10_RESET_CHECKPOINT="0",
                ALG10_TFI_CONSTANCY="1",
                ALG10_WINDOW_MITER="1",
                ALG10_CONE_MITER="1",
                ALG10_GLOBAL_MITER="1",
                ALG10_PHASE_LOCAL_RESUME="1",
                ALG10_EXACT_FRONTIER_RESUME="1",
                ALG10_MAX_PHASES="1",
                ALG10_MAX_CIRCUIT_SECONDS="10",
                ALG10_BUDGETS="100,1000",
                ALG10_CEX_PRUNING="1",
            )
            print(f"{tier} frontier resume: {resumed}")
            assert resumed["resumed"] == 1
            assert resumed["exact_frontier_used"] == 1
            assert resumed["exact_frontier_tier"] == tier
            assert resumed["exact_frontier_skipped_lower"] == cfg["skipped_lower"]
            if tier == "window":
                assert resumed["tfi_checks"] == 0
            if tier == "cone":
                assert resumed["tfi_checks"] == 0
                assert resumed["window_checks"] == 0


def test_rebuild_checkpoint_drops_phase_resume():
    with tempfile.TemporaryDirectory(prefix="alg10_rebuild_") as tmp:
        ckpt = os.path.join(tmp, "ckpt")
        odc = os.path.join(tmp, "odc.aag")
        out = os.path.join(tmp, "odc_out.aag")
        write_odc_redundant_circuit(odc)

        result = run_case(
            odc,
            out,
            ckpt,
            ALG10_RESET_CHECKPOINT="1",
            ALG10_PHASE_LOCAL_RESUME="1",
            ALG10_CEX_POOL="1",
            ALG10_MAX_CIRCUIT_SECONDS="10",
            ALG10_BUDGETS="100,1000",
        )
        print(f"rebuild drops phase state: {result}")
        assert result["final"] < result["orig"]
        checkpoint = load_checkpoint_json(ckpt)
        assert checkpoint.get("phase_resume") is None


def test_checkpoint_resume_survives_dataset_path_change():
    with tempfile.TemporaryDirectory(prefix="alg10_content_ckpt_") as tmp:
        ckpt = os.path.join(tmp, "ckpt")
        first_dir = os.path.join(tmp, "dataset_a")
        second_dir = os.path.join(tmp, "dataset_b")
        os.makedirs(first_dir)
        os.makedirs(second_dir)
        first_src = os.path.join(first_dir, "c432.aag")
        second_src = os.path.join(second_dir, "c432.aag")
        shutil.copy("benchmarks/c432.aag", first_src)
        shutil.copy("benchmarks/c432.aag", second_src)

        first = run_case(
            first_src,
            os.path.join(tmp, "first.aag"),
            ckpt,
            ALG10_RESET_CHECKPOINT="1",
            ALG10_CEX_POOL="1",
            ALG10_MAX_CIRCUIT_SECONDS="10",
            ALG10_BUDGETS="100,1000",
        )
        print(f"content checkpoint seed: {first}")
        assert first["status"] == "PASS"

        second = run_case(
            second_src,
            os.path.join(tmp, "second.aag"),
            ckpt,
            ALG10_RESET_CHECKPOINT="0",
            ALG10_CEX_POOL="1",
            ALG10_MAX_CIRCUIT_SECONDS="10",
            ALG10_BUDGETS="100,1000",
        )
        print(f"content checkpoint path-change resume: {second}")
        assert second["status"] == "PASS"
        assert second["resumed"] == 1
        assert second["checkpoint_start_and2"] == first["final"]
        assert second["checkpoint_start_removed"] == first["removed"]


def test_checkpoint_resume_chooses_best_same_source_branch():
    with tempfile.TemporaryDirectory(prefix="alg10_best_ckpt_") as tmp:
        ckpt = os.path.join(tmp, "ckpt")
        first_dir = os.path.join(tmp, "dataset_a")
        second_dir = os.path.join(tmp, "dataset_b")
        os.makedirs(first_dir)
        os.makedirs(second_dir)
        first_src = os.path.join(first_dir, "c432.aag")
        second_src = os.path.join(second_dir, "c432.aag")
        shutil.copy("benchmarks/c432.aag", first_src)
        shutil.copy("benchmarks/c432.aag", second_src)

        first = run_case(
            first_src,
            os.path.join(tmp, "first.aag"),
            ckpt,
            ALG10_RESET_CHECKPOINT="1",
            ALG10_MAX_CIRCUIT_SECONDS="10",
            ALG10_BUDGETS="100,1000",
        )
        print(f"best checkpoint good seed: {first}")
        assert first["status"] == "PASS"
        assert first["removed"] > 0

        optimizer = load_alg10(
            ALG10_CHECKPOINT_DIR=ckpt,
            ALG10_RESET_CHECKPOINT="0",
            ALG10_MAX_CIRCUIT_SECONDS="10",
        )
        good_json = checkpoint_json(ckpt)
        with open(good_json, "r", encoding="utf-8") as f:
            good_data = json.load(f)
        legacy_stem = optimizer._checkpoint_path_stem(first_src)
        legacy_json, legacy_work = optimizer._checkpoint_path_pair(legacy_stem)
        shutil.copy(good_json, legacy_json)
        shutil.copy(good_data["work_aag"], legacy_work)
        with open(legacy_json, "r", encoding="utf-8") as f:
            legacy_data = json.load(f)
        legacy_data["work_aag"] = legacy_work
        legacy_data["current_gates"] = first["final"]
        legacy_data["telemetry"]["unresolved"] = 0
        with open(legacy_json, "w", encoding="utf-8") as f:
            json.dump(legacy_data, f, indent=2, sort_keys=True)

        content_json, content_work = optimizer._checkpoint_paths(second_src)
        shutil.copy(second_src, content_work)
        worse_data = dict(good_data)
        worse_data["source_path"] = os.path.abspath(second_src)
        worse_data["work_aag"] = content_work
        worse_data["current_gates"] = first["orig"]
        worse_data["telemetry"] = dict(good_data.get("telemetry", {}))
        worse_data["telemetry"]["unresolved"] = 999999
        with open(content_json, "w", encoding="utf-8") as f:
            json.dump(worse_data, f, indent=2, sort_keys=True)

        second = run_case(
            second_src,
            os.path.join(tmp, "second.aag"),
            ckpt,
            ALG10_RESET_CHECKPOINT="0",
            ALG10_MAX_CIRCUIT_SECONDS="10",
            ALG10_BUDGETS="100,1000",
        )
        print(f"best checkpoint path-change resume: {second}")
        assert second["status"] == "PASS"
        assert second["resumed"] == 1
        assert second["checkpoint_start_and2"] == first["final"]
        assert second["checkpoint_start_removed"] == first["removed"]


def test_audit_with_pool_and_presim():
    with tempfile.TemporaryDirectory(prefix="alg10_audit_pool_") as tmp:
        ckpt = os.path.join(tmp, "ckpt")
        c432 = "benchmarks/c432.aag"
        out = os.path.join(tmp, "c432_audit.aag")
        result = run_case(
            c432,
            out,
            ckpt,
            ALG10_RESET_CHECKPOINT="1",
            ALG10_CEX_POOL="1",
            ALG10_PRE_SIM_REJECTION="1",
            ALG10_PRE_SIM_RANDOM_PATTERNS="8",
            ALG10_PRE_SIM_WALK_PATTERNS="4",
            ALG10_AUDIT_CEX_PRUNING="1",
            ALG10_AUDIT_CEX_PRUNING_BUDGET="20000",
            ALG10_AUDIT_CEX_PRUNING_MAX="2000",
            ALG10_MAX_CIRCUIT_SECONDS="10",
        )
        print(f"audit pool/presim: {result}")
        assert result["audit_checked"] > 0
        assert result["audit_false"] == 0
        assert result["fault_total"] > 0
        assert result["fault_unresolved"] >= 0


def run_all():
    test_cex_pool_persist_and_replay()
    test_cex_pool_stale_metadata_is_ignored()
    test_phase_local_resume_valid_and_stale_fallback()
    test_external_checkpoint_preserves_valid_phase_resume()
    test_checkpoint_rank_counts_tier_pending_and_escalated()
    test_tier_frontier_overlap_and_duplicates_are_rejected()
    test_untried_first_global_frontier_order()
    test_exact_frontier_resume_skips_completed_lower_tiers()
    test_exact_frontier_resume_for_tfi_window_and_cone()
    test_rebuild_checkpoint_drops_phase_resume()
    test_checkpoint_resume_survives_dataset_path_change()
    test_checkpoint_resume_chooses_best_same_source_branch()
    test_audit_with_pool_and_presim()


if __name__ == "__main__":
    run_all()
