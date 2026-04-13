import aiger
import aiger_cnf
from pysat.solvers import Solver
import time, os, subprocess, shutil

ABC_PATH = "./abc/abc" 

def run_abc_strash(input_path, output_path):
    """Pre-conditioning: Shrinks the circuit topologically before SAT."""
    if not os.path.exists(ABC_PATH): return False
    cmd = f'{ABC_PATH} -c "read_aiger {input_path}; strash; write_aiger {output_path}"'
    try:
        subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return os.path.exists(output_path)
    except: return False

def count_reachable_gates(file_path):
    try:
        if not os.path.exists(file_path): return 0
        with open(file_path, 'r', errors='ignore') as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith('c')]
        if not lines or not lines[0].startswith('aag'): return 0
        header = lines[0].split()
        I, L, O, A = int(header[2]), int(header[3]), int(header[4]), int(header[5])
        current = 1 + I + L
        output_lits = [int(lines[current + i]) for i in range(O)]
        current += O
        gates = {}
        for _ in range(A):
            p = [int(x) for x in lines[current].split()]
            gates[p[0]] = (p[1], p[2])
            current += 1
        reachable, queue = set(), list(output_lits)
        visited = set(queue)
        while queue:
            lit = queue.pop(0); var = lit >> 1; lhs = var * 2
            if lhs in gates and lhs not in reachable:
                reachable.add(lhs)
                for r in gates[lhs]:
                    if r not in visited: visited.add(r); queue.append(r)
        return len(reachable)
    except: return 0

def parse_aag_strict(filepath):
    for _ in range(10):
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0: break
        time.sleep(0.5)
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
        for s in sym_l + sym_o: f.write(s + '\n')
        f.write("c\nVerified Universal Machine\n")

def solve_circuit(circuit_path, output_path):
    start_time = time.time()
    orig_gates = count_reachable_gates(circuit_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # PHASE 0: ABC Pre-conditioning
    pre_cond_path = output_path + ".precond.aag"
    if run_abc_strash(circuit_path, pre_cond_path): process_path = pre_cond_path
    else: process_path = circuit_path

    try:
        M, I, L, O, A, inputs, latches, outputs, gates_raw, symbols = parse_aag_strict(process_path)
        orig_aig = aiger.load(process_path)
    except: return orig_gates, orig_gates, 0, 0, 0, 0, 0.0

    if A == 0: 
        shutil.copy(process_path, output_path)
        return orig_gates, orig_gates, orig_gates, 0, 0, 0, time.time() - start_time

    univ_aag = output_path + ".univ.aag"
    build_universal_machine(process_path, univ_aag)
    redundant_indices = []
    
    try:
        Mf = aiger.load(univ_aag)
        orig_outs = list(orig_aig.outputs)
        combined = orig_aig['o', {o: f"g_{o}" for o in orig_outs}] | Mf['o', {o: f"f_{o}" for o in orig_outs}]
        
        miter_logic = None
        for o in orig_outs:
            xor = aiger.atom(f"g_{o}") ^ aiger.atom(f"f_{o}")
            miter_logic = xor if miter_logic is None else miter_logic | xor
        
        miter_aig = combined >> miter_logic.aig
        cnf = aiger_cnf.aig2cnf(miter_aig)
        
        # USE G4 (Glucose4) because it supports solve_limited in PySAT
        with Solver(name='g4', bootstrap_with=cnf.clauses) as s:
            miter_lit = cnf.output2lit[list(miter_aig.outputs)[0]]
            f0_lits = [cnf.input2lit[f"f0_{j}"] for j in range(A)]
            f1_lits = [cnf.input2lit[f"f1_{j}"] for j in range(A)]
            base = [-l for l in f0_lits] + [-l for l in f1_lits]
            
            # SET BUDGET: 1500 conflicts max per gate to prevent exponential hangs
            s.conf_budget(1500) 
            
            for i in range(A):
                # Check SA0
                is_sat_0 = s.solve_limited(assumptions=base[:i] + [f0_lits[i]] + base[i+1:] + [miter_lit])
                if is_sat_0 is False: redundant_indices.append((i, 0))

                # Check SA1
                is_sat_1 = s.solve_limited(assumptions=base[:A+i] + [f1_lits[i]] + base[A+i+1:] + [miter_lit])
                if is_sat_1 is False: redundant_indices.append((i, 1))

        # Batch Surgery
        for idx, val in redundant_indices:
            lhs = gates_raw[idx].split()[0]
            gates_raw[idx] = f"{lhs} {val} {val}"

        pre_path = output_path + ".pre.aag"
        with open(pre_path, 'w') as f:
            f.write(f"aag {M} {I} {L} {O} {A}\n")
            for x in inputs + latches + outputs + gates_raw: f.write(str(x)+'\n')
            sym_i = [s for s in symbols if s.startswith('i')]
            sym_l = [s for s in symbols if s.startswith('l')]
            sym_o = [s for s in symbols if s.startswith('o')]
            for s in sym_i + sym_l + sym_o: f.write(s + '\n')
            f.write("c\nAlg3 Surgery\n")
        
        subprocess.run(f'{ABC_PATH} -c "read_aiger {pre_path}; strash; write_aiger {output_path}"', 
                       shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        if not os.path.exists(output_path): shutil.copy(pre_path, output_path)
            
        for f in [univ_aag, pre_path, pre_cond_path]:
            if os.path.exists(f): os.remove(f)
            
        return orig_gates, orig_gates, count_reachable_gates(output_path), 0, 0, len(redundant_indices), time.time() - start_time
    except Exception as e:
        print(f"Algorithm Error: {e}")
        return orig_gates, orig_gates, 0, 0, 0, 0, time.time() - start_time