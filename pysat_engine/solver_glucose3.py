#first file for thesis for c17 chipproject with glucose3 solver 05012026 




import time
import csv
import os
import aiger
import aiger_cnf
from datetime import datetime
from pysat.solvers import Glucose3

# --- CONFIGURATION ---
CIRCUIT_FILE = 'c17.aag'
SOLVER_NAME = 'Glucose3'  # We record this so we can compare solvers later
RESULTS_DIR = 'results'

# 1. Setup the Data Collection (The CSV)
# Create the folder if it doesn't exist
if not os.path.exists(RESULTS_DIR):
    os.makedirs(RESULTS_DIR)

# Generate a unique filename based on time (e.g., benchmark_2023-10-27_14-30.csv)
timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
csv_filename = os.path.join(RESULTS_DIR, f"benchmark_{timestamp_str}.csv")

print(f"Loading {CIRCUIT_FILE}...")
circuit = aiger.load(CIRCUIT_FILE)
cnf = aiger_cnf.aig2cnf(circuit)

# 2. Get the Wire Mapping
if hasattr(cnf, 'output_map'):
    out_map = cnf.output_map
elif hasattr(cnf, 'outputs'):
    out_map = cnf.outputs
else:
    out_map = cnf[2]

output_ids = list(out_map.values())
total_wires = len(output_ids)

print(f"Starting analysis of {total_wires} wires. Logging to: {csv_filename}")

# 3. Open CSV and Write Header
with open(csv_filename, mode='w', newline='') as file:
    writer = csv.writer(file)
    
    # THE HEADER: These are the columns for your future AI Training Data
    # 1. Metadata (When/What)
    # 2. Features (Wire ID - later you will add 'Depth', 'Fan-in' here)
    # 3. Label (Result: SAT/UNSAT)
    # 4. Performance (Time)
    writer.writerow(["Timestamp", "Circuit_Name", "Solver_Library", "Wire_ID", "Time_Sec", "Result_Status", "Result_Binary"])

    # 4. The Experiment Loop
    for i, wire_id in enumerate(output_ids):
        # A. Setup Solver
        solver = Glucose3()
        solver.append_formula(cnf.clauses)
        
        # B. Measure Time
        start_time = time.time()
        is_sat = solver.solve(assumptions=[wire_id])
        end_time = time.time()
        duration = end_time - start_time
        
        # C. Process Result
        status = "SAT" if is_sat else "UNSAT"
        result_binary = 1 if is_sat else 0  # 1=Reachable, 0=Redundant (Useful for ML)
        
        # D. Log to CSV
        current_time = datetime.now().strftime("%H:%M:%S")
        writer.writerow([current_time, CIRCUIT_FILE, SOLVER_NAME, wire_id, f"{duration:.6f}", status, result_binary])
        
        # E. Print progress to screen (so you know it's working)
        print(f"Wire {wire_id:<4} | {status:<5} | {duration:.6f}s")
        
        solver.delete()

print(f"\n[SUCCESS] Data saved to {csv_filename}")