#!/usr/bin/env python3
"""
optimizer_alg9_incremental.py
=============================
Committed in-memory incremental SAT redundancy removal for ASCII AIGER.

This engine keeps one good-vs-configurable-faulty CNF in memory. A candidate
gate replacement is accepted only when the miter remains UNSAT with all
previously accepted replacements plus the new candidate active. That gives a
simple induction proof of equivalence for the accepted sequence, and the main
pipeline still performs final ABC CEC before reporting a verified result.
"""

import os
import random
import shutil
import tempfile
import time

from pysat.solvers import Glucose4

from optimizer_alg8_hybrid import (
    _build_fault_sweep_cnf,
    _copy_gates,
    _parse_latch,
    _simulation_candidates,
    parse_aag,
    pure_python_forward_strash,
    write_aag,
)


SAT_CONFLICT_BUDGET = int(os.environ.get("ALG9_SAT_BUDGET", "20000"))
LARGE_SAT_CONFLICT_BUDGET = int(os.environ.get("ALG9_LARGE_SAT_BUDGET", "1000"))
MAX_PASSES = int(os.environ.get("ALG9_MAX_PASSES", "4"))
EXHAUSTIVE_CHECK = os.environ.get("ALG9_EXHAUSTIVE", "0") != "0"
FAULT_SIM_MAX_GATES = int(os.environ.get("ALG9_FAULT_SIM_MAX_GATES", "2000"))
SIGNATURE_BITS = int(os.environ.get("ALG9_SIGNATURE_BITS", "2048"))
SIGNATURE_BIAS = float(os.environ.get("ALG9_SIGNATURE_BIAS", "0.0"))
RANDOM_OBS_SIM = os.environ.get("ALG9_RANDOM_OBS_SIM", "1") != "0"
REBUILD_ROUNDS = int(os.environ.get("ALG9_REBUILD_ROUNDS", "4"))
REBUILD_AFTER_COMMITS = int(os.environ.get("ALG9_REBUILD_AFTER_COMMITS", "100"))
MAX_CANDIDATES = int(os.environ.get("ALG9_MAX_CANDIDATES", "2000"))
LARGE_GATE_LIMIT = int(os.environ.get("ALG9_LARGE_GATE_LIMIT", "10000"))
LARGE_MAX_CANDIDATES = int(os.environ.get("ALG9_LARGE_MAX_CANDIDATES", "100"))
VERY_LARGE_GATE_LIMIT = int(os.environ.get("ALG9_VERY_LARGE_GATE_LIMIT", "50000"))
ALLOW_VERY_LARGE_SAT = os.environ.get("ALG9_ALLOW_VERY_LARGE_SAT", "0") != "0"
PRE_STRASH = os.environ.get("ALG9_PRE_STRASH", "1") != "0"
PRE_STRASH_MAX_GATES = int(os.environ.get("ALG9_PRE_STRASH_MAX_GATES", "50000"))
COMMIT_UNIT_CLAUSES = os.environ.get("ALG9_COMMIT_UNITS", "1") != "0"
MAX_CONSECUTIVE_TIMEOUTS = int(os.environ.get("ALG9_MAX_CONSEC_TIMEOUTS", "20"))
MIN_CHECKS_FOR_TIMEOUT_RATE = int(os.environ.get("ALG9_MIN_CHECKS_TIMEOUT_RATE", "50"))
MAX_TIMEOUT_RATE = float(os.environ.get("ALG9_MAX_TIMEOUT_RATE", "0.80"))
MAX_SAT_SECONDS = float(os.environ.get("ALG9_MAX_SAT_SECONDS", "30"))


def _write_strashed(filepath, parsed, gates_raw, symbols, comment):
    M, I, L, O, A, inputs, latches, outputs = parsed
    result = pure_python_forward_strash(M, I, L, O, A, inputs, latches, outputs, gates_raw)
    M_f, I_f, L_f, O_f, A_f, in_f, la_f, out_f, gates_f = result
    write_aag(filepath, M_f, I_f, L_f, O_f, A_f, in_f, la_f, out_f, gates_f, symbols, comment)
    return A_f


def _candidate_values(idx, sim_sa0, sim_sa1):
    """Return stuck values to test, preferring values that survived simulation."""
    values = []
    if idx in sim_sa0:
        values.append(0)
    if idx in sim_sa1:
        values.append(1)

    if EXHAUSTIVE_CHECK:
        if 0 not in values:
            values.append(0)
        if 1 not in values:
            values.append(1)

    return values


def _primary_signatures(inputs, latches, bits, seed_value):
    mask = (1 << bits) - 1
    rng = random.Random(seed_value)
    values = {0: 0, 1: mask}

    primary_lits = list(inputs)
    primary_lits.extend(_parse_latch(latch)[0] for latch in latches)
    for lit in primary_lits:
        val = rng.getrandbits(bits)
        base = lit & ~1
        values[base] = val
        values[base ^ 1] = (~val) & mask

    return values, mask


def _signature_candidates(inputs, latches, gates_raw):
    """Linear-time random-signature filter for likely stuck-at candidates."""
    bits = max(64, SIGNATURE_BITS)
    values, mask = _primary_signatures(inputs, latches, bits, 0xA19E9)

    candidate_map = {}
    low_limit = int(bits * SIGNATURE_BIAS)
    high_limit = bits - low_limit

    for idx, (lhs, r0, r1) in enumerate(gates_raw):
        val = values.get(r0, 0) & values.get(r1, 0)
        values[lhs] = val
        values[lhs ^ 1] = (~val) & mask

        stuck_values = []
        if val == 0:
            stuck_values.append(0)
        elif val == mask:
            stuck_values.append(1)
        elif SIGNATURE_BIAS > 0.0:
            ones = val.bit_count()
            if ones <= low_limit:
                stuck_values.append(0)
            elif ones >= high_limit:
                stuck_values.append(1)

        if stuck_values:
            candidate_map[idx] = stuck_values

    return candidate_map


def _random_observability_candidates(inputs, latches, outputs, gates_raw):
    """
    Linear-time random-pattern observability filter for stuck-at candidates.

    A stuck-at-0 candidate needs at least one sampled pattern where the gate is
    1 and a toggle at that gate can reach a sweep root. Stuck-at-1 is symmetric.
    Candidates that do not meet that random detectability condition still go to
    SAT, so this stage only proposes work; it never proves a replacement.
    """
    bits = max(64, SIGNATURE_BITS)
    values, mask = _primary_signatures(inputs, latches, bits, 0x0B5E12AB1E)

    for lhs, r0, r1 in gates_raw:
        val = values.get(r0, 0) & values.get(r1, 0)
        values[lhs] = val
        values[lhs ^ 1] = (~val) & mask

    observability = {}
    for root in outputs:
        if root > 1:
            base = root & ~1
            observability[base] = observability.get(base, 0) | mask

    for lhs, r0, r1 in reversed(gates_raw):
        obs = observability.get(lhs, 0)
        if not obs:
            continue

        if r0 > 1:
            base0 = r0 & ~1
            observability[base0] = observability.get(base0, 0) | (obs & values.get(r1, 0))
        if r1 > 1:
            base1 = r1 & ~1
            observability[base1] = observability.get(base1, 0) | (obs & values.get(r0, 0))

    scored = []
    for idx, (lhs, _, _) in enumerate(gates_raw):
        val = values.get(lhs, 0)
        obs = observability.get(lhs, 0)
        ones = val.bit_count()
        zeros = bits - ones
        stuck_values = []

        if (val & obs) == 0:
            stuck_values.append(0)
        if (((~val) & mask) & obs) == 0:
            stuck_values.append(1)

        if stuck_values:
            obs_count = obs.bit_count()
            best_activation = min(
                [ones if stuck == 0 else zeros for stuck in stuck_values]
            )
            score = (0 if len(stuck_values) == 2 else 1, obs_count, best_activation, idx)
            scored.append((score, idx, stuck_values))

    return {idx: values_for_idx for _, idx, values_for_idx in sorted(scored)}


def _candidate_map(inputs, latches, outputs, gates_raw, timings):
    """Build a candidate map; simulation filters only reject, SAT still proves."""
    t_filter = time.time()
    try:
        if not EXHAUSTIVE_CHECK and len(gates_raw) <= FAULT_SIM_MAX_GATES:
            sim_sa0, sim_sa1 = _simulation_candidates(inputs, latches, outputs, gates_raw)
            result = {}
            for idx in sorted(sim_sa0 | sim_sa1):
                if idx in sim_sa0:
                    result.setdefault(idx, []).append(0)
                if idx in sim_sa1:
                    result.setdefault(idx, []).append(1)
            return result
        if not EXHAUSTIVE_CHECK and RANDOM_OBS_SIM:
            return _random_observability_candidates(inputs, latches, outputs, gates_raw)
        return _signature_candidates(inputs, latches, gates_raw)
    finally:
        timings["Filter"] += time.time() - t_filter


def _limit_candidates(candidates, gate_count):
    if EXHAUSTIVE_CHECK or MAX_CANDIDATES <= 0:
        return candidates

    limit = LARGE_MAX_CANDIDATES if gate_count > LARGE_GATE_LIMIT else MAX_CANDIDATES
    if limit <= 0:
        return {}

    limited = {}
    remaining = limit
    for idx in candidates:
        if remaining <= 0:
            break
        values = candidates[idx][:remaining]
        if values:
            limited[idx] = values
            remaining -= len(values)
    return limited


def _control_position(A, idx, stuck_value, f0_lits, f1_lits):
    if stuck_value == 0:
        return idx, f0_lits[idx], A + idx, f1_lits[idx]
    return A + idx, f1_lits[idx], idx, f0_lits[idx]


def _empty_sat_telemetry(abort_reason=""):
    return {
        "checks": 0,
        "timeouts": 0,
        "passes": 0,
        "candidates": 0,
        "rebuild": False,
        "sat": 0,
        "unsat": 0,
        "accepted_sa0": 0,
        "accepted_sa1": 0,
        "abort_reason": abort_reason,
    }


def _run_committed_incremental_sat(inputs, latches, outputs, gates_raw, timings):
    """Return accepted {gate_index: stuck_value} using one persistent solver."""
    if not gates_raw or not outputs:
        return {}, _empty_sat_telemetry()
    if (
        not EXHAUSTIVE_CHECK
        and not ALLOW_VERY_LARGE_SAT
        and len(gates_raw) > VERY_LARGE_GATE_LIMIT
    ):
        return {}, _empty_sat_telemetry("SKIP_VERY_LARGE")

    candidates = _candidate_map(inputs, latches, outputs, gates_raw, timings)
    candidates = _limit_candidates(candidates, len(gates_raw))
    candidate_count = 2 * len(gates_raw) if EXHAUSTIVE_CHECK else sum(
        len(values) for values in candidates.values()
    )
    if not EXHAUSTIVE_CHECK and candidate_count == 0:
        return {}, _empty_sat_telemetry()

    t_encode = time.time()
    clauses, miter_lit, f0_lits, f1_lits = _build_fault_sweep_cnf(
        inputs, latches, outputs, gates_raw
    )
    timings["Encode"] += time.time() - t_encode

    A = len(gates_raw)
    control_state = [-lit for lit in f0_lits] + [-lit for lit in f1_lits]
    accepted = {}
    telemetry = _empty_sat_telemetry()
    telemetry["candidates"] = candidate_count

    t_sat = time.time()
    consecutive_timeouts = 0
    with Glucose4(bootstrap_with=clauses) as solver:
        for pass_idx in range(MAX_PASSES):
            changed = False
            telemetry["passes"] = pass_idx + 1

            for idx in range(A):
                if idx in accepted:
                    continue

                values = list(candidates.get(idx, []))
                if EXHAUSTIVE_CHECK:
                    if 0 not in values:
                        values.append(0)
                    if 1 not in values:
                        values.append(1)

                for stuck_value in values:
                    if MAX_SAT_SECONDS > 0 and (time.time() - t_sat) >= MAX_SAT_SECONDS:
                        telemetry["abort_reason"] = "SAT_TIME_BUDGET"
                        timings["SAT"] += time.time() - t_sat
                        return accepted, telemetry

                    pos, lit, opposite_pos, opposite_lit = _control_position(
                        A, idx, stuck_value, f0_lits, f1_lits
                    )

                    assumptions = control_state.copy()
                    assumptions[pos] = lit
                    assumptions[opposite_pos] = -opposite_lit
                    assumptions.append(miter_lit)

                    telemetry["checks"] += 1
                    budget = LARGE_SAT_CONFLICT_BUDGET if A > LARGE_GATE_LIMIT else SAT_CONFLICT_BUDGET
                    solver.conf_budget(budget)
                    result = solver.solve_limited(assumptions=assumptions)

                    if result is None:
                        telemetry["timeouts"] += 1
                        consecutive_timeouts += 1
                        if (
                            MAX_CONSECUTIVE_TIMEOUTS > 0
                            and consecutive_timeouts >= MAX_CONSECUTIVE_TIMEOUTS
                        ):
                            telemetry["abort_reason"] = "CONSECUTIVE_TIMEOUTS"
                            timings["SAT"] += time.time() - t_sat
                            return accepted, telemetry
                        if (
                            MIN_CHECKS_FOR_TIMEOUT_RATE > 0
                            and telemetry["checks"] >= MIN_CHECKS_FOR_TIMEOUT_RATE
                            and telemetry["timeouts"] / telemetry["checks"] >= MAX_TIMEOUT_RATE
                        ):
                            telemetry["abort_reason"] = "TIMEOUT_RATE"
                            timings["SAT"] += time.time() - t_sat
                            return accepted, telemetry
                        continue

                    consecutive_timeouts = 0

                    if result is True:
                        telemetry["sat"] += 1
                        continue

                    if result is False:
                        telemetry["unsat"] += 1
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
                        changed = True
                        if len(accepted) >= REBUILD_AFTER_COMMITS:
                            telemetry["rebuild"] = True
                            timings["SAT"] += time.time() - t_sat
                            return accepted, telemetry
                        break

            if not changed:
                break

    timings["SAT"] += time.time() - t_sat
    return accepted, telemetry


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
        "passes": 0,
        "candidates": 0,
        "phases": 0,
        "sat": 0,
        "unsat": 0,
        "accepted_sa0": 0,
        "accepted_sa1": 0,
        "abort_reason": "",
    }
    after_structural_gates = orig_gates

    with tempfile.TemporaryDirectory(prefix="alg9_work_") as tmp:
        work_path = os.path.join(tmp, "work.aag")

        try:
            if PRE_STRASH and A <= PRE_STRASH_MAX_GATES:
                _write_strashed(work_path, parsed_header, gates_raw, symbols, "Alg9 Initial Strash")
            else:
                shutil.copy(circuit_path, work_path)
        except Exception:
            shutil.copy(circuit_path, work_path)

        try:
            after_structural_gates = parse_aag(work_path)[4]
        except Exception:
            after_structural_gates = orig_gates

        for _ in range(max(1, REBUILD_ROUNDS)):
            t_parse = time.time()
            parsed_header, symbols, gates_raw = _parse_current(work_path)
            timings["Parse"] += time.time() - t_parse
            _, I, L, O, _, inputs, latches, outputs = parsed_header
            sweep_roots = list(outputs)
            sweep_roots.extend(_parse_latch(latch)[1] for latch in latches)

            try:
                accepted, phase_telemetry = _run_committed_incremental_sat(
                    inputs, latches, sweep_roots, gates_raw, timings
                )
            except Exception:
                accepted = {}
                phase_telemetry = {
                    "checks": 0,
                    "timeouts": 0,
                    "passes": 0,
                    "candidates": 0,
                    "rebuild": False,
                    "sat": 0,
                    "unsat": 0,
                    "accepted_sa0": 0,
                    "accepted_sa1": 0,
                    "abort_reason": "EXCEPTION",
                }

            telemetry["checks"] += phase_telemetry["checks"]
            telemetry["timeouts"] += phase_telemetry["timeouts"]
            telemetry["passes"] += phase_telemetry["passes"]
            telemetry["candidates"] += phase_telemetry.get("candidates", 0)
            telemetry["sat"] += phase_telemetry.get("sat", 0)
            telemetry["unsat"] += phase_telemetry.get("unsat", 0)
            telemetry["accepted_sa0"] += phase_telemetry.get("accepted_sa0", 0)
            telemetry["accepted_sa1"] += phase_telemetry.get("accepted_sa1", 0)
            if phase_telemetry.get("abort_reason") and not telemetry["abort_reason"]:
                telemetry["abort_reason"] = phase_telemetry["abort_reason"]
            telemetry["phases"] += 1

            if not accepted:
                break

            working_gates = _apply_accepts(gates_raw, accepted)
            _write_strashed(work_path, parsed_header, working_gates, symbols, "Alg9 Rebuild Strash")
            if phase_telemetry.get("abort_reason"):
                break

        shutil.copy(work_path, output_path)

    try:
        final_gates = parse_aag(output_path)[4]
    except Exception:
        shutil.copy(circuit_path, output_path)
        final_gates = orig_gates

    timings["Total"] = time.time() - t_start
    timings["SAT_Checks"] = telemetry["checks"]
    timings["SAT_Timeouts"] = telemetry["timeouts"]
    timings["Passes"] = telemetry["passes"]
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

    removed = max(0, orig_gates - final_gates)
    return orig_gates, orig_gates, final_gates, removed, timings
