#!/usr/bin/env python3
"""Round-robin committing TFO campaign over the best hard checkpoints."""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import alg10_parallel_commit_coordinator as coordinator
import alg10_ranked_frontier_campaign as ranked


DEFAULT_FILTERS = ("sin", "sqrt", "hyp", "div", "log2", "mem_ctrl")


@dataclass
class TargetState:
    key: str
    source_path: str
    seed_checkpoint: str
    seed_work_path: str
    seed_unresolved: int
    seed_removed: int
    phase_tier: str
    visits: int = 0
    complete: bool = False
    failed: bool = False
    last_status: str = ""
    last_abort_reason: str = ""
    next_action: str = ""
    last_unresolved: int = 0
    last_gates: int = 0


def _write_json_atomic(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def _append_jsonl(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, sort_keys=True) + "\n")


def _parse_campaign_checkpoint_target(
    json_path: str,
) -> Optional[ranked.FrontierTarget]:
    target = ranked.parse_checkpoint_target(json_path)
    if target is not None:
        return target

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("phase_resume") is not None:
            return None
        telemetry = data.get("telemetry")
        if not isinstance(telemetry, dict):
            return None
        if int(telemetry.get("parallel_cec_pass_commits", 0) or 0) <= 0:
            return None
        work_path = ranked.checkpoint_work_path(data, json_path)
        source_path = str(data.get("source_path") or "")
        if not os.path.exists(work_path) or not os.path.exists(source_path):
            return None
        source_sha = str(data.get("source_sha256") or "")
        if source_sha and source_sha != ranked.sha256_file(source_path):
            return None
        current_gates = ranked.parse_aag_and_count(work_path)
        source_gates = ranked.parse_aag_and_count(source_path)
        if current_gates <= 0 or source_gates <= 0:
            return None
        if int(data.get("current_gates", 0) or 0) != current_gates:
            return None
        timestamp = float(data.get("timestamp", 0) or 0)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None

    regenerated_count = 2 * current_gates
    return ranked.FrontierTarget(
        key=ranked.normalized_key(data, json_path),
        json_path=os.path.abspath(json_path),
        work_path=os.path.abspath(work_path),
        source_path=os.path.abspath(source_path),
        unresolved=regenerated_count,
        phase_count=regenerated_count,
        telemetry_unresolved=regenerated_count,
        removed=max(0, source_gates - current_gates),
        source_gates=source_gates,
        current_gates=current_gates,
        phase_tier="regenerate",
        status=str(data.get("status", "")),
        timestamp=timestamp,
    )


def _parse_verified_output_summary(
    summary_path: str,
) -> Optional[ranked.FrontierTarget]:
    try:
        with open(summary_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("final_verify") != "PASS":
            return None
        source_path = str(data.get("source") or "")
        output_path = str(data.get("output") or "")
        if not os.path.exists(source_path) or not os.path.exists(output_path):
            return None
        source_gates = ranked.parse_aag_and_count(source_path)
        current_gates = ranked.parse_aag_and_count(output_path)
        if source_gates <= 0 or current_gates <= 0:
            return None
        if int(data.get("final_gates", 0) or 0) != current_gates:
            return None
        timestamp = float(data.get("finished", 0) or 0)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None

    regenerated_count = 2 * current_gates
    return ranked.FrontierTarget(
        key=ranked.normalized_key({"source_path": source_path}, summary_path),
        json_path=os.path.abspath(summary_path),
        work_path=os.path.abspath(output_path),
        source_path=os.path.abspath(source_path),
        unresolved=regenerated_count,
        phase_count=regenerated_count,
        telemetry_unresolved=regenerated_count,
        removed=max(0, source_gates - current_gates),
        source_gates=source_gates,
        current_gates=current_gates,
        phase_tier="verified_output",
        status=str(data.get("status", "")),
        timestamp=timestamp,
    )


def discover_best_targets(
    filters: Sequence[str],
    max_targets: int,
    checkpoint_dirs: Sequence[str] = (),
) -> List[TargetState]:
    dirs = sorted(glob.glob("results_optimized/alg10_checkpoints*"))
    dirs.extend(
        sorted(
            glob.glob(
                "results_optimized/parallel_tfo_*/**/checkpoints",
                recursive=True,
            )
        )
    )
    dirs.extend(checkpoint_dirs)
    candidates = []
    for json_path in ranked.checkpoint_json_paths(dirs):
        target = _parse_campaign_checkpoint_target(json_path)
        if target is not None and ranked.target_filter_match(target, filters):
            candidates.append(target)
    for summary_path in glob.glob(
        "results_optimized/parallel_tfo_*/**/visit_*_summary.json",
        recursive=True,
    ):
        target = _parse_verified_output_summary(summary_path)
        if target is not None and ranked.target_filter_match(target, filters):
            candidates.append(target)

    targets = _choose_best_checkpoint_targets(candidates, max_targets)
    return [
        TargetState(
            key=target.key,
            source_path=target.source_path,
            seed_checkpoint=target.json_path,
            seed_work_path=target.work_path,
            seed_unresolved=target.unresolved,
            seed_removed=target.removed,
            phase_tier=target.phase_tier,
            last_unresolved=target.unresolved,
            last_gates=target.current_gates,
        )
        for target in targets
        if target.source_path and os.path.exists(target.source_path)
    ]


def _choose_best_checkpoint_targets(
    candidates: Sequence[ranked.FrontierTarget],
    max_targets: int,
) -> List[ranked.FrontierTarget]:
    ordered = sorted(
        candidates,
        key=lambda target: (
            target.current_gates,
            target.unresolved,
            -target.timestamp,
            target.json_path,
        )
    )
    best = {}
    for target in ordered:
        best.setdefault(target.key, target)
    targets = sorted(
        best.values(),
        key=lambda target: (
            target.unresolved,
            -target.removed,
            target.current_gates,
            target.key,
        ),
    )
    if max_targets > 0:
        targets = targets[:max_targets]
    return targets


def _physical_core_count() -> int:
    pairs = set()
    physical_id = None
    core_id = None
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    if physical_id is not None and core_id is not None:
                        pairs.add((physical_id, core_id))
                    physical_id = None
                    core_id = None
                    continue
                if line.startswith("physical id"):
                    physical_id = line.split(":", 1)[1].strip()
                elif line.startswith("core id"):
                    core_id = line.split(":", 1)[1].strip()
        if physical_id is not None and core_id is not None:
            pairs.add((physical_id, core_id))
    except OSError:
        pass
    return len(pairs) or max(1, (os.cpu_count() or 1) // 2)


def _available_memory_bytes() -> int:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(re.findall(r"\d+", line)[0]) * 1024
    except (OSError, IndexError, ValueError):
        pass
    return 0


def resolve_worker_count(
    requested: int,
    logical_cores: Optional[int] = None,
    physical_cores: Optional[int] = None,
    available_memory: Optional[int] = None,
) -> Dict[str, int]:
    logical = max(1, int(logical_cores or os.cpu_count() or 1))
    physical = max(1, int(physical_cores or _physical_core_count()))
    available = (
        _available_memory_bytes()
        if available_memory is None
        else max(0, int(available_memory))
    )
    memory_cap = max(1, (available - 2 * 1024**3) // (1024**3)) if available else logical
    safe_cap = max(1, min(logical, memory_cap))
    recommended = max(1, min(physical, safe_cap))
    allow_memory_overcommit = (
        os.environ.get("ALG10_ALLOW_WORKER_MEMORY_OVERSUBSCRIBE", "0") != "0"
    )
    if requested <= 0:
        selected = recommended
    else:
        if requested > logical:
            raise ValueError(
                f"requested {requested} workers, but only {logical} logical CPUs are visible"
            )
        selected = (
            int(requested)
            if allow_memory_overcommit
            else min(int(requested), safe_cap)
        )
    return {
        "selected": int(selected),
        "recommended": int(recommended),
        "logical_cores": int(logical),
        "physical_cores": int(physical),
        "available_memory_bytes": int(available),
        "memory_worker_cap": int(memory_cap),
        "memory_overcommit": bool(allow_memory_overcommit and requested > safe_cap),
    }


def abort_reason_for_result(result: Dict[str, Any]) -> str:
    status = str(result.get("status", ""))
    if status == "COMPLETE":
        return "COMPLETE"
    if status in {"CEC_FAILED_ROLLBACK", "ERROR"}:
        return status

    records = result.get("records")
    last = records[-1] if isinstance(records, list) and records else {}
    transaction = last.get("transaction") if isinstance(last, dict) else {}
    if isinstance(transaction, dict) and transaction.get("committed"):
        return "CEC_PASSED_COMMIT"

    worker_counts = last.get("worker_counts") if isinstance(last, dict) else {}
    coordinator_results = (
        last.get("coordinator_results") if isinstance(last, dict) else []
    )
    if (
        isinstance(worker_counts, dict)
        and int(worker_counts.get("TIMEOUT", 0) or 0) > 0
    ) or any(
        isinstance(item, dict) and item.get("status") == "TIMEOUT"
        for item in coordinator_results or []
    ):
        return "SAT_TIMEOUT"
    if (
        isinstance(worker_counts, dict)
        and int(worker_counts.get("SAT_REJECT", 0) or 0) > 0
    ) or any(
        isinstance(item, dict) and item.get("status") == "SAT_REJECT"
        for item in coordinator_results or []
    ):
        return "SAT_REJECT"
    if status == "TIME_BUDGET_CHECKPOINT":
        return "TIME_SLICE_EXPIRED"
    return status or "UNKNOWN"


def next_action_for_result(result: Dict[str, Any]) -> str:
    reason = abort_reason_for_result(result)
    if reason == "COMPLETE":
        return "COMPLETE"
    if reason in {"CEC_FAILED_ROLLBACK", "ERROR"}:
        return "STOP_AND_AUDIT"
    if reason == "CEC_PASSED_COMMIT":
        return "REGENERATE_FRONTIER"
    if reason == "SAT_TIMEOUT":
        return "INCREASE_BUDGET"
    if reason == "SAT_REJECT":
        return "CONTINUE_FRONTIER"
    if reason == "TIME_SLICE_EXPIRED":
        return "RESUME_EXACT_FRONTIER"
    return "CONTINUE"


def _target_paths(root: str, target: TargetState) -> Dict[str, str]:
    target_root = os.path.join(root, target.key)
    return {
        "root": target_root,
        "checkpoint_dir": os.path.join(target_root, "checkpoints"),
        "output": os.path.join(target_root, target.key + ".aag"),
        "jsonl": os.path.join(target_root, "generations.jsonl"),
    }


def _materialize_verified_output_seed(
    target: TargetState,
    checkpoint_dir: str,
    cec_timeout: float,
) -> str:
    verify, _seconds, _output = coordinator.run_abc_cec(
        target.source_path,
        target.seed_work_path,
        timeout=cec_timeout,
    )
    if verify != "PASS":
        raise RuntimeError(
            f"verified output seed failed fresh CEC: {target.seed_work_path}"
        )
    seed_path = os.path.join(checkpoint_dir, "verified_output_seed.json")
    _write_json_atomic(
        seed_path,
        {
            "algorithm": "ALG10",
            "mode": "parallel_tfo_verified_output_seed",
            "status": "VERIFIED_OUTPUT_SEED",
            "timestamp": time.time(),
            "source_path": os.path.abspath(target.source_path),
            "source_sha256": ranked.sha256_file(target.source_path),
            "work_aag": os.path.abspath(target.seed_work_path),
            "current_gates": target.last_gates,
            "budgets": [],
            "phase_resume": None,
            "telemetry": {
                "unresolved": 2 * target.last_gates,
                "parallel_cec_pass_commits": 1,
            },
        },
    )
    return seed_path


def _checkpoint_unresolved(checkpoint_dir: str) -> Optional[int]:
    paths = glob.glob(os.path.join(checkpoint_dir, "*.json"))
    targets = [
        _parse_campaign_checkpoint_target(path)
        for path in paths
        if not path.endswith(".cex.json")
    ]
    valid = [target for target in targets if target is not None]
    if not valid:
        return None
    return min(target.unresolved for target in valid)


def run_campaign(
    args: argparse.Namespace,
    targets: Optional[Sequence[TargetState]] = None,
) -> Dict[str, Any]:
    if targets is None:
        filters = tuple(
            part.strip()
            for part in args.target_filter.split(",")
            if part.strip()
        )
        targets = discover_best_targets(
            filters,
            args.max_targets,
            args.checkpoint_dir,
        )
    else:
        targets = list(targets)
    if not targets:
        raise RuntimeError("no valid hard benchmark checkpoints were discovered")
    hardware = resolve_worker_count(args.jobs)
    jobs = hardware["selected"]

    started = time.time()
    deadline = started + float(args.seconds)
    root = os.path.abspath(args.output_dir)
    os.makedirs(root, exist_ok=True)
    campaign_jsonl = os.path.join(root, "campaign.jsonl")
    summary_path = os.path.join(root, "summary.json")
    records: List[Dict[str, Any]] = []
    round_number = 0

    print("Selected best benchmark checkpoints:")
    print(
        "Worker sizing:",
        f"selected={jobs}",
        f"recommended={hardware['recommended']}",
        f"physical={hardware['physical_cores']}",
        f"logical={hardware['logical_cores']}",
    )
    for target in targets:
        print(
            f"  {target.key}: unresolved={target.seed_unresolved} "
            f"removed={target.seed_removed} tier={target.phase_tier} "
            f"checkpoint={target.seed_checkpoint}"
        )

    while time.time() < deadline:
        active = [target for target in targets if not target.complete and not target.failed]
        if not active:
            break
        round_number += 1
        for target in active:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            slice_seconds = min(float(args.slice_seconds), remaining)
            paths = _target_paths(root, target)
            os.makedirs(paths["checkpoint_dir"], exist_ok=True)
            visit = target.visits + 1
            report_path = os.path.join(
                paths["root"],
                f"visit_{visit:03d}_summary.json",
            )
            seed_checkpoint = target.seed_checkpoint if target.visits == 0 else ""
            if target.visits == 0 and target.phase_tier == "verified_output":
                seed_checkpoint = _materialize_verified_output_seed(
                    target,
                    paths["checkpoint_dir"],
                    args.cec_timeout,
                )
            config = coordinator.CoordinatorConfig(
                checkpoint_dir=paths["checkpoint_dir"],
                jobs=jobs,
                budgets=coordinator._parse_budgets(args.budgets),
                batch_size=max(1, args.batch_size),
                max_seconds=slice_seconds,
                max_generations=1_000_000,
                solver=args.solver,
                frontier_order=args.order,
                worker_engine="tfo",
                recheck_engine="tfo",
                recheck_budget=0,
                continue_until_deadline=True,
                budget_growth=args.budget_growth,
                max_generated_budget=max(0, args.max_generated_budget),
                checkpoint_json=seed_checkpoint,
                checkpoint_select="gates",
                cec_timeout=args.cec_timeout,
            )
            visit_started = time.time()
            try:
                result = coordinator.run_coordinator(
                    target.source_path,
                    paths["output"],
                    config,
                    report_path=report_path,
                    jsonl_path=paths["jsonl"],
                )
                target.visits = visit
                target.last_status = str(result["status"])
                target.last_abort_reason = abort_reason_for_result(result)
                target.next_action = next_action_for_result(result)
                target.last_gates = int(result["final_gates"])
                unresolved = _checkpoint_unresolved(paths["checkpoint_dir"])
                if unresolved is not None:
                    target.last_unresolved = unresolved
                target.complete = target.last_status == "COMPLETE"
                target.failed = target.last_status == "CEC_FAILED_ROLLBACK"
                record = {
                    "round": round_number,
                    "visit": visit,
                    "target": target.key,
                    "slice_seconds": slice_seconds,
                    "started_offset": visit_started - started,
                    "finished_offset": time.time() - started,
                    "status": target.last_status,
                    "next_action": target.next_action,
                    "unresolved": target.last_unresolved,
                    "final_gates": target.last_gates,
                    "removed": result["removed"],
                    "final_verify": result["final_verify"],
                    "totals": result["totals"],
                    "report": os.path.abspath(report_path),
                }
            except Exception as exc:
                target.failed = True
                target.last_status = "ERROR"
                target.last_abort_reason = "ERROR"
                target.next_action = "STOP_AND_AUDIT"
                record = {
                    "round": round_number,
                    "visit": visit,
                    "target": target.key,
                    "slice_seconds": slice_seconds,
                    "started_offset": visit_started - started,
                    "finished_offset": time.time() - started,
                    "status": "ERROR",
                    "next_action": target.next_action,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            records.append(record)
            _append_jsonl(campaign_jsonl, record)
            _write_json_atomic(
                summary_path,
                {
                    "started": started,
                    "deadline": deadline,
                    "elapsed": time.time() - started,
                    "seconds": args.seconds,
                    "hardware": hardware,
                    "slice_seconds": args.slice_seconds,
                    "round": round_number,
                    "targets": [asdict(item) for item in targets],
                    "records": records,
                    "status": "RUNNING",
                },
            )
            print(
                f"[{target.key}] visit={visit} status={record['status']} "
                f"unresolved={target.last_unresolved} elapsed={time.time() - started:.0f}s"
            )

    finished = time.time()
    if all(target.complete for target in targets):
        status = "ALL_TARGETS_COMPLETE"
    elif finished >= deadline:
        status = "TIME_BUDGET_COMPLETE"
    else:
        status = "NO_ACTIVE_TARGETS"
    summary = {
        "started": started,
        "deadline": deadline,
        "finished": finished,
        "elapsed": finished - started,
        "seconds": args.seconds,
        "hardware": hardware,
        "slice_seconds": args.slice_seconds,
        "rounds": round_number,
        "targets": [asdict(item) for item in targets],
        "records": records,
        "status": status,
        "campaign_jsonl": os.path.abspath(campaign_jsonl),
    }
    _write_json_atomic(summary_path, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Six-hour round-robin committing exact-TFO benchmark campaign."
    )
    parser.add_argument("--seconds", type=int, default=21600)
    parser.add_argument("--slice-seconds", type=int, default=600)
    parser.add_argument(
        "--jobs",
        type=int,
        default=0,
        help="worker processes; 0 selects a hardware-safe physical-core count",
    )
    parser.add_argument("--budgets", default="10000,50000,250000,1000000,5000000")
    parser.add_argument("--budget-growth", type=float, default=2.0)
    parser.add_argument("--max-generated-budget", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-targets", type=int, default=6)
    parser.add_argument("--target-filter", default=",".join(DEFAULT_FILTERS))
    parser.add_argument("--checkpoint-dir", action="append", default=[])
    parser.add_argument("--solver", default="cadical153")
    parser.add_argument("--order", default="proof_reverse_portfolio")
    parser.add_argument("--cec-timeout", type=float, default=180.0)
    parser.add_argument("--output-dir", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    run_campaign(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
