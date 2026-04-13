import os
import csv
import shutil
import glob
from datetime import datetime
from generators import generate_random_circuit, generate_ladder_circuit, generate_parallel_circuit
from optimizer_alg1 import solve_circuit
from verifier import verify_equivalence

# 1. Setup Directories
DATASET_DIR = "dataset_benchmarks"
RESULTS_BASE_DIR = "results_optimized"
RUN_SUBDIR = "latest_run" 
CURRENT_RUN_DIR = os.path.join(RESULTS_BASE_DIR, RUN_SUBDIR)

timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
REPORT_FILE = os.path.join(RESULTS_BASE_DIR, f"thesis_results_ALG1_NAIVE_{timestamp}.csv")

if os.path.exists(DATASET_DIR): shutil.rmtree(DATASET_DIR)
os.makedirs(DATASET_DIR)
if os.path.exists(CURRENT_RUN_DIR): shutil.rmtree(CURRENT_RUN_DIR)
os.makedirs(CURRENT_RUN_DIR)

def normalize_names(file_path):
    """Ensures AIGER files have correct headers and symbol tables."""
    try:
        with open(file_path, 'r', errors='ignore') as f: lines = f.readlines()
        if not lines or not lines[0].startswith('aag'): return
        header = lines[0].strip().split()
        I, L, O, A = int(header[2]), int(header[3]), int(header[4]), int(header[5])
        logic_end = 1 + I + L + O + A
        
        with open(file_path, 'w') as f:
            for i in range(min(len(lines), logic_end)): 
                f.write(lines[i].strip() + '\n')
            for k in range(I): f.write(f"i{k} pi_{k}\n")
            for k in range(O): f.write(f"o{k} po_{k}\n")
            f.write("c\nNormalized\n")
    except Exception as e:
        print(f"Normalization failed for {file_path}: {e}")

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
    print("WARNING: 'benchmarks' folder not found.")

print("[3] Normalizing Dataset...")
for f in sorted(glob.glob(f"{DATASET_DIR}/*.aag")): 
    normalize_names(f)

print("[4] Running Engine ...")
stats = []

for f_path in sorted(glob.glob(f"{DATASET_DIR}/*.aag")):
    name = os.path.basename(f_path)
    opt_path = os.path.join(CURRENT_RUN_DIR, name)
    
    category = "Benchmark"
    if "random" in name: 
        if "pure" in name: category = "Pure_Random"
        elif "stuck" in name: category = "Injected_Stuck"
        elif "idempotent" in name: category = "Injected_Idem"
    elif "ladder" in name: category = "Structural_Ladder"
    elif "parallel" in name: category = "Structural_Parallel"
    
    print(f"    Processing {name:<20}...", end=" ", flush=True)
    try:
        # ALGORITHM 1 CALL
        orig, abc_g, final, fuzz, sat_c, removed, dur = solve_circuit(f_path, opt_path)
        
        is_equiv = verify_equivalence(f_path, opt_path)
        status = "PASS" if is_equiv else "FAIL"
        
        red_total = ((orig - final)/orig * 100) if orig > 0 else 0.0
        print(f"Removed {removed}. Verify: {status}. Time: {dur:.2f}s")
        
        stats.append([name, category, orig, final, removed, f"{red_total:.2f}%", f"{dur:.4f}", status])
        
    except KeyboardInterrupt:
        # CLEANLY HANDLE CTRL+C TO SKIP THE FILE
        print(f"^C Skipped. Verify: SKIPPED. Time: 0.00s")
        stats.append([name, category, 0, 0, 0, "SKIPPED", "0.00", "SKIPPED"])
        continue
        
    except Exception as e:
        print(f"ERROR: {e}")
        stats.append([name, category, 0, 0, 0, "ERR", "0", "ERROR"])

with open(REPORT_FILE, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Circuit", "Type", "Original_Gates", "Final_Gates", "Gates_Removed", "Total_Red%", "Time(s)", "Verify"])
    writer.writerows(stats)

print(f"\n[DONE] Saved report to {REPORT_FILE}")