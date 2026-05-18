import os
import csv
import shutil
import glob          
import random
import time
import importlib
from datetime import datetime
from aag_metrics import compute_aag_metrics
from abc_utils import to_ascii_aag
from generators import (
    generate_planted_live_suite,
    generate_random_circuit,
    generate_ladder_circuit,
    generate_parallel_circuit,
    write_planted_live_manifest,
)
from verifier import verify_equivalence

DATASET_DIR = "dataset_benchmarks"
RESULTS_BASE_DIR = "results_optimized"
RUN_SUBDIR = "latest_run" 
CURRENT_RUN_DIR = os.path.join(RESULTS_BASE_DIR, RUN_SUBDIR)
BENCHMARK_SUITE_DIR = "benchmark_suites"
CUSTOM_CIRCUIT_PATH = os.environ.get("CUSTOM_CIRCUIT_PATH", "custom_circuits")
INCLUDE_BENCHMARK_SUITES = os.environ.get("INCLUDE_BENCHMARK_SUITES", "1") != "0"
INCLUDE_ISCAS_BENCHMARKS = os.environ.get("INCLUDE_ISCAS_BENCHMARKS", "1") != "0"
INCLUDE_CUSTOM_CIRCUITS = os.environ.get("INCLUDE_CUSTOM_CIRCUITS", "0") != "0"
MAX_DATASET_GATES = int(os.environ.get("MAX_DATASET_GATES", "0"))
INCLUDE_SYNTHETIC_FUZZ = os.environ.get("INCLUDE_SYNTHETIC_FUZZ", "1") != "0"
INCLUDE_PLANTED_LIVE = os.environ.get("INCLUDE_PLANTED_LIVE", "1") != "0"
ONLY_PLANTED_LIVE = os.environ.get("ONLY_PLANTED_LIVE", "0") != "0"
PLANTED_LIVE_PER_BASE = int(os.environ.get("PLANTED_LIVE_PER_BASE", "6"))
PLANTED_LIVE_SEED = int(os.environ.get("PLANTED_LIVE_SEED", "20260508"))
RUN_MODE_LABEL = os.environ.get("RUN_MODE_LABEL", "default")
DATASET_PROFILE_LABEL = os.environ.get("DATASET_PROFILE_LABEL", "default")

def setup_directories():
    if os.path.exists(DATASET_DIR): shutil.rmtree(DATASET_DIR)
    os.makedirs(DATASET_DIR)
    if os.path.exists(CURRENT_RUN_DIR): shutil.rmtree(CURRENT_RUN_DIR)
    os.makedirs(CURRENT_RUN_DIR)

def normalize_names(file_path):
    try:
        with open(file_path, 'r', errors='ignore') as f: lines = f.readlines()
        if not lines or not lines[0].startswith('aag'): return
        header = lines[0].strip().split()
        I, L, O, A = int(header[2]), int(header[3]), int(header[4]), int(header[5])
        logic_end = 1 + I + L + O + A
        
        with open(file_path, 'w') as f:
            for i in range(min(len(lines), logic_end)): 
                f.write(lines[i].strip() + '\n')
            for k in range(I): f.write(f"i{k} pi_{k}\n")
            for k in range(O): f.write(f"o{k} po_{k}\n")
            f.write("c\nNormalized\n")
    except Exception as e: pass

def copy_prepared_benchmark_suites():
    copied = 0
    if not INCLUDE_BENCHMARK_SUITES or not os.path.exists(BENCHMARK_SUITE_DIR):
        return copied

    for src in sorted(glob.glob(os.path.join(BENCHMARK_SUITE_DIR, "**", "*.aag"), recursive=True)):
        rel = os.path.relpath(src, BENCHMARK_SUITE_DIR)
        flat_name = rel.replace(os.sep, "_")
        shutil.copy(src, os.path.join(DATASET_DIR, flat_name))
        copied += 1
    return copied

def unique_dataset_name(prefix, src, used_names):
    stem = os.path.splitext(os.path.basename(src))[0]
    candidate = f"{prefix}_{stem}.aag"
    suffix = 1
    while candidate in used_names or os.path.exists(os.path.join(DATASET_DIR, candidate)):
        candidate = f"{prefix}_{stem}_{suffix}.aag"
        suffix += 1
    used_names.add(candidate)
    return candidate

def find_custom_sources(source_path):
    if not source_path:
        return []
    if os.path.isfile(source_path):
        return [source_path] if source_path.lower().endswith((".aag", ".aig")) else []
    if not os.path.isdir(source_path):
        return []

    sources = []
    for pattern in ("**/*.aag", "**/*.aig"):
        sources.extend(glob.glob(os.path.join(source_path, pattern), recursive=True))
    return sorted(set(sources))

def copy_custom_circuits(source_path):
    if not INCLUDE_CUSTOM_CIRCUITS:
        return 0
    if not os.path.exists(source_path) and source_path == "custom_circuits":
        os.makedirs(source_path, exist_ok=True)

    copied = 0
    used_names = set()
    sources = find_custom_sources(source_path)
    if not sources:
        print(f"    No custom .aag/.aig circuits found at: {source_path}")
        return copied

    for src in sources:
        dst_name = unique_dataset_name("custom", src, used_names)
        dst = os.path.join(DATASET_DIR, dst_name)
        if src.lower().endswith(".aag"):
            shutil.copy(src, dst)
            copied += 1
        elif to_ascii_aag(src, dst, comment="Custom binary AIG converted for thesis pipeline"):
            copied += 1
        else:
            print(f"    Could not convert custom circuit: {src}")
    return copied

def prompt_choice(prompt, valid_choices, default):
    try:
        raw = input(prompt).strip()
    except EOFError:
        raw = ""
    if not raw:
        return default
    if raw in valid_choices:
        return raw
    print(f"Invalid choice. Defaulting to {default}.")
    return default

def set_flag(name, enabled):
    os.environ[name] = "1" if enabled else "0"

def set_int(name, value):
    os.environ[name] = str(int(value))

def configure_algorithm9_run():
    """Collect Algorithm 9 mode and dataset profile before importing the module."""
    global INCLUDE_BENCHMARK_SUITES, INCLUDE_ISCAS_BENCHMARKS, INCLUDE_CUSTOM_CIRCUITS
    global MAX_DATASET_GATES, INCLUDE_SYNTHETIC_FUZZ
    global INCLUDE_PLANTED_LIVE, ONLY_PLANTED_LIVE, PLANTED_LIVE_PER_BASE
    global RUN_MODE_LABEL, DATASET_PROFILE_LABEL, CUSTOM_CIRCUIT_PATH

    print("\n" + "="*60)
    print("   ALG 9 IN-MEMORY SAT MODE")
    print("="*60)
    print(" 1: Fast filtered run (default thesis mode)")
    print(" 2: Exhaustive stuck-at sweep (gate-capped at 50k)")
    print(" 3: Large-circuit filtered survey (allows very-large SAT)")
    print(" 4: Full exhaustive stuck-at sweep (no gate cap, no SAT time abort)")
    print("="*60)
    mode = prompt_choice("Select Alg 9 mode (1-4) [1]: ", {"1", "2", "3", "4"}, "1")

    if mode == "2":
        RUN_MODE_LABEL = "alg9_exhaustive_cap50k"
        set_flag("ALG9_EXHAUSTIVE", True)
        set_flag("ALG9_ALLOW_VERY_LARGE_SAT", False)
        set_int("ALG9_MAX_CANDIDATES", 0)
        set_int("ALG9_MAX_SAT_SECONDS", 120)
        MAX_DATASET_GATES = 50000
    elif mode == "3":
        RUN_MODE_LABEL = "alg9_large_filtered"
        set_flag("ALG9_EXHAUSTIVE", False)
        set_flag("ALG9_ALLOW_VERY_LARGE_SAT", True)
        set_int("ALG9_MAX_CANDIDATES", 3000)
        set_int("ALG9_LARGE_MAX_CANDIDATES", 100)
        set_int("ALG9_MAX_SAT_SECONDS", 60)
        MAX_DATASET_GATES = 0
    elif mode == "4":
        RUN_MODE_LABEL = "alg9_exhaustive_full"
        set_flag("ALG9_EXHAUSTIVE", True)
        set_flag("ALG9_ALLOW_VERY_LARGE_SAT", True)
        set_int("ALG9_MAX_CANDIDATES", 0)
        set_int("ALG9_MAX_SAT_SECONDS", 0)
        set_int("ALG9_MAX_CONSEC_TIMEOUTS", 0)
        set_int("ALG9_MIN_CHECKS_TIMEOUT_RATE", 0)
        set_int("ALG9_REBUILD_AFTER_COMMITS", 1000000000)
        set_int("ALG9_MAX_PASSES", 20)
        MAX_DATASET_GATES = 0
    else:
        RUN_MODE_LABEL = "alg9_fast_filtered"
        set_flag("ALG9_EXHAUSTIVE", False)
        set_flag("ALG9_ALLOW_VERY_LARGE_SAT", False)
        set_int("ALG9_MAX_CANDIDATES", 2000)
        set_int("ALG9_LARGE_MAX_CANDIDATES", 100)
        set_int("ALG9_MAX_SAT_SECONDS", 30)
        MAX_DATASET_GATES = 0

    set_int("MAX_DATASET_GATES", MAX_DATASET_GATES)
    os.environ["RUN_MODE_LABEL"] = RUN_MODE_LABEL

    print("\n" + "="*60)
    print("   DATASET PROFILE")
    print("="*60)
    print(" 1: Full mixed run (fuzz + ISCAS + EPFL/prepared + planted-live)")
    print(" 2: Planted-live only (quick ATPG sanity check)")
    print(" 3: Real suites + planted-live (ISCAS + EPFL/prepared, no fuzz)")
    print(" 4: Fuzz + planted-live only (synthetic AIGER fuzz, no real suites)")
    print(" 5: Custom circuit(s) only (.aag/.aig file or folder)")
    print("="*60)
    profile = prompt_choice("Select dataset profile (1-5) [1]: ", {"1", "2", "3", "4", "5"}, "1")

    if profile == "2":
        DATASET_PROFILE_LABEL = "planted_live_only"
        INCLUDE_SYNTHETIC_FUZZ = False
        INCLUDE_ISCAS_BENCHMARKS = False
        INCLUDE_BENCHMARK_SUITES = False
        INCLUDE_CUSTOM_CIRCUITS = False
        INCLUDE_PLANTED_LIVE = True
        ONLY_PLANTED_LIVE = True
    elif profile == "3":
        DATASET_PROFILE_LABEL = "real_suites_planted"
        INCLUDE_SYNTHETIC_FUZZ = False
        INCLUDE_ISCAS_BENCHMARKS = True
        INCLUDE_BENCHMARK_SUITES = True
        INCLUDE_CUSTOM_CIRCUITS = False
        INCLUDE_PLANTED_LIVE = True
        ONLY_PLANTED_LIVE = False
    elif profile == "4":
        DATASET_PROFILE_LABEL = "fuzz_planted"
        INCLUDE_SYNTHETIC_FUZZ = True
        INCLUDE_ISCAS_BENCHMARKS = False
        INCLUDE_BENCHMARK_SUITES = False
        INCLUDE_CUSTOM_CIRCUITS = False
        INCLUDE_PLANTED_LIVE = True
        ONLY_PLANTED_LIVE = False
    elif profile == "5":
        DATASET_PROFILE_LABEL = "custom_only"
        INCLUDE_SYNTHETIC_FUZZ = False
        INCLUDE_ISCAS_BENCHMARKS = False
        INCLUDE_BENCHMARK_SUITES = False
        INCLUDE_CUSTOM_CIRCUITS = True
        INCLUDE_PLANTED_LIVE = False
        ONLY_PLANTED_LIVE = False
        try:
            raw = input(f"Custom file/folder path [{CUSTOM_CIRCUIT_PATH}]: ").strip()
            if raw:
                CUSTOM_CIRCUIT_PATH = raw
        except EOFError:
            pass
    else:
        DATASET_PROFILE_LABEL = "full_mixed"
        INCLUDE_SYNTHETIC_FUZZ = True
        INCLUDE_ISCAS_BENCHMARKS = True
        INCLUDE_BENCHMARK_SUITES = True
        INCLUDE_CUSTOM_CIRCUITS = False
        INCLUDE_PLANTED_LIVE = True
        ONLY_PLANTED_LIVE = False

    if INCLUDE_PLANTED_LIVE:
        try:
            raw = input(f"Plants per base for planted-live circuits [{PLANTED_LIVE_PER_BASE}]: ").strip()
            if raw:
                PLANTED_LIVE_PER_BASE = max(0, int(raw))
        except (EOFError, ValueError):
            print(f"Keeping planted-live count at {PLANTED_LIVE_PER_BASE}.")

    set_flag("INCLUDE_SYNTHETIC_FUZZ", INCLUDE_SYNTHETIC_FUZZ)
    set_flag("INCLUDE_ISCAS_BENCHMARKS", INCLUDE_ISCAS_BENCHMARKS)
    set_flag("INCLUDE_BENCHMARK_SUITES", INCLUDE_BENCHMARK_SUITES)
    set_flag("INCLUDE_CUSTOM_CIRCUITS", INCLUDE_CUSTOM_CIRCUITS)
    set_flag("INCLUDE_PLANTED_LIVE", INCLUDE_PLANTED_LIVE)
    set_flag("ONLY_PLANTED_LIVE", ONLY_PLANTED_LIVE)
    set_int("PLANTED_LIVE_PER_BASE", PLANTED_LIVE_PER_BASE)
    os.environ["DATASET_PROFILE_LABEL"] = DATASET_PROFILE_LABEL
    os.environ["CUSTOM_CIRCUIT_PATH"] = CUSTOM_CIRCUIT_PATH

    gate_cap = MAX_DATASET_GATES if MAX_DATASET_GATES > 0 else "none"
    print("\n[Alg 9 config]")
    print(f"    Mode: {RUN_MODE_LABEL}")
    print(f"    Dataset profile: {DATASET_PROFILE_LABEL}")
    print(f"    Gate cap: {gate_cap}")
    if INCLUDE_CUSTOM_CIRCUITS:
        print(f"    Custom circuit path: {CUSTOM_CIRCUIT_PATH}")
    print(f"    Planted-live plants/base: {PLANTED_LIVE_PER_BASE}")

def configure_algorithm10_run():
    """Collect Algorithm 10 mode/profile before importing the module."""
    global INCLUDE_BENCHMARK_SUITES, INCLUDE_ISCAS_BENCHMARKS, INCLUDE_CUSTOM_CIRCUITS
    global MAX_DATASET_GATES, INCLUDE_SYNTHETIC_FUZZ
    global INCLUDE_PLANTED_LIVE, ONLY_PLANTED_LIVE, PLANTED_LIVE_PER_BASE
    global RUN_MODE_LABEL, DATASET_PROFILE_LABEL, CUSTOM_CIRCUIT_PATH

    print("\n" + "="*60)
    print("   ALG 10 CHECKPOINTED SAT MODE")
    print("="*60)
    print(" 1: Fast save/checkpoint mode (bounded per circuit)")
    print(" 2: Deep resume mode (larger budgets, longer per circuit)")
    print("="*60)
    mode = prompt_choice("Select Alg 10 mode (1-2) [1]: ", {"1", "2"}, "1")

    if mode == "2":
        RUN_MODE_LABEL = "alg10_deep_resume_cex_window"
        os.environ["ALG10_MODE"] = "deep_resume"
        os.environ.setdefault("ALG10_BUDGETS", "1000,5000,20000,100000")
        os.environ.setdefault("ALG10_MAX_CIRCUIT_SECONDS", "600")
        set_int("ALG10_REBUILD_AFTER_COMMITS", 100)
    else:
        RUN_MODE_LABEL = "alg10_fast_save_cex_window"
        os.environ["ALG10_MODE"] = "fast_save"
        os.environ.setdefault("ALG10_BUDGETS", "100,1000,5000")
        os.environ.setdefault("ALG10_MAX_CIRCUIT_SECONDS", "60")
        set_int("ALG10_REBUILD_AFTER_COMMITS", 100)

    # Best tested Algorithm 10 profile as of 2026-05-17:
    # current ordering + TFI + audited bounded window + exact cone + global fallback
    # with rejection-only CEX pruning. Environment variables may still override it.
    os.environ.setdefault("ALG10_TFI_CONSTANCY", "1")
    os.environ.setdefault("ALG10_WINDOW_MITER", "1")
    os.environ.setdefault("ALG10_WINDOW_AUDIT", "1")
    os.environ.setdefault("ALG10_WINDOW_LEVELS", "5")
    os.environ.setdefault("ALG10_CONE_MITER", "1")
    os.environ.setdefault("ALG10_CANDIDATE_ORDER", "current")
    os.environ.setdefault("ALG10_CEX_PRUNING", "1")
    os.environ.setdefault("ALG10_CEX_PRUNING_BATCH_SIZE", "512")

    MAX_DATASET_GATES = 0
    set_int("MAX_DATASET_GATES", MAX_DATASET_GATES)
    os.environ["RUN_MODE_LABEL"] = RUN_MODE_LABEL

    print("\n" + "="*60)
    print("   DATASET PROFILE")
    print("="*60)
    print(" 1: Full mixed run (fuzz + ISCAS + EPFL/prepared + planted-live)")
    print(" 2: Planted-live only (quick ATPG sanity check)")
    print(" 3: Real suites + planted-live (ISCAS + EPFL/prepared, no fuzz)")
    print(" 4: Fuzz + planted-live only (synthetic AIGER fuzz, no real suites)")
    print(" 5: Custom circuit(s) only (.aag/.aig file or folder)")
    print("="*60)
    profile = prompt_choice("Select dataset profile (1-5) [5]: ", {"1", "2", "3", "4", "5"}, "5")

    if profile == "1":
        DATASET_PROFILE_LABEL = "full_mixed"
        INCLUDE_SYNTHETIC_FUZZ = True
        INCLUDE_ISCAS_BENCHMARKS = True
        INCLUDE_BENCHMARK_SUITES = True
        INCLUDE_CUSTOM_CIRCUITS = False
        INCLUDE_PLANTED_LIVE = True
        ONLY_PLANTED_LIVE = False
    elif profile == "2":
        DATASET_PROFILE_LABEL = "planted_live_only"
        INCLUDE_SYNTHETIC_FUZZ = False
        INCLUDE_ISCAS_BENCHMARKS = False
        INCLUDE_BENCHMARK_SUITES = False
        INCLUDE_CUSTOM_CIRCUITS = False
        INCLUDE_PLANTED_LIVE = True
        ONLY_PLANTED_LIVE = True
    elif profile == "3":
        DATASET_PROFILE_LABEL = "real_suites_planted"
        INCLUDE_SYNTHETIC_FUZZ = False
        INCLUDE_ISCAS_BENCHMARKS = True
        INCLUDE_BENCHMARK_SUITES = True
        INCLUDE_CUSTOM_CIRCUITS = False
        INCLUDE_PLANTED_LIVE = True
        ONLY_PLANTED_LIVE = False
    elif profile == "4":
        DATASET_PROFILE_LABEL = "fuzz_planted"
        INCLUDE_SYNTHETIC_FUZZ = True
        INCLUDE_ISCAS_BENCHMARKS = False
        INCLUDE_BENCHMARK_SUITES = False
        INCLUDE_CUSTOM_CIRCUITS = False
        INCLUDE_PLANTED_LIVE = True
        ONLY_PLANTED_LIVE = False
    else:
        DATASET_PROFILE_LABEL = "custom_only"
        INCLUDE_SYNTHETIC_FUZZ = False
        INCLUDE_ISCAS_BENCHMARKS = False
        INCLUDE_BENCHMARK_SUITES = False
        INCLUDE_CUSTOM_CIRCUITS = True
        INCLUDE_PLANTED_LIVE = False
        ONLY_PLANTED_LIVE = False
        try:
            raw = input(f"Custom file/folder path [{CUSTOM_CIRCUIT_PATH}]: ").strip()
            if raw:
                CUSTOM_CIRCUIT_PATH = raw
        except EOFError:
            pass

    if INCLUDE_PLANTED_LIVE:
        try:
            raw = input(f"Plants per base for planted-live circuits [{PLANTED_LIVE_PER_BASE}]: ").strip()
            if raw:
                PLANTED_LIVE_PER_BASE = max(0, int(raw))
        except (EOFError, ValueError):
            print(f"Keeping planted-live count at {PLANTED_LIVE_PER_BASE}.")

    set_flag("INCLUDE_SYNTHETIC_FUZZ", INCLUDE_SYNTHETIC_FUZZ)
    set_flag("INCLUDE_ISCAS_BENCHMARKS", INCLUDE_ISCAS_BENCHMARKS)
    set_flag("INCLUDE_BENCHMARK_SUITES", INCLUDE_BENCHMARK_SUITES)
    set_flag("INCLUDE_CUSTOM_CIRCUITS", INCLUDE_CUSTOM_CIRCUITS)
    set_flag("INCLUDE_PLANTED_LIVE", INCLUDE_PLANTED_LIVE)
    set_flag("ONLY_PLANTED_LIVE", ONLY_PLANTED_LIVE)
    set_int("PLANTED_LIVE_PER_BASE", PLANTED_LIVE_PER_BASE)
    os.environ["DATASET_PROFILE_LABEL"] = DATASET_PROFILE_LABEL
    os.environ["CUSTOM_CIRCUIT_PATH"] = CUSTOM_CIRCUIT_PATH

    print("\n[Alg 10 config]")
    print(f"    Mode: {RUN_MODE_LABEL}")
    print(f"    Dataset profile: {DATASET_PROFILE_LABEL}")
    print(f"    Budgets: {os.environ.get('ALG10_BUDGETS')}")
    print(f"    Max circuit seconds: {os.environ.get('ALG10_MAX_CIRCUIT_SECONDS')}")
    print(f"    Candidate order: {os.environ.get('ALG10_CANDIDATE_ORDER', 'current')}")
    print(f"    TFI constancy: {os.environ.get('ALG10_TFI_CONSTANCY', '1')}")
    print(f"    Window miter: {os.environ.get('ALG10_WINDOW_MITER', '0')}")
    print(f"    Window audit: {os.environ.get('ALG10_WINDOW_AUDIT', '1')}")
    print(f"    Cone miter: {os.environ.get('ALG10_CONE_MITER', '1')}")
    print(f"    CEX pruning: {os.environ.get('ALG10_CEX_PRUNING', '0')}")
    print(f"    CEX audit: {os.environ.get('ALG10_AUDIT_CEX_PRUNING', '0')}")
    print(f"    Checkpoint dir: {os.environ.get('ALG10_CHECKPOINT_DIR', 'results_optimized/alg10_checkpoints')}")
    if INCLUDE_CUSTOM_CIRCUITS:
        print(f"    Custom circuit path: {CUSTOM_CIRCUIT_PATH}")

def select_optimizer():
    """Interactive menu to route to the correct algorithm file."""
    print("\n" + "="*60)
    print("   SELECT OPTIMIZATION ALGORITHM ENGINE")
    print("="*60)
    print(" 1: Alg 1 - Naive SAT Miter (Slowest, Baseline)")
    print(" 2: Alg 2 - Structural Universal Machine")
    print(" 3: Alg 3 - Incremental ATPG (Base)")
    print(" 4: Alg 3 - SAF Batch Injection")
    print(" 5: Alg 3 - Simulation Filter + Incremental (Fastest)")
    print(" 6: Alg 3 - Budget/Timeout with Cadical")
    print(" 7: Alg 7 - Sim Filter + Iterative Surgery (100% Accurate)")
    print(" 8: Alg 8 - Pure Python Hybrid Engine + ABC CEC Verification")
    print(" 9: Alg 9 - Committed In-Memory Incremental SAT")
    print("10: Alg10 - Checkpointed Budget-Cycling Global SAT")
    print("="*60)

    mapping = {
        "1": "optimizer_alg1",
        "2": "optimizer_alg2",
        "3": "optimizer_alg3",
        "4": "optimizer_alg3_saf",
        "5": "optimizer_alg3_sim",
        "6": "optimizer_alg3_timeout_cadical",
        "7": "optimizer_alg7_iterative",
        "8": "optimizer_alg8_hybrid",
        "9": "optimizer_alg9_incremental",
        "10": "optimizer_alg10_tiered"
    }

    choice = prompt_choice("Enter choice (1-10): ", set(mapping), "9")
    return mapping[choice], choice

if __name__ == "__main__":
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    setup_directories()
    
    # --- INTERACTIVE SELECTION ---
    algo_module_name, algo_id = select_optimizer()
    if algo_id == "9":
        configure_algorithm9_run()
    elif algo_id == "10":
        configure_algorithm10_run()

    print(f"\n[+] Loading Engine: {algo_module_name}.py")
    
    # Dynamically load the chosen python file
    optimizer = importlib.import_module(algo_module_name)
    
    report_tag = f"ALG{algo_id}"
    if algo_id in {"9", "10"}:
        report_tag = f"ALG{algo_id}_{RUN_MODE_LABEL}_{DATASET_PROFILE_LABEL}"
    REPORT_FILE = os.path.join(RESULTS_BASE_DIR, f"thesis_results_{report_tag}_{timestamp}.csv")

    print(f"\n--- THESIS PIPELINE STARTED [{timestamp}] ---")
    print(f"    Saving report to: {REPORT_FILE}")

    # --- DATASET GENERATION (COMMERCIAL SCALE) ---
    print("\n[1] Generating Test Dataset...")
    if INCLUDE_SYNTHETIC_FUZZ and not ONLY_PLANTED_LIVE:
        generate_ladder_circuit(f"{DATASET_DIR}/ladder_logic.aag", depth=100)
        generate_parallel_circuit(f"{DATASET_DIR}/parallel_struct.aag", inputs=10, gates=50)

        print("    Generating 50 Stuck-at circuits...")
        for i in range(50):
            generate_random_circuit(f"{DATASET_DIR}/fuzz_stuck_{i}.aag", inputs=random.randint(10, 40), gates=random.randint(100, 1500), injection_mode='stuck')

        print("    Generating 50 Idempotent circuits...")
        for i in range(50):
            generate_random_circuit(f"{DATASET_DIR}/fuzz_idem_{i}.aag", inputs=random.randint(10, 40), gates=random.randint(100, 1500), injection_mode='idempotent')

        print("    Generating 100 Pure Random circuits...")
        for i in range(100):
            generate_random_circuit(f"{DATASET_DIR}/fuzz_pure_{i}.aag", inputs=random.randint(10, 40), gates=random.randint(100, 1500), injection_mode='none')

    planted_records = []
    if INCLUDE_PLANTED_LIVE:
        print(f"    Generating planted-live ATPG circuits ({PLANTED_LIVE_PER_BASE} plants/base)...")
        planted_records = generate_planted_live_suite(
            DATASET_DIR,
            plants_per_base=PLANTED_LIVE_PER_BASE,
            seed=PLANTED_LIVE_SEED,
        )
        manifest_path = os.path.join(RESULTS_BASE_DIR, f"planted_live_manifest_{timestamp}.csv")
        write_planted_live_manifest(manifest_path, planted_records)
        print(f"    Planted {len(planted_records)} live ATPG redundancies.")
        print(f"    Planted manifest: {manifest_path}")
    print("Done.")

    print("\n[2] Loading ISCAS Benchmarks...")
    if INCLUDE_ISCAS_BENCHMARKS and os.path.exists("benchmarks") and not ONLY_PLANTED_LIVE:
        for f in glob.glob("benchmarks/*.aag"): shutil.copy(f, DATASET_DIR)
    else:
        print("    Skipped by dataset profile.")

    suite_count = 0 if ONLY_PLANTED_LIVE else copy_prepared_benchmark_suites()
    if suite_count:
        print(f"    Loaded {suite_count} prepared benchmark-suite circuits.")

    custom_count = copy_custom_circuits(CUSTOM_CIRCUIT_PATH)
    if custom_count:
        print(f"    Loaded {custom_count} custom circuit(s).")

    print("\n[3] Normalizing Dataset...")
    for f in sorted(glob.glob(f"{DATASET_DIR}/*.aag")): normalize_names(f)

    # --- EXECUTION ENGINE ---
    print(f"\n[4] Running Engine ({algo_module_name})...")
    stats = []

    for f_path in sorted(glob.glob(f"{DATASET_DIR}/*.aag")):
        name = os.path.basename(f_path)
        opt_path = os.path.join(CURRENT_RUN_DIR, name)
        
        category = "Benchmark"
        if name.startswith("planted_live_"):
            category = "Planted_Live"
        elif "fuzz" in name:
            if "pure" in name: category = "Pure_Random"
            elif "stuck" in name: category = "Injected_Stuck"
            elif "idem" in name: category = "Injected_Idem"
        elif "ladder" in name: category = "Structural_Ladder"
        elif "parallel" in name: category = "Structural_Parallel"
        elif name.startswith("epfl_"): category = "EPFL"
        elif name.startswith("iscas_"): category = "ISCAS"
        elif name.startswith("external_"): category = "External"
        elif name.startswith("custom_"): category = "Custom"

        try:
            input_metrics = compute_aag_metrics(f_path)
            if MAX_DATASET_GATES > 0 and input_metrics["Gates"] > MAX_DATASET_GATES:
                print(f"    Processing {name:<25}... skipped over gate cap ({input_metrics['Gates']} > {MAX_DATASET_GATES}).")
                stats.append([
                    name, category, RUN_MODE_LABEL, DATASET_PROFILE_LABEL,
                    input_metrics["Gates"], input_metrics["Gates"], 0, "0.00%",
                    input_metrics["Area_AND2"], input_metrics["Area_AND2"], 0, "0.00%",
                    input_metrics["Depth"], input_metrics["Depth"], "0.00%",
                    "0", "0", "0", "0", "0", "0",
                    0, 0, 0, 0, 0, "SKIPPED_GATE_LIMIT",
                    input_metrics["Area_AND2"], input_metrics["Area_AND2"], input_metrics["Area_AND2"],
                    0, 0, 0, 0, 0, "", "", "", "", "", "", "", "", "", "", "",
                    "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "SKIPPED_GATE_LIMIT"
                ])
                continue
        except Exception:
            input_metrics = None
        
        print(f"    Processing {name:<25}...", end=" ", flush=True)
        try:
            # Handle the different return signatures dynamically
            if algo_id in ["5", "7", "8", "9", "10"]:
                orig, _, final, removed, timings = optimizer.solve_circuit(f_path, opt_path)
            else:
                orig, _, final, _, _, removed, dur = optimizer.solve_circuit(f_path, opt_path)
                # Synthesize the timings dictionary for algorithms that don't track deep telemetry
                timings = {"Parse": 0.0, "Filter": 0.0, "Encode": 0.0, "SAT": 0.0, "Total": dur}
            
            print(f"SAT Done. Verifying...", end=" ", flush=True)
            status, cec_time = verify_equivalence(f_path, opt_path)
            
            before_metrics = input_metrics or compute_aag_metrics(f_path)
            after_metrics = compute_aag_metrics(opt_path)

            red_total = ((orig - final)/orig * 100) if orig > 0 else 0.0
            area_before = before_metrics["Area_AND2"]
            area_after = after_metrics["Area_AND2"]
            area_saved = max(0, area_before - area_after)
            area_red = ((area_saved / area_before) * 100) if area_before > 0 else 0.0
            depth_before = before_metrics["Depth"]
            depth_after = after_metrics["Depth"]
            depth_red = ((depth_before - depth_after) / depth_before * 100) if depth_before > 0 else 0.0
            print(
                f"Removed: {removed}. AND2 area saved: {area_saved} nodes. "
                f"Status: {status}. SAT: {timings['SAT']:.2f}s | "
                f"CEC: {cec_time:.2f}s | Total: {timings['Total']:.2f}s"
            )
            
            stats.append([
                name, category, RUN_MODE_LABEL, DATASET_PROFILE_LABEL,
                orig, final, removed, f"{red_total:.2f}%",
                area_before, area_after, area_saved, f"{area_red:.2f}%",
                depth_before, depth_after, f"{depth_red:.2f}%",
                f"{timings['Parse']:.4f}", f"{timings['Filter']:.4f}", 
                f"{timings['Encode']:.4f}", f"{timings['SAT']:.4f}", 
                f"{cec_time:.4f}", f"{timings['Total']:.4f}",
                timings.get("SAT_Candidates", ""), timings.get("SAT_Checks", ""),
                timings.get("SAT_Query_SAT", ""), timings.get("SAT_Query_UNSAT", ""),
                timings.get("SAT_Timeouts", ""), timings.get("SAT_Abort_Reason", ""),
                timings.get("Initial_AND2", ""), timings.get("After_Structural_AND2", ""),
                timings.get("After_SAT_AND2", ""), timings.get("Structural_Removed_AND2", ""),
                timings.get("SAT_Induced_Removed_AND2", ""),
                timings.get("SAT_Accepted_SA0", ""), timings.get("SAT_Accepted_SA1", ""),
                timings.get("Rebuilds", ""),
                timings.get("SAT_Unresolved", ""), timings.get("SAT_Max_Budget", ""),
                timings.get("Checkpoint_Resume", ""),
                timings.get("TFI_Checks", ""), timings.get("TFI_Query_SAT", ""),
                timings.get("TFI_Query_UNSAT", ""), timings.get("TFI_Timeouts", ""),
                timings.get("TFI_Skipped", ""),
                timings.get("Window_Checks", ""), timings.get("Window_Query_SAT", ""),
                timings.get("Window_Query_UNSAT", ""), timings.get("Window_Timeouts", ""),
                timings.get("Window_Skipped", ""), timings.get("Window_Audit_Fail", ""),
                timings.get("Cone_Checks", ""), timings.get("Cone_Query_SAT", ""),
                timings.get("Cone_Query_UNSAT", ""), timings.get("Cone_Timeouts", ""),
                timings.get("Cone_Skipped", ""),
                timings.get("Global_Checks", ""), timings.get("Global_Query_SAT", ""),
                timings.get("Global_Query_UNSAT", ""), timings.get("Global_Timeouts", ""),
                timings.get("CEX_Prune_Events", ""), timings.get("CEX_Prune_Checked", ""),
                timings.get("CEX_Pruned", ""), timings.get("CEX_TFI_Prune_Events", ""),
                timings.get("CEX_TFI_Prune_Checked", ""), timings.get("CEX_TFI_Pruned", ""),
                timings.get("CEX_Pruning_Enabled", ""),
                timings.get("CEX_Audit_Enabled", ""), timings.get("CEX_Audit_Checked", ""),
                timings.get("CEX_Audit_SAT", ""), timings.get("CEX_Audit_False_Prunes", ""),
                timings.get("CEX_Audit_Timeouts", ""), timings.get("CEX_Audit_Skipped", ""),
                timings.get("CEX_Audit_Limit_Hit", ""),
                status
            ])
            
        except KeyboardInterrupt:
            print(f"^C Skipped. Verify: SKIPPED.")
            stats.append([
                name, category, RUN_MODE_LABEL, DATASET_PROFILE_LABEL,
                0, 0, 0, "SKIPPED",
                0, 0, 0, "SKIPPED", 0, 0, "SKIPPED",
                "0", "0", "0", "0", "0", "0",
                "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "",
                "", "", "", "", "", "", "", "", "", "", "", "", "", "", "",
                "", "", "", "", "", "", "", "", "", "", "", "", "SKIPPED"
            ])
            continue
        except Exception as e:
            print(f"ERROR: {e}")
            stats.append([
                name, category, RUN_MODE_LABEL, DATASET_PROFILE_LABEL,
                0, 0, 0, "ERR",
                0, 0, 0, "ERR", 0, 0, "ERR",
                "0", "0", "0", "0", "0", "0",
                "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "",
                "", "", "", "", "", "", "", "", "", "", "", "", "", "", "",
                "", "", "", "", "", "", "", "", "", "", "", "", "ERROR"
            ])

    with open(REPORT_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Circuit", "Type", "Run_Mode", "Dataset_Profile",
            "Original_Gates", "Final_Gates", "Gates_Removed", "Total_Red%",
            "Area_Before_AND2", "Area_After_AND2", "Area_Saved_AND2", "Area_Red%",
            "Depth_Before", "Depth_After", "Depth_Red%",
            "T_Parse(s)", "T_Filter(s)", "T_Encode(s)", "T_SAT(s)", "T_CEC(s)", "T_Total(s)",
            "SAT_Candidates", "SAT_Checks", "SAT_Query_SAT", "SAT_Query_UNSAT", "SAT_Timeouts",
            "SAT_Abort_Reason",
            "Initial_AND2", "After_Structural_AND2", "After_SAT_AND2",
            "Structural_Removed_AND2", "SAT_Induced_Removed_AND2",
            "SAT_Accepted_SA0", "SAT_Accepted_SA1", "Rebuilds",
            "SAT_Unresolved", "SAT_Max_Budget", "Checkpoint_Resume",
            "TFI_Checks", "TFI_Query_SAT", "TFI_Query_UNSAT", "TFI_Timeouts", "TFI_Skipped",
            "Window_Checks", "Window_Query_SAT", "Window_Query_UNSAT", "Window_Timeouts",
            "Window_Skipped", "Window_Audit_Fail",
            "Cone_Checks", "Cone_Query_SAT", "Cone_Query_UNSAT", "Cone_Timeouts", "Cone_Skipped",
            "Global_Checks", "Global_Query_SAT", "Global_Query_UNSAT", "Global_Timeouts",
            "CEX_Prune_Events", "CEX_Prune_Checked", "CEX_Pruned",
            "CEX_TFI_Prune_Events", "CEX_TFI_Prune_Checked", "CEX_TFI_Pruned",
            "CEX_Pruning_Enabled",
            "CEX_Audit_Enabled", "CEX_Audit_Checked", "CEX_Audit_SAT",
            "CEX_Audit_False_Prunes", "CEX_Audit_Timeouts", "CEX_Audit_Skipped",
            "CEX_Audit_Limit_Hit",
            "Verify"
        ])
        width = 73
        for row in stats:
            if len(row) < width:
                row.extend([""] * (width - len(row)))
            elif len(row) > width:
                del row[width:]
        writer.writerows(stats)

    print(f"\n[DONE] Saved report to {REPORT_FILE}")
