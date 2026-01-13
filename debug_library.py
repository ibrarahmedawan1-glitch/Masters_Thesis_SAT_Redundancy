import aiger
import aiger_cnf
import os

# Path to c17.aag
c17_path = "benchmarks/c17.aag"

if not os.path.exists(c17_path):
    print(f"Error: Could not find {c17_path}")
    exit()

print("--- 1. LOADING CIRCUIT ---")
circuit = aiger.load(c17_path)
print(f"Type of circuit: {type(circuit)}")
print("Attributes of circuit:")
print(dir(circuit))

print("\n--- 2. CHECKING FOR GATES ---")
# Let's see where the gates are hiding
if hasattr(circuit, 'aig'):
    print("Found 'aig' attribute. Attributes inside 'circuit.aig':")
    print(dir(circuit.aig))
elif hasattr(circuit, 'nodes'):
    print("Found 'nodes' attribute.")

print("\n--- 3. CHECKING CNF MAPPING ---")
cnf = aiger_cnf.aig2cnf(circuit)
print(f"Type of CNF: {type(cnf)}")
print("Attributes of CNF:")
print(dir(cnf))

# Check content of the CNF object
print("\nCNF Object Content:")
try:
    print(f"Output Map keys: {cnf.output_map.keys() if hasattr(cnf, 'output_map') else 'Not Found'}")
except:
    pass

try:
    print(f"Outputs keys: {cnf.outputs.keys() if hasattr(cnf, 'outputs') else 'Not Found'}")
except:
    pass

# Print raw tuple if it is one
if isinstance(cnf, tuple):
    print(f"CNF is a tuple of length {len(cnf)}")
    print(f"Item 2 (Outputs?): {cnf[2]}")