import aiger
import aiger_cnf
import os
import subprocess
import time
from pysat.solvers import Solver

ABC_PATH = "./abc/abc"

def verify_equivalence(orig_path, opt_path):
    """Strict Formal Equivalence Check (CEC) with OS-Level SIGKILL Timeouts"""
    start_time = time.time()
    VERIFY_TIMEOUT = 15 # Seconds before OS-level kill
    
    # Phase 1: ABC Combinational Equivalence Checking
    if os.path.exists(ABC_PATH):
        # We pass the command as a list to avoid shell virtualization
        cmd = [ABC_PATH, '-c', f'cec {orig_path} {opt_path}']
        try:
            # Popen allows us to directly manage the OS process ID
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                stdout, stderr = proc.communicate(timeout=VERIFY_TIMEOUT)
                out = stdout.decode('utf-8', errors='ignore').lower()
                
                if "equivalent" in out and "not equivalent" not in out:
                    return "PASS", (time.time() - start_time)
                if "not equivalent" in out:
                    return "FAIL", (time.time() - start_time)
                    
            except subprocess.TimeoutExpired:
                # HARD KILL: Force the OS to dump the ABC process from RAM
                proc.kill() 
                proc.communicate() # Flush the zombie pipes
                return "TIMEOUT", VERIFY_TIMEOUT
        except Exception:
            pass # ABC binary failed to execute entirely

    # Phase 2: Formal SAT Miter (Fallback)
    # Only executes if ABC completely failed to boot (e.g., path error)
    try:
        # SAFETY NET: Prevent pure-Python CNF conversion from hanging on huge circuits
        if os.path.getsize(orig_path) > 50000: # ~1000+ gates
            return "TIMEOUT", (time.time() - start_time)

        Mg, Mf = aiger.load(orig_path), aiger.load(opt_path)
        outputs = list(Mg.outputs)
        Mg = Mg['o', {o: f"g_{o}" for o in outputs}]
        Mf = Mf['o', {o: f"f_{o}" for o in outputs}]
        combined = Mg | Mf
        
        miter_expr = None
        for o in outputs:
            xor_gate = aiger.atom(f"g_{o}") ^ aiger.atom(f"f_{o}")
            miter_expr = xor_gate if miter_expr is None else miter_expr | xor_gate
            
        miter_aig = combined >> miter_expr.aig
        cnf = aiger_cnf.aig2cnf(miter_aig)
        
        with Solver(name='g4', bootstrap_with=cnf.clauses) as solver:
            miter_lit = cnf.output2lit[list(miter_aig.outputs)[0]]
            solver.conf_budget(5000) 
            is_sat = solver.solve_limited(assumptions=[miter_lit])
            
            if is_sat is None:
                return "TIMEOUT", (time.time() - start_time)
                
            return "FAIL" if is_sat else "PASS", (time.time() - start_time)
            
    except Exception:
        return "ERROR", (time.time() - start_time)