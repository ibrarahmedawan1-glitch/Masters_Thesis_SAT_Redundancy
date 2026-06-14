#!/usr/bin/env python3
"""Ranked read-only intra-circuit frontier campaign for Alg10.

The campaign starts from the best valid checkpoints, ordered by lowest true
unresolved count and then highest removed-gate count.  It shards SAT checks
inside one circuit at a time using ``alg10_frontier_shard_probe``.

This is intentionally not a committing optimizer.  Parallel workers classify
frontier candidates only; UNSAT results remain proposals and must be rechecked
sequentially before any future AAG rewrite/checkpoint update.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import alg10_frontier_shard_probe as probe


DEFAULT_CHECKPOINT_DIRS = [
    "results_optimized/alg10_checkpoints_frontier_shard_probe",
    "results_optimized/alg10_checkpoints_frontier_fixed_campaign",
    "results_optimized/alg10_checkpoints_preflight_sin_untried_first_high_budget",
    "results_optimized/alg10_checkpoints_best_protected_campaign",
    "results_optimized/alg10_checkpoints_best_unresolved_campaign",
    "results_optimized/alg10_checkpoints_global_strategy_div",
    "results_optimized/alg10_checkpoints_global_strategy_sqrt",
    "results_optimized/alg10_checkpoints_final_sat_strategy",
    "results_optimized/alg10_checkpoints_strict_audit",
    "results_optimized/alg10_checkpoints_resume_pool_presim",
]

DEFAULT_TARGET_FILTERS = ("sin", "sqrt", "hyp", "div", "log2", "mem_ctrl")


@dataclass(frozen=True)
class FrontierTarget:
    key: str
    json_path: str
    work_path: str
    source_path: str
    unresolved: int
    phase_count: int
    telemetry_unresolved: int
    removed: int
    source_gates: int
    current_gates: int
    phase_tier: str
    status: str
    timestamp: float


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_aag_and_count(path: str) -> int:
    try:
        with open(path, "r", encoding="ascii", errors="ignore") as f:
            first = f.readline().strip().split()
    except Exception:
        return 0
    if len(first) >= 6 and first[0] == "aag":
        try:
            return int(first[5])
        except Exception:
            return 0
    return 0


def abs_from_json(path: str, json_path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.abspath(os.path.join(os.getcwd(), path))


def checkpoint_work_path(data: Dict[str, Any], json_path: str) -> str:
    work_path = data.get("work_aag") or os.path.splitext(json_path)[0] + ".work.aag"
    return abs_from_json(str(work_path), json_path)


def phase_candidate_count(phase: Any) -> Optional[int]:
    if not isinstance(phase, dict):
        return None
    if phase.get("schema") == "alg10_global_frontier_v1" or "candidates" in phase:
        candidates = phase.get("candidates")
        return len(candidates) if isinstance(candidates, list) else None
    if phase.get("schema") == "alg10_tier_frontier_v1":
        pending = phase.get("pending")
        escalated = phase.get("escalated")
        if isinstance(pending, list) and isinstance(escalated, list):
            return len(pending) + len(escalated)
    return None


def normalized_key(data: Dict[str, Any], json_path: str) -> str:
    raw = data.get("source_path") or json_path
    base = os.path.splitext(os.path.basename(str(raw)))[0].lower()
    for prefix in ("custom_", "current_", "prepared_"):
        if base.startswith(prefix):
            base = base[len(prefix) :]
    base = base.replace("epfl_epfl_", "epfl_")
    base = re.sub(r"_[0-9a-f]{12}$", "", base)
    return base


def target_filter_match(target: FrontierTarget, filters: Sequence[str]) -> bool:
    if not filters:
        return True
    haystack = " ".join(
        [
            target.key,
            os.path.basename(target.json_path),
            os.path.basename(target.source_path),
            os.path.basename(target.work_path),
        ]
    ).lower()
    return any(part.lower() in haystack for part in filters)


def parse_checkpoint_target(json_path: str) -> Optional[FrontierTarget]:
    if json_path.endswith(".cex.json") or json_path.endswith(".tmp"):
        return None
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    work_path = checkpoint_work_path(data, json_path)
    if not os.path.exists(work_path):
        return None
    work_gates = parse_aag_and_count(work_path)
    if work_gates <= 0:
        return None
    phase = data.get("phase_resume")
    count = phase_candidate_count(phase)
    if count is None or count <= 0:
        return None
    if isinstance(phase, dict):
        expected_hash = phase.get("work_sha256")
        if expected_hash:
            try:
                if expected_hash != sha256_file(work_path):
                    return None
            except Exception:
                return None
        try:
            if int(phase.get("gate_count", -1)) != work_gates:
                return None
        except Exception:
            return None

    telemetry = data.get("telemetry") if isinstance(data.get("telemetry"), dict) else {}
    try:
        telemetry_unresolved = int(telemetry.get("unresolved", count))
    except Exception:
        telemetry_unresolved = count
    unresolved = max(int(count), telemetry_unresolved)

    try:
        current_gates = int(data.get("current_gates", 0) or 0)
    except Exception:
        current_gates = 0
    if current_gates and current_gates != work_gates:
        return None
    current_gates = work_gates
    source_path = str(data.get("source_path") or "")
    source_gates = parse_aag_and_count(source_path) if source_path and os.path.exists(source_path) else 0
    removed = max(0, source_gates - current_gates) if source_gates and current_gates else 0
    try:
        timestamp = float(data.get("timestamp", 0) or 0)
    except Exception:
        timestamp = 0.0

    return FrontierTarget(
        key=normalized_key(data, json_path),
        json_path=os.path.abspath(json_path),
        work_path=os.path.abspath(work_path),
        source_path=os.path.abspath(source_path) if source_path else "",
        unresolved=int(unresolved),
        phase_count=int(count),
        telemetry_unresolved=int(telemetry_unresolved),
        removed=int(removed),
        source_gates=int(source_gates),
        current_gates=int(current_gates),
        phase_tier=str(phase.get("tier", "")) if isinstance(phase, dict) else "",
        status=str(data.get("status", "")),
        timestamp=timestamp,
    )


def checkpoint_json_paths(dirs: Sequence[str]) -> List[str]:
    paths: List[str] = []
    seen = set()
    for directory in dirs:
        for json_path in glob.glob(os.path.join(directory, "*.json")):
            abs_path = os.path.abspath(json_path)
            if abs_path in seen:
                continue
            seen.add(abs_path)
            paths.append(abs_path)
    return sorted(paths)


def discover_checkpoint_dirs(extra: Sequence[str], include_parallel_safe: bool) -> List[str]:
    dirs = list(DEFAULT_CHECKPOINT_DIRS)
    if include_parallel_safe:
        dirs.extend(sorted(glob.glob("results_optimized/alg10_checkpoints_parallel_finishline_parallel_safe_*")))
    for item in extra:
        for part in item.split(","):
            part = part.strip()
            if part:
                dirs.append(part)
    result = []
    seen = set()
    for directory in dirs:
        if not os.path.isdir(directory):
            continue
        abs_dir = os.path.abspath(directory)
        if abs_dir in seen:
            continue
        seen.add(abs_dir)
        result.append(directory)
    return result


def rank_targets(
    targets: Iterable[FrontierTarget],
    filters: Sequence[str] = DEFAULT_TARGET_FILTERS,
    dedupe: bool = True,
) -> List[FrontierTarget]:
    filtered = [target for target in targets if target.unresolved > 0 and target_filter_match(target, filters)]
    filtered.sort(key=lambda t: (t.unresolved, -t.removed, t.current_gates, -t.timestamp, t.json_path))
    if not dedupe:
        return filtered
    best: Dict[str, FrontierTarget] = {}
    for target in filtered:
        if target.key not in best:
            best[target.key] = target
    return list(best.values())


def load_ranked_targets(
    dirs: Sequence[str],
    filters: Sequence[str],
    max_targets: int,
    dedupe: bool = True,
) -> List[FrontierTarget]:
    targets = []
    for json_path in checkpoint_json_paths(dirs):
        target = parse_checkpoint_target(json_path)
        if target is not None:
            targets.append(target)
    ranked = rank_targets(targets, filters=filters, dedupe=dedupe)
    if max_targets > 0:
        ranked = ranked[:max_targets]
    return ranked


def parse_budgets(raw: str) -> List[int]:
    budgets = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        value = int(part)
        if value > 0:
            budgets.append(value)
    if not budgets:
        raise ValueError("at least one positive budget is required")
    return budgets


def write_json_atomic(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def append_jsonl(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, sort_keys=True) + "\n")


def source_for_probe(target: FrontierTarget) -> str:
    if target.source_path and os.path.exists(target.source_path):
        return target.source_path
    return target.work_path


def select_unseen_items(
    items: Sequence[probe.WorkItem],
    seen: set,
    limit: int,
) -> List[probe.WorkItem]:
    selected = []
    for item in items:
        _, idx, stuck_value = item
        key = (int(idx), int(stuck_value))
        if key in seen:
            continue
        selected.append(item)
        if limit > 0 and len(selected) >= limit:
            break
    return selected


def run_campaign(args: argparse.Namespace) -> Dict[str, Any]:
    budgets = parse_budgets(args.budgets)
    dirs = discover_checkpoint_dirs(args.checkpoint_dir, args.include_parallel_safe)
    filters = tuple(part.strip() for part in args.target_filter.split(",") if part.strip())
    targets = load_ranked_targets(dirs, filters, args.max_targets, dedupe=not args.no_dedupe)
    started = time.time()
    deadline = started + float(args.seconds)
    tag = args.tag or time.strftime("ranked_frontier_%Y%m%d_%H%M%S")
    jsonl_path = args.jsonl or os.path.join("results_optimized", f"{tag}.jsonl")
    summary_path = args.summary or os.path.join("results_optimized", f"{tag}_summary.json")

    print(f"Discovered {len(targets)} ranked targets")
    for pos, target in enumerate(targets, start=1):
        print(
            f"{pos:2d}. {target.key:35s} unresolved={target.unresolved} "
            f"removed={target.removed} tier={target.phase_tier} json={target.json_path}"
        )

    summary: Dict[str, Any] = {
        "tag": tag,
        "started": started,
        "seconds": args.seconds,
        "jobs": args.jobs,
        "budgets": budgets,
        "batch_size": args.batch_size,
        "targets": [asdict(target) for target in targets],
        "records": [],
        "jsonl": os.path.abspath(jsonl_path),
    }
    if args.dry_run or not targets:
        write_json_atomic(summary_path, summary)
        print(f"Dry run summary: {summary_path}")
        return summary

    seen_by_target_budget: Dict[Tuple[str, int], set] = {}
    progress = True
    while time.time() < deadline and progress:
        progress = False
        for target in targets:
            if time.time() >= deadline:
                break
            config = probe.Alg10Config(
                checkpoint_dir=args.active_checkpoint_dir,
                extra_checkpoint_dirs=(),
                checkpoint_select="unresolved",
                frontier_order=args.order,
                solver=args.solver,
                phase_mode=args.phase_mode,
            )
            for budget in budgets:
                if time.time() >= deadline:
                    break
                frontier = probe.load_frontier(
                    source_for_probe(target),
                    config,
                    limit=0,
                    use_checkpoint=True,
                    skip_already_tried=args.skip_already_tried,
                    budget=budget,
                    checkpoint_json=target.json_path,
                )
                seen_key = (target.json_path, int(budget))
                seen = seen_by_target_budget.setdefault(seen_key, set())
                items = select_unseen_items(frontier["work_items"], seen, args.batch_size)
                if not items:
                    continue
                progress = True
                for _, idx, stuck_value in items:
                    seen.add((int(idx), int(stuck_value)))

                record_start = time.time()
                print(
                    f"[run] {target.key} budget={budget} batch={len(items)} "
                    f"jobs={args.jobs} elapsed={record_start - started:.0f}s"
                )
                result = probe.run_parallel(
                    frontier["work_path"],
                    items,
                    budget,
                    config,
                    args.jobs,
                    audit_assumptions=not args.no_audit,
                )
                counts = probe.status_counts(result["results"])
                record = {
                    "target": asdict(target),
                    "budget": int(budget),
                    "batch_size": len(items),
                    "seconds": result["seconds"],
                    "counts": counts,
                    "shards": result.get("shards", 0),
                    "frontier": {
                        key: value for key, value in frontier.items() if key != "work_items"
                    },
                    "started_offset": record_start - started,
                    "finished_offset": time.time() - started,
                    "results": result["results"] if args.keep_results else [],
                }
                append_jsonl(jsonl_path, record)
                summary["records"].append(
                    {
                        "target_key": target.key,
                        "budget": int(budget),
                        "batch_size": len(items),
                        "seconds": result["seconds"],
                        "counts": counts,
                    }
                )
                print(
                    f"[done] {target.key} budget={budget} {result['seconds']:.2f}s "
                    f"{counts}"
                )

    summary["finished"] = time.time()
    summary["elapsed"] = summary["finished"] - started
    write_json_atomic(summary_path, summary)
    print(f"Summary: {summary_path}")
    print(f"JSONL: {jsonl_path}")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a ranked, read-only Alg10 intra-circuit frontier campaign."
    )
    parser.add_argument("--seconds", type=int, default=21600)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--budgets", default="1000000,2000000,5000000")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-targets", type=int, default=6)
    parser.add_argument("--target-filter", default=",".join(DEFAULT_TARGET_FILTERS))
    parser.add_argument("--checkpoint-dir", action="append", default=[])
    parser.add_argument("--active-checkpoint-dir", default=probe.DEFAULT_CHECKPOINT_DIR)
    parser.add_argument("--include-parallel-safe", dest="include_parallel_safe", action="store_true", default=True)
    parser.add_argument("--no-include-parallel-safe", dest="include_parallel_safe", action="store_false")
    parser.add_argument("--no-dedupe", action="store_true")
    parser.add_argument("--skip-already-tried", dest="skip_already_tried", action="store_true", default=True)
    parser.add_argument("--no-skip-already-tried", dest="skip_already_tried", action="store_false")
    parser.add_argument("--solver", default="cadical153")
    parser.add_argument(
        "--phase-mode",
        default="none",
        choices=["none", "controls_false", "model", "controls_false_model"],
    )
    parser.add_argument("--order", default="untried_first")
    parser.add_argument("--tag", default="")
    parser.add_argument("--jsonl", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-results", action="store_true")
    parser.add_argument("--no-audit", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    run_campaign(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
