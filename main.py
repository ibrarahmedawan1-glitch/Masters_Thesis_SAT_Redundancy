import os
import csv
import shutil
import glob
from datetime import datetime
from generators import generate_random_circuit, generate_ladder_circuit, generate_parallel_circuit
from optimizer import solve_circuit
from verifier import verify_equivalence

# 1. Setup Directories and Timestamps
DATASET_DIR = "dataset_benchmarks"
RESULTS_BASE_DIR = "results_optimized"

# Get current date and time (e.g., "2023-10-27_15-30-00")
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

# Create a unique folder for THIS run's circuits
CURRENT_RUN_DIR = os.path.join(RESULTS_BASE_DIR, f"circuits_{timestamp}")
os.makedirs(CURRENT_RUN_DIR, exist_ok=True)

# Create the unique CSV filename
REPORT_FILE = os.path.join(RESULTS_BASE_DIR, f"thesis_results_{timestamp}.csv")

# 2. Reset Dataset Folder (Keep this fresh)
if os.path.exists(DATASET_DIR): shutil.rmtree(DATASET_DIR)
os.makedirs(DATASET_DIR)

def normalize_names(file_path):
    try:
        with open(file_path, 'r', errors='ignore') as f: lines = f.readlines()
        if not lines or not lines[0].startswith('aag'): return
        header = lines[0].strip().split()
        try: I, L, O, A = int(header[2]), int(header[3]), int(header[4]), int(header[5])
        except: return
        logic_end = 1 + I + L + O + A
        if len(lines) < logic_end: return
        
        with open(file_path, 'w') as f:
            for i in range(logic_end): f.write(lines[i].strip() + '\n')
            for k in range(I): f.write(f"i{k} i{k}\n")
            for k in range(L): f.write(f"l{k} l{k}\n")
            for k in range(O): f.write(f"o{k} o{k}\n")
            f.write("c\nNormalized\n")
    except: pass

print(f"--- THESIS PIPELINE STARTED [{timestamp}] ---")
print(f"    Saving report to: {REPORT_FILE}")

print("[1] Generating Test Circuits...")
generate_ladder_circuit(f"{DATASET_DIR}/ladder_logic.aag")
generate_parallel_circuit(f"{DATASET_DIR}/parallel_struct.aag")
generate_random_circuit(f"{DATASET_DIR}/random_stuck.aag", injection_mode='stuck')
generate_random_circuit(f"{DATASET_DIR}/random_idempotent.aag", injection_mode='idempotent')

for i in range(1, 6): 
    generate_random_circuit(f"{DATASET_DIR}/random_pure_{i}.aag", injection_mode='none')

print("[2] Loading ISCAS Benchmarks...")
if os.path.exists("benchmarks"):
    for f in glob.glob("benchmarks/*.aag"): 
        shutil.copy(f, DATASET_DIR)
else:
    print("WARNING: 'benchmarks' folder not found. Skipping ISCAS.")

print("[3] Normalizing Dataset...")
for f in glob.glob(f"{DATASET_DIR}/*.aag"): normalize_names(f)

print("[4] Running Engine...")
stats = []

for f_path in sorted(glob.glob(f"{DATASET_DIR}/*.aag")):
    name = os.path.basename(f_path)
    opt_path = f"{CURRENT_RUN_DIR}/{name}"
    
    category = "Benchmark"
    if "random" in name: 
        if "pure" in name: category = "Pure_Random"
        elif "stuck" in name: category = "Injected_Stuck"
        elif "idempotent" in name: category = "Injected_Idem"
    elif "ladder" in name: category = "Structural_Ladder"
    elif "parallel" in name: category = "Structural_Parallel"
    
    print(f"    Processing {name:<20}...", end=" ")
    try:
        orig, abc_g, final, fuzz, sat_c, removed, dur = solve_circuit(f_path, opt_path)
        is_equiv = verify_equivalence(f_path, opt_path)
        status = "PASS" if is_equiv else "FAIL"
        
        red_total = ((orig - final)/orig * 100) if orig > 0 else 0.0
        print(f"Removed {removed}. Verify: {status}. Reduction: {red_total:.2f}%")
        
        red_abc = ((orig - abc_g)/orig * 100) if orig > 0 else 0.0
        
        # ADDED 'removed' to the CSV row
        stats.append([name, category, orig, abc_g, final, removed, f"{red_abc:.2f}%", f"{red_total:.2f}%", fuzz, sat_c, f"{dur:.4f}", status])
    except Exception as e:
        print(f"ERROR: {e}")
        stats.append([name, category, 0, 0, 0, 0, "ERR", "ERR", 0, 0, "0", "ERROR"])

# UPDATED Header with 'Outputs_Removed'
with open(REPORT_FILE, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Circuit", "Type", "Original", "After_Strash", "Final", "Outputs_Removed", "Strash_Red%", "Total_Red%", "Fuzz_Filt", "SAT_Chk", "Time", "Verify"])
    writer.writerows(stats)

print(f"\n[DONE] Saved report to {REPORT_FILE}")