import aiger
import aiger_cnf
from pysat.solvers import Solver
import time
import os
import subprocess
import shutil
from abc_utils import run_abc_strash as abc_run_abc_strash

ABC_PATH = "./abc/abc" 

# --- HELPER FUNCTIONS ---
def count_reachable_gates(file_path):
    try:
        with open(file_path, 'r', errors='ignore') as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith('c')]
        if not lines or not lines[0].startswith('aag'): return 0
        header = lines[0].split()
        I, L, O, A = int(header[2]), int(header[3]), int(header[4]), int(header[5])
        current = 1 + I + L
        output_lits = []
        for _ in range(O):
            try: output_lits.append(int(lines[current]))
            except: pass
            current += 1
        gates = {}
        for _ in range(A):
            if current >= len(lines): break
            try:
                p = [int(x) for x in lines[current].split()]
                if len(p) >= 3: gates[p[0]] = (p[1], p[2])
            except: pass
            current += 1
        reachable = set()
        queue = list(output_lits)
        visited = set(queue)
        count = 0
        while queue:
            lit = queue.pop(0); var = lit >> 1; lhs = var * 2
            if lhs in gates:
                if lhs not in reachable:
                    reachable.add(lhs); count += 1
                    r1, r2 = gates[lhs]
                    if r1 not in visited: visited.add(r1); queue.append(r1)
                    if r2 not in visited: visited.add(r2); queue.append(r2)
        return count
    except: return 0

def run_abc_strash(input_path, output_path):
    return abc_run_abc_strash(input_path, output_path)

# --- ALGORITHM 3: INCREMENTAL ATPG ENGINE ---
def parse_aag(filepath):
    with open(filepath, 'r') as f:
        lines = [l.strip() for l in f.readlines() if l.strip() and not l.startswith('c')]
    header = lines[0]
    parts = header.split()
    M, I, L, O, A = map(int, parts[1:6])
    inputs = lines[1 : 1+I]
    latches = lines[1+I : 1+I+L]
    outputs = lines[1+I+L : 1+I+L+O]
    gates = lines[1+I+L+O : 1+I+L+O+A]
    return M, I, L, O, A, inputs, latches, outputs, gates

def write_aag(filepath, M, I, L, O, A, inputs, latches, outputs, gates):
    with open(filepath, 'w') as f:
        f.write(f"aag {M} {I} {L} {O} {A}\n")
        for i in inputs: f.write(str(i) + '\n')
        for l in latches: f.write(str(l) + '\n')
        for o in outputs: f.write(str(o) + '\n')
        for g in gates: f.write(str(g) + '\n')
        for idx in range(I): f.write(f"i{idx} i{idx}\n")
        for idx in range(O): f.write(f"o{idx} o{idx}\n")
        f.write("c\nAutomated Miter\n")

def build_universal_faulty_machine(current_aag, univ_aag):
    """Dynamically rewrites the AAG to inject an Enable Pin into EVERY gate."""
    M, I, L, O, A, inputs, latches, outputs, gates = parse_aag(current_aag)
    
    new_M = M + 2 * A
    new_I = I + A
    new_A = A * 2
    
    new_inputs = inputs.copy()
    new_gates = []
    
    for i, gate_line in enumerate(gates):
        parts = gate_line.split()
        lhs, r1, r2 = int(parts[0]), int(parts[1]), int(parts[2])
        
        # 1. Create Enable Pin E_i
        var_E = M + i + 1
        lit_E = var_E * 2
        new_inputs.append(str(lit_E))
        
        # 2. Create Intermediate Wire T_i
        var_T = M + A + i + 1
        lit_T = var_T * 2
        
        # 3. Old logic computes T_i
        new_gates.append(f"{lit_T} {r1} {r2}")
        
        # 4. Fault logic computes original lhs: (T_i AND NOT(E_i))
        # NOT(E_i) is lit_E + 1
        new_gates.append(f"{lhs} {lit_T} {lit_E + 1}")
        
    with open(univ_aag, 'w') as f:
        f.write(f"aag {new_M} {new_I} {L} {O} {new_A}\n")
        for inp in new_inputs: f.write(f"{inp}\n")
        for lat in latches: f.write(f"{lat}\n")
        for out in outputs: f.write(f"{out}\n")
        for g in new_gates: f.write(f"{g}\n")
        
        for idx in range(I): f.write(f"i{idx} i{idx}\n")
        # EXPOSE THE FAULT PINS TO PY-AIGER VIA THE SYMBOL TABLE
        for idx in range(A): f.write(f"i{I + idx} fault_en_{idx}\n")
        for idx in range(O): f.write(f"o{idx} o{idx}\n")
        f.write("c\nUniversal Faulty Machine\n")

def get_redundant_gates_incremental(good_aag, univ_aag, num_gates):
    """The Incremental SAT Loop. One solver. Zero file I/O inside the loop."""
    try:
        Mg = aiger.load(good_aag)
        Mf = aiger.load(univ_aag)
        
        outputs = list(Mg.outputs)
        Mg = Mg['o', {o: f"g_{o}" for o in outputs}]
        Mf = Mf['o', {o: f"f_{o}" for o in outputs}]
        
        combined = Mg | Mf
        
        miter_expr = None
        for o in outputs:
            xor_gate = aiger.atom(f"g_{o}") ^ aiger.atom(f"f_{o}")
            if miter_expr is None: miter_expr = xor_gate
            else: miter_expr = miter_expr | xor_gate
            
        miter = combined >> miter_expr.aig
        miter_output = list(miter.outputs)[0]
        
        cnf = aiger_cnf.aig2cnf(miter)
        redundant_indices = []
        
        with Solver(name='g4', bootstrap_with=cnf.clauses) as solver:
            miter_out_lit = cnf.output2lit[miter_output]
            
            # Pre-build assumption array (All faults disabled by default)
            base_assumptions = [miter_out_lit]
            en_lits = []
            for i in range(num_gates):
                lit = cnf.input2lit[f"fault_en_{i}"]
                en_lits.append(lit)
                base_assumptions.append(-lit) 
                
            # THE LIGHTNING LOOP
            for i in range(num_gates):
                current_assumptions = base_assumptions.copy()
                # Activate ONLY fault i (Flip negative literal to positive)
                current_assumptions[i + 1] = en_lits[i] 
                
                is_testable = solver.solve(assumptions=current_assumptions)
                if not is_testable:
                    redundant_indices.append(i)
                    
        return redundant_indices
    except Exception as e:
        # print(f"SAT Error: {e}")
        return []

# --- THE MASTER INTEGRATION LOOP ---
def solve_circuit(circuit_path, output_path):
    start_time = time.time()
    orig_gates = count_reachable_gates(circuit_path)
    
    if orig_gates == 0:
        shutil.copy(circuit_path, output_path)
        return 0, 0, 0, 0, 0, 0, 0.0

    M, I, L, O, A, inputs, latches, outputs, gates = parse_aag(circuit_path)
    current_aag = output_path + ".temp.aag"
    univ_aag = output_path + ".univ.aag"
    write_aag(current_aag, M, I, L, O, A, inputs, latches, outputs, gates)
    
    if not inputs:
        shutil.copy(circuit_path, output_path)
        return orig_gates, orig_gates, orig_gates, 0, 0, 0, time.time() - start_time

    first_in = int(inputs[0])
    sa0_string = f"{first_in} {first_in + 1}"
    
    circuit_changed = True
    total_removed = 0
    
    while circuit_changed:
        circuit_changed = False
        M, I, L, O, A, inputs, latches, outputs, gates = parse_aag(current_aag)
        
        # 1. Build Universal Machine
        build_universal_faulty_machine(current_aag, univ_aag)
        
        # 2. Run Incremental Sweep
        redundant_list = get_redundant_gates_incremental(current_aag, univ_aag, A)
        
        # 3. Process Results
        for idx in redundant_list:
            target_lhs = gates[idx].split()[0]
            if not gates[idx].endswith(sa0_string):
                # Physically sever the gate
                gates[idx] = f"{target_lhs} {sa0_string}" 
                circuit_changed = True
                total_removed += 1
                
        if circuit_changed:
            write_aag(current_aag, M, I, L, O, A, inputs, latches, outputs, gates)
                
    # Cleanup via ABC
    run_abc_strash(current_aag, output_path)
    if not os.path.exists(output_path): shutil.copy(current_aag, output_path)
        
    final_gates = count_reachable_gates(output_path)
    duration = time.time() - start_time
    
    if os.path.exists(current_aag): os.remove(current_aag)
    if os.path.exists(univ_aag): os.remove(univ_aag)
    
    return orig_gates, orig_gates, final_gates, 0, orig_gates, total_removed, duration
