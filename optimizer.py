import aiger
import os
import random
import glob

# --- CONFIGURATION ---
BENCHMARK_DIR = "benchmarks"
OUTPUT_DIR = "optimized_circuits"

def simulate_and_find_stuck(circuit, num_sims=64):
    """
    Runs random simulations to find outputs that never turn 'True'.
    """
    potentially_stuck = set(circuit.outputs)
    input_names = circuit.inputs
    
    # Run Simulations
    for _ in range(num_sims):
        sim_input = {i: random.choice([True, False]) for i in input_names}
        
        # Get result tuple (outputs, latches) -> [0][0]
        output_dict = circuit.simulate([sim_input])[0][0]
        
        # If an output emits 'True', it is NOT stuck.
        for name, val in output_dict.items():
            if val is True and name in potentially_stuck:
                potentially_stuck.remove(name)
        
        if not potentially_stuck:
            break
            
    return list(potentially_stuck)

def optimize_all():
    if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)
    
    circuits = glob.glob(os.path.join(BENCHMARK_DIR, "*.aag"))
    print(f"Found {len(circuits)} circuits.")
    
    for c_path in circuits:
        c_name = os.path.basename(c_path)
        print(f"\nProcessing {c_name}...")
        
        try:
            c = aiger.load(c_path)
            
            # 1. Identify Redundant Outputs
            bad_outputs = simulate_and_find_stuck(c)
            
            if not bad_outputs:
                print("  -> No redundancies found.")
                c.write(os.path.join(OUTPUT_DIR, c_name.replace(".aag", "_optimized.aag")))
                continue
                
            print(f"  -> Removing {len(bad_outputs)} Stuck-at-0 outputs...")

            # 2. THE FIX: Use a 'Sink' to swallow the bad outputs
            # This wires the bad outputs to nowhere, effectively deleting them.
            
            # Create a sink matching the bad names
            sink = aiger.sink(bad_outputs)
            
            # Cascade: Circuit >> Sink
            # The bad outputs go into the sink and disappear from the interface.
            c_opt = c >> sink
            
            # 3. Save
            out_path = os.path.join(OUTPUT_DIR, c_name.replace(".aag", "_optimized.aag"))
            c_opt.write(out_path)
            print(f"  -> [SUCCESS] Saved to {out_path}")
            
        except Exception as e:
            print(f"  [Error] Could not optimize {c_name}: {repr(e)}")

if __name__ == "__main__":
    optimize_all()