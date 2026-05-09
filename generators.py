import csv
import os
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


def _read_simple_aag(path):
    lines = []
    with open(path, "r", encoding="ascii", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line == "c":
                break
            lines.append(line)

    if not lines or not lines[0].startswith("aag "):
        raise ValueError(f"not an ASCII AIGER file: {path}")

    header = lines[0].split()
    M, I, L, O, A = map(int, header[1:6])
    if L != 0:
        raise ValueError(f"planted-live generator expects combinational AAG: {path}")

    logic_end = 1 + I + L + O + A
    if len(lines) < logic_end:
        raise ValueError(f"truncated AAG file: {path}")

    inputs = [int(lines[idx]) for idx in range(1, 1 + I)]
    outputs = [int(lines[1 + I + L + idx]) for idx in range(O)]
    gate_start = 1 + I + L + O
    gates = [list(map(int, lines[gate_start + idx].split())) for idx in range(A)]
    return M, I, O, A, inputs, outputs, gates


def _write_simple_aag(path, M, I, O, inputs, outputs, gates, comment):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(path, "w", encoding="ascii") as f:
        f.write(f"aag {M} {I} 0 {O} {len(gates)}\n")
        for lit in inputs:
            f.write(f"{lit}\n")
        for lit in outputs:
            f.write(f"{lit}\n")
        for lhs, r0, r1 in gates:
            f.write(f"{lhs} {r0} {r1}\n")
        for idx in range(I):
            f.write(f"i{idx} pi_{idx}\n")
        for idx in range(O):
            f.write(f"o{idx} po_{idx}\n")
        f.write(f"c\n{comment}\n")


def _base_lit(lit):
    return lit & ~1


def _choose_side_literal(rng, pool, avoid_lit):
    candidates = [lit for lit in pool if _base_lit(lit) != _base_lit(avoid_lit)]
    if not candidates:
        candidates = list(pool)
    lit = rng.choice(candidates)
    if rng.choice([False, True]):
        lit ^= 1
    return lit


def generate_planted_live_circuit(base_path, output_path, plants=6, seed=0):
    """Wrap live outputs with ATPG-style redundant AIG motifs.

    Every planted motif feeds a primary output, so the extra gates are live.
    Each motif has a known gate whose stuck-at-0 fault is redundant:

    - absorb_or: x OR (x AND y) = x
    - absorb_and: x AND (x OR y) = x
    - covered_product: (x&y) OR (x&~y) OR (x&z) = x

    The third pattern is intentionally less local: SAT should prove the
    covered product redundant, while basic structural cleanup should not
    erase it before the SAT phase.
    """
    M, I, O, A, inputs, outputs, gates = _read_simple_aag(base_path)
    rng = random.Random(seed)
    gates = [list(gate) for gate in gates]
    outputs = list(outputs)
    next_var = max([M] + [lit // 2 for lit in inputs + outputs] + [g[0] // 2 for g in gates]) + 1
    available = list(inputs)
    available.extend(gate[0] for gate in gates)
    records = []

    def new_and(a, b):
        nonlocal next_var
        lhs = next_var * 2
        next_var += 1
        gates.append([lhs, a, b])
        available.append(lhs)
        return lhs

    def new_or(a, b):
        return new_and(a ^ 1, b ^ 1) ^ 1

    patterns = ["absorb_or", "absorb_and", "covered_product"]

    for plant_idx in range(plants):
        out_idx = plant_idx % len(outputs)
        x = outputs[out_idx]
        y = _choose_side_literal(rng, available, x)
        pattern = patterns[plant_idx % len(patterns)]

        if pattern == "absorb_or":
            target = new_and(x, y)
            new_output = new_or(x, target)
            aux = [target]
        elif pattern == "absorb_and":
            target = new_and(x ^ 1, y ^ 1)
            new_output = new_and(x, target ^ 1)
            aux = [target]
        else:
            z = _choose_side_literal(rng, available, x)
            t1 = new_and(x, y)
            t2 = new_and(x, y ^ 1)
            target = new_and(x, z)
            or12 = new_or(t1, t2)
            new_output = new_or(or12, target)
            aux = [t1, t2, target, or12]

        outputs[out_idx] = new_output
        records.append(
            {
                "generated_circuit": os.path.basename(output_path),
                "base_circuit": os.path.basename(base_path),
                "plant_index": plant_idx,
                "pattern": pattern,
                "output_index": out_idx,
                "source_literal": x,
                "side_literal": y,
                "target_literal": target,
                "expected_stuck": "SA0",
                "new_output_literal": new_output,
                "aux_literals": " ".join(str(lit) for lit in aux),
            }
        )

    M_new = max([lit // 2 for lit in inputs + outputs] + [g[0] // 2 for g in gates])
    comment = f"Planted live ATPG redundancies from {os.path.basename(base_path)}"
    _write_simple_aag(output_path, M_new, I, O, inputs, outputs, gates, comment)
    return records


def generate_planted_live_suite(output_dir, plants_per_base=6, seed=20260508, base_paths=None):
    """Generate a small suite of live planted ATPG-redundant benchmarks."""
    os.makedirs(output_dir, exist_ok=True)
    if base_paths is None:
        candidates = [
            "benchmarks/c17.aag",
            "benchmarks/c432.aag",
            "benchmarks/c880.aag",
            "benchmarks/c1355.aag",
            "benchmark_suites/epfl/epfl_random_control_router.aag",
        ]
        base_paths = [path for path in candidates if os.path.exists(path)]

    records = []
    for idx, base_path in enumerate(base_paths):
        if not os.path.exists(base_path):
            continue
        stem = os.path.splitext(os.path.basename(base_path))[0]
        out_path = os.path.join(output_dir, f"planted_live_{stem}.aag")
        try:
            records.extend(
                generate_planted_live_circuit(
                    base_path,
                    out_path,
                    plants=plants_per_base,
                    seed=seed + idx,
                )
            )
        except Exception:
            continue
    return records


def write_planted_live_manifest(path, records):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    fieldnames = [
        "generated_circuit",
        "base_circuit",
        "plant_index",
        "pattern",
        "output_index",
        "source_literal",
        "side_literal",
        "target_literal",
        "expected_stuck",
        "new_output_literal",
        "aux_literals",
    ]
    with open(path, "w", newline="", encoding="ascii") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
