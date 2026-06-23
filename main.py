import os
import csv
import json
import shutil
import glob          
import random
import time
import importlib
import subprocess
import sys
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
DATASET_RUNS_DIR = os.path.join(RESULTS_BASE_DIR, "datasets")
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

def configure_run_directories(timestamp):
    """Use run-local folders so parallel/probe runs cannot delete each other."""
    global DATASET_DIR, RUN_SUBDIR, CURRENT_RUN_DIR
    DATASET_DIR = os.environ.get(
        "THESIS_DATASET_DIR",
        os.path.join(DATASET_RUNS_DIR, f"dataset_{timestamp}"),
    )
    RUN_SUBDIR = os.environ.get("THESIS_RUN_SUBDIR", f"run_{timestamp}")
    CURRENT_RUN_DIR = os.environ.get(
        "THESIS_CURRENT_RUN_DIR",
        os.path.join(RESULTS_BASE_DIR, RUN_SUBDIR),
    )


def _safe_recreate_dir(path):
    abs_path = os.path.abspath(path)
    abs_results = os.path.abspath(RESULTS_BASE_DIR)
    if os.path.exists(path):
        if not abs_path.startswith(abs_results + os.sep):
            raise RuntimeError(f"Refusing to delete non-results directory: {path}")
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


def setup_directories():
    _safe_recreate_dir(DATASET_DIR)
    _safe_recreate_dir(CURRENT_RUN_DIR)

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


def _csv_int(value):
    try:
        if value in ("", None):
            return 0
        return int(float(str(value).replace("%", "")))
    except Exception:
        return 0


def _csv_float(value):
    try:
        if value in ("", None):
            return 0.0
        return float(str(value).replace("%", ""))
    except Exception:
        return 0.0


def print_alg10_diagnostic_summary(header, rows):
    if not str(RUN_MODE_LABEL).startswith("alg10"):
        return

    idx = {name: pos for pos, name in enumerate(header)}

    def get(row, name):
        pos = idx.get(name)
        return row[pos] if pos is not None and pos < len(row) else ""

    alg_rows = [row for row in rows if get(row, "Verify") not in {"SKIPPED", "ERROR"}]
    if not alg_rows:
        return

    by_circuit = {}
    for row in alg_rows:
        by_circuit.setdefault(get(row, "Circuit"), []).append(row)
    latest_rows = [circuit_rows[-1] for circuit_rows in by_circuit.values()]
    best_unresolved_rows = [
        min(circuit_rows, key=lambda row: _csv_int(get(row, "SAT_Unresolved")))
        for circuit_rows in by_circuit.values()
    ]
    best_gate_rows = [
        max(circuit_rows, key=lambda row: _csv_int(get(row, "Gates_Removed")))
        for circuit_rows in by_circuit.values()
    ]

    total_removed = sum(_csv_int(get(row, "Gates_Removed")) for row in latest_rows)
    total_removed_best_gate = sum(_csv_int(get(row, "Gates_Removed")) for row in best_gate_rows)
    total_new_removed = sum(_csv_int(get(row, "New_Removed_This_Run")) for row in alg_rows)
    total_unresolved = sum(_csv_int(get(row, "SAT_Unresolved")) for row in latest_rows)
    total_unresolved_best = sum(_csv_int(get(row, "SAT_Unresolved")) for row in best_unresolved_rows)
    total_timeouts = sum(_csv_int(get(row, "SAT_Timeouts")) for row in alg_rows)
    total_checks = sum(_csv_int(get(row, "SAT_Checks")) for row in alg_rows)
    total_sat = sum(_csv_int(get(row, "SAT_Query_SAT")) for row in alg_rows)
    total_unsat = sum(_csv_int(get(row, "SAT_Query_UNSAT")) for row in alg_rows)
    total_presim = sum(_csv_int(get(row, "PreSAT_Sim_Pruned")) for row in alg_rows)
    total_pool = sum(_csv_int(get(row, "CEX_Pool_Replay_Pruned")) for row in alg_rows)
    total_cex = sum(_csv_int(get(row, "CEX_Pruned")) for row in alg_rows)
    budget_loaded = sum(_csv_int(get(row, "Global_Budget_History_Loaded")) for row in alg_rows)
    budget_skipped = sum(_csv_int(get(row, "Global_Budget_History_Skipped")) for row in alg_rows)
    budget_exhausted = sum(_csv_int(get(row, "Global_Budget_History_Exhausted")) for row in alg_rows)
    cec_pass = sum(1 for row in alg_rows if get(row, "Verify") == "PASS")
    latest_cec_pass = sum(1 for row in latest_rows if get(row, "Verify") == "PASS")

    print("\n[Alg10 diagnostic summary]")
    print(f"    CEC PASS rows: {cec_pass}/{len(alg_rows)}")
    print(f"    CEC PASS latest circuits: {latest_cec_pass}/{len(latest_rows)}")
    if len(alg_rows) != len(latest_rows):
        print(f"    Repeated campaign rows: {len(alg_rows)} rows over {len(latest_rows)} circuits")
    print(f"    Total removed latest circuits: {total_removed} gates")
    if total_removed_best_gate != total_removed:
        print(f"    Best gate-reduction seen: {total_removed_best_gate} gates")
    if total_new_removed:
        print(f"    New removed events this run from checkpoints: {total_new_removed} gates")
    print(f"    SAT unresolved latest circuits: {total_unresolved}")
    if total_unresolved_best != total_unresolved:
        print(f"    Best SAT unresolved seen: {total_unresolved_best}")
    print(
        f"    SAT calls: {total_checks} checks | {total_sat} SAT rejects | "
        f"{total_unsat} UNSAT accepts | {total_timeouts} timeouts"
    )
    print(
        f"    Rejection workload reduction: pre-sim {total_presim}, "
        f"CEX pool {total_pool}, SAT-CEX replay {total_cex}"
    )
    print(
        f"    Global budget history: loaded {budget_loaded}, "
        f"skipped repeated budgets {budget_skipped}, exhausted {budget_exhausted}"
    )

    tier_timeout_totals = [
        ("TFI", sum(_csv_int(get(row, "TFI_Timeouts")) for row in alg_rows)),
        ("Window", sum(_csv_int(get(row, "Window_Timeouts")) for row in alg_rows)),
        ("Cone", sum(_csv_int(get(row, "Cone_Timeouts")) for row in alg_rows)),
        ("Global", sum(_csv_int(get(row, "Global_Timeouts")) for row in alg_rows)),
    ]
    worst_tier, worst_count = max(tier_timeout_totals, key=lambda item: item[1])
    if worst_count:
        print(f"    Main timeout bottleneck: {worst_tier} tier ({worst_count} timeouts)")

    unresolved_rows = sorted(
        (
            (
                _csv_int(get(row, "SAT_Unresolved")),
                get(row, "Circuit"),
                _csv_int(get(row, "Gates_Removed")),
                _csv_int(get(row, "New_Removed_This_Run")),
                get(row, "SAT_Abort_Reason"),
                get(row, "Fault_Coverage_Lower_Bound%"),
                _csv_int(get(row, "Global_Budget_History_Exhausted")),
                _csv_int(get(best_row, "SAT_Unresolved")),
            )
            for row, best_row in (
                (
                    circuit_rows[-1],
                    min(circuit_rows, key=lambda candidate: _csv_int(get(candidate, "SAT_Unresolved"))),
                )
                for circuit_rows in by_circuit.values()
            )
        ),
        reverse=True,
    )
    top = [item for item in unresolved_rows if item[0] > 0][:8]
    if top:
        print("    Top unresolved latest circuits:")
        for unresolved, circuit, removed, new_removed, abort, coverage, exhausted, best_unresolved in top:
            extra = f", exhausted={exhausted}" if exhausted else ""
            best = f", best_seen={best_unresolved}" if best_unresolved != unresolved else ""
            print(
                f"      {circuit}: unresolved={unresolved}, removed={removed}, "
                f"new={new_removed}, coverage={coverage}, abort={abort}{best}{extra}"
            )
    else:
        print("    No unresolved candidates remain in the latest circuit rows.")

    if budget_exhausted:
        print("    Next action hint: increase global budgets or improve cone/window SAT for exhausted candidates.")
    elif total_unresolved and total_timeouts:
        print("    Next action hint: resume option 3; the remaining frontier still has useful budget work.")
    elif total_unresolved:
        print("    Next action hint: inspect skipped/disabled tiers or candidate ordering.")


def maybe_generate_report_charts(report_file):
    if not str(RUN_MODE_LABEL).startswith("alg10"):
        return
    if os.environ.get("ALG10_AUTO_PLOTS", "1") == "0":
        return
    try:
        from alg10_report_plots import generate_alg10_report_plots

        chart_dir = generate_alg10_report_plots(report_file)
        print(f"    Report charts: {chart_dir}")
    except Exception as exc:
        print(f"    Report charts skipped: {exc}")


def campaign_file_iterator(files, repeat, max_cycles):
    if not repeat:
        for path in files:
            yield 1, path
        return
    for cycle in range(1, max_cycles + 1):
        for path in files:
            yield cycle, path

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


def _native_summary_score(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        targets = data.get("targets", [])
        if not targets:
            return None
        total_gates = sum(_csv_int(item.get("current_gates")) for item in targets)
        total_removed = sum(_csv_int(item.get("removed")) for item in targets)
        total_unresolved = sum(_csv_int(item.get("unresolved")) for item in targets)
        finished = 0 if data.get("status") in {"RUNNING", "ERROR", "FAILED"} else 1
        return (
            finished,
            -total_gates,
            total_removed,
            -total_unresolved,
            os.path.getmtime(path),
        )
    except Exception:
        return None


def find_best_native_tfo_summary(results_dir=RESULTS_BASE_DIR):
    patterns = [
        os.path.join(results_dir, "parallel_tfo_native_tfo*", "summary.json"),
        os.path.join(results_dir, "native_tfo_7h_prelaunch_smoke_20260615", "summary.json"),
    ]
    best_path = ""
    best_score = None
    for pattern in patterns:
        for path in glob.glob(pattern):
            score = _native_summary_score(path)
            if score is None:
                continue
            if best_score is None or score > best_score:
                best_path = path
                best_score = score
    return best_path


def _prompt_runtime_minutes(default_minutes=360):
    try:
        raw = input(f"Runtime for native exact-TFO campaign in minutes [{default_minutes}]: ").strip()
        if not raw:
            return int(default_minutes)
        return max(1, int(float(raw)))
    except (EOFError, ValueError):
        print(f"Keeping runtime at {default_minutes} minutes.")
        return int(default_minutes)


def _prompt_positive_int(prompt, default, minimum=1):
    try:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return int(default)
        return max(int(minimum), int(float(raw)))
    except (EOFError, ValueError):
        print(f"Keeping value at {default}.")
        return int(default)


NATIVE_TFO_TARGET_KEYS = (
    "epfl_arithmetic_sin",
    "epfl_arithmetic_sqrt",
    "epfl_arithmetic_hyp",
    "epfl_arithmetic_div",
    "epfl_arithmetic_log2",
    "epfl_random_control_mem_ctrl",
)


def _native_raw_suite_key(prefix, path):
    base = os.path.splitext(os.path.basename(path))[0].lower()
    if prefix:
        base = f"{prefix}_{base}"
    key = "".join(ch if ch.isalnum() else "_" for ch in base)
    return "_".join(part for part in key.split("_") if part)


def _native_raw_iscas_epfl_target_keys():
    keys = []
    for path in sorted(glob.glob(os.path.join("benchmarks", "*.aag"))):
        keys.append(_native_raw_suite_key("iscas", path))
    for path in sorted(glob.glob(os.path.join(BENCHMARK_SUITE_DIR, "epfl", "*.aag"))):
        keys.append(_native_raw_suite_key("", path))
    return keys


def _prompt_native_tfo_targets(raw_suite=""):
    if raw_suite == "iscas_epfl":
        target_keys = _native_raw_iscas_epfl_target_keys()
        custom_choice = len(target_keys) + 1
        print("\n" + "=" * 60)
        print("   RAW ISCAS + EPFL TARGETS")
        print("=" * 60)
        print(f" 0: All raw ISCAS + EPFL circuits ({len(target_keys)} targets)")
        for idx, key in enumerate(target_keys, start=1):
            print(f" {idx}: {key}")
        print(f" {custom_choice}: Custom comma-separated raw target keys")
        print("=" * 60)
        raw = input(f"Select target set (0-{custom_choice}) [0]: ").strip()
        if not raw:
            raw = "0"
        if raw == "0":
            return []
        try:
            numeric = int(raw)
        except ValueError:
            numeric = -1
        if 1 <= numeric <= len(target_keys):
            return [target_keys[numeric - 1]]
        if numeric == custom_choice:
            custom = input("Raw target keys: ").strip()
            selected = [part.strip() for part in custom.split(",") if part.strip()]
            unknown = sorted(set(selected) - set(target_keys))
            if unknown:
                print(f"Unknown raw target(s): {', '.join(unknown)}. Defaulting to all.")
                return []
            return selected
        print("Invalid target choice. Defaulting to all raw suite targets.")
        return []

    print("\n" + "=" * 60)
    print("   NATIVE EXACT-TFO TARGETS")
    print("=" * 60)
    print(" 0: All hard native targets")
    for idx, key in enumerate(NATIVE_TFO_TARGET_KEYS, start=1):
        print(f" {idx}: {key}")
    custom_choice = len(NATIVE_TFO_TARGET_KEYS) + 1
    print(f" {custom_choice}: Custom comma-separated target keys")
    print("=" * 60)
    raw = input(f"Select target set (0-{custom_choice}) [0]: ").strip()
    if not raw:
        raw = "0"
    if raw == "0":
        return []
    if raw in {str(i) for i in range(1, len(NATIVE_TFO_TARGET_KEYS) + 1)}:
        return [NATIVE_TFO_TARGET_KEYS[int(raw) - 1]]
    if raw == str(custom_choice):
        custom = input("Target keys: ").strip()
        selected = [part.strip() for part in custom.split(",") if part.strip()]
        unknown = sorted(set(selected) - set(NATIVE_TFO_TARGET_KEYS))
        if unknown:
            print(f"Unknown target(s): {', '.join(unknown)}. Defaulting to all.")
            return []
        return selected
    print("Invalid target choice. Defaulting to all.")
    return []


def _prompt_native_checkpoint_source():
    print("\n" + "=" * 60)
    print("   NATIVE EXACT-TFO SOURCE")
    print("=" * 60)
    print(" 1: Continue from best native summary")
    print(" 2: Fresh pinned native checkpoints")
    print(" 3: Explicit summary.json path")
    print(" 4: Explicit checkpoint JSON path(s)")
    print(" 5: Full raw ISCAS + EPFL AAG suite (from 0 removed)")
    print("=" * 60)
    choice = prompt_choice("Select source (1-5) [1]: ", {"1", "2", "3", "4", "5"}, "1")
    if choice == "2":
        return True, "", [], ""
    if choice == "5":
        return True, "", [], "iscas_epfl"
    if choice == "3":
        try:
            path = input("Summary JSON path: ").strip()
        except EOFError:
            path = ""
        if path and os.path.exists(path):
            return False, path, [], ""
        print("Summary path missing or not found; using best native summary.")
    elif choice == "4":
        try:
            raw = input("Checkpoint JSON path(s), comma-separated: ").strip()
        except EOFError:
            raw = ""
        paths = [part.strip() for part in raw.split(",") if part.strip()]
        missing = [path for path in paths if not os.path.exists(path)]
        if paths and not missing:
            return False, "", paths, ""
        if missing:
            print(f"Missing checkpoint(s): {', '.join(missing)}. Using best native summary.")
    seed_summary = os.environ.get("ALG10_NATIVE_SEED_SUMMARY", "").strip()
    if not seed_summary:
        seed_summary = find_best_native_tfo_summary()
    if seed_summary:
        print(f"    Seed summary: {seed_summary}")
        return False, seed_summary, [], ""
    print("    No native seed summary found; switching to fresh pinned checkpoints.")
    return True, "", [], ""


NATIVE_TFO_FINAL_STATUSES = {
    "ALL_TARGETS_COMPLETE",
    "FINISHED_WITH_FAILURES",
    "NO_ACTIVE_TARGETS",
    "NO_RUNNABLE_WORK",
    "TIME_BUDGET_COMPLETE",
    "STOPPED_BY_USER",
}


def _native_tfo_duration(seconds):
    seconds = max(0, int(seconds))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _load_native_tfo_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def _render_native_tfo_status(root):
    summary = _load_native_tfo_json(os.path.join(root, "summary.json"))
    if not summary:
        return f"Waiting for {os.path.join(root, 'summary.json')}..."

    now = time.time()
    started = float(summary.get("started", now) or now)
    deadline = float(summary.get("deadline", now) or now)
    status = str(summary.get("status", "UNKNOWN"))
    metrics = summary.get("pool_metrics", {}) or {}
    utilization = 100.0 * float(metrics.get("worker_utilization", 0.0) or 0.0)
    elapsed = _native_tfo_duration(now - started)
    if status in NATIVE_TFO_FINAL_STATUSES and summary.get("elapsed") is not None:
        elapsed = _native_tfo_duration(float(summary.get("elapsed", 0.0) or 0.0))
    lines = [
        f"Campaign: {root}",
        f"Status:   {status}",
        f"Elapsed:  {elapsed}",
        f"Remaining:{_native_tfo_duration(deadline - now)}",
        f"Pool:     workers={summary.get('hardware', {}).get('selected', 0)} "
        f"active_max={metrics.get('max_active_workers', 0)} "
        f"dispatches={summary.get('dispatches', 0)} "
        f"utilization={utilization:.1f}%",
        "",
        f"{'Circuit':32} {'Gen':>4} {'Gates':>9} {'Unresolved':>11} "
        f"{'InFlight':>8} {'Dispatch':>8} {'State':>20}",
        "-" * 101,
    ]
    for target in summary.get("targets", []):
        lines.append(
            f"{str(target.get('key', '?')):32} "
            f"{int(target.get('generation', 0) or 0):4d} "
            f"{int(target.get('current_gates', 0) or 0):9d} "
            f"{int(target.get('unresolved', 0) or 0):11d} "
            f"{int(target.get('inflight', 0) or 0):8d} "
            f"{int(target.get('dispatches', 0) or 0):8d} "
            f"{str(target.get('status', 'UNKNOWN')):>20}"
        )
    if status in NATIVE_TFO_FINAL_STATUSES:
        lines.extend(["", "Campaign has finished."])
    else:
        lines.extend(["", "Press Ctrl-C to stop this display; the run continues in the background."])
    return "\n".join(lines)


def monitor_native_tfo_campaign(output_dir, process=None, interval=10.0):
    root = os.path.abspath(output_dir)
    try:
        while True:
            print("\033[2J\033[H", end="")
            print(_render_native_tfo_status(root), flush=True)
            summary = _load_native_tfo_json(os.path.join(root, "summary.json")) or {}
            status = summary.get("status")
            if status in NATIVE_TFO_FINAL_STATUSES:
                return 0
            if process is not None and process.poll() is not None:
                print(
                    f"\nCampaign process exited with code {process.returncode} "
                    "before a final campaign status was written.",
                    flush=True,
                )
                return process.returncode or 0
            time.sleep(max(1.0, float(interval)))
    except KeyboardInterrupt:
        print("\nStopped status display. Native campaign keeps running in the background.")
        return 0


def build_native_tfo_campaign_command(
    reset,
    runtime_minutes,
    timestamp,
    seed_summary="",
    checkpoint_jsons=None,
    workers=None,
    target_keys=None,
    raw_suite="",
):
    seconds = max(1, int(runtime_minutes) * 60)
    tag = raw_suite.replace("_", "-") if raw_suite else ("fresh" if reset else "continue")
    selected_targets = list(target_keys or [])
    target_label = "all" if not selected_targets else "_".join(
        key.replace("epfl_", "").replace("iscas_", "").replace("_", "-")
        for key in selected_targets[:4]
    )
    if len(selected_targets) > 4:
        target_label = f"{target_label}_{len(selected_targets)}targets"
    output_dir = os.path.join(
        RESULTS_BASE_DIR,
        f"parallel_tfo_native_tfo_main_{tag}_{target_label}_{timestamp}",
    )
    command = [
        sys.executable,
        "-u",
        "alg10_native_tfo_7h_campaign.py",
        "--output-dir",
        output_dir,
        "--seconds",
        str(seconds),
        "--workers",
        str(workers if workers is not None else os.environ.get("ALG10_NATIVE_WORKERS", "12")),
        "--worker-cache-entries",
        os.environ.get("ALG10_NATIVE_WORKER_CACHE_ENTRIES", "2"),
        "--persistent-retry-tiers",
        os.environ.get("ALG10_NATIVE_PERSISTENT_RETRY_TIERS", "3"),
        "--solver",
        os.environ.get("ALG10_NATIVE_SOLVER", "cadical153"),
    ]
    if raw_suite:
        command.extend(["--raw-suite", raw_suite])
    elif not reset and seed_summary:
        command.extend(["--seed-summary", seed_summary])
    if not reset and not raw_suite:
        for path in checkpoint_jsons or []:
            command.extend(["--checkpoint-json", path])
    for key in selected_targets:
        command.extend(["--target", key])
    return command, output_dir


def run_native_tfo_campaign_from_menu(timestamp):
    print("\n" + "=" * 60)
    print("   ALG10 NATIVE EXACT-TFO CAMPAIGN")
    print("=" * 60)
    print("This mode runs the latest multi-circuit exact-TFO pool campaign.")
    print("It writes to a new output folder and does not overwrite prior runs.")
    reset, seed_summary, checkpoint_jsons, raw_suite = _prompt_native_checkpoint_source()
    target_keys = _prompt_native_tfo_targets(raw_suite=raw_suite)
    default_minutes = int(os.environ.get("ALG10_NATIVE_RUNTIME_MINUTES", "360"))
    runtime_minutes = _prompt_runtime_minutes(default_minutes)
    default_workers = int(os.environ.get("ALG10_NATIVE_WORKERS", "12"))
    workers = _prompt_positive_int("Worker processes", default_workers, minimum=1)

    command, output_dir = build_native_tfo_campaign_command(
        reset,
        runtime_minutes,
        timestamp,
        seed_summary=seed_summary,
        checkpoint_jsons=checkpoint_jsons,
        workers=workers,
        target_keys=target_keys,
        raw_suite=raw_suite,
    )
    print(f"    Output directory: {output_dir}")
    print(f"    Runtime: {runtime_minutes} minutes")
    print(f"    Workers: {workers}")
    print(f"    Solver: {os.environ.get('ALG10_NATIVE_SOLVER', 'cadical153')}")
    if raw_suite == "iscas_epfl":
        target_label = ", ".join(target_keys) if target_keys else "all raw ISCAS + EPFL targets"
    else:
        target_label = ", ".join(target_keys) if target_keys else "all hard native targets"
    print(f"    Targets: {target_label}")
    if raw_suite == "iscas_epfl":
        checkpoint_source = "raw ISCAS + EPFL AAG suite (seed_removed=0)"
    elif reset:
        checkpoint_source = "fresh pinned native checkpoints"
    elif checkpoint_jsons:
        checkpoint_source = ", ".join(checkpoint_jsons)
    else:
        checkpoint_source = seed_summary
    print(f"    Checkpoint source: {checkpoint_source}")
    print(f"    Command: {' '.join(command)}")
    os.makedirs(output_dir, exist_ok=True)
    log_path = os.path.join(output_dir, "native_campaign.log")
    pid_path = os.path.join(output_dir, "native_campaign.pid")
    with open(log_path, "ab", buffering=0) as log:
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=os.getcwd(),
            start_new_session=True,
        )
    with open(pid_path, "w", encoding="utf-8") as handle:
        handle.write(f"{process.pid}\n")

    print(f"    Started in background. PID: {process.pid}")
    print(f"    Log file: {log_path}")
    print(f"    PID file: {pid_path}")
    print("    Opening live status display; Ctrl-C stops only the display.")
    monitor_native_tfo_campaign(output_dir, process=process, interval=10.0)

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
    print(" 3: Enhanced deep resume (CEX pool + pre-sim + phase resume)")
    print(" 4: Strict audit unresolved-to-zero campaign (cycles unresolved circuits)")
    print(" 5: Strict audit fast save (assumption audits ON)")
    print(" 6: Strict audit enhanced deep (assumption audits ON)")
    print("="*60)
    mode = prompt_choice("Select Alg 10 mode (1-6) [1]: ", {"1", "2", "3", "4", "5", "6"}, "1")

    if mode == "6":
        RUN_MODE_LABEL = "alg10_strict_audit_resume_pool_presim_deep_current"
        os.environ["ALG10_MODE"] = "deep_resume"
        os.environ.setdefault("ALG10_BUDGETS", "1000,5000,20000,100000")
        os.environ.setdefault("ALG10_MAX_CIRCUIT_SECONDS", "600")
        os.environ.setdefault("ALG10_CHECKPOINT_DIR", "results_optimized/alg10_checkpoints_strict_audit")
        set_int("ALG10_REBUILD_AFTER_COMMITS", 100)
        os.environ["ALG10_CEX_POOL"] = "1"
        os.environ["ALG10_PHASE_LOCAL_RESUME"] = "1"
        os.environ["ALG10_EXACT_FRONTIER_RESUME"] = "1"
        os.environ["ALG10_PRE_SIM_REJECTION"] = "1"
        os.environ["ALG10_AUDIT_ASSUMPTIONS"] = "1"
        os.environ.setdefault("ALG10_PRE_SIM_RANDOM_PATTERNS", "128")
        os.environ.setdefault("ALG10_PRE_SIM_WALK_PATTERNS", "32")
        os.environ.setdefault("ALG10_PRE_SIM_MAX_SECONDS", "60")
        os.environ.setdefault("ALG10_PRE_SIM_MAX_FRACTION", "0.25")
    elif mode == "5":
        RUN_MODE_LABEL = "alg10_strict_audit_fast_save_current"
        os.environ["ALG10_MODE"] = "fast_save"
        os.environ.setdefault("ALG10_BUDGETS", "100,1000,5000")
        os.environ.setdefault("ALG10_MAX_CIRCUIT_SECONDS", "60")
        os.environ.setdefault("ALG10_CHECKPOINT_DIR", "results_optimized/alg10_checkpoints_strict_audit")
        os.environ["ALG10_AUDIT_ASSUMPTIONS"] = "1"
        set_int("ALG10_REBUILD_AFTER_COMMITS", 100)
    elif mode == "4":
        RUN_MODE_LABEL = "alg10_strict_audit_zero_resume_pool_presim_current"
        os.environ["ALG10_MODE"] = "deep_resume"
        os.environ.setdefault("ALG10_BUDGETS", "1000,5000,20000,100000,500000")
        os.environ.setdefault("ALG10_MAX_CIRCUIT_SECONDS", "600")
        os.environ.setdefault("ALG10_TOTAL_SECONDS", "86400")
        os.environ["ALG10_REPEAT_UNTIL_ZERO"] = "1"
        os.environ.setdefault("ALG10_REPEAT_CYCLES", "1000000")
        os.environ.setdefault("ALG10_CHECKPOINT_DIR", "results_optimized/alg10_checkpoints_strict_audit")
        set_int("ALG10_REBUILD_AFTER_COMMITS", 100)
        os.environ["ALG10_CEX_POOL"] = "1"
        os.environ["ALG10_PHASE_LOCAL_RESUME"] = "1"
        os.environ["ALG10_EXACT_FRONTIER_RESUME"] = "1"
        os.environ["ALG10_PRE_SIM_REJECTION"] = "1"
        os.environ["ALG10_AUDIT_ASSUMPTIONS"] = "1"
        os.environ.setdefault("ALG10_PRE_SIM_RANDOM_PATTERNS", "128")
        os.environ.setdefault("ALG10_PRE_SIM_WALK_PATTERNS", "32")
        os.environ.setdefault("ALG10_PRE_SIM_MAX_SECONDS", "60")
        os.environ.setdefault("ALG10_PRE_SIM_MAX_FRACTION", "0.25")
    elif mode == "3":
        RUN_MODE_LABEL = "alg10_resume_pool_presim_deep_current"
        os.environ["ALG10_MODE"] = "deep_resume"
        os.environ.setdefault("ALG10_BUDGETS", "1000,5000,20000,100000")
        os.environ.setdefault("ALG10_MAX_CIRCUIT_SECONDS", "600")
        os.environ.setdefault("ALG10_CHECKPOINT_DIR", "results_optimized/alg10_checkpoints_resume_pool_presim")
        set_int("ALG10_REBUILD_AFTER_COMMITS", 100)
        os.environ["ALG10_CEX_POOL"] = "1"
        os.environ["ALG10_PHASE_LOCAL_RESUME"] = "1"
        os.environ["ALG10_EXACT_FRONTIER_RESUME"] = "1"
        os.environ["ALG10_PRE_SIM_REJECTION"] = "1"
        os.environ.setdefault("ALG10_PRE_SIM_RANDOM_PATTERNS", "128")
        os.environ.setdefault("ALG10_PRE_SIM_WALK_PATTERNS", "32")
        os.environ.setdefault("ALG10_PRE_SIM_MAX_SECONDS", "60")
        os.environ.setdefault("ALG10_PRE_SIM_MAX_FRACTION", "0.25")
    elif mode == "2":
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
    os.environ.setdefault("ALG10_TFI_ENGINE", "persistent")
    os.environ.setdefault("ALG10_TFI_SOLVER", "cadical153")
    os.environ.setdefault("ALG10_WINDOW_MITER", "1")
    os.environ.setdefault("ALG10_WINDOW_AUDIT", "1")
    os.environ.setdefault("ALG10_WINDOW_LEVELS", "5")
    os.environ.setdefault("ALG10_CONE_MITER", "1")
    os.environ.setdefault("ALG10_CONE_ENGINE", "hybrid")
    os.environ.setdefault("ALG10_CONE_SOLVER", "cadical153")
    os.environ.setdefault("ALG10_CONE_GROUP_MIN_SIZE", "8")
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
    if os.environ.get("ALG10_REPEAT_UNTIL_ZERO", "0") != "0":
        print(f"    Total campaign seconds: {os.environ.get('ALG10_TOTAL_SECONDS', '86400')}")
        print(f"    Max campaign cycles: {os.environ.get('ALG10_REPEAT_CYCLES', '1000000')}")
        print("    Repeat unresolved circuits: 1")
    elif os.environ.get("ALG10_TOTAL_SECONDS", "0") not in {"", "0"}:
        print(f"    Total run seconds: {os.environ.get('ALG10_TOTAL_SECONDS')}")
    print(f"    Candidate order: {os.environ.get('ALG10_CANDIDATE_ORDER', 'current')}")
    print(f"    TFI constancy: {os.environ.get('ALG10_TFI_CONSTANCY', '1')}")
    print(f"    TFI engine: {os.environ.get('ALG10_TFI_ENGINE', 'persistent')}")
    print(f"    TFI solver: {os.environ.get('ALG10_TFI_SOLVER', 'cadical153')}")
    print(f"    Window miter: {os.environ.get('ALG10_WINDOW_MITER', '0')}")
    print(f"    Window audit: {os.environ.get('ALG10_WINDOW_AUDIT', '1')}")
    print(f"    Window root strategy: {os.environ.get('ALG10_WINDOW_ROOT_STRATEGY', 'bounded')}")
    print(f"    Cone miter: {os.environ.get('ALG10_CONE_MITER', '1')}")
    print(f"    Cone engine: {os.environ.get('ALG10_CONE_ENGINE', 'hybrid')}")
    print(f"    Cone solver: {os.environ.get('ALG10_CONE_SOLVER', 'cadical153')}")
    print(f"    Global solver: {os.environ.get('ALG10_GLOBAL_SOLVER', 'glucose4')}")
    print(f"    Global frontier order: {os.environ.get('ALG10_GLOBAL_FRONTIER_ORDER', 'current')}")
    print(f"    Global phase mode: {os.environ.get('ALG10_GLOBAL_PHASE_MODE', 'none')}")
    print(f"    CEX pruning: {os.environ.get('ALG10_CEX_PRUNING', '0')}")
    print(f"    CEX pool: {os.environ.get('ALG10_CEX_POOL', '0')}")
    print(f"    Pre-SAT rejection: {os.environ.get('ALG10_PRE_SIM_REJECTION', '0')}")
    print(f"    Phase-local resume: {os.environ.get('ALG10_PHASE_LOCAL_RESUME', '0')}")
    print(f"    Exact frontier resume: {os.environ.get('ALG10_EXACT_FRONTIER_RESUME', '0')}")
    print(f"    Assumption audit: {os.environ.get('ALG10_AUDIT_ASSUMPTIONS', '0')}")
    print(f"    CEX audit: {os.environ.get('ALG10_AUDIT_CEX_PRUNING', '0')}")
    print(f"    Checkpoint dir: {os.environ.get('ALG10_CHECKPOINT_DIR', 'results_optimized/alg10_checkpoints')}")
    print(f"    Extra checkpoint dirs: {os.environ.get('ALG10_EXTRA_CHECKPOINT_DIRS', '')}")
    print(f"    Checkpoint select policy: {os.environ.get('ALG10_CHECKPOINT_SELECT', 'gates')}")
    print(f"    Reset checkpoint: {os.environ.get('ALG10_RESET_CHECKPOINT', '0')}")
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
    print("11: Alg10 Native Exact-TFO Pool Campaign (latest)")
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
        "10": "optimizer_alg10_tiered",
        "11": "__alg10_native_tfo_campaign__",
    }

    choice = prompt_choice("Enter choice (1-11): ", set(mapping), "9")
    return mapping[choice], choice

if __name__ == "__main__":
    timestamp = os.environ.get("THESIS_RUN_TIMESTAMP") or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    configure_run_directories(timestamp)
    setup_directories()
    
    # --- INTERACTIVE SELECTION ---
    algo_module_name, algo_id = select_optimizer()
    if algo_id == "9":
        configure_algorithm9_run()
    elif algo_id == "10":
        configure_algorithm10_run()
    elif algo_id == "11":
        run_native_tfo_campaign_from_menu(timestamp)
        raise SystemExit(0)

    print(f"\n[+] Loading Engine: {algo_module_name}.py")
    
    # Dynamically load the chosen python file
    optimizer = importlib.import_module(algo_module_name)
    
    report_tag = f"ALG{algo_id}"
    if algo_id in {"9", "10"}:
        report_tag = f"ALG{algo_id}_{RUN_MODE_LABEL}_{DATASET_PROFILE_LABEL}"
    REPORT_FILE = os.path.join(RESULTS_BASE_DIR, f"thesis_results_{report_tag}_{timestamp}.csv")

    print(f"\n--- THESIS PIPELINE STARTED [{timestamp}] ---")
    print(f"    Saving report to: {REPORT_FILE}")
    print(f"    Dataset workspace: {DATASET_DIR}")
    print(f"    Optimized outputs: {CURRENT_RUN_DIR}")

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
    dataset_files = sorted(glob.glob(f"{DATASET_DIR}/*.aag"))
    repeat_until_zero = algo_id == "10" and os.environ.get("ALG10_REPEAT_UNTIL_ZERO", "0") != "0"
    repeat_cycles = max(1, int(os.environ.get("ALG10_REPEAT_CYCLES", "1")))
    total_seconds = float(os.environ.get("ALG10_TOTAL_SECONDS", "0") or "0")
    campaign_deadline = time.time() + total_seconds if algo_id == "10" and total_seconds > 0 else None
    latest_unresolved_by_path = {}
    stalled_paths = set()

    for campaign_cycle, f_path in campaign_file_iterator(dataset_files, repeat_until_zero, repeat_cycles):
        if campaign_deadline is not None and time.time() >= campaign_deadline:
            print("    Alg10 campaign deadline reached; saving current report.")
            break
        if (
            repeat_until_zero
            and latest_unresolved_by_path
            and len(latest_unresolved_by_path) == len(dataset_files)
            and all(value == 0 or path in stalled_paths for path, value in latest_unresolved_by_path.items())
        ):
            if all(value == 0 for value in latest_unresolved_by_path.values()):
                print("    Alg10 campaign reached SAT_Unresolved=0 for every circuit seen.")
            else:
                print("    Alg10 campaign has no further progress at the configured budgets.")
            break
        if repeat_until_zero and (latest_unresolved_by_path.get(f_path) == 0 or f_path in stalled_paths):
            continue
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
                if repeat_until_zero:
                    latest_unresolved_by_path[f_path] = 0
                continue
        except Exception:
            input_metrics = None
        
        prefix = f"[cycle {campaign_cycle}] " if repeat_until_zero else ""
        print(f"    {prefix}Processing {name:<25}...", end=" ", flush=True)
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
                timings.get("Checkpoint_Status_Loaded", ""),
                timings.get("Checkpoint_JSON_Loaded", ""),
                timings.get("Checkpoint_Work_Loaded", ""),
                timings.get("Checkpoint_Source_Dir", ""),
                timings.get("Checkpoint_Imported_External", ""),
                timings.get("Checkpoint_Select_Policy", ""),
                timings.get("Checkpoint_Start_AND2", ""),
                timings.get("Checkpoint_Start_Removed_AND2", ""),
                timings.get("New_Removed_This_Run", ""),
                timings.get("Checkpoint_Start_Unresolved", ""),
                timings.get("Checkpoint_Unresolved_Delta", ""),
                timings.get("TFI_Checks", ""), timings.get("TFI_Query_SAT", ""),
                timings.get("TFI_Query_UNSAT", ""), timings.get("TFI_Timeouts", ""),
                timings.get("TFI_Skipped", ""),
                timings.get("Window_Checks", ""), timings.get("Window_Query_SAT", ""),
                timings.get("Window_Query_UNSAT", ""), timings.get("Window_Timeouts", ""),
                timings.get("Window_Skipped", ""), timings.get("Window_Audit_Fail", ""),
                timings.get("Window_Root_Strategy", ""),
                timings.get("Window_Dominator_Attempts", ""),
                timings.get("Window_Dominator_Used", ""),
                timings.get("Window_Dominator_Fallbacks", ""),
                timings.get("Cone_Checks", ""), timings.get("Cone_Query_SAT", ""),
                timings.get("Cone_Query_UNSAT", ""), timings.get("Cone_Timeouts", ""),
                timings.get("Cone_Skipped", ""),
                timings.get("Cone_Engine", ""),
                timings.get("Cone_Solver", ""),
                timings.get("Cone_Group_Min_Size", ""),
                timings.get("Cone_Partition_Size", ""),
                timings.get("Cone_Partition_Min_Roots", ""),
                timings.get("Cone_Partition_Max_Gates", ""),
                timings.get("Cone_Partition_Checks", ""),
                timings.get("Cone_Partition_Query_SAT", ""),
                timings.get("Cone_Partition_Query_UNSAT", ""),
                timings.get("Cone_Partition_Timeouts", ""),
                timings.get("Cone_Partition_Groups", ""),
                timings.get("Cone_Partition_Audit_Fail", ""),
                timings.get("Cone_Partition_Skipped", ""),
                timings.get("Cone_Partition_No_Affected", ""),
                timings.get("Cone_Partition_Below_Min_Roots", ""),
                timings.get("Cone_Partition_Target_Outside_Cone", ""),
                timings.get("Cone_Partition_Cone_Too_Large", ""),
                timings.get("Cone_Partition_Fallbacks", ""),
                timings.get("Cone_Partition_Max_Seen_Cone_Gates", ""),
                timings.get("Cone_Partition_Max_Skipped_Cone_Gates", ""),
                timings.get("Cone_TFO_Max_Good_Gates_Config", ""),
                timings.get("Cone_TFO_Max_Faulty_Gates_Config", ""),
                timings.get("Cone_TFO_Checks", ""),
                timings.get("Cone_TFO_Query_SAT", ""),
                timings.get("Cone_TFO_Query_UNSAT", ""),
                timings.get("Cone_TFO_Timeouts", ""),
                timings.get("Cone_TFO_Skipped", ""),
                timings.get("Cone_TFO_Audit_Fail", ""),
                timings.get("Cone_TFO_Max_Good_Gates", ""),
                timings.get("Cone_TFO_Max_Faulty_Gates", ""),
                timings.get("Global_Checks", ""), timings.get("Global_Solver", ""),
                timings.get("Global_Max_Consecutive_Timeouts", ""),
                timings.get("Global_Frontier_Order", ""),
                timings.get("Global_Phase_Mode", ""),
                timings.get("Global_Phase_Model_Limit", ""),
                timings.get("Global_Query_SAT", ""),
                timings.get("Global_Query_UNSAT", ""), timings.get("Global_Timeouts", ""),
                timings.get("Global_Budget_History_Loaded", ""),
                timings.get("Global_Budget_History_Skipped", ""),
                timings.get("Global_Budget_History_Exhausted", ""),
                timings.get("Phase_Local_Resume_Enabled", ""),
                timings.get("Phase_Local_Resume_Used", ""),
                timings.get("Phase_Local_Resume_Saved", ""),
                timings.get("Phase_Local_Resume_Candidates", ""),
                timings.get("Exact_Frontier_Resume_Enabled", ""),
                timings.get("Exact_Frontier_Resume_Used", ""),
                timings.get("Exact_Frontier_Resume_Candidates", ""),
                timings.get("Exact_Frontier_Skipped_Lower_Tiers", ""),
                timings.get("Exact_Frontier_Resume_Tier", ""),
                timings.get("CEX_Pool_Enabled", ""), timings.get("CEX_Pool_Loaded", ""),
                timings.get("CEX_Pool_Saved", ""), timings.get("CEX_Pool_Size", ""),
                timings.get("CEX_Pool_Added", ""), timings.get("CEX_Pool_Replay_Patterns", ""),
                timings.get("CEX_Pool_Replay_Checked", ""), timings.get("CEX_Pool_Replay_Pruned", ""),
                timings.get("PreSAT_Sim_Enabled", ""), timings.get("PreSAT_Sim_Engine", ""),
                timings.get("PreSAT_Sim_Packed_Max_Bits", ""), timings.get("PreSAT_Sim_After_TFI", ""),
                timings.get("PreSAT_Sim_Patterns", ""),
                timings.get("PreSAT_Sim_Checked", ""), timings.get("PreSAT_Sim_Pruned", ""),
                timings.get("PreSAT_Sim_Structured_Pruned", ""),
                timings.get("PreSAT_Sim_Random_Pruned", ""),
                timings.get("PreSAT_Sim_Time", ""),
                timings.get("PreSAT_Sim_Adaptive_Stop", ""),
                timings.get("CEX_Prune_Events", ""), timings.get("CEX_Prune_Checked", ""),
                timings.get("CEX_Pruned", ""), timings.get("CEX_TFI_Prune_Events", ""),
                timings.get("CEX_TFI_Prune_Checked", ""), timings.get("CEX_TFI_Pruned", ""),
                timings.get("CEX_Pruning_Enabled", ""),
                timings.get("CEX_Audit_Enabled", ""), timings.get("CEX_Audit_Checked", ""),
                timings.get("CEX_Audit_SAT", ""), timings.get("CEX_Audit_False_Prunes", ""),
                timings.get("CEX_Audit_Timeouts", ""), timings.get("CEX_Audit_Skipped", ""),
                timings.get("CEX_Audit_Limit_Hit", ""),
                timings.get("Faults_Total", ""), timings.get("Faults_Unresolved", ""),
                timings.get("Faults_Classified_Lower_Bound", ""),
                timings.get("Fault_Coverage_Lower_Bound%", ""),
                timings.get("Fault_Detection_Events_By_PreSim", ""),
                timings.get("Fault_Detection_Events_By_CEX_Pool", ""),
                timings.get("Fault_Detection_Events_By_CEX_Prune", ""),
                timings.get("Fault_Redundancy_Proof_Events_UNSAT", ""),
                timings.get("Functional_Const_Proofs_TFI", ""),
                timings.get("Exact_Miter_UNSAT_Proofs_Window", ""),
                timings.get("Exact_Miter_UNSAT_Proofs_Cone", ""),
                timings.get("Exact_Miter_UNSAT_Proofs_Global", ""),
                timings.get("Exact_Miter_UNSAT_Proofs_Total", ""),
                status
            ])
            if repeat_until_zero:
                unresolved_now = _csv_int(timings.get("SAT_Unresolved", 0))
                latest_unresolved_by_path[f_path] = unresolved_now
                no_new_removed = _csv_int(timings.get("New_Removed_This_Run", 0)) == 0
                no_unresolved_drop = _csv_int(timings.get("Checkpoint_Unresolved_Delta", 0)) <= 0
                exhausted = _csv_int(timings.get("Global_Budget_History_Exhausted", 0))
                checks_now = _csv_int(timings.get("SAT_Checks", 0))
                if unresolved_now > 0 and no_new_removed and no_unresolved_drop and (
                    checks_now == 0 or exhausted >= unresolved_now
                ):
                    stalled_paths.add(f_path)

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
            if repeat_until_zero:
                latest_unresolved_by_path[f_path] = max(
                    1, _csv_int(latest_unresolved_by_path.get(f_path, 1))
                )
                stalled_paths.add(f_path)

    report_header = [
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
        "Checkpoint_Status_Loaded", "Checkpoint_JSON_Loaded", "Checkpoint_Work_Loaded",
        "Checkpoint_Source_Dir", "Checkpoint_Imported_External", "Checkpoint_Select_Policy",
        "Checkpoint_Start_AND2",
        "Checkpoint_Start_Removed_AND2", "New_Removed_This_Run",
        "Checkpoint_Start_Unresolved", "Checkpoint_Unresolved_Delta",
        "TFI_Checks", "TFI_Query_SAT", "TFI_Query_UNSAT", "TFI_Timeouts", "TFI_Skipped",
        "Window_Checks", "Window_Query_SAT", "Window_Query_UNSAT", "Window_Timeouts",
        "Window_Skipped", "Window_Audit_Fail",
        "Window_Root_Strategy", "Window_Dominator_Attempts", "Window_Dominator_Used",
        "Window_Dominator_Fallbacks",
        "Cone_Checks", "Cone_Query_SAT", "Cone_Query_UNSAT", "Cone_Timeouts", "Cone_Skipped",
        "Cone_Engine", "Cone_Solver", "Cone_Group_Min_Size",
        "Cone_Partition_Size", "Cone_Partition_Min_Roots", "Cone_Partition_Max_Gates",
        "Cone_Partition_Checks",
        "Cone_Partition_Query_SAT", "Cone_Partition_Query_UNSAT",
        "Cone_Partition_Timeouts", "Cone_Partition_Groups",
        "Cone_Partition_Audit_Fail",
        "Cone_Partition_Skipped", "Cone_Partition_No_Affected",
        "Cone_Partition_Below_Min_Roots", "Cone_Partition_Target_Outside_Cone",
        "Cone_Partition_Cone_Too_Large", "Cone_Partition_Fallbacks",
        "Cone_Partition_Max_Seen_Cone_Gates",
        "Cone_Partition_Max_Skipped_Cone_Gates",
        "Cone_TFO_Max_Good_Gates_Config", "Cone_TFO_Max_Faulty_Gates_Config",
        "Cone_TFO_Checks", "Cone_TFO_Query_SAT", "Cone_TFO_Query_UNSAT",
        "Cone_TFO_Timeouts", "Cone_TFO_Skipped", "Cone_TFO_Audit_Fail",
        "Cone_TFO_Max_Good_Gates", "Cone_TFO_Max_Faulty_Gates",
        "Global_Checks", "Global_Solver", "Global_Max_Consecutive_Timeouts",
        "Global_Frontier_Order", "Global_Phase_Mode", "Global_Phase_Model_Limit",
        "Global_Query_SAT", "Global_Query_UNSAT", "Global_Timeouts",
        "Global_Budget_History_Loaded", "Global_Budget_History_Skipped",
        "Global_Budget_History_Exhausted",
        "Phase_Local_Resume_Enabled", "Phase_Local_Resume_Used",
        "Phase_Local_Resume_Saved", "Phase_Local_Resume_Candidates",
        "Exact_Frontier_Resume_Enabled", "Exact_Frontier_Resume_Used",
        "Exact_Frontier_Resume_Candidates", "Exact_Frontier_Skipped_Lower_Tiers",
        "Exact_Frontier_Resume_Tier",
        "CEX_Pool_Enabled", "CEX_Pool_Loaded", "CEX_Pool_Saved", "CEX_Pool_Size",
        "CEX_Pool_Added", "CEX_Pool_Replay_Patterns", "CEX_Pool_Replay_Checked",
        "CEX_Pool_Replay_Pruned",
        "PreSAT_Sim_Enabled", "PreSAT_Sim_Engine", "PreSAT_Sim_Packed_Max_Bits",
        "PreSAT_Sim_After_TFI", "PreSAT_Sim_Patterns", "PreSAT_Sim_Checked",
        "PreSAT_Sim_Pruned", "PreSAT_Sim_Structured_Pruned",
        "PreSAT_Sim_Random_Pruned", "PreSAT_Sim_Time", "PreSAT_Sim_Adaptive_Stop",
        "CEX_Prune_Events", "CEX_Prune_Checked", "CEX_Pruned",
        "CEX_TFI_Prune_Events", "CEX_TFI_Prune_Checked", "CEX_TFI_Pruned",
        "CEX_Pruning_Enabled",
        "CEX_Audit_Enabled", "CEX_Audit_Checked", "CEX_Audit_SAT",
        "CEX_Audit_False_Prunes", "CEX_Audit_Timeouts", "CEX_Audit_Skipped",
        "CEX_Audit_Limit_Hit",
        "Faults_Total", "Faults_Unresolved", "Faults_Classified_Lower_Bound",
        "Fault_Coverage_Lower_Bound%", "Fault_Detection_Events_By_PreSim",
        "Fault_Detection_Events_By_CEX_Pool", "Fault_Detection_Events_By_CEX_Prune",
        "Fault_Redundancy_Proof_Events_UNSAT",
        "Functional_Const_Proofs_TFI", "Exact_Miter_UNSAT_Proofs_Window",
        "Exact_Miter_UNSAT_Proofs_Cone", "Exact_Miter_UNSAT_Proofs_Global",
        "Exact_Miter_UNSAT_Proofs_Total",
        "Verify"
    ]

    with open(REPORT_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(report_header)
        width = len(report_header)
        for row in stats:
            if len(row) < width:
                row.extend([""] * (width - len(row)))
            elif len(row) > width:
                del row[width:]
        writer.writerows(stats)

    print(f"\n[DONE] Saved report to {REPORT_FILE}")
    print_alg10_diagnostic_summary(report_header, stats)
    maybe_generate_report_charts(REPORT_FILE)
