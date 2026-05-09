import aiger
import aiger_cnf
import os
import time
from abc_utils import run_abc_cec
from pysat.solvers import Solver

ABC_PATH = "./abc/abc"


class _CnfBuilder:
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


def _parse_ascii_aag(path):
    lines = []
    with open(path, "r", encoding="ascii", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line == "c":
                break
            lines.append(line)

    if not lines or not lines[0].startswith("aag "):
        return None

    header = lines[0].split()
    M, I, L, O, A = map(int, header[1:6])
    logic_end = 1 + I + L + O + A
    if len(lines) < logic_end:
        raise ValueError(f"truncated AAG file: {path}")

    inputs = [int(lines[i]) for i in range(1, 1 + I)]
    latches = [list(map(int, lines[1 + I + i].split())) for i in range(L)]
    outputs = [int(lines[1 + I + L + i]) for i in range(O)]
    gate_start = 1 + I + L + O
    gates = [list(map(int, lines[gate_start + i].split())) for i in range(A)]
    return {"I": I, "L": L, "O": O, "inputs": inputs, "latches": latches, "outputs": outputs, "gates": gates}


def _encode_aag(cnf, aig, shared_vars):
    mapping = {}
    for idx, lit in enumerate(aig["inputs"]):
        mapping[lit >> 1] = shared_vars[idx]
    for idx, latch in enumerate(aig["latches"]):
        mapping[latch[0] >> 1] = shared_vars[aig["I"] + idx]

    def sat_lit(aig_lit):
        if aig_lit == 0:
            return cnf.const(False)
        if aig_lit == 1:
            return cnf.const(True)
        var = aig_lit >> 1
        if var not in mapping:
            raise ValueError(f"undefined literal in AAG: {aig_lit}")
        sat = mapping[var]
        return -sat if (aig_lit & 1) else sat

    for lhs, r0, r1 in aig["gates"]:
        out = cnf.new_var()
        cnf.and2(out, sat_lit(r0), sat_lit(r1))
        mapping[lhs >> 1] = out

    observed = [sat_lit(out) for out in aig["outputs"]]
    observed.extend(sat_lit(latch[1]) for latch in aig["latches"])
    return observed


def _verify_ascii_aag_equivalence(orig_path, opt_path):
    orig = _parse_ascii_aag(orig_path)
    opt = _parse_ascii_aag(opt_path)
    if orig is None or opt is None:
        return None

    if (orig["I"], orig["L"], orig["O"]) != (opt["I"], opt["L"], opt["O"]):
        return "FAIL"
    for left, right in zip(orig["latches"], opt["latches"]):
        left_reset = left[2] if len(left) > 2 else None
        right_reset = right[2] if len(right) > 2 else None
        if left_reset != right_reset:
            return "FAIL"

    cnf = _CnfBuilder()
    shared_vars = [cnf.new_var() for _ in range(orig["I"] + orig["L"])]
    orig_outputs = _encode_aag(cnf, orig, shared_vars)
    opt_outputs = _encode_aag(cnf, opt, shared_vars)

    xors = []
    for left, right in zip(orig_outputs, opt_outputs):
        xor = cnf.new_var()
        cnf.xor2(xor, left, right)
        xors.append(xor)
    miter_lit = cnf.or_many(xors)

    with Solver(name="g4", bootstrap_with=cnf.clauses) as solver:
        solver.conf_budget(200000)
        is_sat = solver.solve_limited(assumptions=[miter_lit])
        if is_sat is None:
            return "TIMEOUT"
        return "FAIL" if is_sat else "PASS"

def verify_equivalence(orig_path, opt_path):
    """Strict Formal Equivalence Check (CEC) with OS-Level SIGKILL Timeouts"""
    start_time = time.time()
    VERIFY_TIMEOUT = 15 # Seconds before OS-level kill
    
    # Phase 1: ABC Combinational Equivalence Checking.
    # This ABC build rejects ASCII .aag in read_aiger, so the wrapper converts
    # both sides to binary .aig before calling industrial-grade ABC CEC.
    status, duration, _ = run_abc_cec(orig_path, opt_path, timeout=VERIFY_TIMEOUT)
    if status in {"PASS", "FAIL", "TIMEOUT"}:
        return status, duration

    # Phase 2: Deterministic ASCII-AIGER SAT miter.
    # This compares inputs/outputs by position, so symbol-less .aag files do
    # not fail just because py-aiger generated fresh UUID signal names.
    try:
        direct_status = _verify_ascii_aag_equivalence(orig_path, opt_path)
        if direct_status is not None:
            return direct_status, (time.time() - start_time)
    except Exception:
        pass

    # Phase 3: py-aiger fallback for formats not handled by the direct AAG path.
    try:
        # SAFETY NET: Prevent pure-Python CNF conversion from hanging on huge circuits
        if os.path.getsize(orig_path) > 50000: # ~1000+ gates
            return "TIMEOUT", (time.time() - start_time)

        Mg, Mf = aiger.load(orig_path), aiger.load(opt_path)
        outputs = list(Mg.outputs)
        Mg = Mg['o', {o: f"g_{o}" for o in outputs}]
        Mf = Mf['o', {o: f"f_{o}" for o in outputs}]
        combined = Mg | Mf
        
        miter_expr = None
        for o in outputs:
            xor_gate = aiger.atom(f"g_{o}") ^ aiger.atom(f"f_{o}")
            miter_expr = xor_gate if miter_expr is None else miter_expr | xor_gate
            
        miter_aig = combined >> miter_expr.aig
        cnf = aiger_cnf.aig2cnf(miter_aig)
        
        with Solver(name='g4', bootstrap_with=cnf.clauses) as solver:
            miter_lit = cnf.output2lit[list(miter_aig.outputs)[0]]
            solver.conf_budget(5000) 
            is_sat = solver.solve_limited(assumptions=[miter_lit])
            
            if is_sat is None:
                return "TIMEOUT", (time.time() - start_time)
                
            return "FAIL" if is_sat else "PASS", (time.time() - start_time)
            
    except Exception:
        return "ERROR", (time.time() - start_time)
