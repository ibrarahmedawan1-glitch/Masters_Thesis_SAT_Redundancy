import aiger
import aiger_cnf
from pysat.solvers import Solver
from optimizer_alg3_saf import build_universal_faulty_machine, parse_aag
import os

def run_unit_test():
    print("\n--- 🛠️ RUNNING FORMAL EQUIVALENCE UNIT TEST (V3) ---")
    
    # 1. Create a tiny 2-gate circuit: OUT = (A AND B) AND A
    a = aiger.atom('in_A')
    b = aiger.atom('in_B')
    expr = (a & b) & a
    
    orig_file = "debug_orig.aag"
    univ_file = "debug_univ.aag"
    
    # FIX: Use the explicit aiger.AIG object to avoid 'BoolExpr' attribute errors
    with open(orig_file, 'w') as f:
        f.write(str(expr.aig))
        
    print("[1] Generated tiny test circuit (debug_orig.aag).")
    
    # 2. Run the Universal Faulty Machine builder (The Dense Mapper)
    try:
        build_universal_faulty_machine(orig_file, univ_file)
        print("[2] Successfully executed dense variable mapping.")
    except Exception as e:
        print(f"❌ FAILED: Python crashed during mapping: {e}")
        return

    # 3. Load both back into memory to compare them
    orig_aig = aiger.load(orig_file)
    univ_aig = aiger.load(univ_file)
    
    # 4. Tie all fault pins to 0 (False)
    # This is the "Control Case" - the circuit SHOULD be identical to original
    M, I, L, O, A, _, _, _, _ = parse_aag(orig_file)
    fault_assignments = {}
    for i in range(A):
        fault_assignments[f"fault_sa0_{i}"] = False
        fault_assignments[f"fault_sa1_{i}"] = False
        
    print(f"[3] Tying all {2*A} fault pins to 0 (Normal Operation Mode)...")
    tied_univ = aiger.source(fault_assignments) >> univ_aig
    
    # 5. Build the Miter (XOR of the two outputs)
    # We rename outputs to avoid name collisions in the graph merge
    orig_m = orig_aig['o', {list(orig_aig.outputs)[0]: 'out_orig'}]
    univ_m = tied_univ['o', {list(tied_univ.outputs)[0]: 'out_univ'}]
    
    miter_aig = (orig_m | univ_m) >> (aiger.atom('out_orig') ^ aiger.atom('out_univ')).aig
    
    print("[4] Booting SAT Solver to check structural integrity...")
    cnf = aiger_cnf.aig2cnf(miter_aig)
    
    with Solver(name='g4', bootstrap_with=cnf.clauses) as solver:
        # Get the literal for the miter output
        miter_out = list(miter_aig.outputs)[0]
        out_lit = cnf.output2lit[miter_out]
        
        # We ask: "Is it possible for out_orig != out_univ?"
        if solver.solve(assumptions=[out_lit]):
            print("\n❌ FAILED: The SAT solver found a difference!")
            print("Encoding logic is mathematically broken.")
        else:
            print("\n✅ PASSED: Structural Integrity Verified.")
            print("The Universal Machine is identical to the original when fault pins are 0.")

    # 6. Cleanup
    for f in [orig_file, univ_file]:
        if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    run_unit_test()