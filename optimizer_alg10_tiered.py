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
"""

import hashlib
import json
import os
import random
import shutil
import tempfile
import time

from pysat.solvers import Glucose4

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
TFI_CONSTANCY = os.environ.get("ALG10_TFI_CONSTANCY", "1") != "0"
TFI_BUDGET = int(os.environ.get("ALG10_TFI_BUDGET", "500" if MODE == "fast_save" else "2000"))
TFI_MAX_CONE_GATES = int(
    os.environ.get("ALG10_TFI_MAX_CONE_GATES", "2000" if MODE == "fast_save" else "10000")
)
AUDIT_ASSUMPTIONS = os.environ.get("ALG10_AUDIT_ASSUMPTIONS", "0") != "0"
CANDIDATE_ORDER = os.environ.get("ALG10_CANDIDATE_ORDER", "current").strip().lower()
CANDIDATE_RANDOM_SEED = int(os.environ.get("ALG10_CANDIDATE_RANDOM_SEED", "20260517"))
WINDOW_MITER = os.environ.get("ALG10_WINDOW_MITER", "0") != "0"
WINDOW_AUDIT = os.environ.get("ALG10_WINDOW_AUDIT", "1") != "0"
WINDOW_LEVELS = int(os.environ.get("ALG10_WINDOW_LEVELS", "5"))
WINDOW_BUDGET = int(os.environ.get("ALG10_WINDOW_BUDGET", "500" if MODE == "fast_save" else "2000"))
WINDOW_MAX_CONE_GATES = int(
    os.environ.get("ALG10_WINDOW_MAX_CONE_GATES", "2000" if MODE == "fast_save" else "10000")
)
CONE_MITER = os.environ.get("ALG10_CONE_MITER", "1") != "0"
CONE_BUDGET = int(os.environ.get("ALG10_CONE_BUDGET", "1000" if MODE == "fast_save" else "5000"))
CONE_MAX_GATES = int(
    os.environ.get("ALG10_CONE_MAX_GATES", "5000" if MODE == "fast_save" else "20000")
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


def _checkpoint_stem(circuit_path):
    abspath = os.path.abspath(circuit_path).encode("utf-8", errors="ignore")
    path_hash = hashlib.sha1(abspath).hexdigest()[:12]
    base = os.path.splitext(os.path.basename(circuit_path))[0]
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in base)
    return f"{safe}_{path_hash}"


def _checkpoint_paths(circuit_path):
    stem = _checkpoint_stem(circuit_path)
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    return (
        os.path.join(CHECKPOINT_DIR, f"{stem}.json"),
        os.path.join(CHECKPOINT_DIR, f"{stem}.work.aag"),
    )


def _load_checkpoint(circuit_path):
    if RESET_CHECKPOINT:
        return None

    json_path, work_path = _checkpoint_paths(circuit_path)
    if not os.path.exists(json_path) or not os.path.exists(work_path):
        return None

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("source_sha256") != _sha256_file(circuit_path):
            return None
        parse_aag(work_path)
        return data
    except Exception:
        return None


def _save_checkpoint(circuit_path, work_path, telemetry, status):
    json_path, checkpoint_work = _checkpoint_paths(circuit_path)
    shutil.copy(work_path, checkpoint_work)

    try:
        _, _, _, _, current_gates, _, _, _, _, _ = parse_aag(checkpoint_work)
    except Exception:
        current_gates = 0

    data = {
        "algorithm": "ALG10",
        "mode": MODE,
        "status": status,
        "timestamp": time.time(),
        "source_path": os.path.abspath(circuit_path),
        "source_sha256": _sha256_file(circuit_path),
        "work_aag": checkpoint_work,
        "current_gates": current_gates,
        "budgets": SAT_BUDGETS,
        "telemetry": telemetry,
    }

    tmp_path = json_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp_path, json_path)
    return json_path


def _candidate_order(gates_raw, roots=None):
    """Return all SA0/SA1 candidates, ranked but never filtered away."""
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
        "cone_checks": 0,
        "cone_sat": 0,
        "cone_unsat": 0,
        "cone_timeouts": 0,
        "cone_skipped": 0,
        "global_checks": 0,
        "global_sat": 0,
        "global_unsat": 0,
        "global_timeouts": 0,
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
        model = solver.get_model() if result is True and CEX_PRUNING else None

    if result is None:
        return "TIMEOUT", None
    if result is False:
        return "UNSAT", None
    primary_values = (
        _model_primary_values_from_base_map(inputs, latches, model, var_for_base) if model else None
    )
    return "SAT", primary_values


def _cex_prune_tfi_candidates(inputs, latches, gates_raw, primary_values, pending, already_pruned):
    """Skip future TFI-constancy checks disproved by one concrete assignment."""
    if not CEX_PRUNING or not pending:
        return 0, 0

    by_lhs = {lhs & ~1: idx for idx, (lhs, _, _) in enumerate(gates_raw)}
    gate_values, _ = _simulate_good_roots(inputs, latches, [], gates_raw, primary_values, by_lhs)
    checked = 0
    newly_pruned = 0

    for cand in pending:
        if cand in already_pruned:
            continue
        checked += 1
        idx, stuck_value = cand
        if gate_values[idx] != bool(stuck_value):
            already_pruned.add(cand)
            newly_pruned += 1

    return checked, newly_pruned


def _run_tfi_constancy_tier(inputs, latches, gates_raw, deadline):
    """Return constants proved by TFI UNSAT; SAT still escalates globally."""
    telemetry = _empty_phase_telemetry()
    accepted = {}

    if not TFI_CONSTANCY or not gates_raw:
        return accepted, telemetry

    candidates = _candidate_order(gates_raw)
    telemetry["max_budget"] = TFI_BUDGET
    pruned = set()

    try:
        for candidate_pos, (idx, stuck_value) in enumerate(candidates):
            if deadline is not None and time.time() >= deadline:
                telemetry["abort_reason"] = "TIME_BUDGET_CHECKPOINT"
                telemetry["unresolved"] = sum(
                    1
                    for cand in candidates[candidate_pos:]
                    if cand not in pruned and cand[0] not in accepted
                )
                return accepted, telemetry
            if idx in accepted or (idx, stuck_value) in pruned:
                continue

            result, primary_values = _tfi_constancy_check(inputs, latches, gates_raw, idx, stuck_value)
            if result == "SKIP":
                telemetry["tfi_skipped"] += 1
                continue

            telemetry["checks"] += 1
            telemetry["tfi_checks"] += 1

            if result == "TIMEOUT":
                telemetry["timeouts"] += 1
                telemetry["tfi_timeouts"] += 1
                continue
            if result == "SAT":
                telemetry["sat"] += 1
                telemetry["tfi_sat"] += 1
                if primary_values is not None:
                    checked, newly_pruned = _cex_prune_tfi_candidates(
                        inputs,
                        latches,
                        gates_raw,
                        primary_values,
                        candidates[candidate_pos + 1 :],
                        pruned,
                    )
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
                    if cand not in pruned and cand[0] not in accepted
                )
                return accepted, telemetry
    except KeyboardInterrupt:
        telemetry["abort_reason"] = "USER_INTERRUPT_CHECKPOINT"
        telemetry["unresolved"] = len(candidates)
        return accepted, telemetry

    telemetry["unresolved"] = 0
    return accepted, telemetry


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
        model = solver.get_model() if result is True and CEX_PRUNING else None
    timings["SAT"] += time.time() - t_sat

    if result is None:
        return "TIMEOUT", None
    if result is False:
        return "UNSAT", None
    primary_values = _model_primary_values_from_shared(inputs, latches, model, shared) if model else None
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
    roots = _bounded_tfo_window_roots(
        by_lhs, fanout, outputs, gates_raw, target_idx, WINDOW_LEVELS
    )
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
        model = solver.get_model() if result is True and CEX_PRUNING else None
    timings["SAT"] += time.time() - t_sat

    if result is None:
        return "TIMEOUT", None
    if result is False:
        return "UNSAT", None
    primary_values = _model_primary_values_from_shared(inputs, latches, model, shared) if model else None
    return "SAT", primary_values


def _run_window_miter_tier(inputs, latches, outputs, gates_raw, timings, deadline):
    """UNSAT-only bounded TFO window. SAT/timeout/skip escalate to exact cone/global."""
    telemetry = _empty_phase_telemetry()
    accepted = {}

    if not WINDOW_MITER or not gates_raw or not outputs:
        return accepted, telemetry

    candidates = _candidate_order(gates_raw, roots=outputs)
    telemetry["max_budget"] = WINDOW_BUDGET
    working_gates = _copy_gates(gates_raw)
    by_lhs, fanout = _fanout_graph(gates_raw)
    pruned = set()

    try:
        for candidate_pos, (idx, stuck_value) in enumerate(candidates):
            if deadline is not None and time.time() >= deadline:
                telemetry["abort_reason"] = "TIME_BUDGET_CHECKPOINT"
                telemetry["unresolved"] = sum(
                    1
                    for cand in candidates[candidate_pos:]
                    if cand not in pruned and cand[0] not in accepted
                )
                return accepted, telemetry
            if idx in accepted or (idx, stuck_value) in pruned:
                continue

            result, primary_values = _window_miter_check(
                inputs, latches, outputs, working_gates, idx, stuck_value, timings, by_lhs, fanout
            )
            if result in {"SKIP", "AUDIT_FAIL"}:
                telemetry["window_skipped"] += 1
                if result == "AUDIT_FAIL":
                    telemetry["window_audit_fail"] += 1
                continue

            telemetry["checks"] += 1
            telemetry["window_checks"] += 1

            if result == "TIMEOUT":
                telemetry["timeouts"] += 1
                telemetry["window_timeouts"] += 1
                continue
            if result == "SAT":
                telemetry["sat"] += 1
                telemetry["window_sat"] += 1
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
                    )
                    if checked:
                        telemetry["cex_prune_events"] += 1
                        telemetry["cex_prune_checked"] += checked
                        telemetry["cex_pruned"] += newly_pruned
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
        telemetry["unresolved"] = len(candidates)
        return accepted, telemetry

    telemetry["unresolved"] = 0
    return accepted, telemetry


def _run_cone_miter_tier(inputs, latches, outputs, gates_raw, timings, deadline):
    """Prove candidates against only the outputs/latch-next roots they can affect."""
    telemetry = _empty_phase_telemetry()
    accepted = {}

    if not CONE_MITER or not gates_raw or not outputs:
        return accepted, telemetry

    candidates = _candidate_order(gates_raw, roots=outputs)
    telemetry["max_budget"] = CONE_BUDGET
    working_gates = _copy_gates(gates_raw)
    by_lhs, fanout = _fanout_graph(gates_raw)
    pruned = set()

    try:
        for candidate_pos, (idx, stuck_value) in enumerate(candidates):
            if deadline is not None and time.time() >= deadline:
                telemetry["abort_reason"] = "TIME_BUDGET_CHECKPOINT"
                telemetry["unresolved"] = sum(
                    1
                    for cand in candidates[candidate_pos:]
                    if cand not in pruned and cand[0] not in accepted
                )
                return accepted, telemetry
            if idx in accepted or (idx, stuck_value) in pruned:
                continue

            result, primary_values = _cone_miter_check(
                inputs, latches, outputs, working_gates, idx, stuck_value, timings, by_lhs, fanout
            )
            if result == "SKIP":
                telemetry["cone_skipped"] += 1
                continue

            telemetry["checks"] += 1
            telemetry["cone_checks"] += 1

            if result == "TIMEOUT":
                telemetry["timeouts"] += 1
                telemetry["cone_timeouts"] += 1
                continue
            if result == "SAT":
                telemetry["sat"] += 1
                telemetry["cone_sat"] += 1
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
                    )
                    if checked:
                        telemetry["cex_prune_events"] += 1
                        telemetry["cex_prune_checked"] += checked
                        telemetry["cex_pruned"] += newly_pruned
                continue

            telemetry["unsat"] += 1
            telemetry["cone_unsat"] += 1
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
        telemetry["unresolved"] = len(candidates)
        return accepted, telemetry

    telemetry["unresolved"] = 0
    return accepted, telemetry


def _audit_global_assumptions(assumptions, gate_count):
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


def _audit_candidate_with_global_miter(inputs, latches, roots, gates_raw, accepted, candidate, timings):
    """
    Re-check one CEX-pruned candidate in the exact current committed context.

    SAT means the CEX prune was consistent with the full observable miter.
    UNSAT means the prune would have silently discarded a valid redundancy.
    """
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
    inputs, latches, roots, gates_raw, accepted, candidate, telemetry, timings
):
    if not AUDIT_CEX_PRUNING:
        return "NOT_AUDITED"

    if AUDIT_CEX_PRUNING_MAX > 0 and telemetry["cex_audit_checked"] >= AUDIT_CEX_PRUNING_MAX:
        telemetry["cex_audit_limit_hit"] += 1
        return "LIMIT"

    telemetry["cex_audit_checked"] += 1
    result = _audit_candidate_with_global_miter(
        inputs, latches, roots, gates_raw, accepted, candidate, timings
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
):
    """
    Use one concrete global PI/latch assignment to reject candidates in this phase.

    This is a rejection-only optimization. It simulates the same future global
    miter relation under one concrete PI/latch assignment:
      good current circuit vs. current accepted faults plus one candidate.
    If any observable root differs, that candidate would be SAT under this
    assignment and can be skipped until the next structural rebuild/phase.
    """
    if not CEX_PRUNING or not pending:
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
                    )
                if audit_result not in {"UNSAT", "TIMEOUT", "SKIP"}:
                    already_pruned.add(cand)
                    newly_pruned += 1
            diff_mask >>= 1
            bit += 1

    return checked, newly_pruned


def _cex_prune_candidates(
    inputs, latches, roots, gates_raw, model, accepted, pending, already_pruned, telemetry, timings
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
    )


def _run_budgeted_global_sat(inputs, latches, outputs, gates_raw, timings, deadline, record_candidates=True):
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
    pruned = set()
    unresolved = _candidate_order(gates_raw, roots=outputs)

    t_sat = time.time()
    try:
        with Glucose4(bootstrap_with=clauses) as solver:
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
                        timings["SAT"] += time.time() - t_sat
                        return accepted, telemetry
                    if idx in accepted or (idx, stuck_value) in pruned:
                        continue

                    pos, lit, opposite_pos, opposite_lit = _control_position(
                        A, idx, stuck_value, f0_lits, f1_lits
                    )

                    assumptions = control_state.copy()
                    assumptions[pos] = lit
                    assumptions[opposite_pos] = -opposite_lit
                    assumptions.append(miter_lit)
                    if AUDIT_ASSUMPTIONS:
                        _audit_global_assumptions(assumptions, A)

                    telemetry["checks"] += 1
                    telemetry["global_checks"] += 1
                    solver.conf_budget(budget)
                    result = solver.solve_limited(assumptions=assumptions)

                    if result is None:
                        telemetry["timeouts"] += 1
                        telemetry["global_timeouts"] += 1
                        next_unresolved.append((idx, stuck_value))
                        continue

                    if result is True:
                        telemetry["sat"] += 1
                        telemetry["global_sat"] += 1
                        model = solver.get_model() if CEX_PRUNING else None
                        if model:
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
                            )
                            if checked:
                                telemetry["cex_prune_events"] += 1
                                telemetry["cex_prune_checked"] += checked
                                telemetry["cex_pruned"] += newly_pruned
                        continue

                    telemetry["unsat"] += 1
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
        timings["SAT"] += time.time() - t_sat
        return accepted, telemetry

    telemetry["unresolved"] = len(unresolved)
    if unresolved and not telemetry["abort_reason"]:
        telemetry["abort_reason"] = "UNRESOLVED_TIMEOUTS"

    timings["SAT"] += time.time() - t_sat
    return accepted, telemetry


def _run_tiered_sat(inputs, latches, outputs, gates_raw, timings, deadline):
    telemetry = _empty_phase_telemetry()
    telemetry["candidates"] = 2 * len(gates_raw)

    t_tfi = time.time()
    tfi_accepts, tfi_telemetry = _run_tfi_constancy_tier(inputs, latches, gates_raw, deadline)
    timings["SAT"] += time.time() - t_tfi
    _merge_telemetry(telemetry, tfi_telemetry)

    if tfi_accepts or tfi_telemetry.get("abort_reason"):
        return tfi_accepts, telemetry

    window_accepts, window_telemetry = _run_window_miter_tier(
        inputs, latches, outputs, gates_raw, timings, deadline
    )
    _merge_telemetry(telemetry, window_telemetry)

    if window_accepts or window_telemetry.get("abort_reason"):
        return window_accepts, telemetry

    cone_accepts, cone_telemetry = _run_cone_miter_tier(
        inputs, latches, outputs, gates_raw, timings, deadline
    )
    _merge_telemetry(telemetry, cone_telemetry)

    if cone_accepts or cone_telemetry.get("abort_reason"):
        return cone_accepts, telemetry

    global_accepts, global_telemetry = _run_budgeted_global_sat(
        inputs, latches, outputs, gates_raw, timings, deadline, record_candidates=False
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
    total["cone_checks"] += phase.get("cone_checks", 0)
    total["cone_sat"] += phase.get("cone_sat", 0)
    total["cone_unsat"] += phase.get("cone_unsat", 0)
    total["cone_timeouts"] += phase.get("cone_timeouts", 0)
    total["cone_skipped"] += phase.get("cone_skipped", 0)
    total["global_checks"] += phase.get("global_checks", 0)
    total["global_sat"] += phase.get("global_sat", 0)
    total["global_unsat"] += phase.get("global_unsat", 0)
    total["global_timeouts"] += phase.get("global_timeouts", 0)
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
    timings = {"Parse": 0.0, "Filter": 0.0, "Encode": 0.0, "SAT": 0.0, "Total": 0.0}

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
        "cone_checks": 0,
        "cone_sat": 0,
        "cone_unsat": 0,
        "cone_timeouts": 0,
        "cone_skipped": 0,
        "global_checks": 0,
        "global_sat": 0,
        "global_unsat": 0,
        "global_timeouts": 0,
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

    after_structural_gates = orig_gates
    deadline = None
    if MAX_CIRCUIT_SECONDS > 0:
        deadline = t_start + MAX_CIRCUIT_SECONDS

    with tempfile.TemporaryDirectory(prefix="alg10_work_") as tmp:
        work_path = os.path.join(tmp, "work.aag")
        checkpoint = _load_checkpoint(circuit_path)

        if checkpoint is not None:
            _, checkpoint_work = _checkpoint_paths(circuit_path)
            shutil.copy(checkpoint_work, work_path)
            telemetry["resumed"] = 1
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

        status = "RUNNING"
        for _ in range(max(1, MAX_PHASES)):
            telemetry["phases"] += 1
            t_parse = time.time()
            parsed_header, symbols, gates_raw = _parse_current(work_path)
            timings["Parse"] += time.time() - t_parse
            _, I, L, O, _, inputs, latches, outputs = parsed_header
            sweep_roots = list(outputs)
            sweep_roots.extend(_parse_latch(latch)[1] for latch in latches)

            accepted, phase_telemetry = _run_tiered_sat(
                inputs, latches, sweep_roots, gates_raw, timings, deadline
            )
            _merge_telemetry(telemetry, phase_telemetry)

            if accepted:
                working_gates = _apply_accepts(gates_raw, accepted)
                _write_strashed(work_path, parsed_header, working_gates, symbols, "Alg10 Rebuild Strash")
                status = "CHECKPOINTED_AFTER_COMMITS"
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
        _save_checkpoint(circuit_path, work_path, telemetry, status)

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
    timings["Cone_Checks"] = telemetry["cone_checks"]
    timings["Cone_Query_SAT"] = telemetry["cone_sat"]
    timings["Cone_Query_UNSAT"] = telemetry["cone_unsat"]
    timings["Cone_Timeouts"] = telemetry["cone_timeouts"]
    timings["Cone_Skipped"] = telemetry["cone_skipped"]
    timings["Global_Checks"] = telemetry["global_checks"]
    timings["Global_Query_SAT"] = telemetry["global_sat"]
    timings["Global_Query_UNSAT"] = telemetry["global_unsat"]
    timings["Global_Timeouts"] = telemetry["global_timeouts"]
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

    removed = max(0, orig_gates - final_gates)
    return orig_gates, orig_gates, final_gates, removed, timings
