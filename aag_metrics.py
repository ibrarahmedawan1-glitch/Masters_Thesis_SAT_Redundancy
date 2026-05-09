"""Small ASCII AIGER metric helpers used by reports."""


def compute_aag_metrics(path):
    """Return basic AAG metrics, including AND2 area and AIG level depth."""
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
        raise ValueError(f"not an ASCII AIGER file: {path}")

    header = lines[0].split()
    M, I, L, O, A = map(int, header[1:6])
    logic_end = 1 + I + L + O + A
    if len(lines) < logic_end:
        raise ValueError(f"truncated AAG file: {path}")

    inputs = [int(lines[idx]) for idx in range(1, 1 + I)]
    latches = [list(map(int, lines[1 + I + idx].split())) for idx in range(L)]
    outputs = [int(lines[1 + I + L + idx]) for idx in range(O)]
    gate_start = 1 + I + L + O
    gates = [list(map(int, lines[gate_start + idx].split())) for idx in range(A)]

    levels = {0: 0, 1: 0}
    for lit in inputs:
        levels[lit & ~1] = 0
        levels[(lit & ~1) ^ 1] = 0
    for latch in latches:
        curr = latch[0]
        levels[curr & ~1] = 0
        levels[(curr & ~1) ^ 1] = 0

    def lit_level(lit):
        if lit <= 1:
            return 0
        return levels.get(lit & ~1, 0)

    for lhs, r0, r1 in gates:
        level = max(lit_level(r0), lit_level(r1)) + 1
        levels[lhs & ~1] = level
        levels[(lhs & ~1) ^ 1] = level

    observed = list(outputs)
    observed.extend(latch[1] for latch in latches if len(latch) >= 2)
    depth = max((lit_level(lit) for lit in observed), default=0)

    return {
        "M": M,
        "Inputs": I,
        "Latches": L,
        "Outputs": O,
        "Gates": A,
        "Area_AND2": A,
        "Depth": depth,
    }
