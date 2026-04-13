import aiger

def test_activation_literal():
    # 1. Create a simple Good Machine: O = A AND B
    a = aiger.atom('A')
    b = aiger.atom('B')
    good_machine = a & b  # This is a BoolExpr
    
    # 2. Inject an Activation Literal (Fault Enable Pin)
    enable = aiger.atom('Fault_Enable')
    
    # Do the math directly on the expression!
    faulty_machine = (good_machine & ~enable).with_output('Out')
    
    print("--- GOOD MACHINE INPUTS ---")
    print(good_machine.inputs)
    
    print("\n--- FAULTY MACHINE INPUTS (Notice the new pin) ---")
    print(faulty_machine.inputs)
    
    # Let's test the physics.
    print("\n--- SIMULATION ---")
    # Normal operation (Enable = False)
   # Let's test the physics.
    print("\n--- SIMULATION ---")
    
    # Normal operation (Enable = False)
    # BoolExprs are evaluated by calling them directly!
    res_normal = faulty_machine({'A': True, 'B': True, 'Fault_Enable': False})
    print(f"When A=1, B=1, Enable=0 -> Output = {res_normal} (Normal)")
    
    # Fault injected (Enable = True)
    res_fault = faulty_machine({'A': True, 'B': True, 'Fault_Enable': True})
    print(f"When A=1, B=1, Enable=1 -> Output = {res_fault} (Stuck-At-0!)")

if __name__ == "__main__":
    test_activation_literal()