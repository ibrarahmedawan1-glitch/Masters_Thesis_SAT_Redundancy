import subprocess
import os
import re

# --- CONFIGURATION ---
ABC_PATH = "./abc/abc"
OUTPUT_DIR = "bench_demo"
FILENAME = "redundant_logic"

def ensure_directory():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

def create_redundant_bench():
    """
    Creates a .bench file. This is safer than .aag because 
    ABC handles the parsing much more robustly.
    """
    bench_path = os.path.join(OUTPUT_DIR, f"{FILENAME}.bench")
    
    # We write logic that clearly violates the rules:
    # 1. Idempotence: g1 = AND(A, A)  ---> Should become A
    # 2. Duplicate:   g2 = AND(A, B)
    #                 g3 = AND(A, B)  ---> Should merge with g2
    
    content = """
# Thesis Demo
INPUT(A)
INPUT(B)
OUTPUT(g1)
OUTPUT(g2)
OUTPUT(g3)

# Redundancy 1: A & A
g1 = AND(A, A)

# Redundancy 2: Duplicate Gates
g2 = AND(A, B)
g3 = AND(A, B)
"""
    with open(bench_path, "w") as f:
        f.write(content.strip())
    
    return bench_path

def run_abc_check(file_path):
    print("\n🏭 Running ABC Logic Synthesis on BENCH file...")
    
    # 1. read_bench: Load the file
    # 2. strash: Apply Structural Hashing (The Normalization)
    # 3. print_stats: See the reduction
    cmd = f'{ABC_PATH} -c "read_bench {file_path}; strash; print_stats; quit"'
    
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    output = result.stdout
    print(output)
    
    # We look for "and = X"
    matches = re.findall(r"and\s*=\s*(\d+)", output)
    if matches:
        final_gates = int(matches[-1]) # Get the last stat printed
        print(f"📊 Final Gate Count: {final_gates}")
        
        if final_gates == 1:
            print("✅ SUCCESS: Structural Hashing worked!")
            print("   - 'A & A' was removed.")
            print("   - 'Duplicate A & B' was merged.")
            print("   - Only 1 real gate remains.")
        else:
            print("⚠️ Logic was not fully reduced.")

def main():
    ensure_directory()
    path = create_redundant_bench()
    run_abc_check(path)

if __name__ == "__main__":
    main()