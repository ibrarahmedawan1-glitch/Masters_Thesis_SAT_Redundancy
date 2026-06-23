#!/usr/bin/env python3
"""Refresh a compact status view for an Alg10 campaign directory."""

from __future__ import annotations

import argparse
import glob
import json
import os
import time
from datetime import datetime


FINAL_STATUSES = {
    "ALL_TARGETS_COMPLETE",
    "FINISHED_WITH_FAILURES",
    "NO_ACTIVE_TARGETS",
    "NO_RUNNABLE_WORK",
    "TIME_BUDGET_COMPLETE",
    "STOPPED_BY_USER",
}


def _duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _latest_generation(root: str, key: str):
    path = os.path.join(root, key, "generations.jsonl")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            position = f.tell()
            line = b""
            while position > 0:
                position -= 1
                f.seek(position)
                byte = f.read(1)
                if byte == b"\n" and line:
                    break
                line = byte + line
        return json.loads(line.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _render(root: str) -> str:
    summary = _load_json(os.path.join(root, "summary.json"))
    if not summary:
        return f"Waiting for {os.path.join(root, 'summary.json')}..."

    now = time.time()
    started = float(summary.get("started", now))
    deadline = float(summary.get("deadline", now))
    status = str(summary.get("status", "UNKNOWN"))
    lines = [
        f"Campaign: {root}",
        f"Updated:  {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"Status:   {status}",
        f"Elapsed:  {_duration(now - started)}",
        f"Remaining:{_duration(deadline - now)}",
    ]
    targets = summary.get("targets", [])
    dynamic = any("dispatches" in target for target in targets)
    if dynamic:
        metrics = summary.get("pool_metrics", {})
        utilization = 100.0 * float(metrics.get("worker_utilization", 0.0) or 0.0)
        lines.extend(
            [
                f"Pool:     workers={summary.get('hardware', {}).get('selected', 0)} "
                f"active_max={metrics.get('max_active_workers', 0)} "
                f"dispatches={summary.get('dispatches', 0)} "
                f"utilization={utilization:.1f}%",
                "",
                f"{'Circuit':32} {'Gen':>4} {'Gates':>9} {'Unresolved':>11} "
                f"{'InFlight':>8} {'Dispatch':>8} {'State':>20}",
                "-" * 101,
            ]
        )
        for target in targets:
            lines.append(
                f"{str(target.get('key', '?')):32} "
                f"{int(target.get('generation', 0) or 0):4d} "
                f"{int(target.get('current_gates', 0) or 0):9d} "
                f"{int(target.get('unresolved', 0) or 0):11d} "
                f"{int(target.get('inflight', 0) or 0):8d} "
                f"{int(target.get('dispatches', 0) or 0):8d} "
                f"{str(target.get('status', 'UNKNOWN')):>20}"
            )
    else:
        lines.extend(
            [
                "",
                f"{'Circuit':32} {'Visits':>6} {'Gates':>9} {'Unresolved':>11} "
                f"{'Budget':>10} {'Last wave':>10}",
                "-" * 88,
            ]
        )
        for target in targets:
            key = str(target.get("key", "?"))
            generation = _latest_generation(root, key) or {}
            lines.append(
                f"{key:32} "
                f"{int(target.get('visits', 0) or 0):6d} "
                f"{int(target.get('last_gates', target.get('current_gates', 0)) or 0):9d} "
                f"{int(target.get('last_unresolved', target.get('unresolved', 0)) or 0):11d} "
                f"{int(generation.get('budget', 0) or 0):10d} "
                f"{_duration(float(generation.get('wave_seconds', 0) or 0)):>10}"
            )
    if status in FINAL_STATUSES:
        lines.extend(["", "Campaign has finished."])
    else:
        lines.extend(["", "Press Ctrl-C to stop monitoring; this does not stop the run."])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "campaign",
        nargs="?",
        default="results_optimized/parallel_tfo_benchmarks_6h_20260614_215326",
    )
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    root = os.path.abspath(args.campaign)

    try:
        while True:
            print("\033[2J\033[H", end="")
            print(_render(root), flush=True)
            summary = _load_json(os.path.join(root, "summary.json")) or {}
            if args.once or summary.get("status") in FINAL_STATUSES:
                return 0
            time.sleep(max(1.0, args.interval))
    except KeyboardInterrupt:
        print("\nStopped monitoring. Campaign process was not signalled.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
