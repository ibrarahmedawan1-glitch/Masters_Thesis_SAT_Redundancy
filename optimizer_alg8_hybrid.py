#!/usr/bin/env python3
"""
optimizer_alg8_hybrid.py
=============================================
Pure-Python in-memory SAT redundancy sweeping for ASCII AIGER circuits.

This module deliberately avoids ABC for optimization. It parses `.aag`,
checks stuck-at candidates with an incremental SAT miter, applies a safe
candidate batch, then runs an ID-preserving structural cleanup pass.
"""

import os
import shutil
import tempfile
import time
from collections import deque

from pysat.solvers import Glucose4


SAT_CONFLICT_BUDGET = 20000
SIM_BITS = 256


def parse_aag(filepath):
    lines = []
    with open(filepath, "r", encoding="ascii", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line == "c":
                break
            lines.append(line)

    if not lines or not lines[0].startswith("aag "):
        raise ValueError(f"not an ASCII AIGER file: {filepath}")

    header = lines[0].split()
    M, I, L, O, A = map(int, header[1:6])
    logic_end = 1 + I + L + O + A
    if len(lines) < logic_end:
        raise ValueError(f"truncated AAG logic section: {filepath}")

    inputs = [int(lines[i]) for i in range(1, 1 + I)]
    latches = lines[1 + I : 1 + I + L]
    outputs = [int(lines[1 + I + L + i]) for i in range(O)]

    gate_start = 1 + I + L + O
    gates_raw = []
    for i in range(A):
        gate = list(map(int, lines[gate_start + i].split()))
        if len(gate) != 3:
            raise ValueError(f"invalid AND gate line: {lines[gate_start + i]}")
        gates_raw.append(gate)

    symbols = lines[gate_start + A :]
    return M, I, L, O, A, inputs, latches, outputs, gates_raw, symbols


def _parse_latch(line):
    parts = list(map(int, line.split()))
    if len(parts) < 2:
        raise ValueError(f"invalid latch line: {line}")
    return parts


def _format_latch(parts):
    return " ".join(str(x) for x in parts)


def _symbol_lines(symbols, I, L, O):
    """Preserve existing symbols and add deterministic names for missing I/O."""
    by_tag = {}
    for sym in symbols:
        if not sym or sym[0] not in "ilo":
            continue
        tag = sym.split(maxsplit=1)[0]
        by_tag[tag] = sym

    result = []
    for i in range(I):
        result.append(by_tag.get(f"i{i}", f"i{i} i{i}"))
    for i in range(L):
        if f"l{i}" in by_tag:
            result.append(by_tag[f"l{i}"])
    for i in range(O):
        result.append(by_tag.get(f"o{i}", f"o{i} o{i}"))
    return result


def write_aag(filepath, M, I, L, O, A, inputs, latches, outputs, gates, symbols=None, comment="Alg8 Hybrid"):
    parent = os.path.dirname(filepath)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(filepath, "w", encoding="ascii") as f:
        f.write(f"aag {M} {I} {L} {O} {A}\n")
        for lit in inputs:
            f.write(f"{lit}\n")
        for latch in latches:
            f.write(f"{latch}\n")
        for lit in outputs:
            f.write(f"{lit}\n")
        for lhs, r0, r1 in gates:
            f.write(f"{lhs} {r0} {r1}\n")
        for sym in _symbol_lines(symbols or [], I, L, O):
            f.write(f"{sym}\n")
        f.write(f"c\n{comment}\n")


def _max_var(inputs, latches, outputs, gates):
    max_lit = 1
    for lit in inputs + outputs:
        max_lit = max(max_lit, lit)
    for latch in latches:
        for lit in _parse_latch(latch):
            max_lit = max(max_lit, lit)
    for lhs, r0, r1 in gates:
        max_lit = max(max_lit, lhs, r0, r1)
    return max_lit // 2


def pure_python_forward_strash(M, I, L, O, A, inputs, latches, outputs, gates_raw):
    """
    Structurally simplify and garbage collect while preserving surviving IDs.

    Gaps in variable IDs are legal in ASCII AIGER. The only strict requirement
    is that the header's M is at least the largest referenced variable index.
    """
    subst = {0: 0, 1: 1}
    for lit in inputs:
        subst[lit & ~1] = lit & ~1
    for latch in latches:
        curr = _parse_latch(latch)[0]
        subst[curr & ~1] = curr & ~1

    def resolve(lit):
        if lit <= 1:
            return lit
        invert = lit & 1
        base = lit & ~1
        seen = set()
        while base in subst and subst[base] != base:
            if base in seen:
                raise ValueError(f"cyclic substitution at literal {lit}")
            seen.add(base)
            replacement = subst[base] ^ invert
            if replacement <= 1:
                return replacement
            invert = replacement & 1
            base = replacement & ~1
        return base ^ invert

    strash_table = {}
    unique_gates = []

    for old_lhs, r0, r1 in gates_raw:
        lhs_base = old_lhs & ~1

        if r0 == 0 and r1 == 0:
            subst[lhs_base] = 0
            continue
        if r0 == 1 and r1 == 1:
            subst[lhs_base] = 1
            continue

        e0, e1 = resolve(r0), resolve(r1)
        result = None

        if e0 == 0 or e1 == 0:
            result = 0
        elif e0 == 1:
            result = e1
        elif e1 == 1:
            result = e0
        elif e0 == e1:
            result = e0
        elif e0 == (e1 ^ 1):
            result = 0

        if result is not None:
            subst[lhs_base] = result
            continue

        if e0 < e1:
            e0, e1 = e1, e0
        key = (e0, e1)

        if key in strash_table:
            subst[lhs_base] = strash_table[key]
            continue

        strash_table[key] = lhs_base
        subst[lhs_base] = lhs_base
        unique_gates.append((lhs_base, e0, e1))

    resolved_outputs = [resolve(lit) for lit in outputs]
    resolved_latches = []
    roots = list(resolved_outputs)

    for latch in latches:
        parts = _parse_latch(latch)
        parts[1] = resolve(parts[1])
        resolved_latches.append(_format_latch(parts))
        roots.append(parts[1])

    gate_lookup = {lhs: (r0, r1) for lhs, r0, r1 in unique_gates}
    reachable = set()
    stack = [lit & ~1 for lit in roots if lit > 1]

    while stack:
        lhs = stack.pop()
        if lhs in reachable or lhs not in gate_lookup:
            continue
        reachable.add(lhs)
        r0, r1 = gate_lookup[lhs]
        if r0 > 1:
            stack.append(r0 & ~1)
        if r1 > 1:
            stack.append(r1 & ~1)

    final_gates = []
    defined = {lit & ~1 for lit in inputs}
    defined.update(_parse_latch(latch)[0] & ~1 for latch in resolved_latches)

    for lhs, r0, r1 in sorted(unique_gates, key=lambda item: item[0]):
        if lhs not in reachable:
            continue
        for fanin in (r0, r1):
            if fanin > 1 and (fanin & ~1) not in defined:
                raise ValueError(f"fanin {fanin} of {lhs} is not defined")
        final_gates.append([lhs, r0, r1])
        defined.add(lhs)

    M_final = _max_var(inputs, resolved_latches, resolved_outputs, final_gates)
    return M_final, I, L, O, len(final_gates), inputs, resolved_latches, resolved_outputs, final_gates


class _CNFBuilder:
    def __init__(self):
        self.next_var = 1
        self.clauses = []
        self.true_lit = self.new_var()
        self.clauses.append([self.true_lit])

    def new_var(self):
        var = self.next_var
        self.next_var += 1
        return var

    def const(self, value):
        return self.true_lit if value else -self.true_lit

    def and2(self, out, a, b):
        self.clauses.append([-a, -b, out])
        self.clauses.append([a, -out])
        self.clauses.append([b, -out])

    def or2(self, out, a, b):
        self.clauses.append([a, b, -out])
        self.clauses.append([-a, out])
        self.clauses.append([-b, out])

    def xor2(self, out, a, b):
        self.clauses.append([-a, -b, -out])
        self.clauses.append([-a, b, out])
        self.clauses.append([a, -b, out])
        self.clauses.append([a, b, -out])

    def or_many(self, lits):
        if not lits:
            return self.const(False)
        if len(lits) == 1:
            return lits[0]
        out = self.new_var()
        self.clauses.append([-out] + lits)
        for lit in lits:
            self.clauses.append([-lit, out])
        return out


def _simulation_candidates(inputs, latches, outputs, gates_raw):
    mask = (1 << SIM_BITS) - 1
    values = {0: 0, 1: mask}
    seed = 0x9E3779B97F4A7C15

    primary_lits = list(inputs)
    primary_lits.extend(_parse_latch(latch)[0] for latch in latches)

    for lit in primary_lits:
        seed ^= (seed << 13) & mask
        seed ^= seed >> 7
        seed ^= (seed << 17) & mask
        base = lit & ~1
        values[base] = seed & mask
        values[base ^ 1] = (~values[base]) & mask

    for lhs, r0, r1 in gates_raw:
        val = values.get(r0, 0) & values.get(r1, 0)
        values[lhs] = val
        values[lhs ^ 1] = (~val) & mask

    good_outputs = [values.get(out, 0) for out in outputs]
    sa0, sa1 = set(), set()

    for idx, (target, _, _) in enumerate(gates_raw):
        for stuck_value, bucket in ((0, sa0), (1, sa1)):
            fault_values = values.copy()
            fault_values[target] = mask if stuck_value else 0
            fault_values[target ^ 1] = 0 if stuck_value else mask

            for lhs, r0, r1 in gates_raw[idx + 1 :]:
                val = fault_values.get(r0, 0) & fault_values.get(r1, 0)
                fault_values[lhs] = val
                fault_values[lhs ^ 1] = (~val) & mask

            if [fault_values.get(out, 0) for out in outputs] == good_outputs:
                bucket.add(idx)

    return sa0, sa1


def _build_fault_sweep_cnf(inputs, latches, outputs, gates_raw):
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
            sat = mapping[var]
        elif var in shared:
            sat = shared[var]
        else:
            raise ValueError(f"undefined literal in SAT encoding: {aig_lit}")
        return -sat if (aig_lit & 1) else sat

    for lhs, r0, r1 in gates_raw:
        out = cnf.new_var()
        good[lhs >> 1] = out
        cnf.and2(out, lit_from(good, r0), lit_from(good, r1))

    f0_lits = []
    f1_lits = []

    for lhs, r0, r1 in gates_raw:
        normal = cnf.new_var()
        cnf.and2(normal, lit_from(faulty, r0), lit_from(faulty, r1))

        f0 = cnf.new_var()
        f1 = cnf.new_var()
        f0_lits.append(f0)
        f1_lits.append(f1)
        cnf.clauses.append([-f0, -f1])

        not_forced_zero = cnf.new_var()
        cnf.and2(not_forced_zero, normal, -f0)

        out = cnf.new_var()
        cnf.or2(out, not_forced_zero, f1)
        faulty[lhs >> 1] = out

    xors = []
    for out_lit in outputs:
        xor = cnf.new_var()
        cnf.xor2(xor, lit_from(good, out_lit), lit_from(faulty, out_lit))
        xors.append(xor)

    return cnf.clauses, cnf.or_many(xors), f0_lits, f1_lits


def build_miter_and_sweep_all(M, I, L, O, A, inputs, latches, outputs, gates_raw, timings=None):
    if A == 0 or not outputs:
        return []

    t_filter = time.time()
    sim_sa0, sim_sa1 = _simulation_candidates(inputs, latches, outputs, gates_raw)
    if timings is not None:
        timings["Filter"] += time.time() - t_filter

    t_encode = time.time()
    clauses, miter_lit, f0_lits, f1_lits = _build_fault_sweep_cnf(inputs, latches, outputs, gates_raw)
    if timings is not None:
        timings["Encode"] += time.time() - t_encode

    base = [-lit for lit in f0_lits] + [-lit for lit in f1_lits]
    redundant = []
    chosen_gates = set()

    t_sat = time.time()
    with Glucose4(bootstrap_with=clauses) as solver:
        for idx in range(A):
            if idx in sim_sa0:
                assumptions = base.copy()
                assumptions[idx] = f0_lits[idx]
                assumptions.append(miter_lit)
                solver.conf_budget(SAT_CONFLICT_BUDGET)
                if solver.solve_limited(assumptions=assumptions) is False:
                    redundant.append((idx, 0))
                    chosen_gates.add(idx)
                    continue

            if idx not in chosen_gates and idx in sim_sa1:
                assumptions = base.copy()
                assumptions[A + idx] = f1_lits[idx]
                assumptions.append(miter_lit)
                solver.conf_budget(SAT_CONFLICT_BUDGET)
                if solver.solve_limited(assumptions=assumptions) is False:
                    redundant.append((idx, 1))
                    chosen_gates.add(idx)

    if timings is not None:
        timings["SAT"] += time.time() - t_sat
    return redundant


def compute_tfo_conflict_graph(gates_raw, redundant_candidates):
    best_by_gate = {}
    for idx, value in redundant_candidates:
        best_by_gate.setdefault(idx, value)

    candidates = sorted(best_by_gate.items())
    if not candidates:
        return []

    def_var_to_idx = {lhs >> 1: idx for idx, (lhs, _, _) in enumerate(gates_raw)}
    fanout = {idx: set() for idx in range(len(gates_raw))}

    for idx, (_, r0, r1) in enumerate(gates_raw):
        for lit in (r0, r1):
            parent = def_var_to_idx.get(lit >> 1)
            if parent is not None:
                fanout[parent].add(idx)

    tfo_cache = {}

    def tfo(idx):
        if idx in tfo_cache:
            return tfo_cache[idx]
        seen = set()
        queue = deque(fanout[idx])
        while queue:
            item = queue.popleft()
            if item in seen:
                continue
            seen.add(item)
            queue.extend(fanout[item])
        tfo_cache[idx] = seen
        return seen

    selected = []
    selected_indices = []
    for idx, value in candidates:
        conflicts = any(other in tfo(idx) or idx in tfo(other) for other in selected_indices)
        if not conflicts:
            selected.append((idx, value))
            selected_indices.append(idx)
    return selected


def _copy_gates(gates):
    return [[lhs, r0, r1] for lhs, r0, r1 in gates]


def _write_strashed(filepath, parsed, gates_raw, symbols, comment):
    M, I, L, O, A, inputs, latches, outputs = parsed
    result = pure_python_forward_strash(M, I, L, O, A, inputs, latches, outputs, gates_raw)
    M_f, I_f, L_f, O_f, A_f, in_f, la_f, out_f, gates_f = result
    write_aag(filepath, M_f, I_f, L_f, O_f, A_f, in_f, la_f, out_f, gates_f, symbols, comment)
    return A_f


def _verify_output(original, candidate):
    from verifier import verify_equivalence

    status, _ = verify_equivalence(original, candidate)
    return status == "PASS"


def solve_circuit(circuit_path, output_path):
    t_start = time.time()
    timings = {"Parse": 0.0, "Filter": 0.0, "Encode": 0.0, "SAT": 0.0, "Total": 0.0}

    t_parse = time.time()
    M, I, L, O, A, inputs, latches, outputs, gates_raw, symbols = parse_aag(circuit_path)
    timings["Parse"] = time.time() - t_parse
    orig_gates = A
    parsed_header = (M, I, L, O, A, inputs, latches, outputs)

    sweep_roots = list(outputs)
    sweep_roots.extend(_parse_latch(latch)[1] for latch in latches)
    all_redundant = build_miter_and_sweep_all(M, I, L, O, A, inputs, latches, sweep_roots, gates_raw, timings)

    t_filter = time.time()
    safe_batch = compute_tfo_conflict_graph(gates_raw, all_redundant)
    timings["Filter"] += time.time() - t_filter

    working_gates = _copy_gates(gates_raw)
    for gate_idx, value in safe_batch:
        lhs = working_gates[gate_idx][0]
        working_gates[gate_idx] = [lhs, value, value]

    final_removed = len(safe_batch)
    _write_strashed(output_path, parsed_header, working_gates, symbols, "Alg8 Hybrid")

    if safe_batch and not _verify_output(circuit_path, output_path):
        accepted = []
        working_gates = _copy_gates(gates_raw)

        with tempfile.NamedTemporaryFile(prefix="alg8_candidate_", suffix=".aag", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            for gate_idx, value in safe_batch:
                trial_gates = _copy_gates(working_gates)
                lhs = trial_gates[gate_idx][0]
                trial_gates[gate_idx] = [lhs, value, value]
                _write_strashed(tmp_path, parsed_header, trial_gates, symbols, "Alg8 Hybrid Trial")
                if _verify_output(circuit_path, tmp_path):
                    working_gates = trial_gates
                    accepted.append((gate_idx, value))

            final_removed = len(accepted)
            _write_strashed(output_path, parsed_header, working_gates, symbols, "Alg8 Hybrid Safe Fallback")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    if not os.path.exists(output_path):
        shutil.copy(circuit_path, output_path)
        final_gates = orig_gates
    else:
        try:
            final_gates = parse_aag(output_path)[4]
        except Exception:
            final_gates = 0

    timings["Total"] = time.time() - t_start
    return orig_gates, orig_gates, final_gates, final_removed, timings
