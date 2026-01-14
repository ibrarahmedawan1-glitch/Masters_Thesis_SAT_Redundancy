import aiger
import random
import os
import subprocess

ABC_PATH = "./abc/abc"

def verify_equivalence(orig_path, opt_path, num_tests=2000):
    if os.path.exists(ABC_PATH):
        cmd = f'{ABC_PATH} -c "cec {orig_path} {opt_path}"'
        try:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if "Networks are equivalent" in res.stdout: return True
        except: pass

    try:
        c1 = aiger.load(orig_path)
        c2 = aiger.load(opt_path)
        inputs1 = sorted(list(c1.inputs))
        inputs2 = sorted(list(c2.inputs))
        if inputs1 != inputs2: return False
        outputs1 = sorted(list(c1.outputs))
        
        for _ in range(num_tests):
            rand_vals = [random.choice([True, False]) for _ in range(len(inputs1))]
            input_map = dict(zip(inputs1, rand_vals))
            res1 = c1.simulate([input_map])[0][0]
            res2 = c2.simulate([input_map])[0][0]
            for out in outputs1:
                if out in res2:
                    if res1[out] != res2[out]: return False
                else:
                    if res1[out] is True: return False
        return True
    except: return False