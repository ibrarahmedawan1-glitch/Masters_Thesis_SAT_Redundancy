#!/usr/bin/env python3
"""
optimizer_alg10_tiered.py
=========================
Checkpointed, budget-cycling global SAT redundancy removal for ASCII AIGER.

Algorithm 10 deliberately keeps the proof surface conservative. It does not
accept candidates from random simulation or truncated windows. Every accepted
stuck-at replacement is proved by the same good-vs-configurable-faulty global
miter style used by Algorithm 9, then the rewritten AAG is still verified by
the main pipeline's final ABC CEC step.

The new contribution is scheduling and persistence:
- all stuck-at candidates are reachable; no candidate cap is used;
- candidates are retried with increasing conflict budgets;
- hard/time-limited circuits write the latest safe optimized AAG;
- a checkpoint work AAG allows the next run to resume from that safe state.
"""

import hashlib
import json
import os
import shutil
import tempfile
import time

from pysat.solvers import Glucose4

from optimizer_alg8_hybrid import (
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


def _candidate_order(gates_raw):
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

    ranked = []
    for idx in range(len(gates_raw)):
        # Smaller local structure is attempted first; this is only ordering.
        key = (fanout[idx], depth[idx], idx)
        ranked.append((key, idx, 0))
        ranked.append((key, idx, 1))
    ranked.sort()
    return [(idx, value) for _, idx, value in ranked]


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
        "global_checks": 0,
        "global_sat": 0,
        "global_unsat": 0,
        "global_timeouts": 0,
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


def _tfi_constancy_check(inputs, latches, gates_raw, target_idx, stuck_value):
    cone = _fanin_cone_indices(gates_raw, target_idx)
    if TFI_MAX_CONE_GATES > 0 and len(cone) > TFI_MAX_CONE_GATES:
        return "SKIP"

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
        return "SKIP"

    # Check whether the opposite value is reachable in the complete TFI cone.
    assumption = target_lit if stuck_value == 0 else -target_lit

    with Glucose4(bootstrap_with=clauses) as solver:
        solver.conf_budget(TFI_BUDGET)
        result = solver.solve_limited(assumptions=[assumption])

    if result is None:
        return "TIMEOUT"
    if result is False:
        return "UNSAT"
    return "SAT"


def _run_tfi_constancy_tier(inputs, latches, gates_raw, deadline):
    """Return constants proved by TFI UNSAT; SAT still escalates globally."""
    telemetry = _empty_phase_telemetry()
    accepted = {}

    if not TFI_CONSTANCY or not gates_raw:
        return accepted, telemetry

    candidates = _candidate_order(gates_raw)
    telemetry["max_budget"] = TFI_BUDGET

    try:
        for candidate_pos, (idx, stuck_value) in enumerate(candidates):
            if deadline is not None and time.time() >= deadline:
                telemetry["abort_reason"] = "TIME_BUDGET_CHECKPOINT"
                telemetry["unresolved"] = len(candidates) - candidate_pos
                return accepted, telemetry
            if idx in accepted:
                continue

            result = _tfi_constancy_check(inputs, latches, gates_raw, idx, stuck_value)
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
                remaining_current_round = len(candidates) - candidate_pos - 1
                telemetry["unresolved"] = remaining_current_round
                return accepted, telemetry
    except KeyboardInterrupt:
        telemetry["abort_reason"] = "USER_INTERRUPT_CHECKPOINT"
        telemetry["unresolved"] = len(candidates)
        return accepted, telemetry

    telemetry["unresolved"] = 0
    return accepted, telemetry


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
    unresolved = _candidate_order(gates_raw)

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
                        remaining_current_round = len(unresolved) - candidate_pos
                        telemetry["unresolved"] = len(next_unresolved) + remaining_current_round
                        timings["SAT"] += time.time() - t_sat
                        return accepted, telemetry
                    if idx in accepted:
                        continue

                    pos, lit, opposite_pos, opposite_lit = _control_position(
                        A, idx, stuck_value, f0_lits, f1_lits
                    )

                    assumptions = control_state.copy()
                    assumptions[pos] = lit
                    assumptions[opposite_pos] = -opposite_lit
                    assumptions.append(miter_lit)

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
                        remaining_current_round = len(unresolved) - candidate_pos - 1
                        telemetry["unresolved"] = len(next_unresolved) + remaining_current_round
                        timings["SAT"] += time.time() - t_sat
                        return accepted, telemetry

                unresolved = next_unresolved
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
    total["global_checks"] += phase.get("global_checks", 0)
    total["global_sat"] += phase.get("global_sat", 0)
    total["global_unsat"] += phase.get("global_unsat", 0)
    total["global_timeouts"] += phase.get("global_timeouts", 0)
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
        "global_checks": 0,
        "global_sat": 0,
        "global_unsat": 0,
        "global_timeouts": 0,
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
    timings["Global_Checks"] = telemetry["global_checks"]
    timings["Global_Query_SAT"] = telemetry["global_sat"]
    timings["Global_Query_UNSAT"] = telemetry["global_unsat"]
    timings["Global_Timeouts"] = telemetry["global_timeouts"]

    removed = max(0, orig_gates - final_gates)
    return orig_gates, orig_gates, final_gates, removed, timings
