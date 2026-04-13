import aiger
import aiger_cnf
from pysat.solvers import Solver
import time, os, subprocess, shutil

ABC_PATH = "./abc/abc" 

def count_reachable_gates(file_path):
    try:
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
    with open(filepath, 'r') as f: 
        lines = [l.strip() for l in f if l.strip() and not l.startswith('c')]
    header = lines[0].split()
    M, I, L, O, A = map(int, header[1:6])
    inputs = lines[1 : 1+I]
    latches = lines[1+I : 1+I+L]
    outputs = lines[1+I+L : 1+I+L+O]
    gates = lines[1+I+L+O : 1+I+L+O+A]
    symbols = lines[1+I+L+O+A:]
    return M, I, L, O, A, inputs, latches, outputs, gates, symbols

def write_aag_strict(filepath, M, I, L, O, A, inputs, latches, outputs, gates, symbols):
    with open(filepath, 'w') as f:
        f.write(f"aag {M} {I} {L} {O} {A}\n")
        for x in inputs + latches + outputs + gates: f.write(str(x) + '\n')
        sym_i = [s for s in symbols if s.startswith('i')]
        sym_l = [s for s in symbols if s.startswith('l')]
        sym_o = [s for s in symbols if s.startswith('o')]
        for s in sym_i + sym_l + sym_o: f.write(s + '\n')
        f.write("c\nAlg1 Miter\n")

def is_gate_redundant_naive(good_filepath, faulty_filepath):
    try:
        Mg, Mf = aiger.load(good_filepath), aiger.load(faulty_filepath)
        outputs = list(Mg.outputs)
        Mg = Mg['o', {o: f"g_{o}" for o in outputs}]
        Mf = Mf['o', {o: f"f_{o}" for o in outputs}]
        combined = Mg | Mf
        miter_expr = None
        for o in outputs:
            xor_gate = aiger.atom(f"g_{o}") ^ aiger.atom(f"f_{o}")
            miter_expr = xor_gate if miter_expr is None else miter_expr | xor_gate
            
        miter = combined >> miter_expr.aig
        cnf = aiger_cnf.aig2cnf(miter)
        with Solver(name='g4', bootstrap_with=cnf.clauses) as solver:
            output_lit = cnf.output2lit[list(miter.outputs)[0]]
            return not solver.solve(assumptions=[output_lit])
    except KeyboardInterrupt:
        raise # FORCE the interrupt to pass through!
    except Exception as e: 
        return False

def solve_circuit(circuit_path, output_path):
    start_time = time.time()
    orig_gates = count_reachable_gates(circuit_path)
    if orig_gates == 0:
        shutil.copy(circuit_path, output_path)
        return 0, 0, 0, 0, 0, 0, 0.0

    M, I, L, O, A, inputs, latches, outputs, gates, symbols = parse_aag_strict(circuit_path)
    current_aag = output_path + ".temp.aag"
    write_aag_strict(current_aag, M, I, L, O, A, inputs, latches, outputs, gates, symbols)
    
    first_in = int(inputs[0])
    sa0_string = f"{first_in} {first_in + 1}" # Constant 0 (A AND NOT A)
    circuit_changed, total_removed = True, 0
    
    while circuit_changed:
        circuit_changed = False
        M, I, L, O, A, inputs, latches, outputs, gates, symbols = parse_aag_strict(current_aag)
        
        for i in range(len(gates)):
            target_lhs = gates[i].split()[0]
            if gates[i].endswith(sa0_string): continue 
                
            faulty_gates = gates.copy()
            faulty_gates[i] = f"{target_lhs} {sa0_string}"
            faulty_aag = "temp_faulty.aag"
            write_aag_strict(faulty_aag, M, I, L, O, A, inputs, latches, outputs, faulty_gates, symbols)
            
            if is_gate_redundant_naive(current_aag, faulty_aag):
                gates[i] = f"{target_lhs} {sa0_string}" 
                write_aag_strict(current_aag, M, I, L, O, A, inputs, latches, outputs, gates, symbols)
                circuit_changed = True; total_removed += 1
                break 
                
    subprocess.run(f'{ABC_PATH} -c "read_aiger {current_aag}; strash; write_aiger {output_path}"', 
                   shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not os.path.exists(output_path): shutil.copy(current_aag, output_path)
        
    for f in [current_aag, "temp_faulty.aag"]:
        if os.path.exists(f): os.remove(f)
    return orig_gates, orig_gates, count_reachable_gates(output_path), 0, orig_gates, total_removed, time.time() - start_time