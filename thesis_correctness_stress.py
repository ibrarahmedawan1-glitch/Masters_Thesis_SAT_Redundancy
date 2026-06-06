#!/usr/bin/env python3
"""Gatekeeper correctness stress tests for the SAT/AIG optimization pipeline.

This script is intentionally validation-first. It runs optimizers without using
final CEC as an in-loop decision mechanism, then checks produced AAGs afterward
with both the project verifier path and the deterministic ASCII SAT miter when
the circuit size is small enough.
"""

import argparse
import csv
import hashlib
import importlib
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime

from generators import generate_ladder_circuit, generate_parallel_circuit, generate_planted_live_circuit, generate_random_circuit
from optimizer_alg8_hybrid import parse_aag, pure_python_forward_strash, write_aag
from verifier import _verify_ascii_aag_equivalence, verify_equivalence


ALGORITHMS = [
    ("ALG1", "optimizer_alg1"),
    ("ALG2", "optimizer_alg2"),
    ("ALG3", "optimizer_alg3"),
    ("ALG4", "optimizer_alg3_saf"),
    ("ALG5", "optimizer_alg3_sim"),
    ("ALG6", "optimizer_alg3_timeout_cadical"),
    ("ALG7", "optimizer_alg7_iterative"),
    ("ALG8", "optimizer_alg8_hybrid"),
    ("ALG9", "optimizer_alg9_incremental"),
    ("ALG10", "optimizer_alg10_tiered"),
]

ALG_ENV_PREFIXES = ("ALG9_", "ALG10_")

TELEMETRY_KEYS = [
    "SAT_Checks",
    "SAT_Query_SAT",
    "SAT_Query_UNSAT",
    "SAT_Timeouts",
    "SAT_Unresolved",
    "SAT_Abort_Reason",
    "TFI_Query_UNSAT",
    "Window_Query_UNSAT",
    "Window_Audit_Fail",
    "Cone_Query_UNSAT",
    "Global_Query_UNSAT",
    "CEX_Pruning_Enabled",
    "CEX_Pruned",
    "CEX_Audit_Enabled",
    "CEX_Audit_Checked",
    "CEX_Audit_SAT",
    "CEX_Audit_False_Prunes",
    "CEX_Audit_Timeouts",
    "CEX_Audit_Skipped",
    "CEX_Audit_Limit_Hit",
    "Checkpoint_Resume",
    "Window_Enabled",
    "Cone_Enabled",
    "Global_Enabled",
    "Total",
    "SAT",
]


def clear_algorithm_env():
    for key in list(os.environ):
        if key.startswith(ALG_ENV_PREFIXES):
            os.environ.pop(key, None)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in stem)


def aag_gate_count(path):
    return parse_aag(path)[4]


def verify_pair(src, out, require_internal=True):
    abc_status, abc_time = verify_equivalence(src, out)
    internal_status = _verify_ascii_aag_equivalence(src, out)
    ok = abc_status == "PASS"
    if require_internal:
        ok = ok and internal_status == "PASS"
    return ok, abc_status, abc_time, internal_status


def base_row(test, circuit, output, required=True):
    return {
        "Test": test,
        "Circuit": circuit,
        "Output": output,
        "Required": int(required),
        "Result": "PENDING",
        "Reason": "",
        "Algorithm": "",
        "Variant": "",
        "Orig_Gates": "",
        "Final_Gates": "",
        "Removed_Calc": "",
        "Removed_Reported": "",
        "ABC": "",
        "ABC_Time": "",
        "Internal_SAT_Miter": "",
        "Truth_Table": "",
        "Output_SHA256": "",
    }


def finish_row(row, ok, reason=""):
    row["Result"] = "PASS" if ok else "FAIL"
    row["Reason"] = reason
    return row


def add_verification(row, src, out, require_internal=True):
    ok, abc_status, abc_time, internal_status = verify_pair(src, out, require_internal)
    truth_status = truth_table_equivalence(src, out)
    row["ABC"] = abc_status
    row["ABC_Time"] = f"{abc_time:.4f}"
    row["Internal_SAT_Miter"] = internal_status
    row["Truth_Table"] = truth_status
    if os.path.exists(out):
        row["Output_SHA256"] = sha256_file(out)
    if truth_status == "FAIL":
        ok = False
    return ok


def _lit_value(lit, values):
    if lit == 0:
        return False
    if lit == 1:
        return True
    value = values.get(lit & ~1, False)
    return not value if (lit & 1) else value


def _eval_aag_outputs(parsed, assignment_bits):
    _, I, L, _, _, inputs, latches, outputs, gates, _ = parsed
    values = {}
    primary_lits = list(inputs)
    primary_lits.extend(int(latch.split()[0]) for latch in latches)

    for bit, lit in zip(assignment_bits, primary_lits):
        values[lit & ~1] = bool(bit)

    for lhs, r0, r1 in gates:
        values[lhs & ~1] = _lit_value(r0, values) and _lit_value(r1, values)

    observed = [_lit_value(out, values) for out in outputs]
    for latch in latches:
        observed.append(_lit_value(int(latch.split()[1]), values))
    return tuple(observed)


def truth_table_equivalence(src, out, max_primary=12):
    try:
        left = parse_aag(src)
        right = parse_aag(out)
    except Exception:
        return "ERROR"

    if (left[1], left[2], left[3]) != (right[1], right[2], right[3]):
        return "FAIL"

    primary_count = left[1] + left[2]
    if primary_count > max_primary:
        return "SKIP"

    for mask in range(1 << primary_count):
        assignment = [(mask >> idx) & 1 for idx in range(primary_count)]
        if _eval_aag_outputs(left, assignment) != _eval_aag_outputs(right, assignment):
            return "FAIL"
    return "PASS"


def write_odc_redundant_circuit(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="ascii") as f:
        f.write("aag 4 2 0 1 2\n")
        f.write("2\n")
        f.write("4\n")
        f.write("9\n")
        f.write("6 2 4\n")
        f.write("8 7 3\n")
        f.write("i0 x\n")
        f.write("i1 y\n")
        f.write("o0 out\n")
        f.write("c\nODC redundant: out = x OR (x AND y) = x\n")


def write_tfi_constant_circuit(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="ascii") as f:
        f.write("aag 5 2 0 1 3\n")
        f.write("2\n")
        f.write("4\n")
        f.write("10\n")
        f.write("6 2 4\n")
        f.write("8 2 5\n")
        f.write("10 6 8\n")
        f.write("i0 a\n")
        f.write("i1 b\n")
        f.write("o0 out\n")
        f.write("c\nTFI constant: (a & b) & (a & ~b) = 0\n")


def strash_audit(circuits, out_dir):
    rows = []
    for circuit in circuits:
        M, I, L, O, A, inputs, latches, outputs, gates, symbols = parse_aag(circuit)

        roundtrip = os.path.join(out_dir, f"{safe_name(circuit)}_roundtrip.aag")
        write_aag(
            roundtrip,
            M,
            I,
            L,
            O,
            A,
            inputs,
            latches,
            outputs,
            gates,
            symbols,
            "Correctness stress roundtrip",
        )
        row = base_row("roundtrip_write", circuit, roundtrip)
        row["Orig_Gates"] = A
        row["Final_Gates"] = aag_gate_count(roundtrip)
        row["Removed_Calc"] = A - int(row["Final_Gates"])
        ok = add_verification(row, circuit, roundtrip)
        ok = ok and row["Final_Gates"] == row["Orig_Gates"]
        rows.append(finish_row(row, ok, "parse/write changed gate count" if not ok else ""))

        strashed = os.path.join(out_dir, f"{safe_name(circuit)}_zero_commit_strash.aag")
        result = pure_python_forward_strash(M, I, L, O, A, inputs, latches, outputs, gates)
        M_f, I_f, L_f, O_f, A_f, in_f, la_f, out_f, gates_f = result
        write_aag(
            strashed,
            M_f,
            I_f,
            L_f,
            O_f,
            A_f,
            in_f,
            la_f,
            out_f,
            gates_f,
            symbols,
            "Correctness stress zero-commit strash",
        )
        row = base_row("zero_commit_strash", circuit, strashed)
        row["Orig_Gates"] = A
        row["Final_Gates"] = A_f
        row["Removed_Calc"] = A - A_f
        ok = add_verification(row, circuit, strashed)
        rows.append(finish_row(row, ok))
    return rows


def configure_optimizer(label, module_name, tmp_dir):
    clear_algorithm_env()
    if module_name == "optimizer_alg9_incremental":
        os.environ["ALG9_EXHAUSTIVE"] = "1"
        os.environ["ALG9_ALLOW_VERY_LARGE_SAT"] = "1"
        os.environ["ALG9_MAX_CANDIDATES"] = "0"
        os.environ["ALG9_MAX_SAT_SECONDS"] = "20"
    elif module_name == "optimizer_alg10_tiered":
        os.environ["ALG10_MODE"] = "fast_save"
        os.environ["ALG10_CHECKPOINT_DIR"] = os.path.join(tmp_dir, "alg10_smoke_ckpt")
        os.environ["ALG10_RESET_CHECKPOINT"] = "1"
        os.environ["ALG10_MAX_CIRCUIT_SECONDS"] = "30"
        os.environ["ALG10_BUDGETS"] = "100,1000,5000"
        os.environ["ALG10_TFI_CONSTANCY"] = "1"
        os.environ["ALG10_WINDOW_MITER"] = "1"
        os.environ["ALG10_WINDOW_AUDIT"] = "1"
        os.environ["ALG10_CONE_MITER"] = "1"
        os.environ["ALG10_GLOBAL_MITER"] = "1"
        os.environ["ALG10_CEX_PRUNING"] = "1"
        os.environ["ALG10_AUDIT_ASSUMPTIONS"] = "1"
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def normalize_result(result):
    if len(result) == 5:
        orig, _, final, removed, timings = result
    else:
        orig, _, final, _, _, removed, duration = result
        timings = {"Total": duration}
    return orig, final, removed, timings


def algorithm_smoke(cases, out_dir, tmp_dir):
    rows = []
    for label, module_name, circuit in cases:
        out = os.path.join(out_dir, f"{label}_{safe_name(circuit)}.aag")
        row = base_row("algorithm_smoke", circuit, out)
        row["Algorithm"] = label
        try:
            optimizer = configure_optimizer(label, module_name, tmp_dir)
            result = optimizer.solve_circuit(circuit, out)
            orig, final, removed, timings = normalize_result(result)
            row["Orig_Gates"] = orig
            row["Final_Gates"] = final
            row["Removed_Calc"] = orig - final
            row["Removed_Reported"] = removed
            for key in TELEMETRY_KEYS:
                if key in timings:
                    row[key] = timings[key]
            ok = add_verification(row, circuit, out)
            rows.append(finish_row(row, ok))
        except Exception as exc:
            rows.append(finish_row(row, False, repr(exc)))
    return rows


def configure_alg10(env, checkpoint_dir, seconds, budgets, mode="fast_save", reset=True):
    clear_algorithm_env()
    os.environ["ALG10_MODE"] = mode
    os.environ["ALG10_CHECKPOINT_DIR"] = checkpoint_dir
    os.environ["ALG10_RESET_CHECKPOINT"] = "1" if reset else "0"
    os.environ["ALG10_MAX_CIRCUIT_SECONDS"] = str(seconds)
    os.environ["ALG10_BUDGETS"] = budgets
    os.environ["ALG10_MAX_PHASES"] = "100"
    os.environ["ALG10_PRE_STRASH"] = "1"
    os.environ["ALG10_AUDIT_ASSUMPTIONS"] = "1"
    os.environ["ALG10_WINDOW_AUDIT"] = "1"
    os.environ["ALG10_CEX_PRUNING_BATCH_SIZE"] = "512"
    os.environ.update(env)
    sys.modules.pop("optimizer_alg10_tiered", None)
    return importlib.import_module("optimizer_alg10_tiered")


def run_alg10_variant(circuit, variant, env, out_dir, tmp_dir, seconds, budgets, require_internal=True):
    out = os.path.join(out_dir, f"{variant}_{safe_name(circuit)}.aag")
    checkpoint_dir = os.path.join(tmp_dir, "checkpoints", variant, safe_name(circuit))
    row = base_row("alg10_variant", circuit, out)
    row["Algorithm"] = "ALG10"
    row["Variant"] = variant
    try:
        optimizer = configure_alg10(env, checkpoint_dir, seconds, budgets)
        orig, _, final, removed, timings = optimizer.solve_circuit(circuit, out)
        row["Orig_Gates"] = orig
        row["Final_Gates"] = final
        row["Removed_Calc"] = orig - final
        row["Removed_Reported"] = removed
        for key in TELEMETRY_KEYS:
            row[key] = timings.get(key, "")
        ok = add_verification(row, circuit, out, require_internal=require_internal)

        if variant == "full_audited":
            ok = ok and int(timings.get("Window_Audit_Fail", 0)) == 0
            ok = ok and int(timings.get("CEX_Audit_False_Prunes", 0)) == 0
        if variant == "window_isolated":
            ok = ok and int(timings.get("Global_Enabled", 1)) == 0
            ok = ok and int(timings.get("Global_Query_UNSAT", 0)) == 0
            ok = ok and int(timings.get("Cone_Query_UNSAT", 0)) == 0
            ok = ok and int(timings.get("TFI_Query_UNSAT", 0)) == 0
            ok = ok and int(timings.get("Window_Audit_Fail", 0)) == 0
            if orig - final > 0:
                ok = ok and int(timings.get("Window_Query_UNSAT", 0)) > 0
        rows = [finish_row(row, ok)]
    except Exception as exc:
        rows = [finish_row(row, False, repr(exc))]
    return rows


def negative_control(circuit, out_dir):
    corrupt = os.path.join(out_dir, f"{safe_name(circuit)}_corrupt_output.aag")
    shutil.copy(circuit, corrupt)
    M, I, L, O, A, *_ = parse_aag(circuit)
    output_line = 1 + I + L
    with open(corrupt, "r", encoding="ascii") as f:
        lines = f.readlines()
    lines[output_line] = f"{int(lines[output_line].strip()) ^ 1}\n"
    with open(corrupt, "w", encoding="ascii") as f:
        f.writelines(lines)

    row = base_row("negative_control_corrupt_output", circuit, corrupt)
    row["Orig_Gates"] = A
    row["Final_Gates"] = aag_gate_count(corrupt)
    ok, abc_status, abc_time, internal_status = verify_pair(circuit, corrupt)
    row["ABC"] = abc_status
    row["ABC_Time"] = f"{abc_time:.4f}"
    row["Internal_SAT_Miter"] = internal_status
    row["Output_SHA256"] = sha256_file(corrupt)
    caught = abc_status == "FAIL" and internal_status == "FAIL"
    return [finish_row(row, caught, "" if caught else "corruption was not caught")]


def planted_live_probe(base_circuit, out_dir, tmp_dir, seconds, budgets):
    planted = os.path.join(out_dir, f"planted_live_{safe_name(base_circuit)}.aag")
    records = generate_planted_live_circuit(base_circuit, planted, plants=3, seed=20260522)
    env = {
        "ALG10_TFI_CONSTANCY": "1",
        "ALG10_WINDOW_MITER": "1",
        "ALG10_CONE_MITER": "1",
        "ALG10_GLOBAL_MITER": "1",
        "ALG10_CEX_PRUNING": "1",
        "ALG10_AUDIT_CEX_PRUNING": "1",
        "ALG10_AUDIT_CEX_PRUNING_BUDGET": "100000",
    }
    rows = run_alg10_variant(
        planted,
        "planted_live_full_audited",
        env,
        out_dir,
        tmp_dir,
        seconds,
        budgets,
        require_internal=True,
    )
    for row in rows:
        row["Test"] = "planted_live_probe"
        row["Reason"] = row["Reason"] or f"planted_records={len(records)}"
        if row["Result"] == "PASS" and int(row.get("Removed_Calc") or 0) <= 0:
            row["Result"] = "FAIL"
            row["Reason"] = "planted circuit verified but no reduction was found"
    return rows


def generated_small_probes(out_dir, tmp_dir, seconds, budgets):
    input_dir = os.path.join(out_dir, "generated_inputs")
    os.makedirs(input_dir, exist_ok=True)

    circuits = []
    odc = os.path.join(input_dir, "tiny_odc.aag")
    tfi = os.path.join(input_dir, "tiny_tfi_constant.aag")
    ladder = os.path.join(input_dir, "tiny_ladder.aag")
    parallel = os.path.join(input_dir, "tiny_parallel.aag")
    random_plain = os.path.join(input_dir, "tiny_random_plain.aag")
    random_stuck = os.path.join(input_dir, "tiny_random_stuck.aag")
    random_idem = os.path.join(input_dir, "tiny_random_idempotent.aag")

    write_odc_redundant_circuit(odc)
    write_tfi_constant_circuit(tfi)
    generate_ladder_circuit(ladder, depth=8)
    generate_parallel_circuit(parallel, inputs=3, gates=6)

    import random

    random.seed(20260522)
    generate_random_circuit(random_plain, inputs=4, gates=12, injection_mode="none")
    random.seed(20260523)
    generate_random_circuit(random_stuck, inputs=4, gates=12, injection_mode="stuck")
    random.seed(20260524)
    generate_random_circuit(random_idem, inputs=4, gates=12, injection_mode="idempotent")

    circuits.extend([odc, tfi, ladder, parallel, random_plain, random_stuck, random_idem])

    full_env = {
        "ALG10_TFI_CONSTANCY": "1",
        "ALG10_WINDOW_MITER": "1",
        "ALG10_CONE_MITER": "1",
        "ALG10_GLOBAL_MITER": "1",
        "ALG10_CEX_PRUNING": "1",
        "ALG10_AUDIT_CEX_PRUNING": "1",
        "ALG10_AUDIT_CEX_PRUNING_BUDGET": "100000",
    }
    window_env = {
        "ALG10_TFI_CONSTANCY": "0",
        "ALG10_WINDOW_MITER": "1",
        "ALG10_CONE_MITER": "0",
        "ALG10_GLOBAL_MITER": "0",
        "ALG10_CEX_PRUNING": "1",
    }

    rows = []
    for circuit in circuits:
        rows.extend(
            run_alg10_variant(
                circuit,
                "generated_full_audited",
                full_env,
                out_dir,
                tmp_dir,
                seconds,
                budgets,
                require_internal=True,
            )
        )

    # Isolate the riskiest tier on circuits where it is expected to commit.
    for circuit in [odc, random_stuck]:
        rows.extend(
            run_alg10_variant(
                circuit,
                "generated_window_isolated",
                window_env,
                out_dir,
                tmp_dir,
                seconds,
                budgets,
                require_internal=True,
            )
        )

    for row in rows:
        row["Test"] = "generated_small_probe"
        if row["Result"] == "PASS" and row.get("Truth_Table") != "PASS":
            row["Result"] = "FAIL"
            row["Reason"] = "small generated circuit did not get truth-table PASS"
    return rows


def checkpoint_consistency(circuit, out_dir, tmp_dir, seconds, budgets):
    env = {
        "ALG10_TFI_CONSTANCY": "1",
        "ALG10_WINDOW_MITER": "1",
        "ALG10_CONE_MITER": "1",
        "ALG10_GLOBAL_MITER": "1",
        "ALG10_CEX_PRUNING": "1",
    }
    checkpoint_dir = os.path.join(tmp_dir, "checkpoint_consistency", safe_name(circuit))

    continuous_out = os.path.join(out_dir, f"continuous_{safe_name(circuit)}.aag")
    optimizer = configure_alg10(env, checkpoint_dir + "_continuous", seconds, budgets, reset=True)
    c_orig, _, c_final, c_removed, c_timings = optimizer.solve_circuit(circuit, continuous_out)
    c_ok, c_abc, c_abc_time, c_internal = verify_pair(circuit, continuous_out, require_internal=True)

    partial_out = os.path.join(out_dir, f"partial_{safe_name(circuit)}.aag")
    optimizer = configure_alg10(env, checkpoint_dir, 0.001, "1", reset=True)
    p_orig, _, p_final, p_removed, p_timings = optimizer.solve_circuit(circuit, partial_out)
    p_ok, p_abc, p_abc_time, p_internal = verify_pair(circuit, partial_out, require_internal=True)

    resumed_out = os.path.join(out_dir, f"resumed_{safe_name(circuit)}.aag")
    optimizer = configure_alg10(env, checkpoint_dir, seconds, budgets, mode="deep_resume", reset=False)
    r_orig, _, r_final, r_removed, r_timings = optimizer.solve_circuit(circuit, resumed_out)
    r_ok, r_abc, r_abc_time, r_internal = verify_pair(circuit, resumed_out, require_internal=True)

    row = base_row("checkpoint_consistency", circuit, resumed_out)
    row["Algorithm"] = "ALG10"
    row["Variant"] = "continuous_vs_checkpoint_resume"
    row["Orig_Gates"] = r_orig
    row["Final_Gates"] = r_final
    row["Removed_Calc"] = r_orig - r_final
    row["Removed_Reported"] = r_removed
    row["ABC"] = r_abc
    row["ABC_Time"] = f"{r_abc_time:.4f}"
    row["Internal_SAT_Miter"] = r_internal
    row["Output_SHA256"] = sha256_file(resumed_out)
    for key in TELEMETRY_KEYS:
        row[key] = r_timings.get(key, "")

    same_gate_count = c_final == r_final
    row["Reason"] = (
        f"continuous={c_orig}->{c_final}, partial={p_orig}->{p_final}, "
        f"resumed={r_orig}->{r_final}, resumed_flag={r_timings.get('Checkpoint_Resume', 0)}"
    )
    ok = (
        c_ok
        and p_ok
        and r_ok
        and same_gate_count
        and int(r_timings.get("Checkpoint_Resume", 0)) == 1
    )
    return [finish_row(row, ok, row["Reason"])]


def write_rows(rows, csv_path):
    fieldnames = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def print_rows(rows):
    for row in rows:
        status = row["Result"]
        test = row["Test"]
        label = row.get("Algorithm") or "-"
        variant = row.get("Variant") or "-"
        circuit = os.path.basename(row["Circuit"])
        gates = f"{row.get('Orig_Gates', '')}->{row.get('Final_Gates', '')}"
        abc = row.get("ABC", "")
        internal = row.get("Internal_SAT_Miter", "")
        reason = row.get("Reason", "")
        print(f"{status:<4} {test:<32} {label:<5} {variant:<34} {circuit:<30} {gates:<12} ABC={abc:<7} SAT={internal:<7} {reason}")


def main():
    parser = argparse.ArgumentParser(description="Run thesis correctness gatekeeper stress tests.")
    parser.add_argument("--seconds", type=float, default=10.0, help="Per-circuit Algorithm 10 time budget.")
    parser.add_argument("--budgets", default="100,1000,5000", help="Algorithm 10 SAT budgets.")
    parser.add_argument("--include-c7552", action="store_true", help="Add a capped c7552 audit run.")
    parser.add_argument("--include-epfl", action="store_true", help="Add capped EPFL control/arithmetic probes.")
    parser.add_argument("--output-dir", default=None, help="Directory for outputs and CSV.")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_dir = args.output_dir or os.path.join("results_optimized", "correctness_stress", timestamp)
    out_dir = os.path.join(output_dir, "aag_outputs")
    os.makedirs(out_dir, exist_ok=True)

    rows = []
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="thesis_correctness_stress_") as tmp_dir:
        rows.extend(strash_audit(["benchmarks/c17.aag", "benchmarks/c432.aag"], out_dir))

        smoke_cases = [(label, module, "benchmarks/c17.aag") for label, module in ALGORITHMS]
        smoke_cases.extend((label, module, "benchmarks/c432.aag") for label, module in ALGORITHMS[-3:])
        rows.extend(algorithm_smoke(smoke_cases, out_dir, tmp_dir))

        full_env = {
            "ALG10_TFI_CONSTANCY": "1",
            "ALG10_WINDOW_MITER": "1",
            "ALG10_CONE_MITER": "1",
            "ALG10_GLOBAL_MITER": "1",
            "ALG10_CEX_PRUNING": "1",
            "ALG10_AUDIT_CEX_PRUNING": "1",
            "ALG10_AUDIT_CEX_PRUNING_BUDGET": "100000",
        }
        rows.extend(
            run_alg10_variant(
                "benchmarks/c432.aag",
                "full_audited",
                full_env,
                out_dir,
                tmp_dir,
                args.seconds,
                args.budgets,
            )
        )

        window_env = {
            "ALG10_TFI_CONSTANCY": "0",
            "ALG10_WINDOW_MITER": "1",
            "ALG10_CONE_MITER": "0",
            "ALG10_GLOBAL_MITER": "0",
            "ALG10_CEX_PRUNING": "1",
        }
        rows.extend(
            run_alg10_variant(
                "benchmarks/c432.aag",
                "window_isolated",
                window_env,
                out_dir,
                tmp_dir,
                args.seconds,
                args.budgets,
            )
        )

        global_env = {
            "ALG10_TFI_CONSTANCY": "0",
            "ALG10_WINDOW_MITER": "0",
            "ALG10_CONE_MITER": "0",
            "ALG10_GLOBAL_MITER": "1",
            "ALG10_CEX_PRUNING": "0",
        }
        rows.extend(
            run_alg10_variant(
                "benchmarks/c432.aag",
                "global_only_assumption_audit",
                global_env,
                out_dir,
                tmp_dir,
                args.seconds,
                args.budgets,
            )
        )

        rows.extend(planted_live_probe("benchmarks/c17.aag", out_dir, tmp_dir, args.seconds, args.budgets))
        rows.extend(generated_small_probes(out_dir, tmp_dir, args.seconds, args.budgets))
        rows.extend(checkpoint_consistency("benchmarks/c432.aag", out_dir, tmp_dir, args.seconds, args.budgets))
        rows.extend(negative_control("benchmarks/c17.aag", out_dir))

        if args.include_c7552:
            capped_env = dict(full_env)
            capped_env["ALG10_AUDIT_CEX_PRUNING_MAX"] = "5000"
            rows.extend(
                run_alg10_variant(
                    "benchmarks/c7552.aag",
                    "c7552_capped_audit",
                    capped_env,
                    out_dir,
                    tmp_dir,
                    args.seconds,
                    args.budgets,
                    require_internal=False,
                )
            )

        if args.include_epfl:
            capped_env = dict(full_env)
            capped_env["ALG10_AUDIT_CEX_PRUNING_MAX"] = "3000"
            for circuit in [
                "benchmark_suites/epfl/epfl_random_control_router.aag",
                "benchmark_suites/epfl/epfl_arithmetic_sin.aag",
                "benchmark_suites/epfl/epfl_arithmetic_sqrt.aag",
            ]:
                if not os.path.exists(circuit):
                    continue
                rows.extend(
                    run_alg10_variant(
                        circuit,
                        "epfl_capped_audit",
                        capped_env,
                        out_dir,
                        tmp_dir,
                        args.seconds,
                        args.budgets,
                        require_internal=False,
                    )
                )

    csv_path = os.path.join(output_dir, "correctness_stress.csv")
    write_rows(rows, csv_path)
    print_rows(rows)

    required_failures = [row for row in rows if row["Required"] == 1 and row["Result"] != "PASS"]
    print(f"\nWrote: {csv_path}")
    print(f"Elapsed: {time.time() - t0:.2f}s")
    if required_failures:
        print(f"REQUIRED FAILURES: {len(required_failures)}")
        raise SystemExit(1)
    print("All required correctness stress checks passed.")


if __name__ == "__main__":
    main()
