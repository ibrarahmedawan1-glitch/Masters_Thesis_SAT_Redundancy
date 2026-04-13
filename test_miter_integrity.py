import os
import aiger
from generators import generate_parallel_circuit
from optimizer_alg2 import parse_aag_strict, build_universal_faulty_machine

def test_miter_integrity():
    print("--- STARTING STRICT MITER INTEGRITY TEST ---")
    test_file = "test_circuit.aag"
    univ_file = "test_univ.aag"
    
    # 1. Generate a tiny, understandable circuit
    generate_parallel_circuit(test_file)
    
    # Normalize it EXACTLY how main.py does
    with open(test_file, 'r') as f: lines = f.readlines()
    with open(test_file, 'w') as f:
        for i in range(5): f.write(lines[i]) # write header to outputs
        f.write("6 2 4\n8 2 4\n") # Gates
        f.write("i0 pi_0\ni1 pi_1\no0 po_0\no1 po_1\nc\nNorm\n") # STRICT SYMBOLS
        
    M, I, L, O, A, _, _, _, _, _ = parse_aag_strict(test_file)
    print(f"[INFO] Circuit parsed. Inputs: {I}, Gates: {A}")

    # 2. Build Faulty Machine
    build_universal_faulty_machine(test_file, univ_file)
    
    # 3. Load via py-aiger
    try:
        Mg = aiger.load(test_file)
        Mf = aiger.load(univ_file)
    except Exception as e:
        print(f"[FATAL] Aiger load failed: {e}")
        return

    # Rename outputs to avoid collisions during the merge
    out_g = list(Mg.outputs)
    Mg_renamed = Mg['o', {o: f"g_{o}" for o in out_g}]
    Mf_renamed = Mf['o', {o: f"f_{o}" for o in out_g}]

    # 4. THE CRITICAL MERGE
    combined = Mg_renamed | Mf_renamed
    
    # 5. DIAGNOSTICS
    expected_inputs = I + A  # Original inputs + the fault enable pins
    actual_inputs = len(combined.inputs)
    
    print(f"[DIAGNOSTIC] Expected Miter Inputs : {expected_inputs}")
    print(f"[DIAGNOSTIC] Actual Miter Inputs   : {actual_inputs}")
    print(f"[DIAGNOSTIC] Miter Input Names     : {combined.inputs}")
    
    if actual_inputs > expected_inputs:
        print("\n[FAIL] MITER DISCONNECT DETECTED!")
        print("The inputs from the Good and Faulty circuits did not merge.")
        print("Your SAT solver is solving an invalid problem.")
    elif actual_inputs == expected_inputs:
        print("\n[PASS] MITER INTEGRITY VERIFIED.")
        print("The symbol tables align perfectly. You may proceed to Algorithm 3.")
    else:
        print("\n[FAIL] Unknown structural error in miter.")

    # Cleanup
    for f in [test_file, univ_file]:
        if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    test_miter_integrity()