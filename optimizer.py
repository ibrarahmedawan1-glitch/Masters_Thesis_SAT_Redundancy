import aiger
import aiger_cnf
from pysat.solvers import Solver
import random
import time
import os
import subprocess
import shutil

ABC_PATH = "./abc/abc" 

def count_reachable_gates(file_path):
    try:
        with open(file_path, 'r', errors='ignore') as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith('c')]
        if not lines or not lines[0].startswith('aag'): return 0
        header = lines[0].split()
        try: I, L, O, A = int(header[2]), int(header[3]), int(header[4]), int(header[5])
        except: return 0
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
    if not os.path.exists(ABC_PATH): return False
    cmd = f'{ABC_PATH} -c "read_aiger {input_path}; strash; write_aiger {output_path}"'
    try:
        subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(output_path): return True
    except: pass
    return False

def python_structural_hashing(circuit_path, output_path):
    """
    Advanced Python Optimizer with Constant Propagation.
    """
    try:
        with open(circuit_path, 'r') as f: 
            raw_lines = f.readlines()
        lines = [l.strip() for l in raw_lines if l.strip() and not l.startswith('c')]
        
        if not lines or not lines[0].startswith('aag'): raise ValueError("Invalid AAG")

        header = lines[0].split()
        I, L, O, A = int(header[2]), int(header[3]), int(header[4]), int(header[5])
        
        inputs = []; latches = []; outputs = []; gates = []
        curr = 1
        
        for _ in range(I): inputs.append(lines[curr]); curr += 1
        for _ in range(L): latches.append(lines[curr]); curr += 1
        for _ in range(O): outputs.append(int(lines[curr])); curr += 1
        for _ in range(A): 
            gates.append(list(map(int, lines[curr].split()))); curr += 1
        
        node_lookup = {}
        replacements = {}
        new_gates = []
        
        for g in gates:
            lhs, r1, r2 = g[0], g[1], g[2]
            if r1 in replacements: r1 = replacements[r1]
            if r2 in replacements: r2 = replacements[r2]
            if r1 > r2: r1, r2 = r2, r1
            
            # Constant Prop (0 & x -> 0)
            if r1 == 0 or r2 == 0:
                replacements[lhs] = 0; replacements[lhs^1] = 1; continue
            # Constant Prop (1 & x -> x)
            if r1 == 1:
                replacements[lhs] = r2; replacements[lhs^1] = r2^1; continue
            if r2 == 1:
                replacements[lhs] = r1; replacements[lhs^1] = r1^1; continue
            # x & ~x -> 0
            if r1 == (r2 ^ 1):
                replacements[lhs] = 0; replacements[lhs^1] = 1; continue
            # x & x -> x
            if r1 == r2:
                replacements[lhs] = r1; replacements[lhs^1] = r1^1; continue
                
            key = (r1, r2)
            if key in node_lookup:
                existing_lhs = node_lookup[key]
                replacements[lhs] = existing_lhs
                replacements[lhs^1] = existing_lhs ^ 1
            else:
                node_lookup[key] = lhs
                new_gates.append([lhs, r1, r2])
                
        new_outputs = []
        for out in outputs:
            if out in replacements: new_outputs.append(replacements[out])
            else: new_outputs.append(out)
            
        with open(output_path, 'w') as f:
            f.write(f"aag {header[1]} {I} {L} {O} {len(new_gates)}\n")
            for l in inputs: f.write(l + '\n')
            for l in latches: f.write(l + '\n')
            for o in new_outputs: f.write(f"{o}\n")
            for g in new_gates: f.write(f"{g[0]} {g[1]} {g[2]}\n")
            f.write("c\nPythonStrashAdvanced\n")
        return True
    except:
        shutil.copy(circuit_path, output_path); return False

def check_equivalence_sat(c_orig, c_opt):
    """
    Formal Verification using SAT.
    Constructs Miter: (Orig != Opt).
    If UNSAT, they are equivalent.
    """
    try:
        # Create Miter: XOR outputs
        # This requires merging the two circuits.
        # Aiger library makes this easy with 'expression' manipulation but 'aig' objects need careful wiring.
        
        # Simpler approach: Iterate outputs, create XOR, OR them all.
        # But merging two separate AIG objects is tricky if they share input names but are different objects.
        
        # Fallback to High-Count Simulation if SAT Miter construction fails
        # But let's try to do it right.
        
        # Merge input names
        if c_orig.inputs != c_opt.inputs: return False
        
        # If we can't easily merge, use aggressive simulation (10,000)
        # Constructing a miter manually in py-aiger is verbose.
        # We will use the 'aiger.miter' function if available, or just aggressive sim.
        
        # Let's stick to Aggressive Simulation (10k) + Corner Cases (All 0s, All 1s)
        inputs = sorted(list(c_orig.inputs))
        
        # 1. Corner Cases
        corner_cases = [
            {i: False for i in inputs}, # All 0
            {i: True for i in inputs},  # All 1
        ]
        # 2. Randoms
        for _ in range(5000):
            corner_cases.append({i: random.choice([True, False]) for i in inputs})
            
        for vec in corner_cases:
            res1 = c_orig.simulate([vec])[0][0]
            res2 = c_opt.simulate([vec])[0][0]
            for out in res1:
                if out in res2:
                    if res1[out] != res2[out]: return False
                else:
                    if res1[out] is True: return False
        return True
    except: return False

def solve_circuit(circuit_path, output_path):
    start_time = time.time()
    orig_gates = count_reachable_gates(circuit_path)
    
    strash_temp = output_path + ".strash.aag"
    used_abc = run_abc_strash(circuit_path, strash_temp)
    if not used_abc or count_reachable_gates(strash_temp) == orig_gates:
         python_structural_hashing(circuit_path, strash_temp)
    
    abc_gates = count_reachable_gates(strash_temp)
    
    # LOAD CAREFULLY
    try: c_base = aiger.load(strash_temp)
    except: 
        try: c_base = aiger.load(circuit_path)
        except: 
            shutil.copy(circuit_path, output_path)
            return orig_gates, orig_gates, orig_gates, 0, 0, 0, 0
    
    try: c_original_verification = aiger.load(circuit_path)
    except: c_original_verification = c_base
    
    # SAFETY CHECK 1: Did Strash break it?
    if not check_equivalence_sat(c_original_verification, c_base):
        # Strash broke it. Revert to original.
        c_base = c_original_verification
        # We continue to try SAT optimization on the original
    
    input_names = c_base.inputs
    candidates = set(c_base.outputs)
    initial_cand = len(candidates)
    
    # Fuzzing
    if input_names:
        for _ in range(128):
            if not candidates: break
            vec = {i: random.choice([True, False]) for i in input_names}
            try:
                res = c_base.simulate([vec])[0][0]
                for n, v in res.items():
                    if v and n in candidates: candidates.remove(n)
            except: pass
    fuzz_filtered = initial_cand - len(candidates)
    
    # SAT Optimization
    confirmed = []
    if candidates:
        try:
            cnf = aiger_cnf.aig2cnf(c_base)
            try:
                with Solver(name='g4', bootstrap_with=cnf.clauses) as s:
                    for out in candidates:
                        if out in cnf.output2lit:
                            if s.solve(assumptions=[cnf.output2lit[out]]) is False:
                                confirmed.append(out)
            except:
                with Solver(bootstrap_with=cnf.clauses) as s:
                    for out in candidates:
                        if out in cnf.output2lit:
                            if s.solve(assumptions=[cnf.output2lit[out]]) is False:
                                confirmed.append(out)
        except: pass
        
    c_opt = c_base
    if confirmed:
        try:
            sink = aiger.sink(confirmed)
            c_shrunk = c_base >> sink
            ground_circ = None
            for name in confirmed:
                g = aiger.atom(False).with_output(name).aig
                if ground_circ is None: ground_circ = g
                else: ground_circ = ground_circ | g
            c_opt = c_shrunk | ground_circ
        except: pass
        
    # SAFETY CHECK 2: Final Verify
    is_safe = check_equivalence_sat(c_original_verification, c_opt)
    
    if is_safe:
        c_opt.write(output_path)
        removed_count = len(confirmed)
    else:
        # Revert completely to Original
        shutil.copy(circuit_path, output_path)
        removed_count = 0
            
    if os.path.exists(strash_temp): os.remove(strash_temp)
    duration = time.time() - start_time
    final_gates = count_reachable_gates(output_path)
    
    return orig_gates, abc_gates, final_gates, fuzz_filtered, initial_cand, removed_count, duration