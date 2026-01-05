import time
import csv
import os
import glob
import aiger
import aiger_cnf
from datetime import datetime
from pysat.solvers import Solver

# --- CONFIGURATION ---
BENCHMARK_FOLDER = 'benchmarks'
RESULTS_DIR = 'results'
TIMEOUT_SEC = 20.0

# LIST OF SOLVERS TO ATTEMPT
# We include Glucose, MiniSAT, MapleSAT, and CaDiCaL.
# The script will automatically skip ones that don't work on your laptop.
SOLVER_CANDIDATES = ['g3', 'g4', 'm22', 'maplechrono', 'cadical']

# 1. Setup
if not os.path.exists(RESULTS_DIR): 
    os.makedirs(RESULTS_DIR)

timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
csv_file = os.path.join(RESULTS_DIR, f"dataset_full_{timestamp}.csv")

# 2. Find files
circuit_files = glob.glob(os.path.join(BENCHMARK_FOLDER, "*.aag"))
if not circuit_files:
    print(f"[ERROR] No .aag files in {BENCHMARK_FOLDER}/. Run prepare_benchmarks.py first.")
    exit()

print(f"Found {len(circuit_files)} circuits. Solvers to try: {SOLVER_CANDIDATES}")

# 3. Processing
with open(csv_file, mode='w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(["Circuit", "Solver", "Wire_ID", "Time_Sec", "Status", "Label"])

    for c_file in circuit_files:
        c_name = os.path.basename(c_file)
        print(f"\n--- Processing Circuit: {c_name} ---")
        
        # Load Circuit (Once per circuit)
        try:
            circuit = aiger.load(c_file)
            cnf = aiger_cnf.aig2cnf(circuit)
            
            if hasattr(cnf, 'output_map'): out_map = cnf.output_map
            elif hasattr(cnf, 'outputs'): out_map = cnf.outputs
            else: out_map = cnf[2]
            wires = list(out_map.values())
        except Exception as e:
            print(f"  [SKIP] Load failed: {e}")
            continue

        # Try Every Solver in the list
        for solver_name in SOLVER_CANDIDATES:
            try:
                # INCREMENTAL MODE START: We create the solver ONCE here
                with Solver(name=solver_name, bootstrap_with=cnf.clauses) as s:
                    print(f"  > Testing {solver_name} (Incremental)...")
                    
                    for w in wires:
                        start = time.time()
                        
                        # ASSUMPTION-BASED SOLVE:
                        # We assume wire 'w' is True (1) just for this specific check.
                        # The solver learns from this but doesn't break the formula.
                        is_sat = s.solve(assumptions=[w])
                        
                        duration = time.time() - start
                        
                        if duration > TIMEOUT_SEC:
                            status = "TIMEOUT"
                            label = -1
                        else:
                            status = "SAT" if is_sat else "UNSAT"
                            label = 1 if is_sat else 0

                        writer.writerow([c_name, solver_name, w, f"{duration:.6f}", status, label])
            
            except Exception as e:
                # This catches "NoSuchSolverError" so the script continues!
                print(f"  [WARNING] Could not run '{solver_name}': {e}")
                continue

print(f"\n[SUCCESS] Data saved to {csv_file}")