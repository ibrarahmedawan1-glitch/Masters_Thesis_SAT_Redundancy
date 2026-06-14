#!/usr/bin/env python3
"""Launch safe parallel Alg10 portfolio runs.

This script uses process-level parallelism: each worker runs `main.py` on one
custom circuit (or one strategy variant) with its own checkpoint directory.
That keeps checkpoints and ABC CEC verification independent, while still using
multiple CPU cores and the available RAM.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass


BASE_EXTRA_DIRS = [
    "results_optimized/alg10_checkpoints_preflight_sin_untried_first_high_budget",
    "results_optimized/alg10_checkpoints_preflight_sin_tried_asc_high_budget",
    "results_optimized/alg10_checkpoints_best_protected_campaign",
    "results_optimized/alg10_checkpoints_best_unresolved_campaign",
    "results_optimized/alg10_checkpoints_global_strategy_div",
    "results_optimized/alg10_checkpoints_global_strategy_sqrt",
    "results_optimized/alg10_checkpoints_final_sat_strategy",
    "results_optimized/alg10_checkpoints_strict_audit",
    "results_optimized/alg10_checkpoints_resume_pool_presim",
]


@dataclass(frozen=True)
class Task:
    name: str
    path: str
    order: str = "untried_first"


SCENARIOS = {
    "finishline": [
        Task("sin", "benchmark_suites/epfl/epfl_arithmetic_sin.aag"),
        Task("div", "benchmark_suites/epfl/epfl_arithmetic_div.aag"),
        Task("sqrt", "benchmark_suites/epfl/epfl_arithmetic_sqrt.aag"),
        Task("hyp", "benchmark_suites/epfl/epfl_arithmetic_hyp.aag"),
        Task("voter", "benchmark_suites/epfl/epfl_random_control_voter.aag"),
    ],
    "heavyweights": [
        Task("log2", "benchmark_suites/epfl/epfl_arithmetic_log2.aag"),
        Task("mem_ctrl", "benchmark_suites/epfl/epfl_random_control_mem_ctrl.aag"),
    ],
    "sin-portfolio": [
        Task("sin_untried_first", "benchmark_suites/epfl/epfl_arithmetic_sin.aag", "untried_first"),
        Task("sin_tried_asc", "benchmark_suites/epfl/epfl_arithmetic_sin.aag", "tried_asc"),
        Task("sin_reverse", "benchmark_suites/epfl/epfl_arithmetic_sin.aag", "reverse"),
        Task("sin_depth_desc", "benchmark_suites/epfl/epfl_arithmetic_sin.aag", "depth_desc"),
    ],
}


DONE_RE = re.compile(r"\[DONE\] Saved report to (?P<path>\S+)")
START_RE = re.compile(r"Saving report to: (?P<path>\S+)")
STOP_REQUESTED = False


def _timestamp():
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def _existing_dirs(paths):
    return [path for path in paths if path and os.path.isdir(path)]


def _report_from_log(log_path):
    report = ""
    if not os.path.exists(log_path):
        return report
    with open(log_path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            done = DONE_RE.search(line)
            if done:
                report = done.group("path")
            elif not report:
                started = START_RE.search(line)
                if started:
                    report = started.group("path")
    return report


def _tail(path, lines=8):
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as handle:
        content = handle.readlines()
    return "".join(content[-lines:]).rstrip()


def _request_stop(signum, frame):
    del signum, frame
    global STOP_REQUESTED
    STOP_REQUESTED = True


def _terminate_running(running):
    for item in running:
        process = item["process"]
        if process.poll() is None:
            print(f"[stop]  terminating {item['task'].name:<16} pid={process.pid}")
            process.terminate()
    deadline = time.time() + 10
    for item in running:
        process = item["process"]
        if process.poll() is None:
            remaining = max(0.0, deadline - time.time())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                print(f"[stop]  killing {item['task'].name:<16} pid={process.pid}")
                process.kill()
    for item in running:
        try:
            item["log_handle"].close()
        except Exception:
            pass


def _worker_timestamp(tag, task):
    stamp = _dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
    safe_tag = re.sub(r"[^A-Za-z0-9_.-]+", "_", tag)
    safe_task = re.sub(r"[^A-Za-z0-9_.-]+", "_", task.name)
    return f"{stamp}_{safe_tag}_{safe_task}"


def build_env(args, task, checkpoint_dir, sibling_dirs, worker_timestamp):
    env = os.environ.copy()
    extra_dirs = _existing_dirs(BASE_EXTRA_DIRS + list(args.extra_checkpoint_dir or []))
    if args.include_finished_siblings:
        extra_dirs.extend(_existing_dirs(sibling_dirs))
    env.update(
        {
            "ALG10_TOTAL_SECONDS": str(args.seconds),
            "ALG10_BUDGETS": args.budgets,
            "ALG10_RESET_CHECKPOINT": "0",
            "ALG10_CHECKPOINT_DIR": checkpoint_dir,
            "ALG10_EXTRA_CHECKPOINT_DIRS": ",".join(dict.fromkeys(extra_dirs)),
            "ALG10_CHECKPOINT_SELECT": "unresolved",
            "ALG10_PROTECT_BEST_CHECKPOINT": "1",
            "ALG10_PHASE_LOCAL_RESUME": "1",
            "ALG10_EXACT_FRONTIER_RESUME": "1",
            "ALG10_GLOBAL_SOLVER": args.solver,
            "ALG10_GLOBAL_FRONTIER_ORDER": task.order,
            "ALG10_GLOBAL_PHASE_MODE": args.phase_mode,
            "ALG10_GLOBAL_MAX_CONSEC_TIMEOUTS": str(args.max_consec_timeouts),
            "ALG10_AUTO_PLOTS": "1",
            "THESIS_RUN_TIMESTAMP": worker_timestamp,
        }
    )
    return env


def launch_task(args, task, tag, sibling_dirs):
    checkpoint_dir = os.path.join(
        "results_optimized",
        f"alg10_checkpoints_parallel_{tag}_{task.name}",
    )
    os.makedirs(checkpoint_dir, exist_ok=True)
    log_path = f"alg10_parallel_{tag}_{task.name}.log"
    stdin_text = f"10\n4\n5\n{task.path}\n"
    worker_timestamp = _worker_timestamp(tag, task)
    env = build_env(args, task, checkpoint_dir, sibling_dirs, worker_timestamp)
    log_handle = open(log_path, "w", encoding="utf-8")
    process = subprocess.Popen(
        [args.python, "main.py"],
        stdin=subprocess.PIPE,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    assert process.stdin is not None
    process.stdin.write(stdin_text)
    process.stdin.close()
    return {
        "task": task,
        "process": process,
        "log_handle": log_handle,
        "log_path": log_path,
        "checkpoint_dir": checkpoint_dir,
        "worker_timestamp": worker_timestamp,
        "started": time.time(),
    }


def run(args):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    tasks = list(SCENARIOS[args.scenario])
    if args.only:
        wanted = {item.strip() for item in args.only.split(",") if item.strip()}
        tasks = [task for task in tasks if task.name in wanted]
    if not tasks:
        print("No tasks selected.", file=sys.stderr)
        return 2

    tag = args.tag or f"{args.scenario}_{_timestamp()}"
    sibling_dirs = [
        os.path.join("results_optimized", f"alg10_checkpoints_parallel_{tag}_{task.name}")
        for task in tasks
    ]
    pending = list(tasks)
    running = []
    finished = []

    print(f"Launching Alg10 parallel portfolio: scenario={args.scenario}, tag={tag}")
    print(f"Budgets={args.budgets}, seconds/worker={args.seconds}, jobs={args.jobs}")

    while pending or running:
        if STOP_REQUESTED:
            print("[stop]  stop requested; no new workers will be launched")
            pending.clear()
            _terminate_running(running)
            running.clear()
            break
        while pending and len(running) < args.jobs:
            task = pending.pop(0)
            item = launch_task(args, task, tag, sibling_dirs)
            running.append(item)
            print(
                f"[start] {task.name:<16} pid={item['process'].pid} "
                f"order={task.order:<13} stamp={item['worker_timestamp']} "
                f"log={item['log_path']}"
            )

        time.sleep(args.poll_seconds)
        still_running = []
        for item in running:
            rc = item["process"].poll()
            if rc is None:
                elapsed = int(time.time() - item["started"])
                print(f"[run]   {item['task'].name:<16} pid={item['process'].pid} elapsed={elapsed}s")
                still_running.append(item)
                continue
            item["log_handle"].close()
            report = _report_from_log(item["log_path"])
            item["report"] = report
            item["returncode"] = rc
            finished.append(item)
            status = "ok" if rc == 0 else f"exit={rc}"
            print(f"[done]  {item['task'].name:<16} {status} report={report or 'none'}")
            tail = _tail(item["log_path"])
            if tail:
                print(tail)
        running = still_running

    reports = [item.get("report", "") for item in finished if item.get("report") and os.path.exists(item["report"])]
    print("\nCheckpoint dirs:")
    for item in finished:
        print(f"  {item['checkpoint_dir']}")
    if reports:
        print("\nDecision summary:")
        subprocess.run([args.python, "alg10_decision_summary.py", *reports], check=False)
    else:
        print("\nNo finished report CSVs found. Inspect logs above.")
    return 0


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS),
        default="finishline",
        help="Predefined parallel workload.",
    )
    parser.add_argument("--jobs", type=int, default=4, help="Maximum concurrent workers.")
    parser.add_argument("--seconds", type=int, default=43200, help="ALG10_TOTAL_SECONDS per worker.")
    parser.add_argument("--budgets", default="1000000,2000000,5000000", help="ALG10_BUDGETS.")
    parser.add_argument("--solver", default="cadical153", help="Global SAT solver.")
    parser.add_argument("--phase-mode", default="model", help="ALG10_GLOBAL_PHASE_MODE.")
    parser.add_argument("--max-consec-timeouts", type=int, default=80)
    parser.add_argument("--python", default="venv/bin/python")
    parser.add_argument("--tag", default="", help="Run tag for logs/checkpoints.")
    parser.add_argument("--only", default="", help="Comma-separated task names from the selected scenario.")
    parser.add_argument(
        "--extra-checkpoint-dir",
        action="append",
        default=[],
        help="Additional checkpoint directory to import.",
    )
    parser.add_argument(
        "--include-finished-siblings",
        action="store_true",
        help="Allow workers to import same-tag sibling checkpoint dirs. Use only for follow-up waves.",
    )
    parser.add_argument("--poll-seconds", type=int, default=60)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(run(parse_args(sys.argv[1:])))
