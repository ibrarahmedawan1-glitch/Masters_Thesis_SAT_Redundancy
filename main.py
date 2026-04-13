import os
import csv
import shutil
import glob          
import random
import time
import importlib
from datetime import datetime
from generators import generate_random_circuit, generate_ladder_circuit, generate_parallel_circuit
from verifier import verify_equivalence

DATASET_DIR = "dataset_benchmarks"
RESULTS_BASE_DIR = "results_optimized"
RUN_SUBDIR = "latest_run" 
CURRENT_RUN_DIR = os.path.join(RESULTS_BASE_DIR, RUN_SUBDIR)

def setup_directories():
    if os.path.exists(DATASET_DIR): shutil.rmtree(DATASET_DIR)
    os.makedirs(DATASET_DIR)
    if os.path.exists(CURRENT_RUN_DIR): shutil.rmtree(CURRENT_RUN_DIR)
    os.makedirs(CURRENT_RUN_DIR)

def normalize_names(file_path):
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
    except Exception as e: pass

def select_optimizer():
    """Interactive menu to route to the correct algorithm file."""
    print("\n" + "="*60)
    print("   SELECT OPTIMIZATION ALGORITHM ENGINE")
    print("="*60)
    print(" 1: Alg 1 - Naive SAT Miter (Slowest, Baseline)")
    print(" 2: Alg 2 - Structural Universal Machine")
    print(" 3: Alg 3 - Incremental ATPG (Base)")
    print(" 4: Alg 3 - SAF Batch Injection")
    print(" 5: Alg 3 - Simulation Filter + Incremental (Fastest)")
    print(" 6: Alg 3 - Budget/Timeout with Cadical")
    print(" 7: Alg 7 - Sim Filter + Iterative Surgery (100% Accurate)")
    print("="*60)
    
    choice = input("Enter choice (1-7): ").strip()
    mapping = {
        "1": "optimizer_alg1",
        "2": "optimizer_alg2",
        "3": "optimizer_alg3",
        "4": "optimizer_alg3_saf",
        "5": "optimizer_alg3_sim",
        "6": "optimizer_alg3_timeout_cadical",
        "7": "optimizer_alg7_iterative" # <--- ADD THIS
    }
    
    if choice not in mapping:
        print("Invalid choice. Defaulting to 5 (Alg 3 Sim).")
        return mapping["5"], "5"
    return mapping[choice], choice

if __name__ == "__main__":
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    setup_directories()
    
    # --- INTERACTIVE SELECTION ---
    algo_module_name, algo_id = select_optimizer()
    print(f"\n[+] Loading Engine: {algo_module_name}.py")
    
    # Dynamically load the chosen python file
    optimizer = importlib.import_module(algo_module_name)
    
    REPORT_FILE = os.path.join(RESULTS_BASE_DIR, f"thesis_results_ALG{algo_id}_{timestamp}.csv")

    print(f"\n--- THESIS PIPELINE STARTED [{timestamp}] ---")
    print(f"    Saving report to: {REPORT_FILE}")

    # --- DATASET GENERATION (COMMERCIAL SCALE) ---
    print("\n[1] Generating Massive Test Dataset (AIGFuzz Scale)...")
    generate_ladder_circuit(f"{DATASET_DIR}/ladder_logic.aag", depth=100)
    generate_parallel_circuit(f"{DATASET_DIR}/parallel_struct.aag", inputs=10, gates=50)

    print("    Generating 50 Stuck-at circuits...")
    for i in range(50):
        generate_random_circuit(f"{DATASET_DIR}/fuzz_stuck_{i}.aag", inputs=random.randint(10, 40), gates=random.randint(100, 1500), injection_mode='stuck')

    print("    Generating 50 Idempotent circuits...")
    for i in range(50):
        generate_random_circuit(f"{DATASET_DIR}/fuzz_idem_{i}.aag", inputs=random.randint(10, 40), gates=random.randint(100, 1500), injection_mode='idempotent')

    print("    Generating 100 Pure Random circuits...")
    for i in range(100):
        generate_random_circuit(f"{DATASET_DIR}/fuzz_pure_{i}.aag", inputs=random.randint(10, 40), gates=random.randint(100, 1500), injection_mode='none')
    print("Done.")

    print("\n[2] Loading ISCAS Benchmarks...")
    if os.path.exists("benchmarks"):
        for f in glob.glob("benchmarks/*.aag"): shutil.copy(f, DATASET_DIR)

    print("\n[3] Normalizing Dataset...")
    for f in sorted(glob.glob(f"{DATASET_DIR}/*.aag")): normalize_names(f)

    # --- EXECUTION ENGINE ---
    print(f"\n[4] Running Engine ({algo_module_name})...")
    stats = []

    for f_path in sorted(glob.glob(f"{DATASET_DIR}/*.aag")):
        name = os.path.basename(f_path)
        opt_path = os.path.join(CURRENT_RUN_DIR, name)
        
        category = "Benchmark"
        if "fuzz" in name: 
            if "pure" in name: category = "Pure_Random"
            elif "stuck" in name: category = "Injected_Stuck"
            elif "idem" in name: category = "Injected_Idem"
        elif "ladder" in name: category = "Structural_Ladder"
        elif "parallel" in name: category = "Structural_Parallel"
        
        print(f"    Processing {name:<25}...", end=" ", flush=True)
        try:
            # Handle the different return signatures dynamically
            if algo_id in ["5", "7"]:
                orig, _, final, removed, timings = optimizer.solve_circuit(f_path, opt_path)
            else:
                orig, _, final, _, _, removed, dur = optimizer.solve_circuit(f_path, opt_path)
                # Synthesize the timings dictionary for algorithms that don't track deep telemetry
                timings = {"Parse": 0.0, "Filter": 0.0, "Encode": 0.0, "SAT": 0.0, "Total": dur}
            
            print(f"SAT Done. Verifying...", end=" ", flush=True)
            status, cec_time = verify_equivalence(f_path, opt_path)
            
            red_total = ((orig - final)/orig * 100) if orig > 0 else 0.0
            print(f"Removed: {removed}. Status: {status}. SAT: {timings['Total']:.2f}s | CEC: {cec_time:.2f}s")
            
            stats.append([
                name, category, orig, final, removed, f"{red_total:.2f}%", 
                f"{timings['Parse']:.4f}", f"{timings['Filter']:.4f}", 
                f"{timings['Encode']:.4f}", f"{timings['SAT']:.4f}", 
                f"{cec_time:.4f}", f"{timings['Total']:.4f}", status
            ])
            
        except KeyboardInterrupt:
            print(f"^C Skipped. Verify: SKIPPED.")
            stats.append([name, category, 0, 0, 0, "SKIPPED", "0", "0", "0", "0", "0", "0", "SKIPPED"])
            continue
        except Exception as e:
            print(f"ERROR: {e}")
            stats.append([name, category, 0, 0, 0, "ERR", "0", "0", "0", "0", "0", "0", "ERROR"])

    with open(REPORT_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Circuit", "Type", "Original_Gates", "Final_Gates", "Gates_Removed", "Total_Red%", 
            "T_Parse(s)", "T_Filter(s)", "T_Encode(s)", "T_SAT(s)", "T_CEC(s)", "T_Total(s)", "Verify"
        ])
        writer.writerows(stats)

    print(f"\n[DONE] Saved report to {REPORT_FILE}")