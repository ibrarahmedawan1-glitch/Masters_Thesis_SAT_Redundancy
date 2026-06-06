import os
import subprocess

def write_binary_aiger(filename, M, I, L, O, A, inputs, outputs, gates):
    """
    Encodes the in-memory AIG into a Binary .aig file.
    AIGER Binary Format uses a specialized delta-encoding (LEB128-like).
    """
    def encode_delta(val):
        res = bytearray()
        while val & ~0x7f:
            res.append((val & 0x7f) | 0x80)
            val >>= 7
        res.append(val)
        return res

    with open(filename, 'wb') as f:
        # 1. Header (Binary header is 'aig' not 'aag')
        header = f"aig {M} {I} {L} {O} {A}\n".encode('ascii')
        f.write(header)

        # 2. Latches (L=0 for now)
        # 3. Outputs (One literal per output, written as ASCII)
        for out in outputs:
            f.write(f"{out}\n".encode('ascii'))

        # 4. AND Gates (Binary Delta Encoding)
        # Binary AIGER requires gates to be strictly ordered by LHS.
        gates.sort(key=lambda x: x[0])
        
        for lhs, rhs0, rhs1 in gates:
            # Binary AIGER stores (lhs - rhs0) and (rhs0 - rhs1)
            d1 = lhs - rhs0
            d2 = rhs0 - rhs1
            f.write(encode_delta(d1))
            f.write(encode_delta(d2))

def verify_with_abc(aig_file):
    print(f"\n[TEST] Verifying {aig_file} with ABC...")
    # Now we can use read_aiger because the file starts with 'aig'
    cmd = f'./abc/abc -c "read_aiger {aig_file}; print_stats; quit"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if "Reading AIG from file has failed" in result.stdout or result.returncode != 0:
        print("❌ FAILED: ABC still rejected the binary format.")
        print(result.stdout)
    else:
        print("✅ SUCCESS: ABC accepted the Binary Encoding!")
        print(result.stdout.strip())

# MOCK DATA from your previous successful in-memory strash
# M=25, I=20, L=0, O=1, A=5
mock_inputs = [i*2 for i in range(1, 21)]
mock_outputs = [4] # Output points to PI 2
mock_gates = [
    [42, 29, 22],
    [44, 42, 15],
    [46, 37, 13],
    [48, 47, 45],
    [50, 49, 32]
]

write_binary_aiger("test_binary.aig", 25, 20, 0, 1, 5, mock_inputs, mock_outputs, mock_gates)
verify_with_abc("test_binary.aig")