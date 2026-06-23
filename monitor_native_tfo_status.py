#!/usr/bin/env python3
"""Print or watch a native exact-TFO campaign summary."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict


FINAL_STATUSES = {
    "COMPLETE",
    "NO_RUNNABLE_WORK",
    "TIME_BUDGET_COMPLETE",
    "SOURCE_CHANGED_CHECKPOINT",
    "DRAINING_AT_DEADLINE",
    "UNRESOLVED_BUDGETS_EXHAUSTED",
}


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _pid_from_file(root: Path) -> int:
    path = root / "native_campaign.pid"
    if not path.exists():
        return 0
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _ps(pid: int) -> str:
    if pid <= 0:
        return "PID: not recorded"
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "pid,ppid,stat,etime,pcpu,pmem,rss,args"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    output = result.stdout.strip()
    return output if output else f"PID {pid}: not running"


def _fmt_seconds(value: Any) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "-"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def print_status(root: Path) -> None:
    summary = _load_json(root / "summary.json")
    manifest = _load_json(root / "native_run_manifest.json")
    pid = _pid_from_file(root)
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    print("=" * 88)
    print(f"time: {now}")
    print(f"run:  {root}")
    print(_ps(pid))

    if not summary:
        print("summary: not written yet")
        if manifest:
            targets = [item.get("key", "") for item in manifest.get("targets", [])]
            print(f"manifest targets: {', '.join(targets)}")
        return

    status = str(summary.get("status", "UNKNOWN"))
    elapsed = _fmt_seconds(summary.get("elapsed"))
    finished = status in FINAL_STATUSES
    pool = summary.get("pool_metrics", {})
    print(
        "campaign:",
        f"status={status}",
        f"elapsed={elapsed}",
        f"finished={finished}",
    )
    print(
        "pool:",
        f"tasks={pool.get('tasks_completed', 0)}/{pool.get('tasks_submitted', 0)}",
        f"barriers={pool.get('proposal_barriers_completed', 0)}/"
        f"{pool.get('proposal_barriers_submitted', 0)}",
        f"deferred={pool.get('proposal_barriers_deferred', 0)}",
        f"util={float(pool.get('worker_utilization', 0.0) or 0.0):.3f}",
        f"max_active={pool.get('max_active_workers', 0)}",
    )

    print("-" * 88)
    header = (
        f"{'target':34} {'status':22} {'rem':>5} {'unres':>8} "
        f"{'prop':>4} {'commit':>6} {'cec':>3} {'err':>3} last"
    )
    print(header)
    print("-" * len(header))
    for target in summary.get("targets", []):
        totals = target.get("totals", {})
        print(
            f"{str(target.get('key', ''))[:34]:34} "
            f"{str(target.get('status', ''))[:22]:22} "
            f"{int(target.get('removed', 0) or 0):5d} "
            f"{int(target.get('unresolved', 0) or 0):8d} "
            f"{int(target.get('proposals_waiting', 0) or 0):4d} "
            f"{str(bool(target.get('commit_inflight', False))):>6} "
            f"{int(totals.get('cec_pass_commits', 0) or 0):3d} "
            f"{int(totals.get('worker_errors', 0) or 0):3d} "
            f"{target.get('last_abort_reason', '')}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", help="native exact-TFO run directory")
    parser.add_argument(
        "--watch",
        type=float,
        default=0.0,
        help="refresh every N seconds until interrupted",
    )
    args = parser.parse_args()
    root = Path(args.run_dir).resolve()
    if args.watch <= 0:
        print_status(root)
        return 0
    while True:
        os.system("clear")
        print_status(root)
        time.sleep(max(1.0, float(args.watch)))


if __name__ == "__main__":
    raise SystemExit(main())
