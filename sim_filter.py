import random
import aiger

def generate_signatures(circuit, num_simulations=64):
    """
    Step 1: Assign random 64-bit integers to every Input.
    Step 2: Propagate those integers through the AND/NOT logic.
    Step 3: Return a map of {Wire_ID: 64_bit_Signature}
    """
    
    # --- 1. SETUP INPUTS ---
    # Dictionary to store the 'value' (64-bit int) of every wire
    # Key = Wire Name/ID, Value = 64-bit Integer
    wire_values = {}

    # Assign random 64-bit chunks to all inputs
    # If inputs are strings (like 'i0'), use them as keys.
    for inp in circuit.inputs:
        # getrandbits(64) gives us a huge number like 101010... (64 times)
        wire_values[inp] = random.getrandbits(num_simulations)

    # Constant False (0) is always 0
    # Constant True (1) is always all 1s (in bitwise world, typically -1 mask)
    wire_values[0] = 0
    wire_values[1] = (1 << num_simulations) - 1

    # --- 2. SIMULATE (Topological Sort) ---
    # We must calculate gates in order (Inputs -> Middle -> Outputs)
    # The 'aiger' library usually yields gates in topological order automatically.
    
    for gate in circuit.gates:
        # A gate usually has: output, left_input, right_input
        # We need to look up the values we calculated earlier.
        
        # Get Left Input Value
        left_val = resolve_input(gate.input_left, wire_values)
        
        # Get Right Input Value
        right_val = resolve_input(gate.input_right, wire_values)
        
        # BITWISE AND: This simulates 64 tests at once!
        # output = left & right
        wire_values[gate.output] = left_val & right_val

    return wire_values

def resolve_input(wire_id, wire_values):
    """
    Helper to handle AIGER 'Odd number means NOT' logic.
    """
    # If your library uses strings for IDs, this logic changes slightly.
    # Assuming standard integer AIGER format here:
    
    # Logic: Real ID is the even version (wire_id & -2)
    # Logic: If it's odd, we flip the bits.
    
    # Note: If your 'aiger' library objects handle inversion automatically,
    # you might just need `wire_values[wire_id]`. 
    # But usually, raw AIGER requires manual flipping:
    
    is_inverted = (wire_id % 2 == 1)
    actual_wire = wire_id - 1 if is_inverted else wire_id
    
    val = wire_values.get(actual_wire, 0) # Default to 0 if missing
    
    if is_inverted:
        return ~val  # Bitwise NOT (Flip 0s to 1s)
    else:
        return val

def get_candidates(circuit):
    """
    Groups wires that have identical signatures.
    """
    # Run the simulation
    signatures = generate_signatures(circuit)
    
    # Group wires by their 64-bit result
    groups = {}
    for wire_id, sig in signatures.items():
        if sig not in groups:
            groups[sig] = []
        groups[sig].append(wire_id)
        
    # Extract pairs
    candidates = []
    for sig, wires in groups.items():
        if len(wires) > 1:
            # All these wires behaved exactly the same!
            # Pair them up: (Wire1, Wire2), (Wire1, Wire3)...
            base = wires[0]
            for other in wires[1:]:
                candidates.append((base, other))
                
    return candidates