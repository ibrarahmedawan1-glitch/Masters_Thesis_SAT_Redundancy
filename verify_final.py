import aiger
import aiger_cnf
import sys
from pysat.solvers import Solver

def main():
    orig_file = "dataset_benchmarks/fuzz_idem_1.aag"
    opt_file = "dataset_benchmarks/fuzz_idem_1.aag.alg8.aag"
    
    print(f"Loading Original: {orig_file}")
    print(f"Loading Optimized: {opt_file}")
    
    orig = aiger.load(orig_file)
    opt = aiger.load(opt_file)

    print("Building Formal SAT Miter...")
    outputs = list(orig.outputs)
    Mg = orig['o', {o: f"g_{o}" for o in outputs}]
    Mf = opt['o', {o: f"f_{o}" for o in outputs}]
    combined = Mg | Mf
    
    miter_expr = None
    for o in outputs:
        xor_gate = aiger.atom(f"g_{o}") ^ aiger.atom(f"f_{o}")
        miter_expr = xor_gate if miter_expr is None else miter_expr | xor_gate
        
    miter = combined >> miter_expr.aig
    cnf = aiger_cnf.aig2cnf(miter)
    
    print("Solving with Glucose4...")
    with Solver(name='g4', bootstrap_with=cnf.clauses) as s:
        miter_lit = cnf.output2lit[list(miter.outputs)[0]]
        is_sat = s.solve(assumptions=[miter_lit])
        
        if is_sat:
            print("❌ FAIL: The circuits are mathematically different.")
        else:
            print("✅ PASS: 100% Mathematically Equivalent (UNSAT).")

if __name__ == "__main__":
    main()