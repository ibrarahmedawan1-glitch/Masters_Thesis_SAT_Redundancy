import aiger
import aiger_cnf
from pysat.solvers import Solver
import os

def parse_aag(filepath):
    """Reads an AAG file and returns its components."""
    with open(filepath, 'r') as f:
        lines = [l.strip() for l in f.readlines() if l.strip() and not l.startswith('c')]
    
    header = lines[0]
    parts = header.split()
    I, L, O, A = int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5])
    
    inputs = lines[1 : 1+I]
    latches = lines[1+I : 1+I+L]
    outputs = lines[1+I+L : 1+I+L+O]
    gates = lines[1+I+L+O : 1+I+L+O+A]
    
    return header, inputs, latches, outputs, gates

def write_aag(filepath, header, inputs, latches, outputs, gates):
    """Writes the modified components back to an AAG file with a forced symbol table."""
    with open(filepath, 'w') as f:
        f.write(header + '\n')
        for i in inputs: f.write(i + '\n')
        for l in latches: f.write(l + '\n')
        for o in outputs: f.write(o + '\n')
        for g in gates: f.write(g + '\n')
        
        # FORCE SYMBOL TABLE to lock Py-Aiger inputs together
        for idx in range(len(inputs)):
            f.write(f"i{idx} i{idx}\n")
        for idx in range(len(outputs)):
            f.write(f"o{idx} o{idx}\n")
            
        f.write("c\nAutomated ATPG Miter\n")

def generate_faulty_circuit(header, inputs, latches, outputs, gates, target_gate_index):
    """Injects a SA0 fault by forcing the target gate to a structural contradiction."""
    faulty_gates = gates.copy()
    
    target_line = faulty_gates[target_gate_index]
    lhs = target_line.split()[0] 
    
    # Mathematical SA0: Input AND NOT Input
    first_input = int(inputs[0])
    not_first_input = first_input + 1
    
    # INJECT STUCK-AT-0
    faulty_gates[target_gate_index] = f"{lhs} {first_input} {not_first_input}"
    
    faulty_file = "temp_faulty.aag"
    write_aag(faulty_file, header, inputs, latches, outputs, faulty_gates)
    return faulty_file

def is_gate_redundant(good_filepath, faulty_filepath):
    """Builds the Miter and runs SAT. Returns True if UNSAT (Redundant)."""
    try:
        Mg = aiger.load(good_filepath)
        Mf = aiger.load(faulty_filepath)
        
        # 1. Extract original output names
        out_g = list(Mg.outputs)[0]
        out_f = list(Mf.outputs)[0]
        
        # 2. Relabel outputs to prevent collision
        Mg = Mg['o', {out_g: 'good_out'}]
        Mf = Mf['o', {out_f: 'faulty_out'}]
        
        # 3. Merge circuits in parallel (inputs are automatically shared)
        combined = Mg | Mf
        
        # 4. Create an XOR expression and wire it to the combined outputs sequentially
        xor_expr = aiger.atom('good_out') ^ aiger.atom('faulty_out')
        miter = combined >> xor_expr.aig
        
        miter_output = list(miter.outputs)[0]
        
        # 5. Translate to CNF and check with SAT
        cnf = aiger_cnf.aig2cnf(miter)
        
        with Solver(name='g4', bootstrap_with=cnf.clauses) as solver:
            output_lit = cnf.output2lit[miter_output]
            is_testable = solver.solve(assumptions=[output_lit])
            
            return not is_testable 
            
    except Exception as e:
        print(f"Error in SAT evaluation: {e}")
        return False

def optimize_circuit(input_aag):
    """The Master Loop: Iterates until no more redundancies are found."""
    current_aag = "current_working.aag"
    
    header, inputs, latches, outputs, gates = parse_aag(input_aag)
    write_aag(current_aag, header, inputs, latches, outputs, gates)
    
    iteration = 1
    circuit_changed = True
    total_removed = 0
    
    # Pre-calculate the contradiction string
    first_in = int(inputs[0])
    sa0_string = f"{first_in} {first_in + 1}"
    
    print(f"--- STARTING ATPG OPTIMIZATION ---")
    print(f"Initial Gates: {len(gates)}")
    
    while circuit_changed:
        circuit_changed = False
        print(f"\n--- Pass {iteration} ---")
        
        header, inputs, latches, outputs, gates = parse_aag(current_aag)
        
        for i in range(len(gates)):
            target_lhs = gates[i].split()[0]
            
            # Skip gates that are already deleted
            if gates[i].endswith(sa0_string):
                continue 
                
            print(f"Testing Gate {target_lhs} for SA0...", end=" ")
            
            faulty_aag = generate_faulty_circuit(header, inputs, latches, outputs, gates, i)
            redundant = is_gate_redundant(current_aag, faulty_aag)
            
            if redundant:
                print("REDUNDANT! (UNSAT) -> Removing Gate.")
                # Permanently sever the gate using the contradiction
                gates[i] = f"{target_lhs} {sa0_string}" 
                write_aag(current_aag, header, inputs, latches, outputs, gates)
                
                circuit_changed = True
                total_removed += 1
                break 
            else:
                print("Testable (SAT). Keeping Gate.")
                
        iteration += 1

    print(f"\n--- OPTIMIZATION COMPLETE ---")
    print(f"Total Redundant Gates Removed: {total_removed}")
    
    if os.path.exists("temp_faulty.aag"): os.remove("temp_faulty.aag")
    return current_aag

if __name__ == "__main__":
    final_file = optimize_circuit("test.aag")
    print(f"Optimized circuit saved to: {final_file}")