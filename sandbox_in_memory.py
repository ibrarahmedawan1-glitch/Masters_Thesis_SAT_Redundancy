#!/usr/bin/env python3
"""
sandbox_in_memory.py
====================
Isolated validation of In-Memory Incremental SAT testing using Guarded Literals.
Proof of Concept for Master's Thesis V2 Hybrid Engine.
"""

import aiger
import aiger_cnf
from pysat.solvers import Glucose4

def build_toy_aig():
    """
    Constructs a tiny AIG: g = a AND b. 
    We will treat 'g' as the original gate, and 'y' as the physical wire we are faulting.
    """
    a = aiger.atom('a')
    b = aiger.atom('b')
    circ = a & b
    return circ.with_output('y')

def main():
    print("=== STEP 1: Build Toy AIG ===")
    aig = build_toy_aig()
    print(f"[INFO] Circuit created: y = a AND b")

    print("\n=== STEP 2: Convert to CNF ===")
    # Translate to CNF
    cnf = aiger_cnf.aig2cnf(aig)
    
    # Safely find the maximum variable index used by aiger_cnf
    max_base_var = max(abs(lit) for clause in cnf.clauses for lit in clause)
    print(f"[INFO] Base CNF generated with {len(cnf.clauses)} clauses.")
    print(f"[INFO] Maximum variable index used by aiger_cnf: {max_base_var}")

    # Extract the specific variable for our output wire 'y' using your library's API
    y_lit = cnf.output2lit['y']
    y_var = abs(y_lit) 
    g_var = y_var # In this toy circuit, the gate output IS the wire.
    print(f"[INFO] Mapped 'y' to DIMACS literal: {y_lit}, Variable: {y_var}")

    print("\n=== STEP 3: Initialize PySAT ===")
    solver = Glucose4()
    for clause in cnf.clauses:
        solver.add_clause(clause)
    print(f"[INFO] Solver loaded with base circuit.")

    print("\n=== STEP 4: Inject Guarded Fault Literal (k) ===")
    # We allocate k strictly OUTSIDE the aiger_cnf variable space
    k_var = max_base_var + 1
    print(f"[INFO] Allocated Guard Variable k = {k_var}")

    # Injecting the mathematical logic: y = ~k AND g
    guarded_clauses = [
        [k_var, -y_var],           # k -> y=0
        [-k_var, -y_var, g_var],   # ~k -> y follows g
        [-k_var, y_var, -g_var]    # ~k -> g follows y
    ]
    
    for clause in guarded_clauses:
        solver.add_clause(clause)
        print(f"  Injected Clause: {clause}")

    print("\n=== STEP 5: Execute In-Memory SAT Test ===")
    # If the AIG output is inverted, we must test the exact literal, not just the variable
    miter_diff_literal = y_lit 
    0
    # We turn ON the fault (k_var) and assert the Miter difference (miter_diff_literal)
    assumptions = [k_var, miter_diff_literal]
    print(f"[INFO] Testing SAT with assumptions: {assumptions}")
    
    is_sat = solver.solve(assumptions=assumptions)
    
    print("\n==============================")
    print("         FINAL RESULT         ")
    print("==============================")
    if is_sat:
        model = solver.get_model()
        print("[RESULT] SAT! A counterexample exists.")
        print("[CONCLUSION] This gate is NOT redundant. Do not remove it.")
        
        # Safely extract inputs using the local library API
        a_var = abs(cnf.input2lit['a'])
        b_var = abs(cnf.input2lit['b'])
        a_val = 1 if a_var in model else 0
        b_val = 1 if b_var in model else 0
        print(f"  Counterexample: a={a_val}, b={b_val} (This makes y=1, proving it isn't stuck at 0)")
    else:
        print("[RESULT] UNSAT! No counterexample exists.")
        print("[CONCLUSION] This gate IS REDUNDANT (Stuck-at-0 verified).")

    solver.delete()

if __name__ == "__main__":
    main()