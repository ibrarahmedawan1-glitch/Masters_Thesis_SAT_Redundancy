import time
import csv
import os
import aiger
import aiger_cnf
from datetime import datetime
from pysat.solvers import Glucose3

# --- CONFIGURATION ---
CIRCUIT_FILE = 'c17.aag'
SOLVER_NAME = 'Glucose3'
RESULTS_DIR = 'results'

# 1. Check if the circuit file actually exists
if not os.path.exists(CIRCUIT_FILE):
    print(f"[ERROR] Could not find file: {CIRCUIT_FILE}")
    print("Did you run the yosys command to generate it?")
    exit(1)

# 2. Setup the Data Collection (The CSV)
if not os.path.exists(RESULTS_DIR):
    os.makedirs(RESULTS_DIR)

timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
csv_filename = os.path.join(RESULTS_DIR, f"benchmark_{timestamp_str}.csv")

print(f"Loading {CIRCUIT_FILE}...")
circuit = aiger.load(CIRCUIT_FILE)
cnf = aiger_cnf.aig2cnf(circuit)

# 3. Get the Wire Mapping
if hasattr(cnf, 'output_map'):
    out_map = cnf.output_map
elif hasattr(cnf, 'outputs'):
    out_map = cnf.outputs
else:
    out_map = cnf[2]

output_ids = list(out_map.values())
total_wires = len(output_ids)

print(f"Starting analysis of {total_wires} output wires.")
print(f"Logging to: {csv_filename}")

# 4. Open CSV and Write Header
with open(csv_filename, mode='w', newline='') as file:
    writer = csv.writer(file)
    
    # Header Columns
    writer.writerow(["Timestamp", "Circuit_Name", "Solver_Library", "Wire_ID", "Time_Sec", "Result_Status", "Result_Binary"])

    # 5. The Experiment Loop
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
        result_binary = 1 if is_sat else 0
        
        # D. Log to CSV
        current_time = datetime.now().strftime("%H:%M:%S")
        writer.writerow([current_time, CIRCUIT_FILE, SOLVER_NAME, wire_id, f"{duration:.6f}", status, result_binary])
        
        # E. Print progress to screen
        print(f"Wire {wire_id:<4} | {status:<5} | {duration:.6f}s")
        
        solver.delete()

print(f"\n[SUCCESS] Data saved to {csv_filename}")