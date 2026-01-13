import os

# CONFIGURATION
BENCHMARK_DIR = "benchmarks"
OPTIMIZED_DIR = "optimized_circuits"
# Added alu_8bit since your optimizer fixed it!
CIRCUITS_TO_CHECK = ["c5315", "c2670", "c880", "arbiter_8bit", "c3540", "alu_8bit"]

def get_reachable_gates(lines):
    header = lines[0].strip().split()
    if header[0] != 'aag': return 0
    
    # Header: M I L O A
    num_inputs, num_latches, num_outputs = int(header[2]), int(header[3]), int(header[4])
    num_ands = int(header[5])
    
    input_end = 1 + num_inputs
    latch_end = input_end + num_latches
    output_end = latch_end + num_outputs
    and_start = output_end
    
    # 1. Identify Drivers (What feeds the outputs?)
    active_vars = set()
    # Read Outputs
    for i in range(latch_end, output_end):
        try: active_vars.add(int(lines[i].strip()) >> 1)
        except: pass
    # Read Latches
    for i in range(input_end, latch_end):
        try: active_vars.add(int(lines[i].split()[0]) >> 1)
        except: pass

    # 2. Map Gates
    gates = {}
    for line in lines[and_start : and_start + num_ands]:
        parts = [int(x) for x in line.split()]
        gates[parts[0] >> 1] = (parts[1] >> 1, parts[2] >> 1)
        
    # 3. Reachability Trace
    stack = list(active_vars)
    visited = set(active_vars)
    alive_count = 0
    
    while stack:
        curr = stack.pop()
        if curr in gates:
            alive_count += 1
            for inp in gates[curr]:
                if inp not in visited:
                    visited.add(inp)
                    stack.append(inp)
                    
    return alive_count

def verify():
    print(f"{'CIRCUIT':<15} | {'ORIGINAL':<10} | {'OPTIMIZED':<10} | {'REDUCTION'}")
    print("-" * 65)
    
    for name in CIRCUITS_TO_CHECK:
        orig_path = os.path.join(BENCHMARK_DIR, f"{name}.aag")
        opt_path = os.path.join(OPTIMIZED_DIR, f"{name}_optimized.aag")
        
        if not os.path.exists(opt_path): 
            print(f"{name:<15} | Not Found  | -          | -")
            continue
        
        with open(orig_path, 'r') as f: orig_lines = f.readlines()
        with open(opt_path, 'r') as f: opt_lines = f.readlines()
        
        orig_ands = int(orig_lines[0].split()[5])
        alive_after = get_reachable_gates(opt_lines)
        
        removed = orig_ands - alive_after
        percent = (removed / orig_ands * 100) if orig_ands > 0 else 0
        
        print(f"{name:<15} | {orig_ands:<10} | {alive_after:<10} | -{removed} gates ({percent:.1f}%)")

if __name__ == "__main__":
    verify()