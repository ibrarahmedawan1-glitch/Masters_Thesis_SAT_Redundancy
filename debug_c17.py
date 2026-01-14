
import aiger
import os

def debug_c17():
    print("--- DEBUGGING C17 FAILURE ---")
    
    path_orig = "dataset_benchmarks/c17.aag"
    path_opt = "results_optimized/c17.aag"
    
    if not os.path.exists(path_orig) or not os.path.exists(path_opt):
        print("Files not found. Run main.py first.")
        return

    try:
        c1 = aiger.load(path_orig)
        c2 = aiger.load(path_opt)
    except Exception as e:
        print(f"Failed to load: {e}")
        return

    print(f"Original Inputs: {sorted(list(c1.inputs))}")
    print(f"Optimized Inputs: {sorted(list(c2.inputs))}")
    print("-" * 20)
    print(f"Original Outputs: {sorted(list(c1.outputs))}")
    print(f"Optimized Outputs: {sorted(list(c2.outputs))}")
    print("-" * 20)

    # Test alignment
    inputs1 = sorted(list(c1.inputs))
    inputs2 = sorted(list(c2.inputs))

    if inputs1 != inputs2:
        print("CRITICAL: Input names mismatch! This causes verification failure.")
        return
    else:
        print("Input names match.")

    # Run 1 manual simulation
    # Fixed vector: all False
    vec = {i: False for i in inputs1}
    
    res1 = c1.simulate([vec])[0][0]
    res2 = c2.simulate([vec])[0][0]
    
    print(f"Simulating all-False input:")
    print(f"Orig Output: {res1}")
    print(f"Opt  Output: {res2}")
    
    if res1 == res2:
        print("Test Passed. (Maybe random tests hit a corner case?)")
    else:
        print("Test FAILED.")

if __name__ == "__main__":
    debug_c17()
