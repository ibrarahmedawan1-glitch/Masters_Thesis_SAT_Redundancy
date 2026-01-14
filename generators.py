import random

def generate_random_circuit(filename, inputs=8, gates=30, injection_mode='none'):
    with open(filename, 'w') as f:
        M = inputs + gates; I = inputs; L = 0; O = 1; A = gates
        f.write(f"aag {M} {I} {L} {O} {A}\n")
        for i in range(1, I + 1): f.write(f"{i*2}\n")
        
        # Output connects to LAST gate
        last_gate_lit = (inputs + gates) * 2
        f.write(f"{last_gate_lit}\n")
        
        available_lits = [i*2 for i in range(1, I + 1)]
        current_var = inputs + 1
        
        # For forcing the stuck gate to be relevant
        stuck_gate_lit = None

        for k in range(gates):
            lhs = current_var * 2
            
            # Logic for STUCK mode:
            # Force the last gate to combine the stuck signal
            is_last_gate = (k == gates - 1)
            
            inject = False
            if injection_mode != 'none' and random.random() < 0.5: inject = True
            
            if injection_mode == 'stuck' and inject and stuck_gate_lit is None:
                # Create the stuck gate now
                op1 = random.choice(available_lits); op2 = op1 ^ 1
                f.write(f"{lhs} {op1} {op2}\n")
                stuck_gate_lit = lhs # Remember this is 0
                
            elif injection_mode == 'stuck' and is_last_gate and stuck_gate_lit is not None:
                # FORCE output to depend on stuck gate (ANDing with 0 makes it 0)
                op1 = stuck_gate_lit
                op2 = random.choice(available_lits)
                f.write(f"{lhs} {op1} {op2}\n")
                
            elif inject and injection_mode == 'idempotent':
                op1 = random.choice(available_lits); op2 = op1
                f.write(f"{lhs} {op1} {op2}\n")
            else:
                op1 = random.choice(available_lits); op2 = random.choice(available_lits)
                if random.choice([True, False]): op1 ^= 1
                if random.choice([True, False]): op2 ^= 1
                f.write(f"{lhs} {op1} {op2}\n")
            
            available_lits.append(lhs); current_var += 1
            
        for i in range(I): f.write(f"i{i} i{i}\n")
        f.write("o0 o0\n"); f.write("c\nRaw Random Generator\n")
    return inputs, gates

def generate_ladder_circuit(filename, depth=50):
    num_inputs = 1; num_outputs = 1; num_gates = depth
    max_var = num_inputs + num_gates
    with open(filename, 'w') as f:
        f.write(f"aag {max_var} {num_inputs} 0 {num_outputs} {num_gates}\n")
        f.write("2\n"); f.write(f"{2 * (depth + 1)}\n")
        prev = 2
        for k in range(depth):
            lhs = prev + 2; f.write(f"{lhs} {prev} {prev}\n"); prev = lhs
        f.write("i0 i0\n"); f.write("o0 o0\n"); f.write("c\nLadder\n")
    return 1, depth

def generate_parallel_circuit(filename, inputs=5, gates=20):
    with open(filename, 'w') as f:
        f.write(f"aag 8 2 0 2 2\n") 
        f.write("2\n4\n"); f.write("6\n8\n")
        f.write("6 2 4\n"); f.write("8 2 4\n")
        f.write("i0 i0\ni1 i1\no0 o0\no1 o1\nc\nParallel\n")
    return 2, 2