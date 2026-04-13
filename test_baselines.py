import os
from generators import generate_random_circuit
from verifier import verify_equivalence
import optimizer_alg1
import optimizer_alg2

def test_baselines():
    print("--- BASELINE ALGORITHM EVALUATION ---")
    
    # 1. Generate a standardized test circuit with known redundancies
    test_circuit = "test_baseline.aag"
    generate_random_circuit(test_circuit, inputs=8, gates=20, injection_mode='stuck')
    
    # Normalize symbols (simulate main.py behavior)
    with open(test_circuit, 'r') as f: lines = f.readlines()
    header = lines[0].split()
    I, O = int(header[2]), int(header[4])
    with open(test_circuit, 'w') as f:
        for line in lines: f.write(line)
        for k in range(I): f.write(f"i{k} pi_{k}\n")
        for k in range(O): f.write(f"o{k} po_{k}\n")
        f.write("c\nNormalized\n")
        
    print(f"\n[Test Circuit Generated: {test_circuit}]")
    
    # 2. Test Algorithm 1
    out_alg1 = "out_alg1.aag"
    print("\n--- Running Algorithm 1 (Naive One-Shot) ---")
    _, _, final1, _, _, rem1, dur1 = optimizer_alg1.solve_circuit(test_circuit, out_alg1)
    pass1 = verify_equivalence(test_circuit, out_alg1)
    print(f"Gates Removed: {rem1}")
    print(f"Runtime      : {dur1:.2f} seconds")
    print(f"Verification : {'PASS' if pass1 else 'FAIL'}")

    # 3. Test Algorithm 2
    out_alg2 = "out_alg2.aag"
    print("\n--- Running Algorithm 2 (Structural Sharing) ---")
    _, _, final2, _, _, rem2, dur2 = optimizer_alg2.solve_circuit(test_circuit, out_alg2)
    pass2 = verify_equivalence(test_circuit, out_alg2)
    print(f"Gates Removed: {rem2}")
    print(f"Runtime      : {dur2:.2f} seconds")
    print(f"Verification : {'PASS' if pass2 else 'FAIL'}")
    
    # Cleanup
    for f in [test_circuit, out_alg1, out_alg2]:
        if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    test_baselines()