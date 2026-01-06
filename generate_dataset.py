import time
import csv
import os
import glob
import aiger
import aiger_cnf
from datetime import datetime
from pysat.solvers import Solver
from pysat.examples.musx import MUSX
from pysat.formula import CNF

# --- CONFIGURATION ---
BENCHMARK_FOLDER = 'benchmarks'
RESULTS_DIR = 'results'
TIMEOUT_SEC = 20.0

# THESIS SOLVER LIST
# We include specific versions to ensure stability.
SOLVER_CANDIDATES = [
    'minisat22',    # Baseline
    'glucose3',     # Old Standard
    'glucose4',     # New Standard
    'maplechrono',  # Smart Branching
    'cadical153',   # Modern In-processing
    'lingeling',    # Competition Winner
    'mergesat3'     # Hybrid
]

# --- HELPER FUNCTIONS ---

def analyze_conflict(cnf_clauses, faulty_wire_id):
    """
    Calculates the Size of the Minimal Unsatisfiable Set (MUS).
    Returns 0 if no conflict found or if calculation fails.
    """
    try:
        formula = CNF()
        formula.clauses = [c[:] for c in cnf_clauses] # Deep copy
        formula.append([faulty_wire_id]) # Add the conflict assumption
        
        ms = MUSX(formula, verbosity=0)
        mus_indices = ms.compute()
        
        return len(mus_indices) if mus_indices else 0
    except:
        return 0

# --- MAIN SCRIPT ---

if __name__ == "__main__":
    # 1. Setup Directories
    if not os.path.exists(RESULTS_DIR): 
        os.makedirs(RESULTS_DIR)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    csv_file = os.path.join(RESULTS_DIR, f"dataset_ultimate_{timestamp}.csv")

    # 2. Find Benchmarks
    circuit_files = glob.glob(os.path.join(BENCHMARK_FOLDER, "*.aag"))
    if not circuit_files:
        print(f"[ERROR] No .aag files found in '{BENCHMARK_FOLDER}/'")
        print("Please ensure you have run your 'prepare_benchmarks.py' script first.")
        exit()

    print(f"Found {len(circuit_files)} circuits.")
    print(f"Solvers to try: {SOLVER_CANDIDATES}") 

    # 3. Start Processing
    with open(csv_file, mode='w', newline='') as f:
        writer = csv.writer(f)
        # Header for your thesis data
        writer.writerow(["Circuit", "Solver", "Wire_ID", "Time_Sec", "Status", "Label", "MUS_Size"])

        for c_file in circuit_files:
            c_name = os.path.basename(c_file)
            print(f"\n--- Processing Circuit: {c_name} ---")
            
            # Load Circuit (Once per circuit)
            try:
                circuit = aiger.load(c_file)
                cnf = aiger_cnf.aig2cnf(circuit)
                
                # Extract output wires safely
                if hasattr(cnf, 'output_map'): out_map = cnf.output_map
                elif hasattr(cnf, 'outputs'): out_map = cnf.outputs
                else: out_map = cnf[2]
                wires = list(out_map.values())
                
                print(f"    (Circuit has {len(wires)} output wires to check)")
                
            except Exception as e:
                print(f"  [SKIP] Critical Load Error for {c_name}: {e}")
                continue

            # Loop through every solver
            for solver_name in SOLVER_CANDIDATES:
                try:
                    # Incremental Solver Initialization
                    with Solver(name=solver_name, bootstrap_with=cnf.clauses) as s:
                        print(f"  > Testing {solver_name}...")
                        
                        for w in wires:
                            start = time.time()
                            
                            # THE CORE CHECK: Can this wire be True?
                            # If solve() returns False, the wire is stuck (Redundant)
                            is_sat = s.solve(assumptions=[w])
                            
                            duration = time.time() - start
                            
                            mus_size = 0 # Default value
                            
                            if duration > TIMEOUT_SEC:
                                status = "TIMEOUT"
                                label = -1
                            else:
                                if is_sat:
                                    status = "SAT"
                                    label = 1
                                else:
                                    status = "UNSAT"
                                    label = 0
                                    # OPTIONAL: Uncomment below to enable deep analysis
                                    # This slows down the script but gives you MUS data
                                    # mus_size = analyze_conflict(cnf.clauses, w)

                            writer.writerow([c_name, solver_name, w, f"{duration:.6f}", status, label, mus_size])
                            
                except Exception as e:
                    # This handles if a specific solver (like mergesat) crashes on WSL
                    print(f"  [WARNING] Solver '{solver_name}' failed to start or crashed: {e}")
                    continue

    print(f"\n[SUCCESS] Dataset generated at: {csv_file}")