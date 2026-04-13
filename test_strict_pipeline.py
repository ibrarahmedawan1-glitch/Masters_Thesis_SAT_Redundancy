import os
from generators import generate_random_circuit
from verifier import verify_equivalence
import optimizer_alg2

def run_test():
    print("--- STRICT PIPELINE VALIDATION ---")
    test_file = "test_valid.aag"
    out_file = "test_opt.aag"
    
    # Use 'none' to generate a mathematically valid, non-trivial circuit
    generate_random_circuit(test_file, inputs=6, gates=20, injection_mode='none')
    
    print(f"[1] Circuit Generated: {test_file}")
    print("[2] Running Algorithm 2 (Structural Sharing)...")
    
    orig, _, final, _, _, rem, dur = optimizer_alg2.solve_circuit(test_file, out_file)
    
    print(f"    Original Gates : {orig}")
    print(f"    Gates Removed  : {rem}")
    print(f"    Final Gates    : {final}")
    print(f"    Runtime        : {dur:.2f}s")
    
    print("[3] Running Formal Equivalence Check...")
    passed = verify_equivalence(test_file, out_file)
    print(f"    Verification   : {'PASS' if passed else 'FAIL'}")

    for f in [test_file, out_file]:
        if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    run_test()