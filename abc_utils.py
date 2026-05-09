import os
import shutil
import subprocess
import tempfile
import time


ABC_PATH = "./abc/abc"
AIGTOAIG_PATH = "./aiger/aigtoaig"


def normalize_aag_symbols(path, comment="Normalized ASCII AIGER"):
    """Rewrite an ASCII AIGER file with deterministic interface symbols."""
    with open(path, "r", encoding="ascii", errors="ignore") as f:
        lines = []
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line == "c":
                break
            lines.append(line)

    if not lines or not lines[0].startswith("aag "):
        return False

    header = lines[0].split()
    I, L, O, A = int(header[2]), int(header[3]), int(header[4]), int(header[5])
    logic_end = 1 + I + L + O + A
    if len(lines) < logic_end:
        return False

    with open(path, "w", encoding="ascii") as f:
        for line in lines[:logic_end]:
            f.write(line + "\n")
        for idx in range(I):
            f.write(f"i{idx} i{idx}\n")
        for idx in range(L):
            f.write(f"l{idx} l{idx}\n")
        for idx in range(O):
            f.write(f"o{idx} o{idx}\n")
        f.write(f"c\n{comment}\n")
    return True


def convert_aiger(src, dst, ascii_output=False):
    """Convert between ASCII and binary AIGER using the bundled AIGER tool."""
    if not os.path.exists(AIGTOAIG_PATH):
        return False

    if ascii_output:
        cmd = [AIGTOAIG_PATH, "-a", src, "-"]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0 or not result.stdout:
            return False
        if dst == "-":
            return True
        parent = os.path.dirname(dst)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(dst, "wb") as f:
            f.write(result.stdout)
        return os.path.exists(dst) and os.path.getsize(dst) > 0

    cmd = [AIGTOAIG_PATH, src, dst]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 0


def to_binary_aig(src, dst):
    return convert_aiger(src, dst, ascii_output=False)


def to_ascii_aag(src, dst, comment="ABC strash"):
    if not convert_aiger(src, dst, ascii_output=True):
        return False
    return normalize_aag_symbols(dst, comment=comment)


def run_abc_strash(input_path, output_path, timeout=60):
    """Run ABC strash through binary AIGER, then write normalized ASCII AAG."""
    if not os.path.exists(ABC_PATH):
        return False

    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="abc_strash_") as tmp:
        in_aig = os.path.join(tmp, "input.aig")
        out_aig = os.path.join(tmp, "output.aig")
        out_aag = os.path.join(tmp, "output.aag")

        if not to_binary_aig(input_path, in_aig):
            return False

        cmd = [ABC_PATH, "-c", f"read_aiger {in_aig}; strash; write_aiger {out_aig}; quit"]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False

        if result.returncode != 0 or not os.path.exists(out_aig):
            return False
        if not to_ascii_aag(out_aig, out_aag, comment="ABC strash"):
            return False

        shutil.copy(out_aag, output_path)
        return True


def run_abc_cec(orig_path, opt_path, timeout=15):
    """Return (status, duration, log) for ABC CEC after binary conversion."""
    start = time.time()
    if not os.path.exists(ABC_PATH):
        return "ERROR", time.time() - start, "ABC binary not found"

    with tempfile.TemporaryDirectory(prefix="abc_cec_") as tmp:
        orig_aig = os.path.join(tmp, "orig.aig")
        opt_aig = os.path.join(tmp, "opt.aig")

        if not to_binary_aig(orig_path, orig_aig):
            return "ERROR", time.time() - start, f"failed to convert {orig_path} to binary AIG"
        if not to_binary_aig(opt_path, opt_aig):
            return "ERROR", time.time() - start, f"failed to convert {opt_path} to binary AIG"

        cmd = [ABC_PATH, "-c", f"cec -n {orig_aig} {opt_aig}; quit"]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        except subprocess.TimeoutExpired:
            return "TIMEOUT", timeout, "ABC CEC timed out"

        log = (
            result.stdout.decode("utf-8", errors="ignore")
            + result.stderr.decode("utf-8", errors="ignore")
        )
        lower = log.lower()
        if "not equivalent" in lower:
            return "FAIL", time.time() - start, log
        if "are equivalent" in lower or "networks are equivalent" in lower:
            return "PASS", time.time() - start, log
        if result.returncode != 0:
            return "ERROR", time.time() - start, log
        return "ERROR", time.time() - start, log
