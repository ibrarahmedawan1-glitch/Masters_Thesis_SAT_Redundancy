import aiger
import aiger_cnf
from pysat.solvers import Solver

def run_naive_miter():
    print("[1] Loading Good and Faulty AIGs...")
    try:
        # Load the circuits
        c_good = aiger.load("test.aag")
        c_faulty = aiger.load("faulty.aag")
    except Exception as e:
        print(f"Failed to load files: {e}")
        return

    print("[2] Building the XOR Miter...")
    # In py-aiger, the '^' operator performs a bitwise XOR on the outputs!
    # This automatically combines the two circuits into a single Miter.
    miter_circuit = c_good ^ c_faulty
    
    # Get the name of the final output wire of the miter
    miter_output_name = list(miter_circuit.outputs)[0]

    print("[3] Translating to Tseitin CNF...")
    cnf = aiger_cnf.aig2cnf(miter_circuit)

    print("[4] Firing the SAT Solver (Glucose4)...")
    # We load the CNF clauses into the SAT solver
    with Solver(name='g4', bootstrap_with=cnf.clauses) as solver:
        # We ASSUME the miter output is True (1). 
        # "Can this fault ever cause a different output?"
        output_literal = cnf.output2lit[miter_output_name]
        
        is_testable = solver.solve(assumptions=[output_literal])

        print("\n--- ATPG RESULT ---")
        if is_testable:
            print("Status: SAT (TESTABLE)")
            print("The outputs are DIFFERENT. The fault was successfully detected.")
            # Bonus: We can actually ask the solver for the test vector!
            model = solver.get_model()
            print(f"Raw SAT Vector: {model}")
        else:
            print("Status: UNSAT (UNTESTABLE)")
            print("The outputs are IDENTICAL. This gate is REDUNDANT!")

if __name__ == "__main__":
    run_naive_miter()