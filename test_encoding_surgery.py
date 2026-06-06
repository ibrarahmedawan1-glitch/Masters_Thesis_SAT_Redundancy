#!/usr/bin/env python3
"""
test_encoding_surgery.py
=============================================
The Ultimate AIGER Structural Hashing Engine.
The command-line bug is fixed.
"""

import sys
import os
import subprocess
import random

ABC_PATH = "./abc/abc"

def parse_aag(filepath):
    lines = []
    with open(filepath, 'r', encoding='ascii') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            if line == 'c': break  
            lines.append(line)
            
    header = lines[0].split()
    M, I, L, O, A = map(int, header[1:6])
    
    inputs = [int(lines[i]) for i in range(1, I + 1)]
    latches = [lines[1 + I + i] for i in range(L)]
    outputs = [int(lines[1 + I + L + i]) for i in range(O)]
    
    gates_raw = []
    gate_start_idx = 1 + I + L + O
    for i in range(A):
        gates_raw.append(list(map(int, lines[gate_start_idx + i].split())))
        
    return M, I, L, O, A, inputs, latches, outputs, gates_raw

def pure_python_forward_strash(M, I, L, O, A, inputs, latches, outputs, gates_raw, redundancies):
    print(f"\n[STRASH] Executing Full Canonical Structural Hash...")

    subst = {0: 0, 1: 1}
    for pi in inputs:
        subst[pi] = pi
        subst[pi^1] = pi^1
    for latch in latches:
        curr = int(latch.split()[0])
        subst[curr] = curr
        subst[curr^1] = curr^1
        
    for lhs, val in redundancies:
        c_lit = 0 if val == 0 else 1
        subst[lhs] = c_lit
        subst[lhs^1] = c_lit ^ 1

    def resolve(lit):
        seen = set()
        while lit in subst and subst[lit] != lit:
            if lit in seen: break 
            seen.add(lit)
            lit = subst[lit]
        return lit

    strash_table = {}
    unique_gates = [] 

    for old_lhs, r0, r1 in gates_raw:
        if old_lhs in subst: continue 
            
        e0 = resolve(r0)
        e1 = resolve(r1)
        
        res = None
        if e0 == 0 or e1 == 0: res = 0
        elif e0 == 1: res = e1
        elif e1 == 1: res = e0
        elif e0 == e1: res = e0
        elif e0 == (e1 ^ 1): res = 0
        
        if res is not None:
            subst[old_lhs] = res
            subst[old_lhs ^ 1] = res ^ 1
            continue

        if e0 < e1: e0, e1 = e1, e0
            
        key = (e0, e1)
        if key in strash_table:
            res = strash_table[key]
            subst[old_lhs] = res
            subst[old_lhs ^ 1] = res ^ 1
        else:
            strash_table[key] = old_lhs
            subst[old_lhs] = old_lhs
            subst[old_lhs ^ 1] = old_lhs ^ 1
            unique_gates.append((key, old_lhs))

    reachable_vars = set()
    stack = []
    
    resolved_outputs = [resolve(o) for o in outputs]
    for o in resolved_outputs:
        if o > 1: stack.append(o // 2)
            
    resolved_latches = []
    for latch in latches:
        curr, nxt = map(int, latch.split())
        r_nxt = resolve(nxt)
        resolved_latches.append((curr, r_nxt))
        if r_nxt > 1: stack.append(r_nxt // 2)

    gate_deps = {old_lhs // 2: key for key, old_lhs in unique_gates}

    while stack:
        var = stack.pop()
        if var in reachable_vars: continue
        reachable_vars.add(var)
        
        if var in gate_deps:
            r0, r1 = gate_deps[var]
            if r0 > 1: stack.append(r0 // 2)
            if r1 > 1: stack.append(r1 // 2)

    alive_gates = []
    for (e0, e1), old_lhs in unique_gates:
        if (old_lhs // 2) in reachable_vars:
            alive_gates.append(((e0, e1), old_lhs))
            
    alive_gates.sort(key=lambda x: x[1])

    final_gates = []
    final_subst = {0: 0, 1: 1}
    for pi in inputs:
        final_subst[pi] = pi
        final_subst[pi^1] = pi^1
    for curr, _ in resolved_latches:
        final_subst[curr] = curr
        final_subst[curr^1] = curr^1

    new_var_counter = I + L + 1 
    
    for (e0, e1), old_lhs in alive_gates:
        new_lhs = new_var_counter * 2
        final_subst[old_lhs] = new_lhs
        final_subst[old_lhs ^ 1] = new_lhs ^ 1
        
        f0 = final_subst[e0]
        f1 = final_subst[e1]
        if f0 < f1: f0, f1 = f1, f0
            
        final_gates.append([new_lhs, f0, f1])
        new_var_counter += 1

    final_out_list = [final_subst[o] for o in resolved_outputs]
    final_latch_list = [f"{curr} {final_subst[nxt]}" for curr, nxt in resolved_latches]

    new_A = len(final_gates)
    new_M = new_var_counter - 1
    
    print(f"[STRASH] Graph Canonicalized. New M: {new_M}, New A: {new_A}")
    return new_M, I, L, O, new_A, inputs, final_latch_list, final_out_list, final_gates

def main():
    target_file = "dataset_benchmarks/fuzz_idem_1.aag"
    if not os.path.exists(target_file):
        print(f"Error: {target_file} not found.")
        sys.exit(1)
        
    M, I, L, O, A, inputs, latches, outputs, gates_raw = parse_aag(target_file)
    print(f"--- INITIAL AIG ---")
    print(f"M={M}, I={I}, L={L}, O={O}, A={A}")
    
    random.seed(42) 
    test_targets = []
    for _ in range(10):
        g = random.choice(gates_raw)
        val = random.choice([0, 1])
        test_targets.append((g[0], val))
        
    M_new, I_new, L_new, O_new, A_new, in_new, la_new, out_new, gates_new = pure_python_forward_strash(
        M, I, L, O, A, inputs, latches, outputs, gates_raw, test_targets
    )
    
    test_out = "test_python_strash_out.aag"
    with open(test_out, 'w', encoding='ascii') as f:
        f.write(f"aag {M_new} {I_new} {L_new} {O_new} {A_new}\n")
        for x in in_new: f.write(f"{x}\n")
        for latch in la_new: f.write(f"{latch}\n")
        for x in out_new: f.write(f"{x}\n")
        for g in gates_new: f.write(f"{g[0]} {g[1]} {g[2]}\n")
        
    print(f"\n[FILE] Wrote PERFECTLY PURE, unannotated AAG to {test_out}")
    
    print("\n[TEST 1] Running ABC Strash (Checking Structural Integrity)...")
    
    # THE FIX: Changed 'read_aiger' to 'read' and 'write_aiger' to 'write'
    strash_cmd = f'{ABC_PATH} -c "read {test_out}; print_stats; strash; write final_out.aag"'
    
    result = subprocess.run(strash_cmd, shell=True, capture_output=True, text=True)
    
    if "Wrong input file format" in result.stdout or result.returncode != 0:
        print("❌ FAILED. ABC rejected the file.")
        print("STDOUT:\n", result.stdout)
        sys.exit(1)
        
    print("✅ PASSED! ABC loaded the ASCII file successfully!")
    print(result.stdout.strip())
    print("=======================================================")

if __name__ == "__main__":
    main()