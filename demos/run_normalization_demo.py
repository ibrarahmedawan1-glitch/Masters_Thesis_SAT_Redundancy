import subprocess
import os
import re

# --- CONFIGURATION ---
ABC_PATH = "./abc/abc"
OUTPUT_DIR = "normalization_demo"
FILENAME = "bad_circuit"

def ensure_directory():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

def create_non_normalized_circuit():
    """
    Manually writes an ASCII AIG (.aag) that violates normalization rules.
    FIX: Includes INPUT definitions AND enforces SORTED gate logic.
    """
    aag_path = os.path.join(OUTPUT_DIR, f"{FILENAME}.aag")
    
    # --- CIRCUIT DEFINITION ---
    # Header: aag M I L O A
    # M=8 (Max Var), I=2 (Inputs), L=0, O=5 (Outputs), A=6 (Gates)
    header = "aag 8 2 0 5 6\n"
    
    # PART 1: Inputs (Must be listed!)
    # Input 1 = Literal 2
    # Input 2 = Literal 4
    inputs = "2\n4\n"
    
    # PART 2: Outputs (Literals 6, 8, 10, 12, 16)
    outputs = "6\n8\n10\n12\n16\n" 
    
    # PART 3: AND Gates (Format: LHS RHS1 RHS2)
    # CRITICAL RULE: RHS1 >= RHS2 (Largest literal first)
    
    # 1. Redundant AND (A & A)
    # Gate 6 = 2 & 2
    gate_1 = "6 2 2\n" 

    # 2. Constant Zero (A & !A)
    # Gate 8 = 3(!A) & 2(A).   (3 > 2, so this is valid)
    gate_2 = "8 3 2\n"

    # 3. Constant Zero Prop (A & 0)
    # Gate 10 = 2(A) & 0(False). (2 > 0, valid)
    gate_3 = "10 2 0\n"

    # 4. Constant One Prop (A & 1)
    # Gate 12 = 2(A) & 1(True).  (2 > 1, valid)
    gate_4 = "12 2 1\n"

    # 5. Structural Redundancy (Gate 14 and 16 are Identical)
    # Gate 14 = 4(B) & 2(A).   (4 > 2, valid)
    gate_5a = "14 4 2\n"
    # Gate 16 = 4(B) & 2(A).   (Duplicate)
    gate_5b = "16 4 2\n"

    content = header + inputs + outputs + gate_1 + gate_2 + gate_3 + gate_4 + gate_5a + gate_5b
    
    with open(aag_path, "w") as f:
        f.write(content)
    
    print(f"📝 Created Raw Circuit: {aag_path}")
    print(f"   - Gates written to file: 6")
    
    # DEBUG: Print the file content to terminal to verify
    print("-" * 20)
    print("File Content:")
    print(content.strip())
    print("-" * 20)
    
    return aag_path

def run_abc_normalization(file_path):
    """Runs ABC on the raw .aag file"""
    print("\n🏭 Running ABC Logic Synthesis...")
    
    # Command: Read -> Print Stats -> Quit
    # ABC applies structural hashing AUTOMATICALLY during 'read_aiger'
    cmd = f'{ABC_PATH} -c "read_aiger {file_path}; print_stats; quit"'
    
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    output = result.stdout
    print(output)
    
    # Parse results
    matches = re.findall(r"and\s*=\s*(\d+)", output)
    if len(matches) >= 1:
        abc_gates = int(matches[0])
        print("-" * 50)
        print(f"📊 COMPARISON:")
        print(f"   - Gates in .aag file:  6 (The raw messy logic)")
        print(f"   - Gates in ABC memory: {abc_gates} (After Loading)")
        
        if abc_gates < 6:
            print("\n✅ SUCCESS: ABC detected the redundancy immediately upon loading!")
            print("   (Structural Hashing rules were applied instantly during read)")
        else:
            print("\n❌ FAIL: ABC did not reduce the logic.")
    else:
        print("❌ ERROR: Could not parse ABC output. (Check 'Wrong input file format' error above)")

def main():
    ensure_directory()
    path = create_non_normalized_circuit()
    run_abc_normalization(path)

if __name__ == "__main__":
    main()