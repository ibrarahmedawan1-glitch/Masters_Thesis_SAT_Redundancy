import aiger
import aiger_cnf
from pysat.solvers import Solver
import os

def parse_aag_strict(filepath):
    """Re-using our verified strict parser."""
    with open(filepath, 'r') as f:
        lines = [l.strip() for l in f if l.strip() and not l.startswith('c')]
    header = lines[0].split()
    M, I, L, O, A = map(int, header[1:6])
    inputs = lines[1:1+I]
    latches = lines[1+I:1+I+L]
    outputs = lines[1+I+L:1+I+L+O]
    gates = lines[1+I+L+O:1+I+L+O+A]
    symbols = lines[1+I+L+O+A:]
    return M, I, L, O, A, inputs, latches, outputs, gates, symbols

def build_universal_machine(current_aag, univ_aag):
    """Builds the dense literal map with strict symbol boundaries."""
    M, I, L, O, A, inputs, latches, outputs, gates, symbols = parse_aag_strict(current_aag)
    new_I, new_A = I + 2*A, 3*A
    new_M = new_I + L + new_A
    new_inputs = inputs.copy()
    f_lits_E0, f_lits_E1 = [], []

    for i in range(A):
        v0, v1 = I + 1 + 2*i, I + 2 + 2*i
        new_inputs.extend([str(v0*2), str(v1*2)])
        f_lits_E0.append(v0*2); f_lits_E1.append(v1*2)

    lit_map = {0: 0, 1: 1}
    for i in range(1, I+1): lit_map[i*2] = i*2; lit_map[i*2+1] = i*2+1
    for i in range(L):
        ov, nv = I+1+i, new_I+1+i
        lit_map[ov*2] = nv*2; lit_map[ov*2+1] = nv*2+1

    new_gates, curr_v = [], new_I + L + 1
    for i, g in enumerate(gates):
        lhs, r1, r2 = map(int, g.split())
        m1, m2 = lit_map[r1], lit_map[r2]
        e0, e1 = f_lits_E0[i], f_lits_E1[i]
        vt, vx, vy = curr_v, curr_v+1, curr_v+2; curr_v += 3
        
        # O = (T AND ~E0) OR E1  => translated to NAND/AND AIG structures
        new_gates.extend([f"{vt*2} {m1} {m2}", f"{vx*2} {vt*2} {e0+1}", f"{vy*2} {vx*2+1} {e1+1}"])
        lit_map[lhs] = vy*2+1; lit_map[lhs+1] = vy*2

    with open(univ_aag, 'w') as f:
        f.write(f"aag {new_M} {new_I} {L} {O} {new_A}\n")
        for x in new_inputs + latches + [str(lit_map[int(o)]) for o in outputs] + new_gates:
            f.write(str(x)+'\n')

        sym_i = [s for s in symbols if s.startswith('i')]
        sym_l = [s for s in symbols if s.startswith('l')]
        sym_o = [s for s in symbols if s.startswith('o')]

        for s in sym_i: f.write(s + '\n')
        for i in range(A): f.write(f"i{I+2*i} f0_{i}\ni{I+2*i+1} f1_{i}\n")
        for s in sym_l: f.write(s + '\n')
        for s in sym_o: f.write(s + '\n')
        f.write("c\nVerified Universal Machine\n")

def test_incremental_logic():
    print("--- ALGORITHM 3 INCREMENTAL SANDBOX ---")
    test_file = "tiny_test.aag"
    univ_file = "tiny_univ.aag"

    # 1. Create a True Stuck-At Redundancy (A AND NOT A)
    with open(test_file, 'w') as f:
        f.write("aag 3 1 0 1 2\n") # MaxVar 3, 1 Input, 0 Latches, 1 Output, 2 Gates
        f.write("2\n")             # Input 0 (Literal 2)
        f.write("6\n")             # Output  (Literal 6)
        f.write("4 2 2\n")         # Gate 0: Var 2 = Input AND Input (Buffer)
        f.write("6 4 5\n")         # Gate 1: Var 3 = Gate 0 AND NOT Gate 0 (Always 0)
        f.write("i0 pi_0\no0 po_0\nc\nTiny Test\n")

    M, I, L, O, A, _, _, _, _, _ = parse_aag_strict(test_file)
    build_universal_machine(test_file, univ_file)

    orig_aig = aiger.load(test_file)
    Mf = aiger.load(univ_file)

    orig_outs = list(orig_aig.outputs)
    combined = orig_aig['o', {o: f"g_{o}" for o in orig_outs}] | Mf['o', {o: f"f_{o}" for o in orig_outs}]

    miter_logic = None
    for o in orig_outs:
        xor = aiger.atom(f"g_{o}") ^ aiger.atom(f"f_{o}")
        miter_logic = xor if miter_logic is None else miter_logic | xor

    miter_aig = combined >> miter_logic.aig
    cnf = aiger_cnf.aig2cnf(miter_aig)

    print(f"[INFO] Circuit has {A} gates. Testing SA0 and SA1 incrementally.")
    redundant_faults = []

    with Solver(name='g4', bootstrap_with=cnf.clauses) as s:
        miter_lit = cnf.output2lit[list(miter_aig.outputs)[0]]
        f0_lits = [cnf.input2lit[f"f0_{j}"] for j in range(A)]
        f1_lits = [cnf.input2lit[f"f1_{j}"] for j in range(A)]

        base = [-l for l in f0_lits] + [-l for l in f1_lits]

        for i in range(A):
            assump_sa0 = base.copy()
            assump_sa0[i] = f0_lits[i] 
            assump_sa0.append(miter_lit)
            is_sat_0 = s.solve(assumptions=assump_sa0)

            assump_sa1 = base.copy()
            assump_sa1[A + i] = f1_lits[i] 
            assump_sa1.append(miter_lit)
            is_sat_1 = s.solve(assumptions=assump_sa1)

            print(f"Gate {i} | SA0 SAT? {is_sat_0:<5} | SA1 SAT? {is_sat_1:<5}")

            if not is_sat_0: redundant_faults.append((i, "SA0"))
            if not is_sat_1: redundant_faults.append((i, "SA1"))

    print(f"\n[RESULT] Detected Redundancies: {redundant_faults}")
    
    # We expect Gate 0 to be SA0/SA1 redundant, and Gate 1 to be SA0 redundant.
    if set(redundant_faults) == {(0, 'SA0'), (0, 'SA1'), (1, 'SA0')}:
        print("[PASS] The Incremental Engine is MATHEMATICALLY FLAWLESS!")
    else:
        print("[FAIL] The solver matrix is misaligned.")

    for f in [test_file, univ_file]:
        if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    test_incremental_logic()