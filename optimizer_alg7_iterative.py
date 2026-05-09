import aiger
import aiger_cnf
from pysat.solvers import Solver
import time, os, subprocess, shutil, random
from abc_utils import run_abc_strash as abc_run_abc_strash

ABC_PATH = "./abc/abc" 

def run_abc_strash(input_path, output_path):
    return abc_run_abc_strash(input_path, output_path)

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
        time.sleep(0.1)
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

def bit_parallel_filter(I, O, A, inputs, outputs, gates_raw):
    MASK64 = (1 << 64) - 1
    good_vals = {0: 0, 1: MASK64}
    for i in range(1, I+1):
        r = random.getrandbits(64)
        good_vals[i*2] = r; good_vals[i*2+1] = ~r & MASK64
    for g in gates_raw:
        lhs, r1, r2 = map(int, g.split())
        res = good_vals.get(r1, 0) & good_vals.get(r2, 0)
        good_vals[lhs] = res; good_vals[lhs+1] = ~res & MASK64
    good_outs = [good_vals.get(int(o), 0) for o in outputs]
    hard_sa0, hard_sa1 = [], []
    for idx, g_line in enumerate(gates_raw):
        target_lhs = int(g_line.split()[0])
        f_vals = good_vals.copy()
        f_vals[target_lhs] = 0; f_vals[target_lhs+1] = MASK64
        for p_idx in range(idx + 1, len(gates_raw)):
            p_lhs, r1, r2 = map(int, gates_raw[p_idx].split())
            res = f_vals.get(r1, 0) & f_vals.get(r2, 0)
            f_vals[p_lhs] = res; f_vals[p_lhs+1] = ~res & MASK64
        if [f_vals.get(int(o), 0) for o in outputs] == good_outs: hard_sa0.append(idx)
        f_vals = good_vals.copy()
        f_vals[target_lhs] = MASK64; f_vals[target_lhs+1] = 0
        for p_idx in range(idx + 1, len(gates_raw)):
            p_lhs, r1, r2 = map(int, gates_raw[p_idx].split())
            res = f_vals.get(r1, 0) & f_vals.get(r2, 0)
            f_vals[p_lhs] = res; f_vals[p_lhs+1] = ~res & MASK64
        if [f_vals.get(int(o), 0) for o in outputs] == good_outs: hard_sa1.append(idx)
    return hard_sa0, hard_sa1

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
        for x in new_inputs + latches + [str(lit_map[int(o)]) for o in outputs] + new_gates: f.write(str(x)+'\n')
        sym_i = [s for s in symbols if s.startswith('i')]
        sym_l = [s for s in symbols if s.startswith('l')]
        sym_o = [s for s in symbols if s.startswith('o')]
        for s in sym_i: f.write(s + '\n')
        for i in range(A): f.write(f"i{I+2*i} f0_{i}\ni{I+2*i+1} f1_{i}\n")
        for s in sym_l + sym_o: f.write(s + '\n')
        f.write("c\nVerified Universal Machine\n")

def solve_circuit(circuit_path, output_path):
    t_start_total = time.time()
    timings = {"Parse": 0.0, "Filter": 0.0, "Encode": 0.0, "SAT": 0.0, "Total": 0.0}
    orig_gates = count_reachable_gates(circuit_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Init working file
    work_path = output_path + ".work.aag"
    if not run_abc_strash(circuit_path, work_path):
        shutil.copy(circuit_path, work_path)

    total_removed = 0
    circuit_changed = True
    univ_aag = output_path + ".univ.aag"

    # 100% ACCURATE ITERATIVE LOOP
    while circuit_changed:
        circuit_changed = False
        try:
            M, I, L, O, A, inputs, latches, outputs, gates_raw, symbols = parse_aag_strict(work_path)
            if A == 0: break
            orig_aig = aiger.load(work_path)
        except: break

        t_filt = time.time()
        if L == 0: h_sa0, h_sa1 = bit_parallel_filter(I, O, A, inputs, outputs, gates_raw)
        else: h_sa0, h_sa1 = list(range(A)), list(range(A))
        timings["Filter"] += time.time() - t_filt

        t_enc = time.time()
        build_universal_machine(work_path, univ_aag)
        
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
        except: break
        timings["Encode"] += time.time() - t_enc

        t_sat = time.time()
        with Solver(name='g4', bootstrap_with=cnf.clauses) as s:
            miter_lit = cnf.output2lit[list(miter_aig.outputs)[0]]
            f0_lits = [cnf.input2lit[f"f0_{j}"] for j in range(A)]
            f1_lits = [cnf.input2lit[f"f1_{j}"] for j in range(A)]
            base = [-l for l in f0_lits] + [-l for l in f1_lits]
            
            s.conf_budget(5000) # Give it more budget since we want accuracy
            
            found_fault = False
            for i in range(A):
                if gates_raw[i].endswith(" 0 0") or gates_raw[i].endswith(" 1 1"):
                    continue
                if i in h_sa0:
                    if s.solve_limited(assumptions=base[:i] + [f0_lits[i]] + base[i+1:] + [miter_lit]) is False:
                        # SEVER ONE GATE AND INSTANTLY RESTART
                        lhs = gates_raw[i].split()[0]
                        gates_raw[i] = f"{lhs} 0 0"
                        found_fault = True
                        break 
                if i in h_sa1:
                    if s.solve_limited(assumptions=base[:A+i] + [f1_lits[i]] + base[A+i+1:] + [miter_lit]) is False:
                        # SEVER ONE GATE AND INSTANTLY RESTART
                        lhs = gates_raw[i].split()[0]
                        gates_raw[i] = f"{lhs} 1 1"
                        found_fault = True
                        break 
                        
        timings["SAT"] += time.time() - t_sat

        if found_fault:
            # Write modified circuit and trigger loop restart
            with open(work_path, 'w') as f:
                f.write(f"aag {M} {I} {L} {O} {A}\n")
                for x in inputs + latches + outputs + gates_raw: f.write(str(x)+'\n')
                sym_i = [s for s in symbols if s.startswith('i')]
                sym_l = [s for s in symbols if s.startswith('l')]
                sym_o = [s for s in symbols if s.startswith('o')]
                for s in sym_i + sym_l + sym_o: f.write(s + '\n')
                f.write("c\nAlg7 Iterative Surgery\n")
            
            # Use ABC to instantly clean up the dead logic before next loop
            run_abc_strash(work_path, work_path)
            circuit_changed = True
            total_removed += 1

    # Cleanup and Finalize
    if os.path.exists(univ_aag): os.remove(univ_aag)
    shutil.copy(work_path, output_path)
    os.remove(work_path)
        
    timings["Total"] = time.time() - t_start_total
    return orig_gates, orig_gates, count_reachable_gates(output_path), total_removed, timings
