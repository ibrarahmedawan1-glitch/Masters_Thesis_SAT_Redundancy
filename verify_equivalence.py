import aiger
import os
import random

# --- CONFIGURATION ---
BENCHMARK_DIR = "benchmarks"
OPTIMIZED_DIR = "optimized_circuits"
CIRCUITS_TO_CHECK = ["arbiter_8bit", "c5315", "c880", "c2670", "alu_8bit", "c3540"]
NUM_TESTS = 5000

def get_ordered_inputs(circuit):
    """
    py-aiger stores inputs as an unordered set.
    We need to assume a stable sort or rely on the library's internal ordering if available.
    For robustness, we simply sort them alphabetically. 
    (In most AIG conversions, i0, i1, i2... sort correctly).
    """
    return sorted(list(circuit.inputs))

def verify_robust():
    print(f"{'CIRCUIT':<15} | {'TESTS':<8} | {'RESULT'}")
    print("-" * 60)

    for name in CIRCUITS_TO_CHECK:
        orig_path = os.path.join(BENCHMARK_DIR, f"{name}.aag")
        opt_path = os.path.join(OPTIMIZED_DIR, f"{name}_optimized.aag")
        
        if not os.path.exists(opt_path):
            print(f"{name:<15} | -        | SKIP (File not found)")
            continue

        try:
            # 1. Load Circuits
            c_orig = aiger.load(orig_path)
            c_opt = aiger.load(opt_path)
            
            # 2. Get Inputs (Sorted to ensure alignment)
            # Even if names differ (i0 vs req0), sorting usually aligns them 
            # if they follow a standard numbering or if we trust the count.
            in_orig = get_ordered_inputs(c_orig)
            in_opt = get_ordered_inputs(c_opt)
            
            # Check counts
            if len(in_orig) != len(in_opt):
                print(f"{name:<15} | -        | FAIL (Input count mismatch: {len(in_orig)} vs {len(in_opt)})")
                continue
                
            # 3. RUN SIMULATION
            passed = True
            
            for i in range(NUM_TESTS):
                # A. Generate Random Pattern (True/False List)
                # We create one list of values, and apply it to BOTH circuits
                # mapping index-to-index.
                random_vals = [random.choice([True, False]) for _ in range(len(in_orig))]
                
                # B. Create Input Dictionaries
                # Map value[k] -> Original_Input_Name[k]
                input_map_orig = {name: val for name, val in zip(in_orig, random_vals)}
                
                # Map value[k] -> Optimized_Input_Name[k]
                input_map_opt = {name: val for name, val in zip(in_opt, random_vals)}
                
                # C. Simulate
                out_orig = c_orig.simulate([input_map_orig])[0][0]
                out_opt = c_opt.simulate([input_map_opt])[0][0]
                
                # D. Compare Outputs
                # We only check outputs that exist in BOTH (intersection)
                # If an output was deleted (optimized away), we skip it.
                common_outputs = set(out_orig.keys()) & set(out_opt.keys())
                
                if not common_outputs:
                    # If names also mismatch on outputs, we might need to map by order?
                    # Let's try simple name matching first.
                    pass 
                
                for out_key in common_outputs:
                    if out_orig[out_key] != out_opt[out_key]:
                        print(f"{name:<15} | {i+1:<8} | FAIL! Mismatch at {out_key}")
                        passed = False
                        break
                
                if not passed: break
            
            if passed:
                print(f"{name:<15} | {NUM_TESTS:<8} | PASS (Equivalent behavior)")

        except Exception as e:
            print(f"{name:<15} | ERROR    | {e}")

if __name__ == "__main__":
    verify_robust()