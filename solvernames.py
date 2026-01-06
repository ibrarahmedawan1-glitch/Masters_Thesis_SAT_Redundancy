from pysat.solvers import SolverNames

print("--- Available Solvers on this Machine ---")
available = SolverNames.solvernames()
for name in available:
    print(f" - {name}")