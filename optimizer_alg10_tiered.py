#!/usr/bin/env python3
"""
optimizer_alg10_tiered.py
=========================
Checkpointed, budget-cycling global SAT redundancy removal for ASCII AIGER.

Algorithm 10 deliberately keeps the proof surface conservative. It does not
accept candidates from random simulation or unsound windows. Every accepted
stuck-at replacement is proved by SAT in a sound tier: TFI constancy, exact
affected-output cone miter, or the full good-vs-configurable-faulty global
miter. The rewritten AAG is still verified by the main pipeline's final ABC CEC
step.

The new contribution is scheduling and persistence:
- all stuck-at candidates are reachable; no candidate cap is used;
- candidates are retried with increasing conflict budgets;
- hard/time-limited circuits write the latest safe optimized AAG;
- a checkpoint work AAG allows the next run to resume from that safe state.

Experimental exact cone engines also include affected-root partitions and a
single-fault TFO slice. They remain opt-in and preserve the same UNSAT-only
acceptance boundary.
"""

import glob
import hashlib
import json
import os
import random
import shutil
import tempfile
import time

from pysat.solvers import Glucose4, Solver

from optimizer_alg8_hybrid import (
    _CNFBuilder,
    _build_fault_sweep_cnf,
    _copy_gates,
    _parse_latch,
    parse_aag,
    pure_python_forward_strash,
    write_aag,
)


def _parse_budget_list(raw):
    budgets = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        value = int(part)
        if value > 0:
            budgets.append(value)
    return budgets or [1000, 5000, 20000]


MODE = os.environ.get("ALG10_MODE", "fast_save").strip().lower()
if MODE not in {"fast_save", "deep_resume"}:
    MODE = "fast_save"

DEFAULT_BUDGETS = "100,1000,5000" if MODE == "fast_save" else "1000,5000,20000,100000"
SAT_BUDGETS = _parse_budget_list(os.environ.get("ALG10_BUDGETS", DEFAULT_BUDGETS))
MAX_CIRCUIT_SECONDS = float(
    os.environ.get("ALG10_MAX_CIRCUIT_SECONDS", "60" if MODE == "fast_save" else "600")
)
MAX_PHASES = int(os.environ.get("ALG10_MAX_PHASES", "100"))
REBUILD_AFTER_COMMITS = int(os.environ.get("ALG10_REBUILD_AFTER_COMMITS", "100"))
PRE_STRASH = os.environ.get("ALG10_PRE_STRASH", "1") != "0"
PRE_STRASH_MAX_GATES = int(os.environ.get("ALG10_PRE_STRASH_MAX_GATES", "100000"))
COMMIT_UNIT_CLAUSES = os.environ.get("ALG10_COMMIT_UNITS", "1") != "0"
CHECKPOINT_DIR = os.environ.get("ALG10_CHECKPOINT_DIR", "results_optimized/alg10_checkpoints")
RESET_CHECKPOINT = os.environ.get("ALG10_RESET_CHECKPOINT", "0") != "0"
CHECKPOINT_SELECT_POLICY = os.environ.get("ALG10_CHECKPOINT_SELECT", "gates").strip().lower()
if CHECKPOINT_SELECT_POLICY not in {"gates", "unresolved", "recent"}:
    CHECKPOINT_SELECT_POLICY = "gates"
EXTRA_CHECKPOINT_DIRS_RAW = os.environ.get("ALG10_EXTRA_CHECKPOINT_DIRS", "")
PROTECT_BEST_CHECKPOINT = os.environ.get("ALG10_PROTECT_BEST_CHECKPOINT", "1") != "0"
TFI_CONSTANCY = os.environ.get("ALG10_TFI_CONSTANCY", "1") != "0"
TFI_BUDGET = int(os.environ.get("ALG10_TFI_BUDGET", "500" if MODE == "fast_save" else "2000"))
TFI_MAX_CONE_GATES = int(
    os.environ.get("ALG10_TFI_MAX_CONE_GATES", "2000" if MODE == "fast_save" else "10000")
)
TFI_ENGINE = os.environ.get("ALG10_TFI_ENGINE", "persistent").strip().lower()
if TFI_ENGINE not in {"persistent", "local"}:
    TFI_ENGINE = "persistent"
TFI_SOLVER = os.environ.get("ALG10_TFI_SOLVER", "cadical153").strip() or "cadical153"
AUDIT_ASSUMPTIONS = os.environ.get("ALG10_AUDIT_ASSUMPTIONS", "0") != "0"
CANDIDATE_ORDER = os.environ.get("ALG10_CANDIDATE_ORDER", "current").strip().lower()
CANDIDATE_RANDOM_SEED = int(os.environ.get("ALG10_CANDIDATE_RANDOM_SEED", "20260517"))
WINDOW_MITER = os.environ.get("ALG10_WINDOW_MITER", "0") != "0"
WINDOW_AUDIT = os.environ.get("ALG10_WINDOW_AUDIT", "1") != "0"
WINDOW_LEVELS = int(os.environ.get("ALG10_WINDOW_LEVELS", "5"))
WINDOW_ROOT_STRATEGY = os.environ.get("ALG10_WINDOW_ROOT_STRATEGY", "bounded").strip().lower()
if WINDOW_ROOT_STRATEGY not in {"bounded", "dominator", "hybrid"}:
    WINDOW_ROOT_STRATEGY = "bounded"
WINDOW_DOMINATOR_MAX_LEVELS = int(os.environ.get("ALG10_WINDOW_DOMINATOR_MAX_LEVELS", "64"))
WINDOW_DOMINATOR_MAX_ROOTS = int(os.environ.get("ALG10_WINDOW_DOMINATOR_MAX_ROOTS", "512"))
WINDOW_BUDGET = int(os.environ.get("ALG10_WINDOW_BUDGET", "500" if MODE == "fast_save" else "2000"))
WINDOW_MAX_CONE_GATES = int(
    os.environ.get("ALG10_WINDOW_MAX_CONE_GATES", "2000" if MODE == "fast_save" else "10000")
)
CONE_MITER = os.environ.get("ALG10_CONE_MITER", "1") != "0"
CONE_ENGINE = os.environ.get("ALG10_CONE_ENGINE", "single").strip().lower()
if CONE_ENGINE not in {
    "single",
    "grouped",
    "hybrid",
    "partitioned",
    "hybrid_partitioned",
    "tfo",
    "hybrid_tfo",
}:
    CONE_ENGINE = "single"
CONE_SOLVER = os.environ.get("ALG10_CONE_SOLVER", "cadical153").strip() or "cadical153"
CONE_GROUP_MIN_SIZE = max(1, int(os.environ.get("ALG10_CONE_GROUP_MIN_SIZE", "8")))
CONE_PARTITION_SIZE = max(1, int(os.environ.get("ALG10_CONE_PARTITION_SIZE", "1")))
CONE_PARTITION_MIN_ROOTS = max(1, int(os.environ.get("ALG10_CONE_PARTITION_MIN_ROOTS", "2")))
CONE_PARTITION_CONTINUE_AFTER_TIMEOUT = (
    os.environ.get("ALG10_CONE_PARTITION_CONTINUE_AFTER_TIMEOUT", "1") != "0"
)
CONE_BUDGET = int(os.environ.get("ALG10_CONE_BUDGET", "1000" if MODE == "fast_save" else "5000"))
CONE_MAX_GATES = int(
    os.environ.get("ALG10_CONE_MAX_GATES", "5000" if MODE == "fast_save" else "20000")
)
CONE_PARTITION_MAX_GATES = max(
    0,
    int(os.environ.get("ALG10_CONE_PARTITION_MAX_GATES", str(CONE_MAX_GATES))),
)
CONE_TFO_MAX_GOOD_GATES = max(
    0,
    int(os.environ.get("ALG10_CONE_TFO_MAX_GOOD_GATES", "0")),
)
CONE_TFO_MAX_FAULTY_GATES = max(
    0,
    int(os.environ.get("ALG10_CONE_TFO_MAX_FAULTY_GATES", "20000")),
)
GLOBAL_MITER = os.environ.get("ALG10_GLOBAL_MITER", "1") != "0"
GLOBAL_SOLVER = os.environ.get("ALG10_GLOBAL_SOLVER", "glucose4").strip() or "glucose4"
GLOBAL_MAX_CONSEC_TIMEOUTS = max(
    0, int(os.environ.get("ALG10_GLOBAL_MAX_CONSEC_TIMEOUTS", "0"))
)
GLOBAL_FRONTIER_ORDER = os.environ.get("ALG10_GLOBAL_FRONTIER_ORDER", "current").strip().lower()
if GLOBAL_FRONTIER_ORDER not in {
    "current",
    "untried_first",
    "tried_asc",
    "tried_desc",
    "topo",
    "forward",
    "reverse",
    "reverse_topo",
    "depth_desc",
    "depth_asc",
    "fanout_desc",
    "fanout_asc",
    "proof_cost",
    "proof_cost_untried",
    "proof_reverse_portfolio",
    "stuck0_first",
    "stuck1_first",
    "random",
}:
    GLOBAL_FRONTIER_ORDER = "current"
GLOBAL_PHASE_MODE = os.environ.get("ALG10_GLOBAL_PHASE_MODE", "none").strip().lower()
if GLOBAL_PHASE_MODE not in {"none", "controls_false", "model", "controls_false_model"}:
    GLOBAL_PHASE_MODE = "none"
GLOBAL_PHASE_MODEL_LIMIT = max(
    0, int(os.environ.get("ALG10_GLOBAL_PHASE_MODEL_LIMIT", "20000"))
)
PHASE_LOCAL_RESUME = os.environ.get("ALG10_PHASE_LOCAL_RESUME", "0") != "0"
EXACT_FRONTIER_RESUME = os.environ.get("ALG10_EXACT_FRONTIER_RESUME", "0") != "0"
CEX_POOL = os.environ.get("ALG10_CEX_POOL", "0") != "0"
CEX_POOL_MAX_VECTORS = int(os.environ.get("ALG10_CEX_POOL_MAX_VECTORS", "10000"))
CEX_POOL_REPLAY_MAX_VECTORS = int(os.environ.get("ALG10_CEX_POOL_REPLAY_MAX_VECTORS", "0"))
PRE_SIM_REJECTION = os.environ.get("ALG10_PRE_SIM_REJECTION", "0") != "0"
PRE_SIM_ENGINE = os.environ.get("ALG10_PRE_SIM_ENGINE", "scalar").strip().lower()
if PRE_SIM_ENGINE not in {"scalar", "packed"}:
    PRE_SIM_ENGINE = "scalar"
PRE_SIM_PACKED_MAX_BITS = max(1, int(os.environ.get("ALG10_PRE_SIM_PACKED_MAX_BITS", "4096")))
PRE_SIM_RANDOM_PATTERNS = int(
    os.environ.get("ALG10_PRE_SIM_RANDOM_PATTERNS", "64" if MODE == "fast_save" else "128")
)
PRE_SIM_WALK_PATTERNS = int(
    os.environ.get("ALG10_PRE_SIM_WALK_PATTERNS", "16" if MODE == "fast_save" else "32")
)
PRE_SIM_MAX_SECONDS = float(
    os.environ.get("ALG10_PRE_SIM_MAX_SECONDS", "10" if MODE == "fast_save" else "60")
)
PRE_SIM_MAX_FRACTION = float(os.environ.get("ALG10_PRE_SIM_MAX_FRACTION", "0.25"))
PRE_SIM_SEED = int(os.environ.get("ALG10_PRE_SIM_SEED", "20260525"))
PRE_SIM_AFTER_TFI = os.environ.get("ALG10_PRE_SIM_AFTER_TFI", "0") != "0"
PRE_SIM_ADAPTIVE = os.environ.get("ALG10_PRE_SIM_ADAPTIVE", "0") != "0"
PRE_SIM_ADAPTIVE_MIN_RANDOM_PRUNED = int(
    os.environ.get("ALG10_PRE_SIM_ADAPTIVE_MIN_RANDOM_PRUNED", "256")
)
PRE_SIM_ADAPTIVE_MIN_RANDOM_FRACTION = float(
    os.environ.get("ALG10_PRE_SIM_ADAPTIVE_MIN_RANDOM_FRACTION", "0.01")
)
PRE_SIM_ADAPTIVE_RANDOM_PATIENCE = int(
    os.environ.get("ALG10_PRE_SIM_ADAPTIVE_RANDOM_PATIENCE", "4")
)
CEX_PRUNING = os.environ.get("ALG10_CEX_PRUNING", "0") != "0"
CEX_PRUNING_MAX_CANDIDATES = int(os.environ.get("ALG10_CEX_PRUNING_MAX_CANDIDATES", "0"))
CEX_PRUNING_BATCH_SIZE = max(1, int(os.environ.get("ALG10_CEX_PRUNING_BATCH_SIZE", "512")))
AUDIT_CEX_PRUNING = os.environ.get("ALG10_AUDIT_CEX_PRUNING", "0") != "0"
AUDIT_CEX_PRUNING_BUDGET = int(
    os.environ.get(
        "ALG10_AUDIT_CEX_PRUNING_BUDGET",
        str(max(SAT_BUDGETS + [TFI_BUDGET, WINDOW_BUDGET, CONE_BUDGET])),
    )
)
AUDIT_CEX_PRUNING_MAX = int(os.environ.get("ALG10_AUDIT_CEX_PRUNING_MAX", "0"))


def _write_strashed(filepath, parsed, gates_raw, symbols, comment):
    M, I, L, O, A, inputs, latches, outputs = parsed
    result = pure_python_forward_strash(M, I, L, O, A, inputs, latches, outputs, gates_raw)
    M_f, I_f, L_f, O_f, A_f, in_f, la_f, out_f, gates_f = result
    write_aag(filepath, M_f, I_f, L_f, O_f, A_f, in_f, la_f, out_f, gates_f, symbols, comment)
    return A_f


def _parse_current(path):
    M, I, L, O, A, inputs, latches, outputs, gates_raw, symbols = parse_aag(path)
    parsed_header = (M, I, L, O, A, inputs, latches, outputs)
    return parsed_header, symbols, gates_raw


def _apply_accepts(gates_raw, accepted):
    working_gates = _copy_gates(gates_raw)
    for gate_idx, value in accepted.items():
        lhs = working_gates[gate_idx][0]
        working_gates[gate_idx] = [lhs, value, value]
    return working_gates


def _control_position(A, idx, stuck_value, f0_lits, f1_lits):
    if stuck_value == 0:
        return idx, f0_lits[idx], A + idx, f1_lits[idx]
    return A + idx, f1_lits[idx], idx, f0_lits[idx]


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_checkpoint_base(circuit_path):
    base = os.path.splitext(os.path.basename(circuit_path))[0]
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in base)


def _checkpoint_path_stem(circuit_path):
    abspath = os.path.abspath(circuit_path).encode("utf-8", errors="ignore")
    path_hash = hashlib.sha1(abspath).hexdigest()[:12]
    safe = _safe_checkpoint_base(circuit_path)
    return f"{safe}_{path_hash}"


def _checkpoint_content_stem(circuit_path):
    try:
        content_hash = _sha256_file(circuit_path)[:12]
    except Exception:
        return _checkpoint_path_stem(circuit_path)
    safe = _safe_checkpoint_base(circuit_path)
    return f"{safe}_{content_hash}"


def _checkpoint_stem(circuit_path):
    return _checkpoint_content_stem(circuit_path)


def _checkpoint_path_pair(stem):
    return (
        os.path.join(CHECKPOINT_DIR, f"{stem}.json"),
        os.path.join(CHECKPOINT_DIR, f"{stem}.work.aag"),
    )


def _checkpoint_dirs_to_search():
    dirs = [CHECKPOINT_DIR]
    raw = EXTRA_CHECKPOINT_DIRS_RAW.replace(os.pathsep, ",")
    for part in raw.split(","):
        directory = part.strip()
        if directory and directory not in dirs:
            dirs.append(directory)
    return dirs


def _checkpoint_path_candidates(circuit_path):
    content_stem = _checkpoint_content_stem(circuit_path)
    legacy_stem = _checkpoint_path_stem(circuit_path)
    stems = [content_stem]
    if legacy_stem != content_stem:
        stems.append(legacy_stem)
    return [_checkpoint_path_pair(stem) for stem in stems]


def _same_source_checkpoint_candidates(circuit_path, source_sha, checkpoint_dir=None):
    checkpoint_dir = checkpoint_dir or CHECKPOINT_DIR
    safe = _safe_checkpoint_base(circuit_path)
    preferred_pattern = os.path.join(checkpoint_dir, f"{safe}_*.json")
    fallback_pattern = os.path.join(checkpoint_dir, "*.json")
    pairs = []
    seen = set()
    for json_path in sorted(glob.glob(preferred_pattern)) + sorted(glob.glob(fallback_pattern)):
        if json_path.endswith(".cex.json") or json_path in seen:
            continue
        seen.add(json_path)
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("source_sha256") != source_sha:
                continue
            work_path = data.get("work_aag") or os.path.splitext(json_path)[0] + ".work.aag"
            if not os.path.isabs(work_path):
                work_path = os.path.join(os.getcwd(), work_path)
            pairs.append((json_path, work_path, checkpoint_dir))
        except Exception:
            continue
    return pairs


def _checkpoint_rank(gates, unresolved, timestamp):
    if CHECKPOINT_SELECT_POLICY == "unresolved":
        return (unresolved, gates, -timestamp)
    if CHECKPOINT_SELECT_POLICY == "recent":
        return (-timestamp, gates, unresolved)
    return (gates, unresolved, -timestamp)


def _phase_resume_unresolved_count(state):
    if not isinstance(state, dict):
        return None
    if state.get("schema") == "alg10_global_frontier_v1" or "candidates" in state:
        candidates = state.get("candidates")
        return len(candidates) if isinstance(candidates, list) else None
    if state.get("schema") == "alg10_tier_frontier_v1":
        pending = state.get("pending")
        escalated = state.get("escalated")
        if isinstance(pending, list) and isinstance(escalated, list):
            return len(pending) + len(escalated)
    return None


def _checkpoint_unresolved_from_data(data):
    try:
        unresolved = int(data.get("telemetry", {}).get("unresolved", 10**18))
    except Exception:
        unresolved = 10**18
    frontier_unresolved = _phase_resume_unresolved_count(data.get("phase_resume"))
    if frontier_unresolved is not None:
        unresolved = max(unresolved, int(frontier_unresolved))
    return unresolved


def _checkpoint_rank_from_data(data, work_path):
    _, _, _, _, current_gates, _, _, _, _, _ = parse_aag(work_path)
    try:
        stored_gates = int(data.get("current_gates", current_gates))
    except Exception:
        stored_gates = current_gates
    unresolved = _checkpoint_unresolved_from_data(data)
    try:
        timestamp = float(data.get("timestamp", 0) or 0)
    except Exception:
        timestamp = 0.0
    return _checkpoint_rank(min(stored_gates, current_gates), unresolved, timestamp)


def _checkpoint_paths(circuit_path):
    stem = _checkpoint_stem(circuit_path)
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    return _checkpoint_path_pair(stem)


def _cex_pool_path(circuit_path):
    stem = _checkpoint_stem(circuit_path)
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    return os.path.join(CHECKPOINT_DIR, f"{stem}.cex.json")


def _cex_pool_path_candidates(circuit_path):
    content_stem = _checkpoint_content_stem(circuit_path)
    legacy_stem = _checkpoint_path_stem(circuit_path)
    stems = [content_stem]
    if legacy_stem != content_stem:
        stems.append(legacy_stem)
    return [os.path.join(CHECKPOINT_DIR, f"{stem}.cex.json") for stem in stems]


_ACTIVE_CEX_POOL = []
_ACTIVE_CEX_POOL_SET = set()


def _primary_bases(inputs, latches):
    bases = [lit & ~1 for lit in inputs]
    bases.extend(_parse_latch(latch)[0] & ~1 for latch in latches)
    return bases


def _encode_primary_values(inputs, latches, primary_values):
    return "".join("1" if primary_values.get(base, False) else "0" for base in _primary_bases(inputs, latches))


def _decode_primary_values(inputs, latches, encoded):
    bases = _primary_bases(inputs, latches)
    if len(encoded) != len(bases) or any(ch not in "01" for ch in encoded):
        return None
    return {base: encoded[pos] == "1" for pos, base in enumerate(bases)}


def _reset_cex_pool():
    global _ACTIVE_CEX_POOL, _ACTIVE_CEX_POOL_SET
    _ACTIVE_CEX_POOL = []
    _ACTIVE_CEX_POOL_SET = set()


def _load_cex_pool(circuit_path, inputs, latches, telemetry):
    _reset_cex_pool()
    if not CEX_POOL:
        return

    path = None
    for candidate_path in _cex_pool_path_candidates(circuit_path):
        if os.path.exists(candidate_path):
            path = candidate_path
            break
    if path is None:
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("source_sha256") != _sha256_file(circuit_path):
            return
        if data.get("primary_bases") != _primary_bases(inputs, latches):
            return
        for encoded in data.get("vectors", []):
            if _decode_primary_values(inputs, latches, encoded) is None:
                continue
            if encoded not in _ACTIVE_CEX_POOL_SET:
                _ACTIVE_CEX_POOL_SET.add(encoded)
                _ACTIVE_CEX_POOL.append(encoded)
        telemetry["cex_pool_loaded"] = len(_ACTIVE_CEX_POOL)
        telemetry["cex_pool_size"] = len(_ACTIVE_CEX_POOL)
    except Exception:
        _reset_cex_pool()


def _save_cex_pool(circuit_path, inputs, latches, telemetry):
    if not CEX_POOL:
        return

    path = _cex_pool_path(circuit_path)
    data = {
        "algorithm": "ALG10",
        "source_path": os.path.abspath(circuit_path),
        "source_sha256": _sha256_file(circuit_path),
        "primary_bases": _primary_bases(inputs, latches),
        "vectors": _ACTIVE_CEX_POOL,
    }
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp_path, path)
    telemetry["cex_pool_saved"] = len(_ACTIVE_CEX_POOL)
    telemetry["cex_pool_size"] = len(_ACTIVE_CEX_POOL)


def _cex_pool_add(inputs, latches, primary_values, telemetry):
    if not CEX_POOL or CEX_POOL_MAX_VECTORS <= 0:
        return False
    encoded = _encode_primary_values(inputs, latches, primary_values)
    if encoded in _ACTIVE_CEX_POOL_SET:
        return False
    if len(_ACTIVE_CEX_POOL) >= CEX_POOL_MAX_VECTORS:
        return False
    _ACTIVE_CEX_POOL_SET.add(encoded)
    _ACTIVE_CEX_POOL.append(encoded)
    telemetry["cex_pool_added"] += 1
    telemetry["cex_pool_size"] = len(_ACTIVE_CEX_POOL)
    return True


def _candidate_list_for_resume(candidates):
    return [[int(idx), int(stuck_value)] for idx, stuck_value in candidates]


def _unique_candidates(candidates):
    result = []
    seen = set()
    for idx, stuck_value in candidates:
        cand = (int(idx), int(stuck_value))
        if cand in seen:
            continue
        seen.add(cand)
        result.append(cand)
    return result


def _candidate_set_from_resume_items(items, gate_count):
    result = []
    seen = set()
    for item in items:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            return None
        idx, stuck_value = item
        if not isinstance(idx, int) or not isinstance(stuck_value, int):
            return None
        if idx < 0 or idx >= gate_count or stuck_value not in (0, 1):
            return None
        cand = (idx, stuck_value)
        if cand in seen:
            return None
        seen.add(cand)
        result.append(cand)
    return result


def _tier_frontier_state(tier, reason, pending, escalated):
    return {
        "schema": "alg10_tier_frontier_v1",
        "tier": tier,
        "reason": reason,
        "candidate_order": CANDIDATE_ORDER,
        "sat_budgets": list(SAT_BUDGETS),
        "pending": _candidate_list_for_resume(_unique_candidates(pending)),
        "escalated": _candidate_list_for_resume(_unique_candidates(escalated)),
    }


def _candidate_budget_list_for_resume(candidates, max_budget_tried):
    result = []
    for idx, stuck_value in candidates:
        tried = int(max_budget_tried.get((idx, stuck_value), 0))
        result.append([int(idx), int(stuck_value), max(0, tried)])
    return result


def _candidate_info_from_resume(state, gate_count):
    if not PHASE_LOCAL_RESUME or not state or state.get("tier") != "global":
        return None
    result = []
    max_budget_tried = {}
    seen = set()
    for item in state.get("candidates", []):
        if not isinstance(item, (list, tuple)) or len(item) not in (2, 3):
            return None
        idx, stuck_value = item[0], item[1]
        tried = item[2] if len(item) == 3 else 0
        if (
            not isinstance(idx, int)
            or not isinstance(stuck_value, int)
            or not isinstance(tried, int)
        ):
            return None
        if idx < 0 or idx >= gate_count or stuck_value not in (0, 1):
            return None
        cand = (idx, stuck_value)
        if cand in seen:
            return None
        seen.add(cand)
        result.append(cand)
        max_budget_tried[cand] = max(0, tried)
    return result, max_budget_tried


def _tier_frontier_info_from_resume(state, gate_count):
    if (
        not PHASE_LOCAL_RESUME
        or not state
        or state.get("schema") != "alg10_tier_frontier_v1"
        or state.get("tier") not in {"tfi", "window", "cone"}
    ):
        return None
    pending = _candidate_set_from_resume_items(state.get("pending", []), gate_count)
    escalated = _candidate_set_from_resume_items(state.get("escalated", []), gate_count)
    if pending is None or escalated is None:
        return None
    if set(pending).intersection(escalated):
        return None
    return {
        "tier": state.get("tier"),
        "pending": pending,
        "escalated": escalated,
    }


def _candidate_list_from_resume(state, gate_count):
    info = _candidate_info_from_resume(state, gate_count)
    if info is None:
        return None
    return info[0]


def _valid_phase_resume_state(state, work_path, gate_count):
    if not PHASE_LOCAL_RESUME or not state:
        return None
    try:
        if state.get("work_sha256") != _sha256_file(work_path):
            return None
        if int(state.get("gate_count", -1)) != int(gate_count):
            return None
        info = _candidate_info_from_resume(state, gate_count)
        if info is not None:
            candidates, max_budget_tried = info
            return {
                "tier": state.get("tier"),
                "candidates": candidates,
                "max_budget_tried": max_budget_tried,
            }
        frontier = _tier_frontier_info_from_resume(state, gate_count)
        if frontier is not None:
            return frontier
        return None
    except Exception:
        return None


def _load_checkpoint(circuit_path):
    if RESET_CHECKPOINT:
        return None

    try:
        source_sha = _sha256_file(circuit_path)
    except Exception:
        return None

    active_dir_abs = os.path.abspath(CHECKPOINT_DIR)
    candidates = [
        (json_path, work_path, CHECKPOINT_DIR)
        for json_path, work_path in _checkpoint_path_candidates(circuit_path)
    ]
    for checkpoint_dir in _checkpoint_dirs_to_search():
        for pair in _same_source_checkpoint_candidates(circuit_path, source_sha, checkpoint_dir):
            if pair not in candidates:
                candidates.append(pair)

    valid = []
    for json_path, work_path, checkpoint_dir in candidates:
        if not os.path.exists(json_path) or not os.path.exists(work_path):
            continue

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("source_sha256") != source_sha:
                continue
            _, _, _, _, current_gates, _, _, _, _, _ = parse_aag(work_path)
            data["_checkpoint_json_path"] = json_path
            data["_checkpoint_work_path"] = work_path
            data["_checkpoint_source_dir"] = checkpoint_dir
            imported = os.path.abspath(checkpoint_dir) != active_dir_abs
            data["_checkpoint_imported_external"] = int(imported)
            rank = _checkpoint_rank_from_data(data, work_path)
            valid.append((*rank, data))
        except Exception:
            continue
    if valid:
        valid.sort(key=lambda item: item[:-1])
        return valid[0][-1]
    return None


def _save_checkpoint(circuit_path, work_path, telemetry, status, phase_resume_state=None):
    json_path, checkpoint_work = _checkpoint_paths(circuit_path)

    try:
        _, _, _, _, current_gates, _, _, _, _, _ = parse_aag(work_path)
    except Exception:
        current_gates = 0

    source_sha = _sha256_file(circuit_path)
    timestamp = time.time()

    if phase_resume_state and PHASE_LOCAL_RESUME:
        phase_resume_state = dict(phase_resume_state)
        phase_resume_state["work_sha256"] = _sha256_file(work_path)
        phase_resume_state["gate_count"] = current_gates
    else:
        phase_resume_state = None

    stored_telemetry = dict(telemetry)
    frontier_unresolved = _phase_resume_unresolved_count(phase_resume_state)
    if frontier_unresolved is not None:
        try:
            telemetry_unresolved = int(stored_telemetry.get("unresolved", 0))
        except Exception:
            telemetry_unresolved = 0
        stored_telemetry["unresolved"] = max(telemetry_unresolved, frontier_unresolved)

    data = {
        "algorithm": "ALG10",
        "mode": MODE,
        "status": status,
        "timestamp": timestamp,
        "source_path": os.path.abspath(circuit_path),
        "source_sha256": source_sha,
        "work_aag": checkpoint_work,
        "current_gates": current_gates,
        "budgets": SAT_BUDGETS,
        "phase_resume": phase_resume_state,
        "telemetry": stored_telemetry,
    }

    if PROTECT_BEST_CHECKPOINT:
        try:
            unresolved = _checkpoint_unresolved_from_data(data)
            candidate_rank = _checkpoint_rank(current_gates, unresolved, timestamp)
            best_existing = None
            for checkpoint_dir in _checkpoint_dirs_to_search():
                for existing_json, existing_work, _dir in _same_source_checkpoint_candidates(
                    circuit_path, source_sha, checkpoint_dir
                ):
                    if not os.path.exists(existing_json) or not os.path.exists(existing_work):
                        continue
                    with open(existing_json, "r", encoding="utf-8") as f:
                        existing_data = json.load(f)
                    if existing_data.get("source_sha256") != source_sha:
                        continue
                    existing_rank = _checkpoint_rank_from_data(existing_data, existing_work)
                    if best_existing is None or existing_rank < best_existing[0]:
                        best_existing = (existing_rank, existing_json)
            if best_existing is not None and best_existing[0] < candidate_rank:
                return best_existing[1]
        except Exception:
            pass

    shutil.copy(work_path, checkpoint_work)
    tmp_path = json_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp_path, json_path)
    return json_path


def _gate_depth_fanout(gates_raw):
    defined_by_var = {lhs >> 1: idx for idx, (lhs, _, _) in enumerate(gates_raw)}
    fanout = [0 for _ in gates_raw]
    depth = [0 for _ in gates_raw]

    for idx, (_, r0, r1) in enumerate(gates_raw):
        d0 = d1 = 0
        for lit, slot in ((r0, 0), (r1, 1)):
            parent = defined_by_var.get(lit >> 1)
            if parent is not None:
                fanout[parent] += 1
                if slot == 0:
                    d0 = depth[parent] + 1
                else:
                    d1 = depth[parent] + 1
        depth[idx] = max(d0, d1)
    return depth, fanout


def _candidate_order(gates_raw, roots=None):
    """Return all SA0/SA1 candidates, ranked but never filtered away."""
    depth, fanout = _gate_depth_fanout(gates_raw)

    order = CANDIDATE_ORDER
    candidates = [(idx, value) for idx in range(len(gates_raw)) for value in (0, 1)]
    if order == "random":
        rng = random.Random(CANDIDATE_RANDOM_SEED + len(gates_raw))
        rng.shuffle(candidates)
        return candidates

    cone_sizes = None
    if order in {"cone_size", "small_cone", "large_cone"} and roots:
        by_lhs, fanout_graph = _fanout_graph(gates_raw)
        cone_sizes = []
        for idx in range(len(gates_raw)):
            affected = _affected_roots_from_graph(by_lhs, fanout_graph, roots, idx)
            if not affected:
                cone_sizes.append(0)
            else:
                cone_sizes.append(len(_fanin_indices_for_roots(gates_raw, affected, by_lhs=by_lhs)))

    def key(item):
        idx, value = item
        if order in {"topo", "forward", "forward_topo"}:
            return (idx, value)
        if order in {"reverse", "reverse_topo", "po_to_pi"}:
            return (-idx, value)
        if order in {"depth_desc", "reverse_depth"}:
            return (-depth[idx], idx, value)
        if order == "depth_asc":
            return (depth[idx], idx, value)
        if order in {"fanout_desc", "high_fanout"}:
            return (-fanout[idx], -depth[idx], idx, value)
        if order in {"cone_size", "small_cone"} and cone_sizes is not None:
            return (cone_sizes[idx], fanout[idx], depth[idx], idx, value)
        if order == "large_cone" and cone_sizes is not None:
            return (-cone_sizes[idx], -fanout[idx], -depth[idx], idx, value)
        # Current historical order: small local structure first.
        return (fanout[idx], depth[idx], idx, value)

    return sorted(candidates, key=key)


def _observable_proof_costs(gates_raw, roots):
    """Estimate exact-partition SAT cost without filtering any candidate."""
    gate_count = len(gates_raw)
    if not gate_count or not roots:
        return [(0, 0, 0) for _ in gates_raw]

    by_lhs, fanout = _fanout_graph(gates_raw)
    direct_root_bits = [0 for _ in gates_raw]
    root_cone_sizes = []
    cone_size_cache = {}

    for root_pos, root in enumerate(roots):
        base = root & ~1
        root_idx = by_lhs.get(base)
        if root_idx is None:
            root_cone_sizes.append(0)
            continue
        direct_root_bits[root_idx] |= 1 << root_pos
        if base not in cone_size_cache:
            cone_size_cache[base] = len(
                _fanin_indices_for_roots(gates_raw, [root], by_lhs=by_lhs)
            )
        root_cone_sizes.append(cone_size_cache[base])

    affected_bits = direct_root_bits[:]
    for idx in range(gate_count - 1, -1, -1):
        bits = affected_bits[idx]
        for child in fanout[idx]:
            bits |= affected_bits[child]
        affected_bits[idx] = bits

    metric_cache = {0: (0, 0, 0)}
    costs = []
    for bits in affected_bits:
        metric = metric_cache.get(bits)
        if metric is None:
            count = bits.bit_count()
            max_cone = 0
            total_cone = 0
            remaining = bits
            while remaining:
                low_bit = remaining & -remaining
                root_pos = low_bit.bit_length() - 1
                cone_size = root_cone_sizes[root_pos]
                max_cone = max(max_cone, cone_size)
                total_cone += cone_size
                remaining ^= low_bit
            metric = (max_cone, count, total_cone)
            metric_cache[bits] = metric
        costs.append(metric)
    return costs


def _order_global_frontier(
    candidates,
    gates_raw,
    max_budget_tried,
    roots=None,
    order=None,
):
    order = (order or GLOBAL_FRONTIER_ORDER).strip().lower()
    items = list(candidates)
    if order == "current":
        return items
    if order == "random":
        rng = random.Random(CANDIDATE_RANDOM_SEED + len(gates_raw) + len(items))
        rng.shuffle(items)
        return items

    depth, fanout = _gate_depth_fanout(gates_raw)
    proof_costs = None
    if order in {"proof_cost", "proof_cost_untried", "proof_reverse_portfolio"}:
        proof_costs = _observable_proof_costs(gates_raw, roots)

    def key(item):
        idx, value = item
        tried = max_budget_tried.get((idx, value), 0)
        if proof_costs is not None:
            max_partition_cone, affected_roots, total_partition_cone = proof_costs[idx]
            cost = (
                max_partition_cone,
                affected_roots,
                total_partition_cone,
                fanout[idx],
                -depth[idx],
                idx,
                value,
            )
            if order == "proof_cost_untried":
                return (1 if tried > 0 else 0, tried) + cost
            return cost + (tried,)
        if order == "untried_first":
            return (1 if tried > 0 else 0, tried, idx, value)
        if order == "tried_asc":
            return (tried, idx, value)
        if order == "tried_desc":
            return (-tried, idx, value)
        if order in {"topo", "forward"}:
            return (idx, value)
        if order in {"reverse", "reverse_topo"}:
            return (-idx, value)
        if order == "depth_desc":
            return (-depth[idx], idx, value)
        if order == "depth_asc":
            return (depth[idx], idx, value)
        if order == "fanout_desc":
            return (-fanout[idx], -depth[idx], idx, value)
        if order == "fanout_asc":
            return (fanout[idx], depth[idx], idx, value)
        if order == "stuck0_first":
            return (value, idx)
        if order == "stuck1_first":
            return (-value, idx)
        return (idx, value)

    if order == "proof_reverse_portfolio":
        proof_ranked = sorted(items, key=key)
        reverse_ranked = sorted(items, key=lambda item: (-item[0], item[1]))
        merged = []
        seen = set()
        for pos in range(max(len(proof_ranked), len(reverse_ranked))):
            for ranked in (proof_ranked, reverse_ranked):
                if pos >= len(ranked):
                    continue
                candidate = ranked[pos]
                if candidate in seen:
                    continue
                seen.add(candidate)
                merged.append(candidate)
        return merged

    return sorted(items, key=key)


def _empty_phase_telemetry():
    return {
        "checks": 0,
        "timeouts": 0,
        "sat": 0,
        "unsat": 0,
        "accepted_sa0": 0,
        "accepted_sa1": 0,
        "candidates": 0,
        "budget_rounds": 0,
        "unresolved": 0,
        "max_budget": 0,
        "tfi_checks": 0,
        "tfi_sat": 0,
        "tfi_unsat": 0,
        "tfi_timeouts": 0,
        "tfi_skipped": 0,
        "window_checks": 0,
        "window_sat": 0,
        "window_unsat": 0,
        "window_timeouts": 0,
        "window_skipped": 0,
        "window_audit_fail": 0,
        "window_dominator_attempts": 0,
        "window_dominator_used": 0,
        "window_dominator_fallbacks": 0,
        "cone_checks": 0,
        "cone_sat": 0,
        "cone_unsat": 0,
        "cone_timeouts": 0,
        "cone_skipped": 0,
        "cone_partition_checks": 0,
        "cone_partition_sat": 0,
        "cone_partition_unsat": 0,
        "cone_partition_timeouts": 0,
        "cone_partition_groups": 0,
        "cone_partition_audit_fail": 0,
        "cone_partition_skipped": 0,
        "cone_partition_no_affected": 0,
        "cone_partition_below_min_roots": 0,
        "cone_partition_target_outside_cone": 0,
        "cone_partition_cone_too_large": 0,
        "cone_partition_fallbacks": 0,
        "cone_partition_max_cone_gates": 0,
        "cone_partition_max_seen_cone_gates": 0,
        "cone_partition_max_skipped_cone_gates": 0,
        "cone_tfo_checks": 0,
        "cone_tfo_sat": 0,
        "cone_tfo_unsat": 0,
        "cone_tfo_timeouts": 0,
        "cone_tfo_skipped": 0,
        "cone_tfo_audit_fail": 0,
        "cone_tfo_max_good_gates": 0,
        "cone_tfo_max_faulty_gates": 0,
        "global_checks": 0,
        "global_sat": 0,
        "global_unsat": 0,
        "global_timeouts": 0,
        "global_budget_history_loaded": 0,
        "global_budget_history_skipped": 0,
        "global_budget_history_exhausted": 0,
        "phase_resume_used": 0,
        "phase_resume_saved": 0,
        "phase_resume_candidates": 0,
        "exact_frontier_resume_enabled": int(EXACT_FRONTIER_RESUME),
        "exact_frontier_resume_used": 0,
        "exact_frontier_resume_candidates": 0,
        "exact_frontier_resume_skipped_lower_tiers": 0,
        "exact_frontier_resume_tier": "",
        "cex_pool_loaded": 0,
        "cex_pool_saved": 0,
        "cex_pool_size": 0,
        "cex_pool_added": 0,
        "cex_pool_replay_patterns": 0,
        "cex_pool_replay_checked": 0,
        "cex_pool_replay_pruned": 0,
        "pre_sim_after_tfi": int(PRE_SIM_AFTER_TFI),
        "pre_sim_patterns": 0,
        "pre_sim_checked": 0,
        "pre_sim_pruned": 0,
        "pre_sim_structured_pruned": 0,
        "pre_sim_random_pruned": 0,
        "pre_sim_time": 0.0,
        "pre_sim_adaptive_stop": "",
        "cex_prune_events": 0,
        "cex_prune_checked": 0,
        "cex_pruned": 0,
        "cex_tfi_prune_events": 0,
        "cex_tfi_prune_checked": 0,
        "cex_tfi_pruned": 0,
        "cex_audit_checked": 0,
        "cex_audit_sat": 0,
        "cex_audit_unsat_false_prune": 0,
        "cex_audit_timeouts": 0,
        "cex_audit_skipped": 0,
        "cex_audit_limit_hit": 0,
        "abort_reason": "",
    }


def _fanin_cone_indices(gates_raw, target_idx):
    by_lhs = {lhs & ~1: idx for idx, (lhs, _, _) in enumerate(gates_raw)}
    cone = set()
    stack = [gates_raw[target_idx][0] & ~1]

    while stack:
        lhs = stack.pop()
        idx = by_lhs.get(lhs)
        if idx is None or idx in cone:
            continue
        cone.add(idx)
        _, r0, r1 = gates_raw[idx]
        if r0 > 1:
            stack.append(r0 & ~1)
        if r1 > 1:
            stack.append(r1 & ~1)

    return cone


def _model_primary_values_from_base_map(inputs, latches, model, var_for_base):
    assigned = {abs(lit): lit > 0 for lit in model}
    values = {}

    for lit in inputs:
        sat_var = var_for_base.get(lit & ~1)
        values[lit & ~1] = assigned.get(sat_var, False) if sat_var is not None else False
    for latch in latches:
        current = _parse_latch(latch)[0]
        sat_var = var_for_base.get(current & ~1)
        values[current & ~1] = assigned.get(sat_var, False) if sat_var is not None else False

    return values


def _tfi_constancy_check(inputs, latches, gates_raw, target_idx, stuck_value):
    cone = _fanin_cone_indices(gates_raw, target_idx)
    if TFI_MAX_CONE_GATES > 0 and len(cone) > TFI_MAX_CONE_GATES:
        return "SKIP", None

    primary_bases = {lit & ~1 for lit in inputs}
    primary_bases.update(_parse_latch(latch)[0] & ~1 for latch in latches)
    var_for_base = {}
    next_var = 1

    def sat_var(base):
        nonlocal next_var
        if base not in var_for_base:
            var_for_base[base] = next_var
            next_var += 1
        return var_for_base[base]

    def lit_to_sat(aig_lit):
        if aig_lit == 0:
            return None
        if aig_lit == 1:
            return None
        var = sat_var(aig_lit & ~1)
        return -var if (aig_lit & 1) else var

    clauses = []

    for base in primary_bases:
        sat_var(base)

    for idx in sorted(cone):
        lhs, r0, r1 = gates_raw[idx]
        out = sat_var(lhs & ~1)
        a = lit_to_sat(r0)
        b = lit_to_sat(r1)

        if r0 == 0 or r1 == 0:
            clauses.append([-out])
        elif r0 == 1 and r1 == 1:
            clauses.append([out])
        elif r0 == 1:
            clauses.append([-b, out])
            clauses.append([b, -out])
        elif r1 == 1:
            clauses.append([-a, out])
            clauses.append([a, -out])
        else:
            clauses.append([-a, -b, out])
            clauses.append([a, -out])
            clauses.append([b, -out])

    target_lit = lit_to_sat(gates_raw[target_idx][0])
    if target_lit is None:
        return "SKIP", None

    # Check whether the opposite value is reachable in the complete TFI cone.
    assumption = target_lit if stuck_value == 0 else -target_lit

    with Glucose4(bootstrap_with=clauses) as solver:
        solver.conf_budget(TFI_BUDGET)
        result = solver.solve_limited(assumptions=[assumption])
        model = solver.get_model() if result is True and (CEX_PRUNING or CEX_POOL) else None

    if result is None:
        return "TIMEOUT", None
    if result is False:
        return "UNSAT", None
    primary_values = (
        _model_primary_values_from_base_map(inputs, latches, model, var_for_base) if model else None
    )
    return "SAT", primary_values


def _tfi_add_and_clauses(clauses, out, a, b):
    if a is False or b is False:
        clauses.append([-out])
    elif a is True and b is True:
        clauses.append([out])
    elif a is True:
        clauses.append([-b, out])
        clauses.append([b, -out])
    elif b is True:
        clauses.append([-a, out])
        clauses.append([a, -out])
    else:
        clauses.append([-a, -b, out])
        clauses.append([a, -out])
        clauses.append([b, -out])


def _build_full_good_tfi_cnf(inputs, latches, gates_raw):
    """Encode the current good circuit once for phase-local TFI constancy checks."""
    primary_bases = {lit & ~1 for lit in inputs}
    primary_bases.update(_parse_latch(latch)[0] & ~1 for latch in latches)
    var_for_base = {}
    next_var = 1

    def sat_var(base):
        nonlocal next_var
        if base not in var_for_base:
            var_for_base[base] = next_var
            next_var += 1
        return var_for_base[base]

    def lit_to_sat(aig_lit):
        if aig_lit == 0:
            return False
        if aig_lit == 1:
            return True
        var = sat_var(aig_lit & ~1)
        return -var if (aig_lit & 1) else var

    for base in primary_bases:
        sat_var(base)

    clauses = []
    for lhs, r0, r1 in gates_raw:
        out = sat_var(lhs & ~1)
        _tfi_add_and_clauses(clauses, out, lit_to_sat(r0), lit_to_sat(r1))

    return clauses, var_for_base


def _tfi_candidate_assumption(gates_raw, var_for_base, idx, stuck_value):
    target_lit = var_for_base.get(gates_raw[idx][0] & ~1)
    if target_lit is None:
        return None
    return target_lit if stuck_value == 0 else -target_lit


def _solve_limited_with_budget(solver, assumptions, budget):
    if budget > 0:
        solver.conf_budget(budget)
        return solver.solve_limited(assumptions=assumptions)
    return solver.solve(assumptions=assumptions)


def _apply_global_initial_phases(solver, f0_lits, f1_lits):
    if GLOBAL_PHASE_MODE in {"controls_false", "controls_false_model"}:
        solver.set_phases([-lit for lit in f0_lits])
        solver.set_phases([-lit for lit in f1_lits])


def _apply_global_model_phases(solver, model):
    if GLOBAL_PHASE_MODE not in {"model", "controls_false_model"} or not model:
        return
    if GLOBAL_PHASE_MODEL_LIMIT > 0:
        solver.set_phases(model[:GLOBAL_PHASE_MODEL_LIMIT])
    else:
        solver.set_phases(model)


def _cex_prune_tfi_candidates(
    inputs, latches, gates_raw, primary_values, pending, already_pruned, deadline=None
):
    """Skip future TFI-constancy checks disproved by one concrete assignment."""
    if not CEX_PRUNING or not pending:
        return 0, 0

    by_lhs = {lhs & ~1: idx for idx, (lhs, _, _) in enumerate(gates_raw)}
    gate_values, _ = _simulate_good_roots(inputs, latches, [], gates_raw, primary_values, by_lhs)
    checked = 0
    newly_pruned = 0

    for cand in pending:
        if _deadline_expired(deadline):
            break
        if cand in already_pruned:
            continue
        checked += 1
        idx, stuck_value = cand
        if gate_values[idx] != bool(stuck_value):
            already_pruned.add(cand)
            newly_pruned += 1

    return checked, newly_pruned


def _run_tfi_constancy_tier_local(
    inputs, latches, gates_raw, deadline, initial_pruned=None, candidates_override=None, escalated=None
):
    """Return constants proved by TFI UNSAT; SAT still escalates globally."""
    telemetry = _empty_phase_telemetry()
    accepted = {}

    if not TFI_CONSTANCY or not gates_raw:
        return accepted, telemetry

    candidates = list(candidates_override) if candidates_override is not None else _candidate_order(gates_raw)
    telemetry["max_budget"] = TFI_BUDGET
    initial_rejected = set(initial_pruned or [])
    tfi_pruned = set()
    escalated_candidates = _unique_candidates(escalated or [])
    escalated_seen = set(escalated_candidates)

    def add_escalated(cand):
        if cand in initial_rejected or cand in escalated_seen:
            return
        escalated_seen.add(cand)
        escalated_candidates.append(cand)

    try:
        for candidate_pos, (idx, stuck_value) in enumerate(candidates):
            if deadline is not None and time.time() >= deadline:
                telemetry["abort_reason"] = "TIME_BUDGET_CHECKPOINT"
                remaining = [
                    cand
                    for cand in candidates[candidate_pos:]
                    if cand not in initial_rejected and cand not in tfi_pruned and cand[0] not in accepted
                ]
                telemetry["unresolved"] = len(remaining)
                if not accepted:
                    telemetry["_phase_resume_state"] = _tier_frontier_state(
                        "tfi", "TIME_BUDGET_CHECKPOINT", remaining, escalated_candidates
                    )
                return accepted, telemetry
            cand = (idx, stuck_value)
            if idx in accepted or cand in initial_rejected:
                continue
            if cand in tfi_pruned:
                add_escalated(cand)
                continue

            result, primary_values = _tfi_constancy_check(inputs, latches, gates_raw, idx, stuck_value)
            if result == "SKIP":
                telemetry["tfi_skipped"] += 1
                add_escalated(cand)
                continue

            telemetry["checks"] += 1
            telemetry["tfi_checks"] += 1

            if result == "TIMEOUT":
                telemetry["timeouts"] += 1
                telemetry["tfi_timeouts"] += 1
                add_escalated(cand)
                continue
            if result == "SAT":
                telemetry["sat"] += 1
                telemetry["tfi_sat"] += 1
                add_escalated(cand)
                if primary_values is not None:
                    before_pruned = set(tfi_pruned)
                    pending = [c for c in candidates[candidate_pos + 1 :] if c not in initial_rejected]
                    checked, newly_pruned = _cex_prune_tfi_candidates(
                        inputs,
                        latches,
                        gates_raw,
                        primary_values,
                        pending,
                        tfi_pruned,
                        deadline=deadline,
                    )
                    for pruned_cand in tfi_pruned - before_pruned:
                        add_escalated(pruned_cand)
                    if checked:
                        telemetry["cex_tfi_prune_events"] += 1
                        telemetry["cex_tfi_prune_checked"] += checked
                        telemetry["cex_tfi_pruned"] += newly_pruned
                continue

            telemetry["unsat"] += 1
            telemetry["tfi_unsat"] += 1
            accepted[idx] = stuck_value
            if stuck_value == 0:
                telemetry["accepted_sa0"] += 1
            else:
                telemetry["accepted_sa1"] += 1

            if len(accepted) >= REBUILD_AFTER_COMMITS:
                telemetry["abort_reason"] = "REBUILD_COMMIT_LIMIT"
                telemetry["unresolved"] = sum(
                    1
                    for cand in candidates[candidate_pos + 1 :]
                    if cand not in initial_rejected and cand not in tfi_pruned and cand[0] not in accepted
                )
                return accepted, telemetry
    except KeyboardInterrupt:
        telemetry["abort_reason"] = "USER_INTERRUPT_CHECKPOINT"
        remaining = [
            cand
            for cand in candidates
            if cand not in initial_rejected and cand not in tfi_pruned and cand[0] not in accepted
        ]
        telemetry["unresolved"] = len(remaining)
        if not accepted:
            telemetry["_phase_resume_state"] = _tier_frontier_state(
                "tfi", "USER_INTERRUPT_CHECKPOINT", remaining, escalated_candidates
            )
        return accepted, telemetry

    telemetry["_tier_escalated_candidates"] = _candidate_list_for_resume(escalated_candidates)
    telemetry["unresolved"] = 0
    return accepted, telemetry


def _run_tfi_constancy_tier_persistent(
    inputs, latches, gates_raw, deadline, initial_pruned=None, candidates_override=None, escalated=None
):
    """Phase-local good-circuit TFI solver. UNSAT proves functional constancy."""
    telemetry = _empty_phase_telemetry()
    accepted = {}

    if not TFI_CONSTANCY or not gates_raw:
        return accepted, telemetry

    candidates = list(candidates_override) if candidates_override is not None else _candidate_order(gates_raw)
    telemetry["max_budget"] = TFI_BUDGET
    initial_rejected = set(initial_pruned or [])
    tfi_pruned = set()
    escalated_candidates = _unique_candidates(escalated or [])
    escalated_seen = set(escalated_candidates)

    def add_escalated(cand):
        if cand in initial_rejected or cand in escalated_seen:
            return
        escalated_seen.add(cand)
        escalated_candidates.append(cand)

    try:
        clauses, var_for_base = _build_full_good_tfi_cnf(inputs, latches, gates_raw)
        with Solver(name=TFI_SOLVER, bootstrap_with=clauses) as solver:
            for candidate_pos, (idx, stuck_value) in enumerate(candidates):
                if deadline is not None and time.time() >= deadline:
                    telemetry["abort_reason"] = "TIME_BUDGET_CHECKPOINT"
                    remaining = [
                        cand
                        for cand in candidates[candidate_pos:]
                        if cand not in initial_rejected and cand not in tfi_pruned and cand[0] not in accepted
                    ]
                    telemetry["unresolved"] = len(remaining)
                    if not accepted:
                        telemetry["_phase_resume_state"] = _tier_frontier_state(
                            "tfi", "TIME_BUDGET_CHECKPOINT", remaining, escalated_candidates
                        )
                    return accepted, telemetry
                cand = (idx, stuck_value)
                if idx in accepted or cand in initial_rejected:
                    continue
                if cand in tfi_pruned:
                    add_escalated(cand)
                    continue

                assumption = _tfi_candidate_assumption(gates_raw, var_for_base, idx, stuck_value)
                if assumption is None:
                    telemetry["tfi_skipped"] += 1
                    add_escalated(cand)
                    continue

                telemetry["checks"] += 1
                telemetry["tfi_checks"] += 1
                try:
                    result = _solve_limited_with_budget(solver, [assumption], TFI_BUDGET)
                except NotImplementedError:
                    return _run_tfi_constancy_tier_local(
                        inputs,
                        latches,
                        gates_raw,
                        deadline,
                        initial_pruned=initial_pruned,
                        candidates_override=candidates,
                        escalated=escalated_candidates,
                    )

                if result is None:
                    telemetry["timeouts"] += 1
                    telemetry["tfi_timeouts"] += 1
                    add_escalated(cand)
                    continue
                if result is True:
                    telemetry["sat"] += 1
                    telemetry["tfi_sat"] += 1
                    add_escalated(cand)
                    if CEX_PRUNING or CEX_POOL:
                        model = solver.get_model()
                        if model is not None:
                            primary_values = _model_primary_values_from_base_map(
                                inputs, latches, model, var_for_base
                            )
                            before_pruned = set(tfi_pruned)
                            pending = [
                                c for c in candidates[candidate_pos + 1 :] if c not in initial_rejected
                            ]
                            checked, newly_pruned = _cex_prune_tfi_candidates(
                                inputs,
                                latches,
                                gates_raw,
                                primary_values,
                                pending,
                                tfi_pruned,
                                deadline=deadline,
                            )
                            for pruned_cand in tfi_pruned - before_pruned:
                                add_escalated(pruned_cand)
                            if checked:
                                telemetry["cex_tfi_prune_events"] += 1
                                telemetry["cex_tfi_prune_checked"] += checked
                                telemetry["cex_tfi_pruned"] += newly_pruned
                    continue

                telemetry["unsat"] += 1
                telemetry["tfi_unsat"] += 1
                accepted[idx] = stuck_value
                if stuck_value == 0:
                    telemetry["accepted_sa0"] += 1
                else:
                    telemetry["accepted_sa1"] += 1

                if len(accepted) >= REBUILD_AFTER_COMMITS:
                    telemetry["abort_reason"] = "REBUILD_COMMIT_LIMIT"
                    telemetry["unresolved"] = sum(
                        1
                        for cand in candidates[candidate_pos + 1 :]
                        if cand not in initial_rejected and cand not in tfi_pruned and cand[0] not in accepted
                    )
                    return accepted, telemetry
    except KeyboardInterrupt:
        telemetry["abort_reason"] = "USER_INTERRUPT_CHECKPOINT"
        remaining = [
            cand
            for cand in candidates
            if cand not in initial_rejected and cand not in tfi_pruned and cand[0] not in accepted
        ]
        telemetry["unresolved"] = len(remaining)
        if not accepted:
            telemetry["_phase_resume_state"] = _tier_frontier_state(
                "tfi", "USER_INTERRUPT_CHECKPOINT", remaining, escalated_candidates
            )
        return accepted, telemetry
    except Exception:
        return _run_tfi_constancy_tier_local(
            inputs,
            latches,
            gates_raw,
            deadline,
            initial_pruned=initial_pruned,
            candidates_override=candidates,
            escalated=escalated_candidates,
        )

    telemetry["_tier_escalated_candidates"] = _candidate_list_for_resume(escalated_candidates)
    telemetry["unresolved"] = 0
    return accepted, telemetry


def _run_tfi_constancy_tier(
    inputs, latches, gates_raw, deadline, initial_pruned=None, candidates_override=None, escalated=None
):
    if TFI_ENGINE == "persistent":
        return _run_tfi_constancy_tier_persistent(
            inputs,
            latches,
            gates_raw,
            deadline,
            initial_pruned=initial_pruned,
            candidates_override=candidates_override,
            escalated=escalated,
        )
    return _run_tfi_constancy_tier_local(
        inputs,
        latches,
        gates_raw,
        deadline,
        initial_pruned=initial_pruned,
        candidates_override=candidates_override,
        escalated=escalated,
    )


def _fanout_graph(gates_raw):
    by_lhs = {lhs & ~1: idx for idx, (lhs, _, _) in enumerate(gates_raw)}
    fanout = [set() for _ in gates_raw]

    for idx, (_, r0, r1) in enumerate(gates_raw):
        for lit in (r0, r1):
            parent = by_lhs.get(lit & ~1)
            if parent is not None:
                fanout[parent].add(idx)

    return by_lhs, fanout


def _affected_roots_from_graph(by_lhs, fanout, roots, target_idx):
    affected_gates = set()
    stack = [target_idx]

    while stack:
        idx = stack.pop()
        if idx in affected_gates:
            continue
        affected_gates.add(idx)
        stack.extend(fanout[idx])

    affected = []
    for root in roots:
        root_idx = by_lhs.get(root & ~1)
        if root_idx in affected_gates:
            affected.append(root)
    return affected


def _affected_roots(gates_raw, roots, target_idx):
    by_lhs, fanout = _fanout_graph(gates_raw)
    return _affected_roots_from_graph(by_lhs, fanout, roots, target_idx)


def _fanin_indices_for_roots(gates_raw, roots, by_lhs=None):
    if by_lhs is None:
        by_lhs = {lhs & ~1: idx for idx, (lhs, _, _) in enumerate(gates_raw)}
    cone = set()
    stack = [root & ~1 for root in roots if root > 1]

    while stack:
        lhs = stack.pop()
        idx = by_lhs.get(lhs)
        if idx is None or idx in cone:
            continue
        cone.add(idx)
        _, r0, r1 = gates_raw[idx]
        if r0 > 1:
            stack.append(r0 & ~1)
        if r1 > 1:
            stack.append(r1 & ~1)

    return cone


def _build_single_fault_cone_miter(inputs, latches, roots, gates_raw, target_idx, stuck_value, cone):
    cnf = _CNFBuilder()
    shared = {}
    good = {}
    faulty = {}

    for lit in inputs:
        shared[lit >> 1] = cnf.new_var()
    for latch in latches:
        shared[_parse_latch(latch)[0] >> 1] = cnf.new_var()

    def lit_from(mapping, aig_lit):
        if aig_lit == 0:
            return cnf.const(False)
        if aig_lit == 1:
            return cnf.const(True)
        var = aig_lit >> 1
        if var in mapping:
            sat_lit = mapping[var]
        elif var in shared:
            sat_lit = shared[var]
        else:
            raise ValueError(f"undefined literal in cone SAT encoding: {aig_lit}")
        return -sat_lit if (aig_lit & 1) else sat_lit

    for idx in sorted(cone):
        lhs, r0, r1 = gates_raw[idx]

        good_out = cnf.new_var()
        good[lhs >> 1] = good_out
        cnf.and2(good_out, lit_from(good, r0), lit_from(good, r1))

        if idx == target_idx:
            faulty[lhs >> 1] = cnf.const(bool(stuck_value))
            continue

        faulty_out = cnf.new_var()
        faulty[lhs >> 1] = faulty_out
        cnf.and2(faulty_out, lit_from(faulty, r0), lit_from(faulty, r1))

    xors = []
    for root in roots:
        xor = cnf.new_var()
        cnf.xor2(xor, lit_from(good, root), lit_from(faulty, root))
        xors.append(xor)

    return cnf.clauses, cnf.or_many(xors), shared


def _build_configurable_cone_miter(inputs, latches, roots, gates_raw, cone):
    """Build one exact cone miter with per-gate stuck-at controls inside the cone."""
    cnf = _CNFBuilder()
    shared = {}
    good = {}
    faulty = {}
    controls = {}

    for lit in inputs:
        shared[lit >> 1] = cnf.new_var()
    for latch in latches:
        shared[_parse_latch(latch)[0] >> 1] = cnf.new_var()

    def lit_from(mapping, aig_lit):
        if aig_lit == 0:
            return cnf.const(False)
        if aig_lit == 1:
            return cnf.const(True)
        var = aig_lit >> 1
        if var in mapping:
            sat_lit = mapping[var]
        elif var in shared:
            sat_lit = shared[var]
        else:
            raise ValueError(f"undefined literal in grouped cone SAT encoding: {aig_lit}")
        return -sat_lit if (aig_lit & 1) else sat_lit

    for idx in sorted(cone):
        lhs, r0, r1 = gates_raw[idx]
        good_out = cnf.new_var()
        good[lhs >> 1] = good_out
        cnf.and2(good_out, lit_from(good, r0), lit_from(good, r1))

    for idx in sorted(cone):
        lhs, r0, r1 = gates_raw[idx]
        normal = cnf.new_var()
        cnf.and2(normal, lit_from(faulty, r0), lit_from(faulty, r1))

        f0 = cnf.new_var()
        f1 = cnf.new_var()
        controls[idx] = (f0, f1)
        cnf.clauses.append([-f0, -f1])

        not_forced_zero = cnf.new_var()
        cnf.and2(not_forced_zero, normal, -f0)
        faulty_out = cnf.new_var()
        cnf.or2(faulty_out, not_forced_zero, f1)
        faulty[lhs >> 1] = faulty_out

    xors = []
    for root in roots:
        xor = cnf.new_var()
        cnf.xor2(xor, lit_from(good, root), lit_from(faulty, root))
        xors.append(xor)

    return cnf.clauses, cnf.or_many(xors), controls, shared


def _cone_group_key(gates_raw, outputs, target_idx, by_lhs, fanout):
    affected = tuple(_affected_roots_from_graph(by_lhs, fanout, outputs, target_idx))
    if not affected:
        return None, None
    cone = _fanin_indices_for_roots(gates_raw, affected, by_lhs=by_lhs)
    if target_idx not in cone:
        return None, None
    if CONE_MAX_GATES > 0 and len(cone) > CONE_MAX_GATES:
        return None, None
    return affected, cone


class _ConeGroupSolver:
    def __init__(self, solver, miter_lit, controls, shared):
        self.solver = solver
        self.miter_lit = miter_lit
        self.controls = controls
        self.shared = shared
        self.control_state = []
        self.positions = {}
        for gate_idx, (f0, f1) in controls.items():
            self.positions[(gate_idx, 0)] = len(self.control_state)
            self.control_state.append(-f0)
            self.positions[(gate_idx, 1)] = len(self.control_state)
            self.control_state.append(-f1)

    def activate_accepted(self, gate_idx, stuck_value):
        pair = self.controls.get(gate_idx)
        if pair is None:
            return
        f0, f1 = pair
        if stuck_value == 0:
            active, inactive = f0, -f1
            self.control_state[self.positions[(gate_idx, 0)]] = f0
            self.control_state[self.positions[(gate_idx, 1)]] = -f1
        else:
            active, inactive = f1, -f0
            self.control_state[self.positions[(gate_idx, 1)]] = f1
            self.control_state[self.positions[(gate_idx, 0)]] = -f0
        self.solver.add_clause([active])
        self.solver.add_clause([inactive])

    def assumptions_for(self, gate_idx, stuck_value):
        pair = self.controls.get(gate_idx)
        if pair is None:
            return None
        f0, f1 = pair
        assumptions = self.control_state.copy()
        if stuck_value == 0:
            assumptions[self.positions[(gate_idx, 0)]] = f0
            assumptions[self.positions[(gate_idx, 1)]] = -f1
        else:
            assumptions[self.positions[(gate_idx, 1)]] = f1
            assumptions[self.positions[(gate_idx, 0)]] = -f0
        assumptions.append(self.miter_lit)
        return assumptions

    def delete(self):
        self.solver.delete()


def _audit_cone_group_assumptions(assumptions, state, candidate, accepted=None):
    expected_len = 2 * len(state.controls) + 1
    if len(assumptions) != expected_len:
        raise AssertionError(
            f"grouped cone assumption count {len(assumptions)} != {expected_len}"
        )

    seen = set()
    for lit in assumptions:
        if lit in seen:
            raise AssertionError(f"duplicate grouped cone assumption literal {lit}")
        if -lit in seen:
            raise AssertionError(
                f"contradictory grouped cone assumption literals {lit} and {-lit}"
            )
        seen.add(lit)

    accepted = accepted or {}
    cand_idx, cand_value = candidate
    if cand_idx not in state.controls:
        raise AssertionError(f"grouped cone candidate {cand_idx} is outside the control set")

    expected = []
    for gate_idx, (f0, f1) in state.controls.items():
        stuck_value = None
        if gate_idx == cand_idx:
            stuck_value = cand_value
        elif gate_idx in accepted:
            stuck_value = accepted[gate_idx]

        if stuck_value is None:
            expected.extend([-f0, -f1])
        elif stuck_value == 0:
            expected.extend([f0, -f1])
        elif stuck_value == 1:
            expected.extend([-f0, f1])
        else:
            raise AssertionError(f"invalid grouped cone stuck value: {stuck_value}")

    expected.append(state.miter_lit)
    if assumptions != expected:
        missing = sorted(set(expected) - set(assumptions), key=abs)
        extra = sorted(set(assumptions) - set(expected), key=abs)
        raise AssertionError(
            "grouped cone assumption content mismatch; "
            f"candidate=({cand_idx}, SA{cand_value}), "
            f"missing={missing[:10]}, extra={extra[:10]}"
        )


def _make_cone_group_solver(inputs, latches, roots, gates_raw, cone, accepted, timings):
    t_encode = time.time()
    clauses, miter_lit, controls, shared = _build_configurable_cone_miter(
        inputs, latches, roots, gates_raw, cone
    )
    timings["Encode"] += time.time() - t_encode
    state = _ConeGroupSolver(Solver(name=CONE_SOLVER, bootstrap_with=clauses), miter_lit, controls, shared)
    for gate_idx, stuck_value in accepted.items():
        state.activate_accepted(gate_idx, stuck_value)
    return state


def _cone_miter_check(
    inputs, latches, outputs, gates_raw, target_idx, stuck_value, timings, by_lhs, fanout
):
    affected = _affected_roots_from_graph(by_lhs, fanout, outputs, target_idx)
    if not affected:
        return "SKIP", None

    cone = _fanin_indices_for_roots(gates_raw, affected, by_lhs=by_lhs)
    if target_idx not in cone:
        return "SKIP", None
    if CONE_MAX_GATES > 0 and len(cone) > CONE_MAX_GATES:
        return "SKIP", None

    t_encode = time.time()
    clauses, miter_lit, shared = _build_single_fault_cone_miter(
        inputs, latches, affected, gates_raw, target_idx, stuck_value, cone
    )
    timings["Encode"] += time.time() - t_encode

    t_sat = time.time()
    with Glucose4(bootstrap_with=clauses) as solver:
        solver.conf_budget(CONE_BUDGET)
        result = solver.solve_limited(assumptions=[miter_lit])
        model = solver.get_model() if result is True and (CEX_PRUNING or CEX_POOL) else None
    timings["SAT"] += time.time() - t_sat

    if result is None:
        return "TIMEOUT", None
    if result is False:
        return "UNSAT", None
    primary_values = _model_primary_values_from_shared(inputs, latches, model, shared) if model else None
    return "SAT", primary_values


def _partition_roots(roots, partition_size):
    return [list(roots[pos : pos + partition_size]) for pos in range(0, len(roots), partition_size)]


def _root_counts(roots):
    counts = {}
    for root in roots:
        counts[root] = counts.get(root, 0) + 1
    return counts


def _audit_cone_root_partitions(affected, partitions):
    if affected and not partitions:
        raise AssertionError("non-empty affected roots produced no cone partitions")
    if any(not group for group in partitions):
        raise AssertionError("empty cone partition")
    flattened = []
    for group in partitions:
        flattened.extend(group)
    if _root_counts(flattened) != _root_counts(affected):
        raise AssertionError("cone partition roots do not exactly cover affected roots")


def _solve_single_fault_roots(
    inputs,
    latches,
    roots,
    gates_raw,
    target_idx,
    stuck_value,
    timings,
    by_lhs,
    telemetry=None,
):
    cone = _fanin_indices_for_roots(gates_raw, roots, by_lhs=by_lhs)
    if telemetry is not None:
        telemetry["cone_partition_max_seen_cone_gates"] = max(
            telemetry["cone_partition_max_seen_cone_gates"], len(cone)
        )
    if target_idx not in cone:
        return "SKIP_TARGET_OUTSIDE_CONE", None
    if CONE_PARTITION_MAX_GATES > 0 and len(cone) > CONE_PARTITION_MAX_GATES:
        return f"SKIP_CONE_TOO_LARGE:{len(cone)}", None

    t_encode = time.time()
    clauses, miter_lit, shared = _build_single_fault_cone_miter(
        inputs, latches, roots, gates_raw, target_idx, stuck_value, cone
    )
    timings["Encode"] += time.time() - t_encode

    t_sat = time.time()
    with Glucose4(bootstrap_with=clauses) as solver:
        solver.conf_budget(CONE_BUDGET)
        result = solver.solve_limited(assumptions=[miter_lit])
        model = solver.get_model() if result is True and (CEX_PRUNING or CEX_POOL) else None
    timings["SAT"] += time.time() - t_sat

    if result is None:
        return "TIMEOUT", None
    if result is False:
        return "UNSAT", None
    primary_values = _model_primary_values_from_shared(inputs, latches, model, shared) if model else None
    return "SAT", primary_values


def _partitioned_cone_miter_check(
    inputs,
    latches,
    outputs,
    gates_raw,
    target_idx,
    stuck_value,
    timings,
    by_lhs,
    fanout,
    telemetry=None,
):
    affected = _affected_roots_from_graph(by_lhs, fanout, outputs, target_idx)
    if not affected:
        if telemetry is not None:
            telemetry["cone_partition_skipped"] += 1
            telemetry["cone_partition_no_affected"] += 1
        return "SKIP", None
    if len(affected) < CONE_PARTITION_MIN_ROOTS:
        if telemetry is not None:
            telemetry["cone_partition_skipped"] += 1
            telemetry["cone_partition_below_min_roots"] += 1
        return "SKIP", None

    partitions = _partition_roots(affected, CONE_PARTITION_SIZE)
    try:
        _audit_cone_root_partitions(affected, partitions)
    except AssertionError:
        if telemetry is not None:
            telemetry["cone_partition_audit_fail"] += 1
        return "SKIP", None

    if telemetry is not None:
        telemetry["cone_partition_checks"] += 1

    saw_timeout = False
    for roots in partitions:
        if telemetry is not None:
            telemetry["cone_partition_groups"] += 1
        result, primary_values = _solve_single_fault_roots(
            inputs,
            latches,
            roots,
            gates_raw,
            target_idx,
            stuck_value,
            timings,
            by_lhs,
            telemetry=telemetry,
        )
        if result == "SAT":
            if telemetry is not None:
                telemetry["cone_partition_sat"] += 1
            return "SAT", primary_values
        if result == "UNSAT":
            continue
        if result == "TIMEOUT":
            saw_timeout = True
            if not CONE_PARTITION_CONTINUE_AFTER_TIMEOUT:
                if telemetry is not None:
                    telemetry["cone_partition_timeouts"] += 1
                return "TIMEOUT", None
            continue
        if result == "SKIP_TARGET_OUTSIDE_CONE":
            if telemetry is not None:
                telemetry["cone_partition_audit_fail"] += 1
                telemetry["cone_partition_target_outside_cone"] += 1
                telemetry["cone_partition_skipped"] += 1
            return "SKIP", None
        if result.startswith("SKIP_CONE_TOO_LARGE:"):
            if telemetry is not None:
                telemetry["cone_partition_cone_too_large"] += 1
                telemetry["cone_partition_skipped"] += 1
                try:
                    cone_gates = int(result.split(":", 1)[1])
                    telemetry["cone_partition_max_seen_cone_gates"] = max(
                        telemetry["cone_partition_max_seen_cone_gates"], cone_gates
                    )
                    telemetry["cone_partition_max_skipped_cone_gates"] = max(
                        telemetry["cone_partition_max_skipped_cone_gates"], cone_gates
                    )
                except Exception:
                    pass
            return "SKIP", None
        if telemetry is not None:
            telemetry["cone_partition_skipped"] += 1
        return "SKIP", None

    if saw_timeout:
        if telemetry is not None:
            telemetry["cone_partition_timeouts"] += 1
        return "TIMEOUT", None

    if telemetry is not None:
        telemetry["cone_partition_unsat"] += 1
    return "UNSAT", None


def _observable_tfo_slice(fanout, target_idx, good_cone):
    relevant = set(good_cone)
    tfo = set()
    stack = [target_idx]
    while stack:
        idx = stack.pop()
        if idx not in relevant or idx in tfo:
            continue
        tfo.add(idx)
        for child in fanout[idx]:
            if child in relevant:
                stack.append(child)
    return tfo


def _fanin_dependency_tfo_slice(by_lhs, gates_raw, target_idx, good_cone):
    """Derive target dependence from fanins, independently of the fanout walk."""
    good_cone = set(good_cone)
    dependent = set()
    for idx in sorted(good_cone):
        if idx == target_idx:
            dependent.add(idx)
            continue
        _, r0, r1 = gates_raw[idx]
        if any(by_lhs.get(lit & ~1) in dependent for lit in (r0, r1)):
            dependent.add(idx)
    return dependent


def _audit_tfo_slice(
    by_lhs,
    fanout,
    affected_roots,
    target_idx,
    good_cone,
    tfo_slice,
    gates_raw=None,
):
    good_cone = set(good_cone)
    tfo_slice = set(tfo_slice)
    if target_idx not in good_cone or target_idx not in tfo_slice:
        raise AssertionError("TFO slice does not contain the target")

    expected = _observable_tfo_slice(fanout, target_idx, good_cone)
    if tfo_slice != expected:
        missing = sorted(expected - tfo_slice)
        extra = sorted(tfo_slice - expected)
        raise AssertionError(
            f"TFO slice mismatch; missing={missing[:10]}, extra={extra[:10]}"
        )

    if gates_raw is not None:
        independent = _fanin_dependency_tfo_slice(
            by_lhs,
            gates_raw,
            target_idx,
            good_cone,
        )
        if not independent.issubset(tfo_slice):
            missing = sorted(independent - tfo_slice)
            raise AssertionError(
                "TFO fanin-dependency audit mismatch; "
                f"missing={missing[:10]}"
            )

    for root in affected_roots:
        root_idx = by_lhs.get(root & ~1)
        if root_idx is None or root_idx not in tfo_slice:
            raise AssertionError(f"affected root {root} is outside the TFO slice")


def _build_single_fault_tfo_miter(
    inputs,
    latches,
    roots,
    gates_raw,
    target_idx,
    stuck_value,
    good_cone,
    tfo_slice,
):
    """Encode one exact fault using a good cone and only its faulty TFO slice."""
    cnf = _CNFBuilder()
    shared = {}
    good = {}
    faulty = {}

    for lit in inputs:
        shared[lit >> 1] = cnf.new_var()
    for latch in latches:
        shared[_parse_latch(latch)[0] >> 1] = cnf.new_var()

    def good_lit(aig_lit):
        if aig_lit == 0:
            return cnf.const(False)
        if aig_lit == 1:
            return cnf.const(True)
        var = aig_lit >> 1
        if var in good:
            sat_lit = good[var]
        elif var in shared:
            sat_lit = shared[var]
        else:
            raise ValueError(f"undefined literal in good TFO encoding: {aig_lit}")
        return -sat_lit if (aig_lit & 1) else sat_lit

    def faulty_lit(aig_lit):
        if aig_lit == 0:
            return cnf.const(False)
        if aig_lit == 1:
            return cnf.const(True)
        var = aig_lit >> 1
        if var in faulty:
            sat_lit = faulty[var]
        elif var in good:
            sat_lit = good[var]
        elif var in shared:
            sat_lit = shared[var]
        else:
            raise ValueError(f"undefined literal in faulty TFO encoding: {aig_lit}")
        return -sat_lit if (aig_lit & 1) else sat_lit

    for idx in sorted(good_cone):
        lhs, r0, r1 = gates_raw[idx]
        good_out = cnf.new_var()
        good[lhs >> 1] = good_out
        cnf.and2(good_out, good_lit(r0), good_lit(r1))

    for idx in sorted(tfo_slice):
        lhs, r0, r1 = gates_raw[idx]
        if idx == target_idx:
            faulty[lhs >> 1] = cnf.const(bool(stuck_value))
            continue
        faulty_out = cnf.new_var()
        faulty[lhs >> 1] = faulty_out
        cnf.and2(faulty_out, faulty_lit(r0), faulty_lit(r1))

    xors = []
    for root in roots:
        xor = cnf.new_var()
        cnf.xor2(xor, good_lit(root), faulty_lit(root))
        xors.append(xor)
    return cnf.clauses, cnf.or_many(xors), shared


def _tfo_miter_check(
    inputs,
    latches,
    outputs,
    gates_raw,
    target_idx,
    stuck_value,
    timings,
    by_lhs,
    fanout,
    telemetry=None,
):
    affected = _affected_roots_from_graph(by_lhs, fanout, outputs, target_idx)
    if not affected:
        if telemetry is not None:
            telemetry["cone_tfo_skipped"] += 1
        return "SKIP", None

    good_cone = _fanin_indices_for_roots(gates_raw, affected, by_lhs=by_lhs)
    tfo_slice = _observable_tfo_slice(fanout, target_idx, good_cone)
    try:
        _audit_tfo_slice(
            by_lhs,
            fanout,
            affected,
            target_idx,
            good_cone,
            tfo_slice,
            gates_raw,
        )
    except AssertionError:
        if telemetry is not None:
            telemetry["cone_tfo_audit_fail"] += 1
            telemetry["cone_tfo_skipped"] += 1
        return "SKIP", None

    if telemetry is not None:
        telemetry["cone_tfo_max_good_gates"] = max(
            telemetry["cone_tfo_max_good_gates"], len(good_cone)
        )
        telemetry["cone_tfo_max_faulty_gates"] = max(
            telemetry["cone_tfo_max_faulty_gates"], len(tfo_slice)
        )
    if CONE_TFO_MAX_GOOD_GATES > 0 and len(good_cone) > CONE_TFO_MAX_GOOD_GATES:
        if telemetry is not None:
            telemetry["cone_tfo_skipped"] += 1
        return "SKIP", None
    if CONE_TFO_MAX_FAULTY_GATES > 0 and len(tfo_slice) > CONE_TFO_MAX_FAULTY_GATES:
        if telemetry is not None:
            telemetry["cone_tfo_skipped"] += 1
        return "SKIP", None

    t_encode = time.time()
    clauses, miter_lit, shared = _build_single_fault_tfo_miter(
        inputs,
        latches,
        affected,
        gates_raw,
        target_idx,
        stuck_value,
        good_cone,
        tfo_slice,
    )
    timings["Encode"] += time.time() - t_encode

    t_sat = time.time()
    with Solver(name=CONE_SOLVER, bootstrap_with=clauses) as solver:
        result = _solve_limited_with_budget(solver, [miter_lit], CONE_BUDGET)
        model = solver.get_model() if result is True and (CEX_PRUNING or CEX_POOL) else None
    timings["SAT"] += time.time() - t_sat

    if telemetry is not None:
        telemetry["cone_tfo_checks"] += 1
    if result is None:
        if telemetry is not None:
            telemetry["cone_tfo_timeouts"] += 1
        return "TIMEOUT", None
    if result is False:
        if telemetry is not None:
            telemetry["cone_tfo_unsat"] += 1
        return "UNSAT", None
    if telemetry is not None:
        telemetry["cone_tfo_sat"] += 1
    primary_values = (
        _model_primary_values_from_shared(inputs, latches, model, shared) if model else None
    )
    return "SAT", primary_values


def _bounded_tfo_window_roots(by_lhs, fanout, observable_roots, gates_raw, target_idx, levels):
    if levels < 0:
        return []

    observable_by_idx = {}
    for root in observable_roots:
        root_idx = by_lhs.get(root & ~1)
        if root_idx is not None:
            observable_by_idx.setdefault(root_idx, []).append(root)

    roots = []
    seen_roots = set()
    queue = [(target_idx, 0)]
    head = 0
    best_depth = {}

    while head < len(queue):
        idx, depth = queue[head]
        head += 1
        old_depth = best_depth.get(idx)
        if old_depth is not None and old_depth <= depth:
            continue
        best_depth[idx] = depth

        if idx in observable_by_idx:
            for root in observable_by_idx[idx]:
                if root not in seen_roots:
                    seen_roots.add(root)
                    roots.append(root)
            continue

        if depth >= levels:
            root = gates_raw[idx][0]
            if root not in seen_roots:
                seen_roots.add(root)
                roots.append(root)
            continue

        children = sorted(fanout[idx])
        if not children:
            continue
        for child in children:
            queue.append((child, depth + 1))

    return roots


def _dominator_tfo_window_roots(by_lhs, fanout, observable_roots, gates_raw, target_idx):
    """Find a single audited TFO cut root, if one exists in the current graph.

    This is intentionally conservative: it proposes one internal/observable
    root only when the existing complete-cut audit says every path from the
    target to a real observable root crosses that root.
    """
    observable_by_idx = {}
    for root in observable_roots:
        root_idx = by_lhs.get(root & ~1)
        if root_idx is not None:
            observable_by_idx.setdefault(root_idx, []).append(root)

    queue = [(target_idx, 0)]
    head = 0
    best_depth = {}
    candidates = []
    considered = 0

    while head < len(queue):
        idx, depth = queue[head]
        head += 1
        old_depth = best_depth.get(idx)
        if old_depth is not None and old_depth <= depth:
            continue
        best_depth[idx] = depth

        if idx != target_idx:
            considered += 1
            if idx in observable_by_idx:
                roots = list(observable_by_idx[idx])
            else:
                roots = [gates_raw[idx][0]]

            if _window_roots_form_observable_cut(
                by_lhs, fanout, observable_roots, roots, target_idx
            ):
                cone = _fanin_indices_for_roots(gates_raw, roots, by_lhs=by_lhs)
                if target_idx in cone and (
                    WINDOW_MAX_CONE_GATES <= 0 or len(cone) <= WINDOW_MAX_CONE_GATES
                ):
                    candidates.append((len(cone), depth, roots))

            if WINDOW_DOMINATOR_MAX_ROOTS > 0 and considered >= WINDOW_DOMINATOR_MAX_ROOTS:
                break

        if WINDOW_DOMINATOR_MAX_LEVELS > 0 and depth >= WINDOW_DOMINATOR_MAX_LEVELS:
            continue
        for child in sorted(fanout[idx]):
            queue.append((child, depth + 1))

    if not candidates:
        return []
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates[0][2]


def _select_window_roots(by_lhs, fanout, observable_roots, gates_raw, target_idx):
    if WINDOW_ROOT_STRATEGY in {"dominator", "hybrid"}:
        roots = _dominator_tfo_window_roots(
            by_lhs, fanout, observable_roots, gates_raw, target_idx
        )
        if roots:
            return roots, "dominator"
        if WINDOW_ROOT_STRATEGY == "dominator":
            return [], "dominator"

    return (
        _bounded_tfo_window_roots(
            by_lhs, fanout, observable_roots, gates_raw, target_idx, WINDOW_LEVELS
        ),
        "bounded",
    )


def _solve_window_miter_for_roots(
    inputs, latches, outputs, gates_raw, target_idx, stuck_value, timings, by_lhs, fanout, roots
):
    if not roots:
        return "SKIP", None
    if WINDOW_AUDIT and not _window_roots_form_observable_cut(
        by_lhs, fanout, outputs, roots, target_idx
    ):
        return "AUDIT_FAIL", None

    cone = _fanin_indices_for_roots(gates_raw, roots, by_lhs=by_lhs)
    if target_idx not in cone:
        return "SKIP", None
    if WINDOW_MAX_CONE_GATES > 0 and len(cone) > WINDOW_MAX_CONE_GATES:
        return "SKIP", None

    t_encode = time.time()
    clauses, miter_lit, shared = _build_single_fault_cone_miter(
        inputs, latches, roots, gates_raw, target_idx, stuck_value, cone
    )
    timings["Encode"] += time.time() - t_encode

    t_sat = time.time()
    with Glucose4(bootstrap_with=clauses) as solver:
        solver.conf_budget(WINDOW_BUDGET)
        result = solver.solve_limited(assumptions=[miter_lit])
        model = solver.get_model() if result is True and (CEX_PRUNING or CEX_POOL) else None
    timings["SAT"] += time.time() - t_sat

    if result is None:
        return "TIMEOUT", None
    if result is False:
        return "UNSAT", None
    primary_values = _model_primary_values_from_shared(inputs, latches, model, shared) if model else None
    return "SAT", primary_values


def _window_roots_form_observable_cut(by_lhs, fanout, observable_roots, roots, target_idx):
    """Return True when roots cut every fanout path from target to an observable root."""
    observable_indices = {
        by_lhs[root & ~1] for root in observable_roots if (root & ~1) in by_lhs
    }
    root_indices = {by_lhs[root & ~1] for root in roots if (root & ~1) in by_lhs}
    if not root_indices:
        return False

    seen = set()
    stack = [target_idx]
    while stack:
        idx = stack.pop()
        if idx in seen:
            continue
        seen.add(idx)

        if idx in root_indices:
            continue
        if idx in observable_indices:
            return False
        stack.extend(fanout[idx])

    return True


def _window_miter_check(
    inputs, latches, outputs, gates_raw, target_idx, stuck_value, timings, by_lhs, fanout
):
    roots, root_source = _select_window_roots(by_lhs, fanout, outputs, gates_raw, target_idx)
    result, primary_values = _solve_window_miter_for_roots(
        inputs, latches, outputs, gates_raw, target_idx, stuck_value, timings, by_lhs, fanout, roots
    )
    if root_source == "dominator" and WINDOW_ROOT_STRATEGY == "hybrid" and result != "UNSAT":
        bounded_roots = _bounded_tfo_window_roots(
            by_lhs, fanout, outputs, gates_raw, target_idx, WINDOW_LEVELS
        )
        bounded_result, bounded_primary_values = _solve_window_miter_for_roots(
            inputs,
            latches,
            outputs,
            gates_raw,
            target_idx,
            stuck_value,
            timings,
            by_lhs,
            fanout,
            bounded_roots,
        )
        return bounded_result, bounded_primary_values, "bounded_after_dominator"
    return result, primary_values, root_source


def _run_window_miter_tier(
    inputs,
    latches,
    outputs,
    gates_raw,
    timings,
    deadline,
    initial_pruned=None,
    candidates_override=None,
    escalated=None,
):
    """UNSAT-only bounded TFO window. SAT/timeout/skip escalate to exact cone/global."""
    telemetry = _empty_phase_telemetry()
    accepted = {}

    if not WINDOW_MITER or not gates_raw or not outputs:
        return accepted, telemetry

    candidates = list(candidates_override) if candidates_override is not None else _candidate_order(gates_raw, roots=outputs)
    telemetry["max_budget"] = WINDOW_BUDGET
    working_gates = _copy_gates(gates_raw)
    by_lhs, fanout = _fanout_graph(gates_raw)
    pruned = set(initial_pruned or [])
    escalated_candidates = _unique_candidates(escalated or [])
    escalated_seen = set(escalated_candidates)

    def add_escalated(cand):
        if cand in pruned or cand in escalated_seen:
            return
        escalated_seen.add(cand)
        escalated_candidates.append(cand)

    try:
        for candidate_pos, (idx, stuck_value) in enumerate(candidates):
            if deadline is not None and time.time() >= deadline:
                telemetry["abort_reason"] = "TIME_BUDGET_CHECKPOINT"
                remaining = [
                    cand
                    for cand in candidates[candidate_pos:]
                    if cand not in pruned and cand[0] not in accepted
                ]
                telemetry["unresolved"] = len(remaining)
                if not accepted:
                    telemetry["_phase_resume_state"] = _tier_frontier_state(
                        "window", "TIME_BUDGET_CHECKPOINT", remaining, escalated_candidates
                    )
                return accepted, telemetry
            cand = (idx, stuck_value)
            if idx in accepted or cand in pruned:
                continue

            result, primary_values, root_source = _window_miter_check(
                inputs, latches, outputs, working_gates, idx, stuck_value, timings, by_lhs, fanout
            )
            if WINDOW_ROOT_STRATEGY in {"dominator", "hybrid"}:
                telemetry["window_dominator_attempts"] += 1
                if root_source == "dominator":
                    telemetry["window_dominator_used"] += 1
                elif WINDOW_ROOT_STRATEGY == "hybrid":
                    telemetry["window_dominator_fallbacks"] += 1
            if result in {"SKIP", "AUDIT_FAIL"}:
                telemetry["window_skipped"] += 1
                if result == "AUDIT_FAIL":
                    telemetry["window_audit_fail"] += 1
                add_escalated(cand)
                continue

            telemetry["checks"] += 1
            telemetry["window_checks"] += 1

            if result == "TIMEOUT":
                telemetry["timeouts"] += 1
                telemetry["window_timeouts"] += 1
                add_escalated(cand)
                continue
            if result == "SAT":
                telemetry["sat"] += 1
                telemetry["window_sat"] += 1
                add_escalated(cand)
                if primary_values is not None:
                    checked, newly_pruned = _cex_prune_from_primary_values(
                        inputs,
                        latches,
                        outputs,
                        working_gates,
                        primary_values,
                        {},
                        candidates[candidate_pos + 1 :],
                        pruned,
                        telemetry,
                        timings,
                        deadline=deadline,
                    )
                    if checked:
                        telemetry["cex_prune_events"] += 1
                        telemetry["cex_prune_checked"] += checked
                        telemetry["cex_pruned"] += newly_pruned
                        if newly_pruned:
                            _cex_pool_add(inputs, latches, primary_values, telemetry)
                continue

            telemetry["unsat"] += 1
            telemetry["window_unsat"] += 1
            accepted[idx] = stuck_value
            lhs = working_gates[idx][0]
            working_gates[idx] = [lhs, stuck_value, stuck_value]
            if stuck_value == 0:
                telemetry["accepted_sa0"] += 1
            else:
                telemetry["accepted_sa1"] += 1

            if len(accepted) >= REBUILD_AFTER_COMMITS:
                telemetry["abort_reason"] = "REBUILD_COMMIT_LIMIT"
                telemetry["unresolved"] = sum(
                    1
                    for cand in candidates[candidate_pos + 1 :]
                    if cand not in pruned and cand[0] not in accepted
                )
                return accepted, telemetry
    except KeyboardInterrupt:
        telemetry["abort_reason"] = "USER_INTERRUPT_CHECKPOINT"
        remaining = [
            cand
            for cand in candidates
            if cand not in pruned and cand[0] not in accepted
        ]
        telemetry["unresolved"] = len(remaining)
        if not accepted:
            telemetry["_phase_resume_state"] = _tier_frontier_state(
                "window", "USER_INTERRUPT_CHECKPOINT", remaining, escalated_candidates
            )
        return accepted, telemetry

    telemetry["_output_pruned_candidates"] = _candidate_list_for_resume(pruned)
    telemetry["_tier_escalated_candidates"] = _candidate_list_for_resume(
        [cand for cand in escalated_candidates if cand not in pruned]
    )
    telemetry["unresolved"] = 0
    return accepted, telemetry


def _run_cone_miter_tier(
    inputs,
    latches,
    outputs,
    gates_raw,
    timings,
    deadline,
    initial_pruned=None,
    candidates_override=None,
    escalated=None,
):
    """Prove candidates against only the outputs/latch-next roots they can affect."""
    telemetry = _empty_phase_telemetry()
    accepted = {}

    if not CONE_MITER or not gates_raw or not outputs:
        return accepted, telemetry

    candidates = list(candidates_override) if candidates_override is not None else _candidate_order(gates_raw, roots=outputs)
    telemetry["max_budget"] = CONE_BUDGET
    working_gates = _copy_gates(gates_raw)
    by_lhs, fanout = _fanout_graph(gates_raw)
    pruned = set(initial_pruned or [])
    escalated_candidates = _unique_candidates(escalated or [])
    escalated_seen = set(escalated_candidates)

    def add_escalated(cand):
        if cand in pruned or cand in escalated_seen:
            return
        escalated_seen.add(cand)
        escalated_candidates.append(cand)

    grouped_enabled = CONE_ENGINE in {"grouped", "hybrid"}
    partitioned_enabled = CONE_ENGINE in {"partitioned", "hybrid_partitioned"}
    tfo_enabled = CONE_ENGINE in {"tfo", "hybrid_tfo"}
    group_keys = {}
    group_cones = {}
    group_sizes = {}
    group_solvers = {}
    if grouped_enabled:
        pending_for_groups = [cand for cand in candidates if cand not in pruned]
        for idx, stuck_value in pending_for_groups:
            key, cone = _cone_group_key(gates_raw, outputs, idx, by_lhs, fanout)
            if key is None:
                continue
            group_keys[(idx, stuck_value)] = key
            group_cones[key] = cone
            group_sizes[key] = group_sizes.get(key, 0) + 1

    def close_group_solvers():
        for state in group_solvers.values():
            state.delete()
        group_solvers.clear()

    def should_use_grouped(candidate):
        if not grouped_enabled:
            return False
        key = group_keys.get(candidate)
        if key is None:
            return False
        if CONE_ENGINE == "grouped":
            return True
        return group_sizes.get(key, 0) >= CONE_GROUP_MIN_SIZE

    def grouped_check(candidate):
        idx, stuck_value = candidate
        key = group_keys.get(candidate)
        if key is None:
            return "SKIP", None
        state = group_solvers.get(key)
        if state is None:
            state = _make_cone_group_solver(
                inputs, latches, key, gates_raw, group_cones[key], accepted, timings
            )
            group_solvers[key] = state
        assumptions = state.assumptions_for(idx, stuck_value)
        if assumptions is None:
            return "SKIP", None
        if AUDIT_ASSUMPTIONS:
            _audit_cone_group_assumptions(
                assumptions,
                state,
                (idx, stuck_value),
                accepted=accepted,
            )

        t_sat = time.time()
        try:
            result = _solve_limited_with_budget(state.solver, assumptions, CONE_BUDGET)
        except NotImplementedError:
            return "SKIP", None
        model = state.solver.get_model() if result is True and (CEX_PRUNING or CEX_POOL) else None
        timings["SAT"] += time.time() - t_sat

        if result is None:
            return "TIMEOUT", None
        if result is False:
            return "UNSAT", None
        primary_values = (
            _model_primary_values_from_shared(inputs, latches, model, state.shared) if model else None
        )
        return "SAT", primary_values

    def activate_group_accept(gate_idx, stuck_value):
        for state in group_solvers.values():
            state.activate_accepted(gate_idx, stuck_value)

    try:
        for candidate_pos, (idx, stuck_value) in enumerate(candidates):
            if deadline is not None and time.time() >= deadline:
                telemetry["abort_reason"] = "TIME_BUDGET_CHECKPOINT"
                remaining = [
                    cand
                    for cand in candidates[candidate_pos:]
                    if cand not in pruned and cand[0] not in accepted
                ]
                telemetry["unresolved"] = len(remaining)
                if not accepted:
                    telemetry["_phase_resume_state"] = _tier_frontier_state(
                        "cone", "TIME_BUDGET_CHECKPOINT", remaining, escalated_candidates
                    )
                return accepted, telemetry
            cand = (idx, stuck_value)
            if idx in accepted or cand in pruned:
                continue

            if tfo_enabled:
                result, primary_values = _tfo_miter_check(
                    inputs,
                    latches,
                    outputs,
                    working_gates,
                    idx,
                    stuck_value,
                    timings,
                    by_lhs,
                    fanout,
                    telemetry=telemetry,
                )
                if result == "SKIP" and CONE_ENGINE == "hybrid_tfo":
                    result, primary_values = _cone_miter_check(
                        inputs,
                        latches,
                        outputs,
                        working_gates,
                        idx,
                        stuck_value,
                        timings,
                        by_lhs,
                        fanout,
                    )
            elif partitioned_enabled:
                result, primary_values = _partitioned_cone_miter_check(
                    inputs,
                    latches,
                    outputs,
                    working_gates,
                    idx,
                    stuck_value,
                    timings,
                    by_lhs,
                    fanout,
                    telemetry=telemetry,
                )
                if result == "SKIP":
                    telemetry["cone_partition_fallbacks"] += 1
                    result, primary_values = _cone_miter_check(
                        inputs, latches, outputs, working_gates, idx, stuck_value, timings, by_lhs, fanout
                    )
            elif should_use_grouped((idx, stuck_value)):
                result, primary_values = grouped_check((idx, stuck_value))
                if result == "SKIP" and CONE_ENGINE == "hybrid":
                    result, primary_values = _cone_miter_check(
                        inputs, latches, outputs, working_gates, idx, stuck_value, timings, by_lhs, fanout
                    )
            else:
                result, primary_values = _cone_miter_check(
                    inputs, latches, outputs, working_gates, idx, stuck_value, timings, by_lhs, fanout
                )
            if result == "SKIP":
                telemetry["cone_skipped"] += 1
                add_escalated(cand)
                continue

            telemetry["checks"] += 1
            telemetry["cone_checks"] += 1

            if result == "TIMEOUT":
                telemetry["timeouts"] += 1
                telemetry["cone_timeouts"] += 1
                add_escalated(cand)
                continue
            if result == "SAT":
                telemetry["sat"] += 1
                telemetry["cone_sat"] += 1
                pruned.add((idx, stuck_value))
                if primary_values is not None:
                    _cex_pool_add(inputs, latches, primary_values, telemetry)
                if primary_values is not None:
                    checked, newly_pruned = _cex_prune_from_primary_values(
                        inputs,
                        latches,
                        outputs,
                        working_gates,
                        primary_values,
                        {},
                        candidates[candidate_pos + 1 :],
                        pruned,
                        telemetry,
                        timings,
                        deadline=deadline,
                    )
                    if checked:
                        telemetry["cex_prune_events"] += 1
                        telemetry["cex_prune_checked"] += checked
                        telemetry["cex_pruned"] += newly_pruned
                        if newly_pruned:
                            _cex_pool_add(inputs, latches, primary_values, telemetry)
                continue

            telemetry["unsat"] += 1
            telemetry["cone_unsat"] += 1
            accepted[idx] = stuck_value
            lhs = working_gates[idx][0]
            working_gates[idx] = [lhs, stuck_value, stuck_value]
            activate_group_accept(idx, stuck_value)
            if stuck_value == 0:
                telemetry["accepted_sa0"] += 1
            else:
                telemetry["accepted_sa1"] += 1

            if len(accepted) >= REBUILD_AFTER_COMMITS:
                telemetry["abort_reason"] = "REBUILD_COMMIT_LIMIT"
                telemetry["unresolved"] = sum(
                    1
                    for cand in candidates[candidate_pos + 1 :]
                    if cand not in pruned and cand[0] not in accepted
                )
                return accepted, telemetry
    except KeyboardInterrupt:
        telemetry["abort_reason"] = "USER_INTERRUPT_CHECKPOINT"
        remaining = [
            cand
            for cand in candidates
            if cand not in pruned and cand[0] not in accepted
        ]
        telemetry["unresolved"] = len(remaining)
        if not accepted:
            telemetry["_phase_resume_state"] = _tier_frontier_state(
                "cone", "USER_INTERRUPT_CHECKPOINT", remaining, escalated_candidates
            )
        return accepted, telemetry
    finally:
        close_group_solvers()

    telemetry["_output_pruned_candidates"] = _candidate_list_for_resume(pruned)
    telemetry["_tier_escalated_candidates"] = _candidate_list_for_resume(
        [cand for cand in escalated_candidates if cand not in pruned]
    )
    telemetry["unresolved"] = 0
    return accepted, telemetry


def _audit_global_assumptions(
    assumptions,
    gate_count,
    f0_lits=None,
    f1_lits=None,
    candidate=None,
    accepted=None,
    miter_lit=None,
):
    if len(assumptions) != 2 * gate_count + 1:
        raise AssertionError(
            f"global SAT assumption count {len(assumptions)} != {2 * gate_count + 1}"
        )

    seen = set()
    for lit in assumptions:
        if lit in seen:
            raise AssertionError(f"duplicate assumption literal {lit}")
        if -lit in seen:
            raise AssertionError(f"contradictory assumption literals {lit} and {-lit}")
        seen.add(lit)

    if f0_lits is None or f1_lits is None or candidate is None or miter_lit is None:
        return

    accepted = accepted or {}
    cand_idx, cand_value = candidate
    expected_f0 = []
    expected_f1 = []

    for idx in range(gate_count):
        stuck_value = None
        if idx == cand_idx:
            stuck_value = cand_value
        elif idx in accepted:
            stuck_value = accepted[idx]

        if stuck_value is None:
            expected_f0.append(-f0_lits[idx])
            expected_f1.append(-f1_lits[idx])
        elif stuck_value == 0:
            expected_f0.append(f0_lits[idx])
            expected_f1.append(-f1_lits[idx])
        elif stuck_value == 1:
            expected_f0.append(-f0_lits[idx])
            expected_f1.append(f1_lits[idx])
        else:
            raise AssertionError(f"invalid stuck value in assumption audit: {stuck_value}")

    expected = expected_f0 + expected_f1 + [miter_lit]
    if assumptions != expected:
        missing = sorted(set(expected) - set(assumptions), key=abs)
        extra = sorted(set(assumptions) - set(expected), key=abs)
        raise AssertionError(
            "global SAT assumption content mismatch; "
            f"candidate=({cand_idx}, SA{cand_value}), "
            f"missing={missing[:10]}, extra={extra[:10]}"
        )


def _model_primary_values(inputs, latches, model):
    """Recover global PI/latch-current values from _build_fault_sweep_cnf's var order."""
    assigned = {abs(lit): lit > 0 for lit in model}
    sat_var = 2  # CNF var 1 is the builder's forced-true constant.
    values = {}

    for lit in inputs:
        values[lit & ~1] = assigned.get(sat_var, False)
        sat_var += 1
    for latch in latches:
        current = _parse_latch(latch)[0]
        values[current & ~1] = assigned.get(sat_var, False)
        sat_var += 1

    return values


def _model_primary_values_from_shared(inputs, latches, model, shared):
    """Recover a concrete global assignment from a local cone/window SAT model."""
    assigned = {abs(lit): lit > 0 for lit in model}
    values = {}

    for lit in inputs:
        sat_var = shared.get(lit >> 1)
        values[lit & ~1] = assigned.get(sat_var, False) if sat_var is not None else False
    for latch in latches:
        current = _parse_latch(latch)[0]
        sat_var = shared.get(current >> 1)
        values[current & ~1] = assigned.get(sat_var, False) if sat_var is not None else False

    return values


def _deadline_expired(deadline):
    return deadline is not None and time.time() >= deadline


def _scalar_lit_value(aig_lit, primary_values, gate_values, by_lhs):
    if aig_lit == 0:
        return False
    if aig_lit == 1:
        return True

    base = aig_lit & ~1
    idx = by_lhs.get(base)
    if idx is not None:
        value = gate_values[idx]
    else:
        value = primary_values.get(base, False)
    return not value if (aig_lit & 1) else value


def _simulate_good_roots(inputs, latches, roots, gates_raw, primary_values, by_lhs):
    del inputs, latches  # Primary values are already extracted from the model.
    gate_values = [False for _ in gates_raw]
    for idx, (lhs, r0, r1) in enumerate(gates_raw):
        gate_values[idx] = _scalar_lit_value(r0, primary_values, gate_values, by_lhs) and _scalar_lit_value(
            r1, primary_values, gate_values, by_lhs
        )
    root_values = tuple(_scalar_lit_value(root, primary_values, gate_values, by_lhs) for root in roots)
    return gate_values, root_values


def _audit_candidate_with_global_miter(
    inputs, latches, roots, gates_raw, accepted, candidate, timings, deadline=None
):
    """
    Re-check one CEX-pruned candidate in the exact current committed context.

    SAT means the CEX prune was consistent with the full observable miter.
    UNSAT means the prune would have silently discarded a valid redundancy.
    """
    if _deadline_expired(deadline):
        return "TIMEOUT"
    if not roots:
        return "SKIP"

    idx, stuck_value = candidate
    working_gates = _apply_accepts(gates_raw, accepted) if accepted else gates_raw
    by_lhs = {lhs & ~1: gate_idx for gate_idx, (lhs, _, _) in enumerate(working_gates)}
    cone = _fanin_indices_for_roots(working_gates, roots, by_lhs=by_lhs)
    if idx not in cone:
        return "UNSAT"

    t_encode = time.time()
    try:
        clauses, miter_lit, _ = _build_single_fault_cone_miter(
            inputs, latches, roots, working_gates, idx, stuck_value, cone
        )
    except Exception:
        return "SKIP"
    timings["Encode"] += time.time() - t_encode

    if _deadline_expired(deadline):
        return "TIMEOUT"

    t_sat = time.time()
    with Glucose4(bootstrap_with=clauses) as solver:
        solver.conf_budget(AUDIT_CEX_PRUNING_BUDGET)
        result = solver.solve_limited(assumptions=[miter_lit])
    timings["SAT"] += time.time() - t_sat

    if result is None:
        return "TIMEOUT"
    if result is False:
        return "UNSAT"
    return "SAT"


def _audit_cex_prune_if_enabled(
    inputs, latches, roots, gates_raw, accepted, candidate, telemetry, timings, deadline=None
):
    if not AUDIT_CEX_PRUNING:
        return "NOT_AUDITED"

    if _deadline_expired(deadline):
        telemetry["cex_audit_timeouts"] += 1
        return "TIMEOUT"

    if AUDIT_CEX_PRUNING_MAX > 0 and telemetry["cex_audit_checked"] >= AUDIT_CEX_PRUNING_MAX:
        telemetry["cex_audit_limit_hit"] += 1
        return "LIMIT"

    telemetry["cex_audit_checked"] += 1
    result = _audit_candidate_with_global_miter(
        inputs, latches, roots, gates_raw, accepted, candidate, timings, deadline=deadline
    )
    if result == "SAT":
        telemetry["cex_audit_sat"] += 1
    elif result == "UNSAT":
        telemetry["cex_audit_unsat_false_prune"] += 1
    elif result == "TIMEOUT":
        telemetry["cex_audit_timeouts"] += 1
    else:
        telemetry["cex_audit_skipped"] += 1
    return result


def _batch_lit_mask(aig_lit, primary_values, gate_masks, by_lhs, full_mask):
    if aig_lit == 0:
        return 0
    if aig_lit == 1:
        return full_mask

    base = aig_lit & ~1
    idx = by_lhs.get(base)
    if idx is not None:
        mask = gate_masks[idx]
    else:
        mask = full_mask if primary_values.get(base, False) else 0
    return mask ^ full_mask if (aig_lit & 1) else mask


def _cex_prune_from_primary_values(
    inputs,
    latches,
    roots,
    gates_raw,
    primary_values,
    accepted,
    pending,
    already_pruned,
    telemetry=None,
    timings=None,
    deadline=None,
):
    """
    Use one concrete global PI/latch assignment to reject candidates in this phase.

    This is a rejection-only optimization. It simulates the same future global
    miter relation under one concrete PI/latch assignment:
      good current circuit vs. current accepted faults plus one candidate.
    If any observable root differs, that candidate would be SAT under this
    assignment and can be skipped until the next structural rebuild/phase.
    """
    if not (CEX_PRUNING or PRE_SIM_REJECTION or CEX_POOL) or not pending:
        return 0, 0

    by_lhs = {lhs & ~1: idx for idx, (lhs, _, _) in enumerate(gates_raw)}
    _, good_roots = _simulate_good_roots(inputs, latches, roots, gates_raw, primary_values, by_lhs)

    candidates = [
        cand
        for cand in pending
        if cand not in already_pruned and cand[0] not in accepted
    ]
    if CEX_PRUNING_MAX_CANDIDATES > 0:
        candidates = candidates[:CEX_PRUNING_MAX_CANDIDATES]
    if not candidates:
        return 0, 0

    checked = 0
    newly_pruned = 0

    for start in range(0, len(candidates), CEX_PRUNING_BATCH_SIZE):
        if _deadline_expired(deadline):
            if telemetry is not None:
                telemetry["abort_reason"] = "TIME_BUDGET_CHECKPOINT"
                telemetry["unresolved"] = len(candidates) - start
            break

        batch = candidates[start : start + CEX_PRUNING_BATCH_SIZE]
        checked += len(batch)
        full_mask = (1 << len(batch)) - 1
        force_zero = {}
        force_one = {}

        for bit, (idx, stuck_value) in enumerate(batch):
            bit_mask = 1 << bit
            if stuck_value == 0:
                force_zero[idx] = force_zero.get(idx, 0) | bit_mask
            else:
                force_one[idx] = force_one.get(idx, 0) | bit_mask

        gate_masks = [0 for _ in gates_raw]
        for idx, (_, r0, r1) in enumerate(gates_raw):
            if idx in accepted:
                mask = full_mask if accepted[idx] else 0
            else:
                mask = _batch_lit_mask(r0, primary_values, gate_masks, by_lhs, full_mask) & _batch_lit_mask(
                    r1, primary_values, gate_masks, by_lhs, full_mask
                )

            if idx in force_zero:
                mask &= full_mask ^ force_zero[idx]
            if idx in force_one:
                mask |= force_one[idx]
            gate_masks[idx] = mask

        diff_mask = 0
        for root_pos, root in enumerate(roots):
            root_mask = _batch_lit_mask(root, primary_values, gate_masks, by_lhs, full_mask)
            good_mask = full_mask if good_roots[root_pos] else 0
            diff_mask |= root_mask ^ good_mask

        bit = 0
        while diff_mask:
            if _deadline_expired(deadline):
                if telemetry is not None:
                    telemetry["abort_reason"] = "TIME_BUDGET_CHECKPOINT"
                    telemetry["unresolved"] = len(candidates) - start
                return checked, newly_pruned
            if diff_mask & 1:
                cand = batch[bit]
                audit_result = "NOT_AUDITED"
                if telemetry is not None and timings is not None:
                    audit_result = _audit_cex_prune_if_enabled(
                        inputs,
                        latches,
                        roots,
                        gates_raw,
                        accepted,
                        cand,
                        telemetry,
                        timings,
                        deadline=deadline,
                    )
                if audit_result not in {"UNSAT", "TIMEOUT", "SKIP"}:
                    already_pruned.add(cand)
                    newly_pruned += 1
            diff_mask >>= 1
            bit += 1

    return checked, newly_pruned


def _cex_prune_candidates(
    inputs, latches, roots, gates_raw, model, accepted, pending, already_pruned, telemetry, timings, deadline=None
):
    primary_values = _model_primary_values(inputs, latches, model)
    return _cex_prune_from_primary_values(
        inputs,
        latches,
        roots,
        gates_raw,
        primary_values,
        accepted,
        pending,
        already_pruned,
        telemetry,
        timings,
        deadline=deadline,
    )


def _packed_pre_sim_lit_mask(aig_lit, primary_masks, gate_masks, by_lhs, full_mask):
    if aig_lit == 0:
        return 0
    if aig_lit == 1:
        return full_mask

    base = aig_lit & ~1
    idx = by_lhs.get(base)
    if idx is not None:
        mask = gate_masks[idx]
    else:
        mask = primary_masks.get(base, 0)
    return mask ^ full_mask if (aig_lit & 1) else mask


def _repeat_pre_sim_pattern_mask(mask, pattern_count, repeat_count):
    result = 0
    shift = 0
    for _ in range(repeat_count):
        result |= mask << shift
        shift += pattern_count
    return result


def _primary_pre_sim_pattern_masks(inputs, latches, patterns):
    bases = _primary_bases(inputs, latches)
    masks = {base: 0 for base in bases}
    for bit, (_kind, primary_values) in enumerate(patterns):
        for base in bases:
            if primary_values.get(base, False):
                masks[base] |= 1 << bit
    return masks


def _good_root_pre_sim_pattern_masks(gates_raw, roots, primary_masks, by_lhs, pattern_mask):
    gate_masks = [0 for _ in gates_raw]
    for idx, (_lhs, r0, r1) in enumerate(gates_raw):
        mask = _packed_pre_sim_lit_mask(r0, primary_masks, gate_masks, by_lhs, pattern_mask)
        mask &= _packed_pre_sim_lit_mask(r1, primary_masks, gate_masks, by_lhs, pattern_mask)
        gate_masks[idx] = mask
    return [
        _packed_pre_sim_lit_mask(root, primary_masks, gate_masks, by_lhs, pattern_mask)
        for root in roots
    ]


def _cex_prune_from_primary_patterns_packed(
    inputs,
    latches,
    roots,
    gates_raw,
    patterns,
    accepted,
    pending,
    already_pruned,
    telemetry=None,
    timings=None,
    deadline=None,
):
    """
    Reject candidates using many concrete PI assignments packed into one pass.

    This is equivalent in acceptance policy to repeated calls to
    _cex_prune_from_primary_values: it only rejects candidates that produce an
    observable root difference under at least one concrete assignment.
    """
    if not (CEX_PRUNING or PRE_SIM_REJECTION or CEX_POOL) or not pending or not patterns:
        return 0, 0, 0, 0

    candidates = [
        cand
        for cand in pending
        if cand not in already_pruned and cand[0] not in accepted
    ]
    if CEX_PRUNING_MAX_CANDIDATES > 0:
        candidates = candidates[:CEX_PRUNING_MAX_CANDIDATES]
    if not candidates:
        return 0, 0, 0, 0

    pattern_count = len(patterns)
    by_lhs = {lhs & ~1: idx for idx, (lhs, _, _) in enumerate(gates_raw)}
    pattern_mask = (1 << pattern_count) - 1
    primary_patterns = _primary_pre_sim_pattern_masks(inputs, latches, patterns)
    good_roots = _good_root_pre_sim_pattern_masks(
        gates_raw, roots, primary_patterns, by_lhs, pattern_mask
    )

    structured_mask = 0
    for bit, (kind, _primary_values) in enumerate(patterns):
        if kind == "structured":
            structured_mask |= 1 << bit
    random_mask = pattern_mask ^ structured_mask

    batch_candidates = max(1, PRE_SIM_PACKED_MAX_BITS // pattern_count)
    checked = 0
    newly_pruned = 0
    structured_pruned = 0
    random_pruned = 0

    for start in range(0, len(candidates), batch_candidates):
        if _deadline_expired(deadline):
            if telemetry is not None:
                telemetry["abort_reason"] = "TIME_BUDGET_CHECKPOINT"
                telemetry["unresolved"] = len(candidates) - start
            break

        batch = candidates[start : start + batch_candidates]
        batch_len = len(batch)
        full_mask = (1 << (batch_len * pattern_count)) - 1
        primary_masks = {
            base: _repeat_pre_sim_pattern_mask(mask, pattern_count, batch_len)
            for base, mask in primary_patterns.items()
        }
        good_batch_roots = [
            _repeat_pre_sim_pattern_mask(mask, pattern_count, batch_len)
            for mask in good_roots
        ]

        force_zero = {}
        force_one = {}
        for slot, (idx, stuck_value) in enumerate(batch):
            lane_mask = pattern_mask << (slot * pattern_count)
            if stuck_value == 0:
                force_zero[idx] = force_zero.get(idx, 0) | lane_mask
            else:
                force_one[idx] = force_one.get(idx, 0) | lane_mask

        gate_masks = [0 for _ in gates_raw]
        for idx, (_lhs, r0, r1) in enumerate(gates_raw):
            if idx in accepted:
                mask = full_mask if accepted[idx] else 0
            else:
                mask = _packed_pre_sim_lit_mask(r0, primary_masks, gate_masks, by_lhs, full_mask)
                mask &= _packed_pre_sim_lit_mask(r1, primary_masks, gate_masks, by_lhs, full_mask)
            if idx in force_zero:
                mask &= full_mask ^ force_zero[idx]
            if idx in force_one:
                mask |= force_one[idx]
            gate_masks[idx] = mask

        diff_mask = 0
        for root, good_mask in zip(roots, good_batch_roots):
            root_mask = _packed_pre_sim_lit_mask(root, primary_masks, gate_masks, by_lhs, full_mask)
            diff_mask |= root_mask ^ good_mask

        checked += len(batch) * pattern_count
        for slot, cand in enumerate(batch):
            lane_diff = (diff_mask >> (slot * pattern_count)) & pattern_mask
            if not lane_diff:
                continue

            audit_result = "NOT_AUDITED"
            if telemetry is not None and timings is not None:
                audit_result = _audit_cex_prune_if_enabled(
                    inputs,
                    latches,
                    roots,
                    gates_raw,
                    accepted,
                    cand,
                    telemetry,
                    timings,
                    deadline=deadline,
                )
            if audit_result in {"UNSAT", "TIMEOUT", "SKIP"}:
                continue

            already_pruned.add(cand)
            newly_pruned += 1
            if lane_diff & structured_mask:
                structured_pruned += 1
            elif lane_diff & random_mask:
                random_pruned += 1

    return checked, newly_pruned, structured_pruned, random_pruned


def _pre_sim_assignment(bases, bits):
    return {base: bool(bit) for base, bit in zip(bases, bits)}


def _iter_pre_sim_patterns(inputs, latches):
    bases = _primary_bases(inputs, latches)
    n = len(bases)
    if n == 0:
        yield "structured", {}
        return

    yield "structured", _pre_sim_assignment(bases, [0] * n)
    yield "structured", _pre_sim_assignment(bases, [1] * n)
    yield "structured", _pre_sim_assignment(bases, [(idx & 1) for idx in range(n)])
    yield "structured", _pre_sim_assignment(bases, [((idx + 1) & 1) for idx in range(n)])

    walk_count = min(n, max(0, PRE_SIM_WALK_PATTERNS))
    for idx in range(walk_count):
        bits = [0] * n
        bits[idx] = 1
        yield "structured", _pre_sim_assignment(bases, bits)

    for idx in range(walk_count):
        bits = [1] * n
        bits[idx] = 0
        yield "structured", _pre_sim_assignment(bases, bits)

    rng = random.Random(PRE_SIM_SEED + n)
    for _ in range(max(0, PRE_SIM_RANDOM_PATTERNS)):
        yield "random", {base: bool(rng.getrandbits(1)) for base in bases}


def _run_pre_sim_rejection(inputs, latches, roots, gates_raw, candidates, telemetry, timings, deadline=None):
    """Reject globally observable candidates using concrete deterministic assignments."""
    pruned = set()
    if not PRE_SIM_REJECTION or not candidates or not roots:
        return pruned

    local_seconds = PRE_SIM_MAX_SECONDS
    if deadline is not None and PRE_SIM_MAX_FRACTION > 0:
        remaining = max(0.0, deadline - time.time())
        fraction_cap = remaining * PRE_SIM_MAX_FRACTION
        local_seconds = min(local_seconds, fraction_cap) if local_seconds > 0 else fraction_cap
    local_deadline = time.time() + local_seconds if local_seconds > 0 else None
    t_start = time.time()
    random_started = False
    low_gain_random_streak = 0

    if PRE_SIM_ENGINE == "packed":
        effective_deadline = local_deadline
        if deadline is not None:
            effective_deadline = min(deadline, local_deadline) if local_deadline is not None else deadline

        patterns = []
        for pattern in _iter_pre_sim_patterns(inputs, latches):
            patterns.append(pattern)
        structured_patterns = [pattern for pattern in patterns if pattern[0] != "random"]
        random_patterns = [pattern for pattern in patterns if pattern[0] == "random"]

        def run_packed(pattern_subset):
            if not pattern_subset or _deadline_expired(deadline) or _deadline_expired(local_deadline):
                return 0, 0, 0, 0
            checked, newly_pruned, structured_pruned, random_pruned = (
                _cex_prune_from_primary_patterns_packed(
                    inputs,
                    latches,
                    roots,
                    gates_raw,
                    pattern_subset,
                    {},
                    candidates,
                    pruned,
                    telemetry if AUDIT_CEX_PRUNING else None,
                    timings if AUDIT_CEX_PRUNING else None,
                    deadline=effective_deadline,
                )
            )
            telemetry["pre_sim_patterns"] += len(pattern_subset)
            telemetry["pre_sim_checked"] += checked
            telemetry["pre_sim_pruned"] += newly_pruned
            telemetry["pre_sim_structured_pruned"] += structured_pruned
            telemetry["pre_sim_random_pruned"] += random_pruned
            if newly_pruned:
                for _kind, primary_values in pattern_subset[:4]:
                    _cex_pool_add(inputs, latches, primary_values, telemetry)
            return checked, newly_pruned, structured_pruned, random_pruned

        _checked, _newly_pruned, _structured_pruned, _random_pruned = run_packed(
            structured_patterns
        )
        if PRE_SIM_ADAPTIVE:
            min_pruned = max(
                PRE_SIM_ADAPTIVE_MIN_RANDOM_PRUNED,
                int(len(candidates) * PRE_SIM_ADAPTIVE_MIN_RANDOM_FRACTION),
            )
            if len(pruned) < min_pruned:
                telemetry["pre_sim_adaptive_stop"] = "LOW_STRUCTURED_GAIN"
                elapsed = time.time() - t_start
                telemetry["pre_sim_time"] += elapsed
                timings["PreSAT_Sim"] += elapsed
                return pruned

        if len(pruned) < len(candidates):
            run_packed(random_patterns)

        elapsed = time.time() - t_start
        telemetry["pre_sim_time"] += elapsed
        timings["PreSAT_Sim"] += elapsed
        return pruned

    for kind, primary_values in _iter_pre_sim_patterns(inputs, latches):
        if _deadline_expired(deadline) or _deadline_expired(local_deadline):
            break
        if PRE_SIM_ADAPTIVE and kind == "random" and not random_started:
            random_started = True
            min_pruned = max(
                PRE_SIM_ADAPTIVE_MIN_RANDOM_PRUNED,
                int(len(candidates) * PRE_SIM_ADAPTIVE_MIN_RANDOM_FRACTION),
            )
            if len(pruned) < min_pruned:
                telemetry["pre_sim_adaptive_stop"] = "LOW_STRUCTURED_GAIN"
                break

        checked, newly_pruned = _cex_prune_from_primary_values(
            inputs,
            latches,
            roots,
            gates_raw,
            primary_values,
            {},
            candidates,
            pruned,
            telemetry if AUDIT_CEX_PRUNING else None,
            timings if AUDIT_CEX_PRUNING else None,
            deadline=deadline,
        )
        telemetry["pre_sim_patterns"] += 1
        telemetry["pre_sim_checked"] += checked
        telemetry["pre_sim_pruned"] += newly_pruned
        if kind == "random":
            telemetry["pre_sim_random_pruned"] += newly_pruned
            if PRE_SIM_ADAPTIVE:
                if newly_pruned <= 0:
                    low_gain_random_streak += 1
                else:
                    low_gain_random_streak = 0
        else:
            telemetry["pre_sim_structured_pruned"] += newly_pruned
        if newly_pruned:
            _cex_pool_add(inputs, latches, primary_values, telemetry)

        if len(pruned) == len(candidates):
            break
        if (
            PRE_SIM_ADAPTIVE
            and kind == "random"
            and PRE_SIM_ADAPTIVE_RANDOM_PATIENCE > 0
            and low_gain_random_streak >= PRE_SIM_ADAPTIVE_RANDOM_PATIENCE
        ):
            telemetry["pre_sim_adaptive_stop"] = "LOW_RANDOM_GAIN"
            break

    elapsed = time.time() - t_start
    telemetry["pre_sim_time"] += elapsed
    timings["PreSAT_Sim"] += elapsed
    return pruned


def _run_cex_pool_replay(inputs, latches, roots, gates_raw, candidates, telemetry, timings, deadline=None):
    pruned = set()
    if not CEX_POOL or not _ACTIVE_CEX_POOL or not candidates or not roots:
        return pruned

    vectors = _ACTIVE_CEX_POOL
    if CEX_POOL_REPLAY_MAX_VECTORS > 0:
        vectors = vectors[:CEX_POOL_REPLAY_MAX_VECTORS]

    for encoded in vectors:
        if _deadline_expired(deadline):
            break
        primary_values = _decode_primary_values(inputs, latches, encoded)
        if primary_values is None:
            continue
        checked, newly_pruned = _cex_prune_from_primary_values(
            inputs,
            latches,
            roots,
            gates_raw,
            primary_values,
            {},
            candidates,
            pruned,
            telemetry if AUDIT_CEX_PRUNING else None,
            timings if AUDIT_CEX_PRUNING else None,
            deadline=deadline,
        )
        telemetry["cex_pool_replay_patterns"] += 1
        telemetry["cex_pool_replay_checked"] += checked
        telemetry["cex_pool_replay_pruned"] += newly_pruned
        if len(pruned) == len(candidates):
            break

    return pruned


def _run_budgeted_global_sat(
    inputs,
    latches,
    outputs,
    gates_raw,
    timings,
    deadline,
    record_candidates=True,
    initial_pruned=None,
    run_pre_sim=True,
    resume_candidates=None,
    resume_max_budget_tried=None,
    resume_from_phase=False,
):
    """Return accepted {gate_index: stuck_value} using increasing budgets."""
    telemetry = _empty_phase_telemetry()
    if not gates_raw or not outputs:
        return {}, telemetry

    t_encode = time.time()
    clauses, miter_lit, f0_lits, f1_lits = _build_fault_sweep_cnf(
        inputs, latches, outputs, gates_raw
    )
    timings["Encode"] += time.time() - t_encode

    A = len(gates_raw)
    telemetry["candidates"] = 2 * A if record_candidates else 0
    control_state = [-lit for lit in f0_lits] + [-lit for lit in f1_lits]
    accepted = {}
    pruned = set(initial_pruned or [])
    unresolved = list(resume_candidates) if resume_candidates is not None else _candidate_order(gates_raw, roots=outputs)
    max_budget_tried = dict(resume_max_budget_tried or {})
    if resume_from_phase:
        telemetry["phase_resume_used"] = 1
        telemetry["global_budget_history_loaded"] = sum(
            1 for cand in unresolved if max_budget_tried.get(cand, 0) > 0
        )

    if run_pre_sim:
        pre_pruned = _run_pre_sim_rejection(
            inputs, latches, outputs, gates_raw, unresolved, telemetry, timings, deadline=deadline
        )
        if pre_pruned:
            pruned.update(pre_pruned)
        if _deadline_expired(deadline):
            telemetry["abort_reason"] = "TIME_BUDGET_CHECKPOINT"
            telemetry["unresolved"] = sum(1 for cand in unresolved if cand not in pruned)
            return accepted, telemetry

    unresolved = [cand for cand in unresolved if cand not in pruned]
    if not unresolved:
        telemetry["unresolved"] = 0
        return accepted, telemetry
    unresolved = _order_global_frontier(
        unresolved,
        gates_raw,
        max_budget_tried,
        roots=outputs,
    )

    t_sat = time.time()
    try:
        with Solver(name=GLOBAL_SOLVER, bootstrap_with=clauses) as solver:
            _apply_global_initial_phases(solver, f0_lits, f1_lits)
            last_phase_model = None
            consecutive_timeouts = 0
            for budget in SAT_BUDGETS:
                telemetry["budget_rounds"] += 1
                telemetry["max_budget"] = budget
                next_unresolved = []

                for candidate_pos, (idx, stuck_value) in enumerate(unresolved):
                    if deadline is not None and time.time() >= deadline:
                        telemetry["abort_reason"] = "TIME_BUDGET_CHECKPOINT"
                        remaining = [
                            cand
                            for cand in next_unresolved + unresolved[candidate_pos:]
                            if cand not in pruned and cand[0] not in accepted
                        ]
                        telemetry["unresolved"] = len(remaining)
                        telemetry["_phase_resume_state"] = {
                            "schema": "alg10_global_frontier_v1",
                            "tier": "global",
                            "reason": "TIME_BUDGET_CHECKPOINT",
                            "candidate_order": CANDIDATE_ORDER,
                            "sat_budgets": list(SAT_BUDGETS),
                            "candidates": _candidate_budget_list_for_resume(remaining, max_budget_tried),
                        }
                        timings["SAT"] += time.time() - t_sat
                        return accepted, telemetry
                    if idx in accepted or (idx, stuck_value) in pruned:
                        continue
                    cand = (idx, stuck_value)
                    if budget <= max_budget_tried.get(cand, 0):
                        telemetry["global_budget_history_skipped"] += 1
                        next_unresolved.append(cand)
                        continue

                    pos, lit, opposite_pos, opposite_lit = _control_position(
                        A, idx, stuck_value, f0_lits, f1_lits
                    )

                    assumptions = control_state.copy()
                    assumptions[pos] = lit
                    assumptions[opposite_pos] = -opposite_lit
                    assumptions.append(miter_lit)
                    if AUDIT_ASSUMPTIONS:
                        _audit_global_assumptions(
                            assumptions,
                            A,
                            f0_lits=f0_lits,
                            f1_lits=f1_lits,
                            candidate=(idx, stuck_value),
                            accepted=accepted,
                            miter_lit=miter_lit,
                        )

                    telemetry["checks"] += 1
                    telemetry["global_checks"] += 1
                    _apply_global_model_phases(solver, last_phase_model)
                    solver.conf_budget(budget)
                    result = solver.solve_limited(assumptions=assumptions)

                    if result is None:
                        telemetry["timeouts"] += 1
                        telemetry["global_timeouts"] += 1
                        max_budget_tried[(idx, stuck_value)] = max(
                            max_budget_tried.get((idx, stuck_value), 0), budget
                        )
                        next_unresolved.append((idx, stuck_value))
                        consecutive_timeouts += 1
                        if (
                            GLOBAL_MAX_CONSEC_TIMEOUTS > 0
                            and consecutive_timeouts >= GLOBAL_MAX_CONSEC_TIMEOUTS
                        ):
                            telemetry["abort_reason"] = "GLOBAL_TIMEOUT_STREAK"
                            remaining = [
                                cand
                                for cand in next_unresolved + unresolved[candidate_pos + 1 :]
                                if cand not in pruned and cand[0] not in accepted
                            ]
                            telemetry["unresolved"] = len(remaining)
                            telemetry["_phase_resume_state"] = {
                                "schema": "alg10_global_frontier_v1",
                                "tier": "global",
                                "reason": "GLOBAL_TIMEOUT_STREAK",
                                "candidate_order": CANDIDATE_ORDER,
                                "sat_budgets": list(SAT_BUDGETS),
                                "candidates": _candidate_budget_list_for_resume(
                                    remaining, max_budget_tried
                                ),
                            }
                            timings["SAT"] += time.time() - t_sat
                            return accepted, telemetry
                        continue

                    if result is True:
                        consecutive_timeouts = 0
                        telemetry["sat"] += 1
                        telemetry["global_sat"] += 1
                        want_model = (
                            CEX_PRUNING
                            or CEX_POOL
                            or GLOBAL_PHASE_MODE in {"model", "controls_false_model"}
                        )
                        model = solver.get_model() if want_model else None
                        if model and GLOBAL_PHASE_MODE in {"model", "controls_false_model"}:
                            last_phase_model = model
                        if model:
                            _cex_pool_add(
                                inputs,
                                latches,
                                _model_primary_values(inputs, latches, model),
                                telemetry,
                            )
                            pending = next_unresolved + unresolved[candidate_pos + 1 :]
                            checked, newly_pruned = _cex_prune_candidates(
                                inputs,
                                latches,
                                outputs,
                                gates_raw,
                                model,
                                accepted,
                                pending,
                                pruned,
                                telemetry,
                                timings,
                                deadline=deadline,
                            )
                            if checked:
                                telemetry["cex_prune_events"] += 1
                                telemetry["cex_prune_checked"] += checked
                                telemetry["cex_pruned"] += newly_pruned
                        continue

                    telemetry["unsat"] += 1
                    consecutive_timeouts = 0
                    telemetry["global_unsat"] += 1
                    accepted[idx] = stuck_value
                    if stuck_value == 0:
                        telemetry["accepted_sa0"] += 1
                    else:
                        telemetry["accepted_sa1"] += 1
                    control_state[pos] = lit
                    control_state[opposite_pos] = -opposite_lit
                    if COMMIT_UNIT_CLAUSES:
                        solver.add_clause([lit])
                        solver.add_clause([-opposite_lit])

                    if len(accepted) >= REBUILD_AFTER_COMMITS:
                        telemetry["abort_reason"] = "REBUILD_COMMIT_LIMIT"
                        remaining = [
                            cand
                            for cand in next_unresolved + unresolved[candidate_pos + 1 :]
                            if cand not in pruned and cand[0] not in accepted
                        ]
                        telemetry["unresolved"] = len(remaining)
                        timings["SAT"] += time.time() - t_sat
                        return accepted, telemetry

                unresolved = [
                    cand for cand in next_unresolved if cand not in pruned and cand[0] not in accepted
                ]
                if not unresolved:
                    break
    except KeyboardInterrupt:
        telemetry["abort_reason"] = "USER_INTERRUPT_CHECKPOINT"
        telemetry["unresolved"] = len(unresolved)
        telemetry["_phase_resume_state"] = {
            "schema": "alg10_global_frontier_v1",
            "tier": "global",
            "reason": "USER_INTERRUPT_CHECKPOINT",
            "candidate_order": CANDIDATE_ORDER,
            "sat_budgets": list(SAT_BUDGETS),
            "candidates": _candidate_budget_list_for_resume(unresolved, max_budget_tried),
        }
        timings["SAT"] += time.time() - t_sat
        return accepted, telemetry

    telemetry["unresolved"] = len(unresolved)
    max_configured_budget = max(SAT_BUDGETS) if SAT_BUDGETS else 0
    telemetry["global_budget_history_exhausted"] = sum(
        1 for cand in unresolved if max_budget_tried.get(cand, 0) >= max_configured_budget
    )
    if unresolved and not telemetry["abort_reason"]:
        telemetry["abort_reason"] = "UNRESOLVED_TIMEOUTS"
        telemetry["_phase_resume_state"] = {
            "schema": "alg10_global_frontier_v1",
            "tier": "global",
            "reason": "UNRESOLVED_TIMEOUTS",
            "candidate_order": CANDIDATE_ORDER,
            "sat_budgets": list(SAT_BUDGETS),
            "candidates": _candidate_budget_list_for_resume(unresolved, max_budget_tried),
        }

    timings["SAT"] += time.time() - t_sat
    return accepted, telemetry


def _run_tiered_sat(inputs, latches, outputs, gates_raw, timings, deadline, phase_resume_state=None):
    telemetry = _empty_phase_telemetry()
    telemetry["candidates"] = 2 * len(gates_raw)
    all_candidates = _candidate_order(gates_raw, roots=outputs)

    def telemetry_candidates(data, key, fallback=None):
        if key not in data:
            return list(fallback or [])
        parsed = _candidate_set_from_resume_items(data.get(key, []), len(gates_raw))
        if parsed is None:
            return list(fallback or [])
        return parsed

    resume_candidates = None
    resume_max_budget_tried = {}
    resume_from_global_phase = False
    if phase_resume_state and phase_resume_state.get("tier") == "global":
        resume_candidates = list(phase_resume_state.get("candidates", []))
        resume_max_budget_tried = dict(phase_resume_state.get("max_budget_tried", {}))
        resume_from_global_phase = True

    if (
        EXACT_FRONTIER_RESUME
        and phase_resume_state
        and phase_resume_state.get("tier") in {"tfi", "window", "cone"}
    ):
        resume_tier = phase_resume_state.get("tier")
        telemetry["exact_frontier_resume_used"] = 1
        telemetry["exact_frontier_resume_tier"] = resume_tier
        telemetry["exact_frontier_resume_candidates"] = len(
            phase_resume_state.get("pending", [])
        )
        telemetry["phase_resume_used"] = 1
        telemetry["exact_frontier_resume_skipped_lower_tiers"] = {
            "tfi": 1,
            "window": 2,
            "cone": 3,
        }.get(resume_tier, 0)

        initial_pruned = set()
        window_candidates = None
        cone_candidates = None
        global_candidates = None

        if resume_tier == "tfi":
            t_tfi = time.time()
            tfi_accepts, tfi_telemetry = _run_tfi_constancy_tier(
                inputs,
                latches,
                gates_raw,
                deadline,
                initial_pruned=initial_pruned,
                candidates_override=phase_resume_state.get("pending", []),
                escalated=phase_resume_state.get("escalated", []),
            )
            timings["SAT"] += time.time() - t_tfi
            _merge_telemetry(telemetry, tfi_telemetry)
            if tfi_accepts or tfi_telemetry.get("abort_reason"):
                return tfi_accepts, telemetry
            window_candidates = telemetry_candidates(tfi_telemetry, "_tier_escalated_candidates")

        elif resume_tier == "window":
            window_candidates = list(phase_resume_state.get("pending", []))
            window_escalated = list(phase_resume_state.get("escalated", []))
            window_accepts, window_telemetry = _run_window_miter_tier(
                inputs,
                latches,
                outputs,
                gates_raw,
                timings,
                deadline,
                initial_pruned=initial_pruned,
                candidates_override=window_candidates,
                escalated=window_escalated,
            )
            _merge_telemetry(telemetry, window_telemetry)
            initial_pruned.update(
                tuple(cand) for cand in window_telemetry.get("_output_pruned_candidates", [])
            )
            if window_accepts or window_telemetry.get("abort_reason"):
                return window_accepts, telemetry
            cone_candidates = telemetry_candidates(window_telemetry, "_tier_escalated_candidates")
            window_candidates = None

        elif resume_tier == "cone":
            cone_candidates = list(phase_resume_state.get("pending", []))

        if window_candidates is not None:
            window_accepts, window_telemetry = _run_window_miter_tier(
                inputs,
                latches,
                outputs,
                gates_raw,
                timings,
                deadline,
                initial_pruned=initial_pruned,
                candidates_override=window_candidates,
                escalated=[],
            )
            _merge_telemetry(telemetry, window_telemetry)
            initial_pruned.update(
                tuple(cand) for cand in window_telemetry.get("_output_pruned_candidates", [])
            )
            if window_accepts or window_telemetry.get("abort_reason"):
                return window_accepts, telemetry
            cone_candidates = telemetry_candidates(window_telemetry, "_tier_escalated_candidates")

        if cone_candidates is not None:
            cone_accepts, cone_telemetry = _run_cone_miter_tier(
                inputs,
                latches,
                outputs,
                gates_raw,
                timings,
                deadline,
                initial_pruned=initial_pruned,
                candidates_override=cone_candidates,
                escalated=phase_resume_state.get("escalated", []) if resume_tier == "cone" else [],
            )
            _merge_telemetry(telemetry, cone_telemetry)
            initial_pruned.update(
                tuple(cand) for cand in cone_telemetry.get("_output_pruned_candidates", [])
            )
            if cone_accepts or cone_telemetry.get("abort_reason"):
                return cone_accepts, telemetry
            global_candidates = telemetry_candidates(cone_telemetry, "_tier_escalated_candidates")

        if not GLOBAL_MITER:
            telemetry["unresolved"] = len(global_candidates or [])
            telemetry["abort_reason"] = "GLOBAL_DISABLED"
            return {}, telemetry

        global_accepts, global_telemetry = _run_budgeted_global_sat(
            inputs,
            latches,
            outputs,
            gates_raw,
            timings,
            deadline,
            record_candidates=False,
            initial_pruned=initial_pruned,
            run_pre_sim=False,
            resume_candidates=global_candidates or [],
            resume_max_budget_tried={},
            resume_from_phase=False,
        )
        _merge_telemetry(telemetry, global_telemetry)
        return global_accepts, telemetry

    if EXACT_FRONTIER_RESUME and resume_candidates is not None:
        telemetry["exact_frontier_resume_used"] = 1
        telemetry["exact_frontier_resume_tier"] = "global"
        telemetry["exact_frontier_resume_candidates"] = len(resume_candidates)
        telemetry["exact_frontier_resume_skipped_lower_tiers"] = 1

        pool_pruned = _run_cex_pool_replay(
            inputs,
            latches,
            outputs,
            gates_raw,
            resume_candidates,
            telemetry,
            timings,
            deadline=deadline,
        )
        pre_candidates = [cand for cand in resume_candidates if cand not in pool_pruned]
        pre_pruned = _run_pre_sim_rejection(
            inputs,
            latches,
            outputs,
            gates_raw,
            pre_candidates,
            telemetry,
            timings,
            deadline=deadline,
        )
        initial_pruned = set(pool_pruned)
        initial_pruned.update(pre_pruned)
        if _deadline_expired(deadline):
            telemetry["abort_reason"] = "TIME_BUDGET_CHECKPOINT"
            telemetry["unresolved"] = max(0, len(resume_candidates) - len(initial_pruned))
            return {}, telemetry

        if not GLOBAL_MITER:
            telemetry["unresolved"] = max(0, len(resume_candidates) - len(initial_pruned))
            telemetry["abort_reason"] = "GLOBAL_DISABLED"
            return {}, telemetry

        resume_candidates = [cand for cand in resume_candidates if cand not in initial_pruned]
        resume_max_budget_tried = {
            cand: resume_max_budget_tried.get(cand, 0)
            for cand in resume_candidates
        }
        global_accepts, global_telemetry = _run_budgeted_global_sat(
            inputs,
            latches,
            outputs,
            gates_raw,
            timings,
            deadline,
            record_candidates=False,
            initial_pruned=initial_pruned,
            run_pre_sim=False,
            resume_candidates=resume_candidates,
            resume_max_budget_tried=resume_max_budget_tried,
            resume_from_phase=True,
        )
        _merge_telemetry(telemetry, global_telemetry)
        return global_accepts, telemetry

    pool_pruned = _run_cex_pool_replay(
        inputs,
        latches,
        outputs,
        gates_raw,
        all_candidates,
        telemetry,
        timings,
        deadline=deadline,
    )
    initial_pruned = set(pool_pruned)
    if not PRE_SIM_AFTER_TFI:
        pre_candidates = [cand for cand in all_candidates if cand not in pool_pruned]
        pre_pruned = _run_pre_sim_rejection(
            inputs,
            latches,
            outputs,
            gates_raw,
            pre_candidates,
            telemetry,
            timings,
            deadline=deadline,
        )
        initial_pruned.update(pre_pruned)
        if _deadline_expired(deadline):
            telemetry["abort_reason"] = "TIME_BUDGET_CHECKPOINT"
            telemetry["unresolved"] = max(0, telemetry["candidates"] - len(initial_pruned))
            return {}, telemetry

    t_tfi = time.time()
    tfi_accepts, tfi_telemetry = _run_tfi_constancy_tier(
        inputs, latches, gates_raw, deadline, initial_pruned=initial_pruned
    )
    timings["SAT"] += time.time() - t_tfi
    _merge_telemetry(telemetry, tfi_telemetry)

    if tfi_accepts or tfi_telemetry.get("abort_reason"):
        return tfi_accepts, telemetry
    window_candidates = telemetry_candidates(tfi_telemetry, "_tier_escalated_candidates", all_candidates)
    if PRE_SIM_AFTER_TFI:
        pre_candidates = [cand for cand in window_candidates if cand not in initial_pruned]
        pre_pruned = _run_pre_sim_rejection(
            inputs,
            latches,
            outputs,
            gates_raw,
            pre_candidates,
            telemetry,
            timings,
            deadline=deadline,
        )
        initial_pruned.update(pre_pruned)
        if _deadline_expired(deadline):
            telemetry["abort_reason"] = "TIME_BUDGET_CHECKPOINT"
            telemetry["unresolved"] = sum(1 for cand in window_candidates if cand not in initial_pruned)
            return {}, telemetry
        window_candidates = [cand for cand in window_candidates if cand not in initial_pruned]

    window_accepts, window_telemetry = _run_window_miter_tier(
        inputs,
        latches,
        outputs,
        gates_raw,
        timings,
        deadline,
        initial_pruned=initial_pruned,
        candidates_override=window_candidates,
    )
    _merge_telemetry(telemetry, window_telemetry)
    initial_pruned.update(tuple(cand) for cand in window_telemetry.get("_output_pruned_candidates", []))

    if window_accepts or window_telemetry.get("abort_reason"):
        return window_accepts, telemetry
    cone_candidates = telemetry_candidates(window_telemetry, "_tier_escalated_candidates", window_candidates)

    cone_accepts, cone_telemetry = _run_cone_miter_tier(
        inputs,
        latches,
        outputs,
        gates_raw,
        timings,
        deadline,
        initial_pruned=initial_pruned,
        candidates_override=cone_candidates,
    )
    _merge_telemetry(telemetry, cone_telemetry)
    initial_pruned.update(tuple(cand) for cand in cone_telemetry.get("_output_pruned_candidates", []))

    if cone_accepts or cone_telemetry.get("abort_reason"):
        return cone_accepts, telemetry
    global_frontier_candidates = telemetry_candidates(
        cone_telemetry, "_tier_escalated_candidates", cone_candidates
    )

    if not GLOBAL_MITER:
        telemetry["unresolved"] = max(0, 2 * len(gates_raw) - len(initial_pruned))
        telemetry["abort_reason"] = "GLOBAL_DISABLED"
        return {}, telemetry

    if resume_candidates is not None:
        resume_candidates = [cand for cand in resume_candidates if cand not in initial_pruned]
        resume_max_budget_tried = {
            cand: resume_max_budget_tried.get(cand, 0)
            for cand in resume_candidates
        }
    else:
        resume_candidates = [cand for cand in global_frontier_candidates if cand not in initial_pruned]

    global_accepts, global_telemetry = _run_budgeted_global_sat(
        inputs,
        latches,
        outputs,
        gates_raw,
        timings,
        deadline,
        record_candidates=False,
        initial_pruned=initial_pruned,
        run_pre_sim=False,
        resume_candidates=resume_candidates,
        resume_max_budget_tried=resume_max_budget_tried,
        resume_from_phase=resume_from_global_phase,
    )
    _merge_telemetry(telemetry, global_telemetry)
    return global_accepts, telemetry


def _merge_telemetry(total, phase):
    total["checks"] += phase.get("checks", 0)
    total["timeouts"] += phase.get("timeouts", 0)
    total["sat"] += phase.get("sat", 0)
    total["unsat"] += phase.get("unsat", 0)
    total["accepted_sa0"] += phase.get("accepted_sa0", 0)
    total["accepted_sa1"] += phase.get("accepted_sa1", 0)
    total["candidates"] += phase.get("candidates", 0)
    total["budget_rounds"] += phase.get("budget_rounds", 0)
    total["unresolved"] = phase.get("unresolved", total.get("unresolved", 0))
    total["max_budget"] = max(total.get("max_budget", 0), phase.get("max_budget", 0))
    total["tfi_checks"] += phase.get("tfi_checks", 0)
    total["tfi_sat"] += phase.get("tfi_sat", 0)
    total["tfi_unsat"] += phase.get("tfi_unsat", 0)
    total["tfi_timeouts"] += phase.get("tfi_timeouts", 0)
    total["tfi_skipped"] += phase.get("tfi_skipped", 0)
    total["window_checks"] += phase.get("window_checks", 0)
    total["window_sat"] += phase.get("window_sat", 0)
    total["window_unsat"] += phase.get("window_unsat", 0)
    total["window_timeouts"] += phase.get("window_timeouts", 0)
    total["window_skipped"] += phase.get("window_skipped", 0)
    total["window_audit_fail"] += phase.get("window_audit_fail", 0)
    total["window_dominator_attempts"] += phase.get("window_dominator_attempts", 0)
    total["window_dominator_used"] += phase.get("window_dominator_used", 0)
    total["window_dominator_fallbacks"] += phase.get("window_dominator_fallbacks", 0)
    total["cone_checks"] += phase.get("cone_checks", 0)
    total["cone_sat"] += phase.get("cone_sat", 0)
    total["cone_unsat"] += phase.get("cone_unsat", 0)
    total["cone_timeouts"] += phase.get("cone_timeouts", 0)
    total["cone_skipped"] += phase.get("cone_skipped", 0)
    total["cone_partition_checks"] += phase.get("cone_partition_checks", 0)
    total["cone_partition_sat"] += phase.get("cone_partition_sat", 0)
    total["cone_partition_unsat"] += phase.get("cone_partition_unsat", 0)
    total["cone_partition_timeouts"] += phase.get("cone_partition_timeouts", 0)
    total["cone_partition_groups"] += phase.get("cone_partition_groups", 0)
    total["cone_partition_audit_fail"] += phase.get("cone_partition_audit_fail", 0)
    total["cone_partition_skipped"] += phase.get("cone_partition_skipped", 0)
    total["cone_partition_no_affected"] += phase.get("cone_partition_no_affected", 0)
    total["cone_partition_below_min_roots"] += phase.get("cone_partition_below_min_roots", 0)
    total["cone_partition_target_outside_cone"] += phase.get(
        "cone_partition_target_outside_cone", 0
    )
    total["cone_partition_cone_too_large"] += phase.get("cone_partition_cone_too_large", 0)
    total["cone_partition_fallbacks"] += phase.get("cone_partition_fallbacks", 0)
    total["cone_partition_max_cone_gates"] = max(
        total.get("cone_partition_max_cone_gates", 0),
        phase.get("cone_partition_max_cone_gates", 0),
    )
    total["cone_partition_max_seen_cone_gates"] = max(
        total.get("cone_partition_max_seen_cone_gates", 0),
        phase.get("cone_partition_max_seen_cone_gates", 0),
    )
    total["cone_partition_max_skipped_cone_gates"] = max(
        total.get("cone_partition_max_skipped_cone_gates", 0),
        phase.get("cone_partition_max_skipped_cone_gates", 0),
    )
    total["cone_tfo_checks"] += phase.get("cone_tfo_checks", 0)
    total["cone_tfo_sat"] += phase.get("cone_tfo_sat", 0)
    total["cone_tfo_unsat"] += phase.get("cone_tfo_unsat", 0)
    total["cone_tfo_timeouts"] += phase.get("cone_tfo_timeouts", 0)
    total["cone_tfo_skipped"] += phase.get("cone_tfo_skipped", 0)
    total["cone_tfo_audit_fail"] += phase.get("cone_tfo_audit_fail", 0)
    total["cone_tfo_max_good_gates"] = max(
        total.get("cone_tfo_max_good_gates", 0),
        phase.get("cone_tfo_max_good_gates", 0),
    )
    total["cone_tfo_max_faulty_gates"] = max(
        total.get("cone_tfo_max_faulty_gates", 0),
        phase.get("cone_tfo_max_faulty_gates", 0),
    )
    total["global_checks"] += phase.get("global_checks", 0)
    total["global_sat"] += phase.get("global_sat", 0)
    total["global_unsat"] += phase.get("global_unsat", 0)
    total["global_timeouts"] += phase.get("global_timeouts", 0)
    total["global_budget_history_loaded"] += phase.get("global_budget_history_loaded", 0)
    total["global_budget_history_skipped"] += phase.get("global_budget_history_skipped", 0)
    total["global_budget_history_exhausted"] += phase.get("global_budget_history_exhausted", 0)
    total["phase_resume_used"] += phase.get("phase_resume_used", 0)
    if phase.get("_phase_resume_state"):
        phase_resume_state = phase["_phase_resume_state"]
        if "candidates" in phase_resume_state:
            phase_resume_candidates = len(phase_resume_state.get("candidates", []))
        else:
            phase_resume_candidates = len(phase_resume_state.get("pending", [])) + len(
                phase_resume_state.get("escalated", [])
            )
        total["phase_resume_saved"] += 1
        total["phase_resume_candidates"] = phase_resume_candidates
        total["_phase_resume_state"] = phase_resume_state
    total["exact_frontier_resume_enabled"] = int(EXACT_FRONTIER_RESUME)
    total["exact_frontier_resume_used"] += phase.get("exact_frontier_resume_used", 0)
    total["exact_frontier_resume_candidates"] = max(
        total.get("exact_frontier_resume_candidates", 0),
        phase.get("exact_frontier_resume_candidates", 0),
    )
    total["exact_frontier_resume_skipped_lower_tiers"] += phase.get(
        "exact_frontier_resume_skipped_lower_tiers", 0
    )
    if phase.get("exact_frontier_resume_tier"):
        total["exact_frontier_resume_tier"] = phase["exact_frontier_resume_tier"]
    total["cex_pool_loaded"] = max(total.get("cex_pool_loaded", 0), phase.get("cex_pool_loaded", 0))
    total["cex_pool_saved"] = max(total.get("cex_pool_saved", 0), phase.get("cex_pool_saved", 0))
    total["cex_pool_size"] = max(total.get("cex_pool_size", 0), phase.get("cex_pool_size", 0))
    total["cex_pool_added"] += phase.get("cex_pool_added", 0)
    total["cex_pool_replay_patterns"] += phase.get("cex_pool_replay_patterns", 0)
    total["cex_pool_replay_checked"] += phase.get("cex_pool_replay_checked", 0)
    total["cex_pool_replay_pruned"] += phase.get("cex_pool_replay_pruned", 0)
    total["pre_sim_after_tfi"] = int(PRE_SIM_AFTER_TFI)
    total["pre_sim_patterns"] += phase.get("pre_sim_patterns", 0)
    total["pre_sim_checked"] += phase.get("pre_sim_checked", 0)
    total["pre_sim_pruned"] += phase.get("pre_sim_pruned", 0)
    total["pre_sim_structured_pruned"] += phase.get("pre_sim_structured_pruned", 0)
    total["pre_sim_random_pruned"] += phase.get("pre_sim_random_pruned", 0)
    total["pre_sim_time"] += phase.get("pre_sim_time", 0.0)
    if phase.get("pre_sim_adaptive_stop"):
        total["pre_sim_adaptive_stop"] = phase["pre_sim_adaptive_stop"]
    total["cex_prune_events"] += phase.get("cex_prune_events", 0)
    total["cex_prune_checked"] += phase.get("cex_prune_checked", 0)
    total["cex_pruned"] += phase.get("cex_pruned", 0)
    total["cex_tfi_prune_events"] += phase.get("cex_tfi_prune_events", 0)
    total["cex_tfi_prune_checked"] += phase.get("cex_tfi_prune_checked", 0)
    total["cex_tfi_pruned"] += phase.get("cex_tfi_pruned", 0)
    total["cex_audit_checked"] += phase.get("cex_audit_checked", 0)
    total["cex_audit_sat"] += phase.get("cex_audit_sat", 0)
    total["cex_audit_unsat_false_prune"] += phase.get("cex_audit_unsat_false_prune", 0)
    total["cex_audit_timeouts"] += phase.get("cex_audit_timeouts", 0)
    total["cex_audit_skipped"] += phase.get("cex_audit_skipped", 0)
    total["cex_audit_limit_hit"] += phase.get("cex_audit_limit_hit", 0)
    if phase.get("abort_reason"):
        total["abort_reason"] = phase["abort_reason"]


def solve_circuit(circuit_path, output_path):
    t_start = time.time()
    timings = {
        "Parse": 0.0,
        "Filter": 0.0,
        "Encode": 0.0,
        "SAT": 0.0,
        "PreSAT_Sim": 0.0,
        "Total": 0.0,
    }

    t_parse = time.time()
    M, I, L, O, A, inputs, latches, outputs, gates_raw, symbols = parse_aag(circuit_path)
    timings["Parse"] = time.time() - t_parse

    orig_gates = A
    parsed_header = (M, I, L, O, A, inputs, latches, outputs)

    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    telemetry = {
        "checks": 0,
        "timeouts": 0,
        "sat": 0,
        "unsat": 0,
        "accepted_sa0": 0,
        "accepted_sa1": 0,
        "candidates": 0,
        "budget_rounds": 0,
        "unresolved": 0,
        "max_budget": 0,
        "abort_reason": "",
        "phases": 0,
        "resumed": 0,
        "tfi_checks": 0,
        "tfi_sat": 0,
        "tfi_unsat": 0,
        "tfi_timeouts": 0,
        "tfi_skipped": 0,
        "window_checks": 0,
        "window_sat": 0,
        "window_unsat": 0,
        "window_timeouts": 0,
        "window_skipped": 0,
        "window_audit_fail": 0,
        "window_dominator_attempts": 0,
        "window_dominator_used": 0,
        "window_dominator_fallbacks": 0,
        "cone_checks": 0,
        "cone_sat": 0,
        "cone_unsat": 0,
        "cone_timeouts": 0,
        "cone_skipped": 0,
        "cone_partition_checks": 0,
        "cone_partition_sat": 0,
        "cone_partition_unsat": 0,
        "cone_partition_timeouts": 0,
        "cone_partition_groups": 0,
        "cone_partition_audit_fail": 0,
        "cone_partition_skipped": 0,
        "cone_partition_no_affected": 0,
        "cone_partition_below_min_roots": 0,
        "cone_partition_target_outside_cone": 0,
        "cone_partition_cone_too_large": 0,
        "cone_partition_fallbacks": 0,
        "cone_partition_max_cone_gates": 0,
        "cone_partition_max_seen_cone_gates": 0,
        "cone_partition_max_skipped_cone_gates": 0,
        "cone_tfo_checks": 0,
        "cone_tfo_sat": 0,
        "cone_tfo_unsat": 0,
        "cone_tfo_timeouts": 0,
        "cone_tfo_skipped": 0,
        "cone_tfo_audit_fail": 0,
        "cone_tfo_max_good_gates": 0,
        "cone_tfo_max_faulty_gates": 0,
        "global_checks": 0,
        "global_sat": 0,
        "global_unsat": 0,
        "global_timeouts": 0,
        "global_budget_history_loaded": 0,
        "global_budget_history_skipped": 0,
        "global_budget_history_exhausted": 0,
        "phase_resume_used": 0,
        "phase_resume_saved": 0,
        "phase_resume_candidates": 0,
        "exact_frontier_resume_enabled": int(EXACT_FRONTIER_RESUME),
        "exact_frontier_resume_used": 0,
        "exact_frontier_resume_candidates": 0,
        "exact_frontier_resume_skipped_lower_tiers": 0,
        "exact_frontier_resume_tier": "",
        "cex_pool_loaded": 0,
        "cex_pool_saved": 0,
        "cex_pool_size": 0,
        "cex_pool_added": 0,
        "cex_pool_replay_patterns": 0,
        "cex_pool_replay_checked": 0,
        "cex_pool_replay_pruned": 0,
        "pre_sim_after_tfi": int(PRE_SIM_AFTER_TFI),
        "pre_sim_patterns": 0,
        "pre_sim_checked": 0,
        "pre_sim_pruned": 0,
        "pre_sim_structured_pruned": 0,
        "pre_sim_random_pruned": 0,
        "pre_sim_time": 0.0,
        "pre_sim_adaptive_stop": "",
        "cex_prune_events": 0,
        "cex_prune_checked": 0,
        "cex_pruned": 0,
        "cex_tfi_prune_events": 0,
        "cex_tfi_prune_checked": 0,
        "cex_tfi_pruned": 0,
        "cex_audit_checked": 0,
        "cex_audit_sat": 0,
        "cex_audit_unsat_false_prune": 0,
        "cex_audit_timeouts": 0,
        "cex_audit_skipped": 0,
        "cex_audit_limit_hit": 0,
    }
    _load_cex_pool(circuit_path, inputs, latches, telemetry)

    after_structural_gates = orig_gates
    deadline = None
    if MAX_CIRCUIT_SECONDS > 0:
        deadline = t_start + MAX_CIRCUIT_SECONDS

    with tempfile.TemporaryDirectory(prefix="alg10_work_") as tmp:
        work_path = os.path.join(tmp, "work.aag")
        checkpoint = _load_checkpoint(circuit_path)
        checkpoint_start_gates = None
        checkpoint_start_unresolved = None
        checkpoint_status_loaded = ""
        checkpoint_json_loaded = ""
        checkpoint_work_loaded = ""
        checkpoint_source_dir = ""
        checkpoint_imported_external = 0

        if checkpoint is not None:
            checkpoint_work = checkpoint.get("_checkpoint_work_path")
            if not checkpoint_work:
                _, checkpoint_work = _checkpoint_paths(circuit_path)
            checkpoint_json_loaded = checkpoint.get("_checkpoint_json_path", "")
            checkpoint_work_loaded = checkpoint_work
            checkpoint_source_dir = checkpoint.get("_checkpoint_source_dir", "")
            checkpoint_imported_external = int(checkpoint.get("_checkpoint_imported_external", 0) or 0)
            shutil.copy(checkpoint_work, work_path)
            telemetry["resumed"] = 1
            try:
                checkpoint_start_gates = int(checkpoint.get("current_gates", 0))
            except Exception:
                checkpoint_start_gates = None
            try:
                checkpoint_start_unresolved = int(
                    checkpoint.get("telemetry", {}).get("unresolved", 0)
                )
            except Exception:
                checkpoint_start_unresolved = None
            checkpoint_status_loaded = str(checkpoint.get("status", ""))
        else:
            try:
                if PRE_STRASH and A <= PRE_STRASH_MAX_GATES:
                    _write_strashed(work_path, parsed_header, gates_raw, symbols, "Alg10 Initial Strash")
                else:
                    shutil.copy(circuit_path, work_path)
            except Exception:
                shutil.copy(circuit_path, work_path)

        try:
            after_structural_gates = parse_aag(work_path)[4]
        except Exception:
            after_structural_gates = orig_gates
        phase_resume_state = None
        if checkpoint is not None:
            phase_resume_state = _valid_phase_resume_state(
                checkpoint.get("phase_resume"), work_path, after_structural_gates
            )

        status = "RUNNING"
        latest_phase_resume_state = None
        if checkpoint is not None and checkpoint_status_loaded == "COMPLETE" and checkpoint_start_unresolved == 0:
            status = "COMPLETE"
            telemetry["unresolved"] = 0
        else:
            for _ in range(max(1, MAX_PHASES)):
                telemetry["phases"] += 1
                t_parse = time.time()
                parsed_header, symbols, gates_raw = _parse_current(work_path)
                timings["Parse"] += time.time() - t_parse
                _, I, L, O, _, inputs, latches, outputs = parsed_header
                sweep_roots = list(outputs)
                sweep_roots.extend(_parse_latch(latch)[1] for latch in latches)

                accepted, phase_telemetry = _run_tiered_sat(
                    inputs,
                    latches,
                    sweep_roots,
                    gates_raw,
                    timings,
                    deadline,
                    phase_resume_state=phase_resume_state,
                )
                phase_resume_state = None
                _merge_telemetry(telemetry, phase_telemetry)
                latest_phase_resume_state = phase_telemetry.get("_phase_resume_state")
                frontier_unresolved = _phase_resume_unresolved_count(latest_phase_resume_state)
                if frontier_unresolved is not None:
                    telemetry["unresolved"] = max(telemetry["unresolved"], frontier_unresolved)

                if accepted:
                    working_gates = _apply_accepts(gates_raw, accepted)
                    _write_strashed(
                        work_path, parsed_header, working_gates, symbols, "Alg10 Rebuild Strash"
                    )
                    status = "CHECKPOINTED_AFTER_COMMITS"
                    latest_phase_resume_state = None
                    _save_checkpoint(circuit_path, work_path, telemetry, status)

                abort_reason = phase_telemetry.get("abort_reason", "")
                if abort_reason in {
                    "TIME_BUDGET_CHECKPOINT",
                    "USER_INTERRUPT_CHECKPOINT",
                    "UNRESOLVED_TIMEOUTS",
                }:
                    status = abort_reason
                    break
                if not accepted:
                    status = "COMPLETE"
                    break
            else:
                status = "MAX_PHASES_REACHED"
                telemetry["abort_reason"] = status

        shutil.copy(work_path, output_path)
        _save_cex_pool(circuit_path, inputs, latches, telemetry)
        _save_checkpoint(circuit_path, work_path, telemetry, status, latest_phase_resume_state)

    try:
        final_gates = parse_aag(output_path)[4]
    except Exception:
        shutil.copy(circuit_path, output_path)
        final_gates = orig_gates

    timings["Total"] = time.time() - t_start
    timings["SAT_Checks"] = telemetry["checks"]
    timings["SAT_Timeouts"] = telemetry["timeouts"]
    timings["Passes"] = telemetry["budget_rounds"]
    timings["SAT_Candidates"] = telemetry["candidates"]
    timings["Rebuilds"] = max(0, telemetry["phases"] - 1)
    timings["Initial_AND2"] = orig_gates
    timings["After_Structural_AND2"] = after_structural_gates
    timings["After_SAT_AND2"] = final_gates
    timings["Structural_Removed_AND2"] = max(0, orig_gates - after_structural_gates)
    timings["SAT_Induced_Removed_AND2"] = max(0, after_structural_gates - final_gates)
    timings["SAT_Query_SAT"] = telemetry["sat"]
    timings["SAT_Query_UNSAT"] = telemetry["unsat"]
    timings["SAT_Accepted_SA0"] = telemetry["accepted_sa0"]
    timings["SAT_Accepted_SA1"] = telemetry["accepted_sa1"]
    timings["SAT_Abort_Reason"] = telemetry["abort_reason"]
    timings["SAT_Unresolved"] = telemetry["unresolved"]
    timings["SAT_Max_Budget"] = telemetry["max_budget"]
    timings["Checkpoint_Resume"] = telemetry["resumed"]
    timings["Checkpoint_Status_Loaded"] = checkpoint_status_loaded
    timings["Checkpoint_JSON_Loaded"] = checkpoint_json_loaded
    timings["Checkpoint_Work_Loaded"] = checkpoint_work_loaded
    timings["Checkpoint_Source_Dir"] = checkpoint_source_dir
    timings["Checkpoint_Imported_External"] = checkpoint_imported_external
    timings["Checkpoint_Select_Policy"] = CHECKPOINT_SELECT_POLICY
    timings["Checkpoint_Start_AND2"] = checkpoint_start_gates if checkpoint_start_gates is not None else ""
    timings["Checkpoint_Start_Removed_AND2"] = (
        max(0, orig_gates - checkpoint_start_gates)
        if checkpoint_start_gates is not None
        else ""
    )
    timings["New_Removed_This_Run"] = (
        max(0, checkpoint_start_gates - final_gates)
        if checkpoint_start_gates is not None
        else max(0, after_structural_gates - final_gates)
    )
    timings["Checkpoint_Start_Unresolved"] = (
        checkpoint_start_unresolved if checkpoint_start_unresolved is not None else ""
    )
    timings["Checkpoint_Unresolved_Delta"] = (
        checkpoint_start_unresolved - telemetry["unresolved"]
        if checkpoint_start_unresolved is not None
        else ""
    )
    timings["TFI_Engine"] = TFI_ENGINE
    timings["TFI_Solver"] = TFI_SOLVER if TFI_ENGINE == "persistent" else "local"
    timings["TFI_Checks"] = telemetry["tfi_checks"]
    timings["TFI_Query_SAT"] = telemetry["tfi_sat"]
    timings["TFI_Query_UNSAT"] = telemetry["tfi_unsat"]
    timings["TFI_Timeouts"] = telemetry["tfi_timeouts"]
    timings["TFI_Skipped"] = telemetry["tfi_skipped"]
    timings["Window_Checks"] = telemetry["window_checks"]
    timings["Window_Query_SAT"] = telemetry["window_sat"]
    timings["Window_Query_UNSAT"] = telemetry["window_unsat"]
    timings["Window_Timeouts"] = telemetry["window_timeouts"]
    timings["Window_Skipped"] = telemetry["window_skipped"]
    timings["Window_Audit_Fail"] = telemetry["window_audit_fail"]
    timings["Window_Root_Strategy"] = WINDOW_ROOT_STRATEGY
    timings["Window_Dominator_Attempts"] = telemetry["window_dominator_attempts"]
    timings["Window_Dominator_Used"] = telemetry["window_dominator_used"]
    timings["Window_Dominator_Fallbacks"] = telemetry["window_dominator_fallbacks"]
    timings["Cone_Checks"] = telemetry["cone_checks"]
    timings["Cone_Query_SAT"] = telemetry["cone_sat"]
    timings["Cone_Query_UNSAT"] = telemetry["cone_unsat"]
    timings["Cone_Timeouts"] = telemetry["cone_timeouts"]
    timings["Cone_Skipped"] = telemetry["cone_skipped"]
    timings["Cone_Engine"] = CONE_ENGINE
    timings["Cone_Solver"] = (
        CONE_SOLVER
        if CONE_ENGINE in {"grouped", "hybrid", "tfo", "hybrid_tfo"}
        else "single"
    )
    timings["Cone_Group_Min_Size"] = CONE_GROUP_MIN_SIZE
    timings["Cone_Partition_Size"] = CONE_PARTITION_SIZE
    timings["Cone_Partition_Min_Roots"] = CONE_PARTITION_MIN_ROOTS
    timings["Cone_Partition_Max_Gates"] = CONE_PARTITION_MAX_GATES
    timings["Cone_Partition_Checks"] = telemetry["cone_partition_checks"]
    timings["Cone_Partition_Query_SAT"] = telemetry["cone_partition_sat"]
    timings["Cone_Partition_Query_UNSAT"] = telemetry["cone_partition_unsat"]
    timings["Cone_Partition_Timeouts"] = telemetry["cone_partition_timeouts"]
    timings["Cone_Partition_Groups"] = telemetry["cone_partition_groups"]
    timings["Cone_Partition_Audit_Fail"] = telemetry["cone_partition_audit_fail"]
    timings["Cone_Partition_Skipped"] = telemetry["cone_partition_skipped"]
    timings["Cone_Partition_No_Affected"] = telemetry["cone_partition_no_affected"]
    timings["Cone_Partition_Below_Min_Roots"] = telemetry["cone_partition_below_min_roots"]
    timings["Cone_Partition_Target_Outside_Cone"] = telemetry[
        "cone_partition_target_outside_cone"
    ]
    timings["Cone_Partition_Cone_Too_Large"] = telemetry["cone_partition_cone_too_large"]
    timings["Cone_Partition_Fallbacks"] = telemetry["cone_partition_fallbacks"]
    timings["Cone_Partition_Max_Seen_Cone_Gates"] = telemetry[
        "cone_partition_max_seen_cone_gates"
    ]
    timings["Cone_Partition_Max_Skipped_Cone_Gates"] = telemetry[
        "cone_partition_max_skipped_cone_gates"
    ]
    timings["Cone_TFO_Max_Good_Gates_Config"] = CONE_TFO_MAX_GOOD_GATES
    timings["Cone_TFO_Max_Faulty_Gates_Config"] = CONE_TFO_MAX_FAULTY_GATES
    timings["Cone_TFO_Checks"] = telemetry["cone_tfo_checks"]
    timings["Cone_TFO_Query_SAT"] = telemetry["cone_tfo_sat"]
    timings["Cone_TFO_Query_UNSAT"] = telemetry["cone_tfo_unsat"]
    timings["Cone_TFO_Timeouts"] = telemetry["cone_tfo_timeouts"]
    timings["Cone_TFO_Skipped"] = telemetry["cone_tfo_skipped"]
    timings["Cone_TFO_Audit_Fail"] = telemetry["cone_tfo_audit_fail"]
    timings["Cone_TFO_Max_Good_Gates"] = telemetry["cone_tfo_max_good_gates"]
    timings["Cone_TFO_Max_Faulty_Gates"] = telemetry["cone_tfo_max_faulty_gates"]
    timings["Global_Checks"] = telemetry["global_checks"]
    timings["Global_Solver"] = GLOBAL_SOLVER
    timings["Global_Max_Consecutive_Timeouts"] = GLOBAL_MAX_CONSEC_TIMEOUTS
    timings["Global_Frontier_Order"] = GLOBAL_FRONTIER_ORDER
    timings["Global_Phase_Mode"] = GLOBAL_PHASE_MODE
    timings["Global_Phase_Model_Limit"] = GLOBAL_PHASE_MODEL_LIMIT
    timings["Global_Query_SAT"] = telemetry["global_sat"]
    timings["Global_Query_UNSAT"] = telemetry["global_unsat"]
    timings["Global_Timeouts"] = telemetry["global_timeouts"]
    timings["Global_Budget_History_Loaded"] = telemetry["global_budget_history_loaded"]
    timings["Global_Budget_History_Skipped"] = telemetry["global_budget_history_skipped"]
    timings["Global_Budget_History_Exhausted"] = telemetry["global_budget_history_exhausted"]
    timings["Phase_Local_Resume_Enabled"] = int(PHASE_LOCAL_RESUME)
    timings["Phase_Local_Resume_Used"] = telemetry["phase_resume_used"]
    timings["Phase_Local_Resume_Saved"] = telemetry["phase_resume_saved"]
    timings["Phase_Local_Resume_Candidates"] = telemetry["phase_resume_candidates"]
    timings["Exact_Frontier_Resume_Enabled"] = int(EXACT_FRONTIER_RESUME)
    timings["Exact_Frontier_Resume_Used"] = telemetry["exact_frontier_resume_used"]
    timings["Exact_Frontier_Resume_Candidates"] = telemetry["exact_frontier_resume_candidates"]
    timings["Exact_Frontier_Skipped_Lower_Tiers"] = telemetry[
        "exact_frontier_resume_skipped_lower_tiers"
    ]
    timings["Exact_Frontier_Resume_Tier"] = telemetry.get("exact_frontier_resume_tier", "")
    timings["CEX_Pool_Enabled"] = int(CEX_POOL)
    timings["CEX_Pool_Loaded"] = telemetry["cex_pool_loaded"]
    timings["CEX_Pool_Saved"] = telemetry["cex_pool_saved"]
    timings["CEX_Pool_Size"] = telemetry["cex_pool_size"]
    timings["CEX_Pool_Added"] = telemetry["cex_pool_added"]
    timings["CEX_Pool_Replay_Patterns"] = telemetry["cex_pool_replay_patterns"]
    timings["CEX_Pool_Replay_Checked"] = telemetry["cex_pool_replay_checked"]
    timings["CEX_Pool_Replay_Pruned"] = telemetry["cex_pool_replay_pruned"]
    timings["PreSAT_Sim_Enabled"] = int(PRE_SIM_REJECTION)
    timings["PreSAT_Sim_Engine"] = PRE_SIM_ENGINE
    timings["PreSAT_Sim_Packed_Max_Bits"] = PRE_SIM_PACKED_MAX_BITS
    timings["PreSAT_Sim_After_TFI"] = int(PRE_SIM_AFTER_TFI)
    timings["PreSAT_Sim_Patterns"] = telemetry["pre_sim_patterns"]
    timings["PreSAT_Sim_Checked"] = telemetry["pre_sim_checked"]
    timings["PreSAT_Sim_Pruned"] = telemetry["pre_sim_pruned"]
    timings["PreSAT_Sim_Structured_Pruned"] = telemetry["pre_sim_structured_pruned"]
    timings["PreSAT_Sim_Random_Pruned"] = telemetry["pre_sim_random_pruned"]
    timings["PreSAT_Sim_Time"] = telemetry["pre_sim_time"]
    timings["PreSAT_Sim_Adaptive_Stop"] = telemetry.get("pre_sim_adaptive_stop", "")
    timings["CEX_Prune_Events"] = telemetry["cex_prune_events"]
    timings["CEX_Prune_Checked"] = telemetry["cex_prune_checked"]
    timings["CEX_Pruned"] = telemetry["cex_pruned"]
    timings["CEX_TFI_Prune_Events"] = telemetry["cex_tfi_prune_events"]
    timings["CEX_TFI_Prune_Checked"] = telemetry["cex_tfi_prune_checked"]
    timings["CEX_TFI_Pruned"] = telemetry["cex_tfi_pruned"]
    timings["CEX_Pruning_Enabled"] = int(CEX_PRUNING)
    timings["CEX_Audit_Enabled"] = int(AUDIT_CEX_PRUNING)
    timings["CEX_Audit_Checked"] = telemetry["cex_audit_checked"]
    timings["CEX_Audit_SAT"] = telemetry["cex_audit_sat"]
    timings["CEX_Audit_False_Prunes"] = telemetry["cex_audit_unsat_false_prune"]
    timings["CEX_Audit_Timeouts"] = telemetry["cex_audit_timeouts"]
    timings["CEX_Audit_Skipped"] = telemetry["cex_audit_skipped"]
    timings["CEX_Audit_Limit_Hit"] = telemetry["cex_audit_limit_hit"]
    timings["Candidate_Order"] = CANDIDATE_ORDER
    timings["Window_Enabled"] = int(WINDOW_MITER)
    timings["Cone_Enabled"] = int(CONE_MITER)
    timings["Global_Enabled"] = int(GLOBAL_MITER)
    fault_total = max(0, 2 * final_gates)
    fault_unresolved = min(fault_total, max(0, int(telemetry["unresolved"]))) if fault_total else 0
    fault_classified = max(0, fault_total - fault_unresolved)
    timings["Faults_Total"] = fault_total
    timings["Faults_Unresolved"] = fault_unresolved
    timings["Faults_Classified_Lower_Bound"] = fault_classified
    timings["Fault_Coverage_Lower_Bound%"] = (
        f"{(100.0 * fault_classified / fault_total):.2f}%" if fault_total else "100.00%"
    )
    # These source counters are diagnostic events across phases and can overlap.
    # The conservative coverage metric above is derived only from final unresolved count.
    timings["Fault_Detection_Events_By_PreSim"] = telemetry["pre_sim_pruned"]
    timings["Fault_Detection_Events_By_CEX_Pool"] = telemetry["cex_pool_replay_pruned"]
    timings["Fault_Detection_Events_By_CEX_Prune"] = telemetry["cex_pruned"]
    timings["Fault_Redundancy_Proof_Events_UNSAT"] = (
        telemetry["accepted_sa0"] + telemetry["accepted_sa1"]
    )
    timings["Functional_Const_Proofs_TFI"] = telemetry["tfi_unsat"]
    timings["Exact_Miter_UNSAT_Proofs_Window"] = telemetry["window_unsat"]
    timings["Exact_Miter_UNSAT_Proofs_Cone"] = telemetry["cone_unsat"]
    timings["Exact_Miter_UNSAT_Proofs_Global"] = telemetry["global_unsat"]
    timings["Exact_Miter_UNSAT_Proofs_Total"] = (
        telemetry["window_unsat"] + telemetry["cone_unsat"] + telemetry["global_unsat"]
    )

    removed = max(0, orig_gates - final_gates)
    return orig_gates, orig_gates, final_gates, removed, timings
