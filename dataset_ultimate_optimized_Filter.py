import time
import csv
import os
import glob
import random
import aiger
import aiger_cnf
from datetime import datetime
from pysat.solvers import Solver

# --- CONFIGURATION ---
BENCHMARK_FOLDER = 'benchmarks'
RESULTS_DIR = 'results'
TIMEOUT_SEC = 20.0
SOLVER_CANDIDATES = ['glucose4'] 

# --- NEW: ROBUST SIMULATION FILTER ---
def run_simulation_filter(circuit, cnf_map, num_sims=16):
    """
    Uses the library's BUILT-IN simulator.
    Runs 'num_sims' random input vectors.
    Returns: A set of integer Lits (Wire IDs) that are NOT stuck-at-0.
    """
    active_wires = set()
    input_names = circuit.inputs
    
    # Run N random simulations
    for _ in range(num_sims):
        # 1. Create random inputs { 'i0': True, 'i1': False ... }
        sim_input = {i: random.choice([True, False]) for i in input_names}
        
        # 2. Run built-in simulation
        # FIX: The simulator returns a list of time steps. We take [0].
        # That step is a tuple (outputs, latches). We take [0] again to get outputs.
        # result_tuple = (outputs_dict, latches_dict)
        output_dict = circuit.simulate([sim_input])[0][0]
        
        # 3. Check results
        for out_name, val in output_dict.items():
            if val is True:
                # We need to find the Integer ID for this output name
                # We use the CNF map to translate Name -> Number
                if out_name in cnf_map:
                    lit = cnf_map[out_name]
                    active_wires.add(lit)
                    
    return active_wires

# --- MAIN SCRIPT ---

if __name__ == "__main__":
    if not os.path.exists(RESULTS_DIR): os.makedirs(RESULTS_DIR)
    
    csv_file = os.path.join(RESULTS_DIR, f"results_optimized_{datetime.now().strftime('%H-%M-%S')}.csv")

    circuit_files = glob.glob(os.path.join(BENCHMARK_FOLDER, "*.aag"))
    print(f"Found {len(circuit_files)} circuits. Solvers: {SOLVER_CANDIDATES}") 

    with open(csv_file, mode='w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Circuit", "Solver", "Wire_ID", "Time_Sec", "Status", "Method"])

        for c_file in circuit_files:
            c_name = os.path.basename(c_file)
            print(f"\n--- Processing: {c_name} ---")
            
            try:
                # 1. Load Circuit & CNF
                circuit = aiger.load(c_file)
                cnf = aiger_cnf.aig2cnf(circuit)
                
                # 2. Extract Wire IDs safely (Using output2lit)
                if hasattr(cnf, 'output2lit'):
                    out_map = cnf.output2lit
                elif hasattr(cnf, 'outputs'): 
                    out_map = cnf.outputs
                else: 
                    # Fallback for tuples
                    out_map = cnf[2]
                
                wires = list(out_map.values())
                print(f"    Total Output Wires: {len(wires)}")

                if len(wires) == 0:
                    print("    [WARNING] No outputs found to check. Skipping.")
                    continue

                # 3. Run Simulation Filter
                print("    > Running Simulation Filter...")
                start_sim = time.time()
                
                # Pass the circuit AND the map so we can translate names to numbers
                active_wires = run_simulation_filter(circuit, out_map)
                
                sim_time = time.time() - start_sim
                print(f"      [Filter] Found {len(active_wires)} active wires in {sim_time:.4f}s.")
                
                # Calculate how many are left to check
                remaining = [w for w in wires if w not in active_wires]
                print(f"      [Filter] Only {len(remaining)} wires remain for PySAT check.")

            except Exception as e:
                print(f"    [Error] {e}")
                # import traceback
                # traceback.print_exc() 
                continue

            # 4. Run Solvers on the REMAINING wires
            for solver_name in SOLVER_CANDIDATES:
                with Solver(name=solver_name, bootstrap_with=cnf.clauses) as s:
                    for w in wires:
                        
                        # OPTIMIZATION: SKIP if simulation already passed
                        if w in active_wires:
                            writer.writerow([c_name, solver_name, w, "0.000001", "SAT", "SIMULATION"])
                            continue 

                        # If we are here, Simulation returned 0 every time. It MIGHT be stuck.
                        start = time.time()
                        is_sat = s.solve(assumptions=[w])
                        duration = time.time() - start
                        
                        status = "SAT" if is_sat else "UNSAT (REDUNDANT)"
                        writer.writerow([c_name, solver_name, w, f"{duration:.6f}", status, "PYSAT"])
                        
    print(f"\n[SUCCESS] Results saved to: {csv_file}")