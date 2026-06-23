#!/usr/bin/env python3
"""Launch the frozen seven-hour native exact-TFO benchmark campaign."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

import alg10_dynamic_tfo_pool_campaign as dynamic
import alg10_parallel_tfo_benchmark_campaign as benchmark
import alg10_ranked_frontier_campaign as ranked


NATIVE_CHECKPOINT_ROOT = Path(
    "results_optimized/native_tfo_7h_prelaunch_smoke_20260615"
)
RAW_ISCAS_DIR = Path("benchmarks")
RAW_EPFL_DIR = Path("benchmark_suites/epfl")

NATIVE_CHECKPOINTS = (
    "epfl_arithmetic_sin/checkpoints/custom_epfl_arithmetic_sin_b17da687e8a4.json",
    "epfl_arithmetic_sqrt/checkpoints/epfl_epfl_arithmetic_sqrt_02dcd1dab783.json",
    "epfl_arithmetic_hyp/checkpoints/custom_epfl_arithmetic_hyp_9c0d564fda30.json",
    "epfl_arithmetic_div/checkpoints/custom_epfl_arithmetic_div_242292af29fd.json",
    "epfl_arithmetic_log2/checkpoints/custom_epfl_arithmetic_log2_8bfd84a960b5.json",
    "epfl_random_control_mem_ctrl/checkpoints/epfl_epfl_random_control_mem_ctrl_8f4971c1dcf7.json",
)


def _raw_suite_key(prefix: str, path: Path) -> str:
    base = path.stem.lower()
    if prefix:
        base = f"{prefix}_{base}"
    key = "".join(ch if ch.isalnum() else "_" for ch in base)
    return "_".join(part for part in key.split("_") if part)


def _raw_iscas_epfl_sources():
    sources = []
    for path in sorted(RAW_ISCAS_DIR.glob("*.aag")):
        sources.append(("iscas", path))
    for path in sorted(RAW_EPFL_DIR.glob("*.aag")):
        sources.append(("", path))
    return sources


def _targets_from_raw_iscas_epfl_suite():
    targets = []
    seen = set()
    for prefix, path in _raw_iscas_epfl_sources():
        source_path = path.resolve()
        key = _raw_suite_key(prefix, path)
        if key in seen:
            raise RuntimeError(f"duplicate raw suite target key: {key}")
        seen.add(key)
        gates = ranked.parse_aag_and_count(str(source_path))
        if gates <= 0:
            raise RuntimeError(f"invalid raw suite AAG: {source_path}")
        targets.append(
            benchmark.TargetState(
                key=key,
                source_path=str(source_path),
                seed_checkpoint="",
                seed_work_path=str(source_path),
                seed_unresolved=2 * gates,
                seed_removed=0,
                phase_tier="raw_iscas_epfl",
                last_unresolved=2 * gates,
                last_gates=gates,
            )
        )
    if not targets:
        raise RuntimeError(
            f"no raw suite AAG targets found in {RAW_ISCAS_DIR} or {RAW_EPFL_DIR}"
        )
    return targets


def _load_native_targets():
    targets = []
    seen = set()
    for relative in NATIVE_CHECKPOINTS:
        path = (NATIVE_CHECKPOINT_ROOT / relative).resolve()
        lowered = str(path).lower()
        if "abc_baseline" in lowered or "post_abc" in lowered:
            raise RuntimeError(f"non-native checkpoint rejected: {path}")
        parsed = benchmark._parse_campaign_checkpoint_target(str(path))
        if parsed is None:
            raise RuntimeError(f"invalid native checkpoint: {path}")
        if parsed.key in seen:
            raise RuntimeError(f"duplicate native target key: {parsed.key}")
        seen.add(parsed.key)
        targets.append(
            benchmark.TargetState(
                key=parsed.key,
                source_path=parsed.source_path,
                seed_checkpoint=parsed.json_path,
                seed_work_path=parsed.work_path,
                seed_unresolved=parsed.unresolved,
                seed_removed=parsed.removed,
                phase_tier=parsed.phase_tier,
                last_unresolved=parsed.unresolved,
                last_gates=parsed.current_gates,
            )
        )
    return targets


def _checkpoint_target_from_dir(checkpoint_dir: str, key: str):
    candidates = []
    for path in sorted(Path(checkpoint_dir).glob("*.json")):
        if str(path).endswith(".cex.json"):
            continue
        parsed = benchmark._parse_campaign_checkpoint_target(str(path))
        if parsed is not None and parsed.key == key:
            candidates.append(parsed)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda target: (
            target.current_gates,
            target.unresolved,
            -target.timestamp,
            target.json_path,
        ),
    )


def _targets_from_summary(summary_path: str, skip_complete: bool = True):
    with open(summary_path, "r", encoding="utf-8") as handle:
        summary = json.load(handle)
    targets = []
    seen = set()
    for item in summary.get("targets", []):
        key = str(item.get("key") or "")
        if not key:
            continue
        if skip_complete and bool(item.get("complete")):
            continue
        checkpoint_dir = str(item.get("checkpoint_dir") or "")
        parsed = _checkpoint_target_from_dir(checkpoint_dir, key)
        if parsed is None:
            output = str(item.get("output") or "")
            source_path = str(item.get("source_path") or "")
            if not output or not source_path or not os.path.exists(output):
                raise RuntimeError(f"cannot build continuation seed for {key}")
            current_gates = int(item.get("current_gates", 0) or 0)
            removed = int(item.get("removed", 0) or 0)
            target = benchmark.TargetState(
                key=key,
                source_path=source_path,
                seed_checkpoint=os.path.abspath(summary_path),
                seed_work_path=output,
                seed_unresolved=2 * current_gates,
                seed_removed=removed,
                phase_tier="verified_output",
                last_unresolved=2 * current_gates,
                last_gates=current_gates,
            )
        else:
            target = benchmark.TargetState(
                key=parsed.key,
                source_path=parsed.source_path,
                seed_checkpoint=parsed.json_path,
                seed_work_path=parsed.work_path,
                seed_unresolved=parsed.unresolved,
                seed_removed=parsed.removed,
                phase_tier=parsed.phase_tier,
                last_unresolved=parsed.unresolved,
                last_gates=parsed.current_gates,
            )
        if target.key in seen:
            raise RuntimeError(f"duplicate continuation target key: {target.key}")
        seen.add(target.key)
        targets.append(target)
    if not targets:
        raise RuntimeError(f"no continuation targets found in {summary_path}")
    return targets


def _targets_from_checkpoint_jsons(json_paths):
    targets = []
    seen = set()
    for raw_path in json_paths:
        parsed = benchmark._parse_campaign_checkpoint_target(str(raw_path))
        if parsed is None:
            raise RuntimeError(f"invalid checkpoint JSON: {raw_path}")
        if parsed.key in seen:
            raise RuntimeError(f"duplicate checkpoint target key: {parsed.key}")
        seen.add(parsed.key)
        targets.append(
            benchmark.TargetState(
                key=parsed.key,
                source_path=parsed.source_path,
                seed_checkpoint=parsed.json_path,
                seed_work_path=parsed.work_path,
                seed_unresolved=parsed.unresolved,
                seed_removed=parsed.removed,
                phase_tier=parsed.phase_tier,
                last_unresolved=parsed.unresolved,
                last_gates=parsed.current_gates,
            )
        )
    if not targets:
        raise RuntimeError("no checkpoint JSON targets supplied")
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the pinned native exact-TFO campaign for seven hours."
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seconds", type=int, default=25200)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--worker-cache-entries", type=int, default=2)
    parser.add_argument("--persistent-retry-tiers", type=int, default=3)
    parser.add_argument(
        "--solver",
        default="cadical153",
        help="PySAT solver name to use for native exact-TFO worker and recheck SAT calls",
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="run only the named target key; can be passed more than once",
    )
    parser.add_argument(
        "--seed-summary",
        default="",
        help="resume from a finished dynamic campaign summary instead of pinned seeds",
    )
    parser.add_argument(
        "--checkpoint-json",
        action="append",
        default=[],
        help="run from an explicit Alg10/native checkpoint JSON; can be repeated",
    )
    parser.add_argument(
        "--raw-suite",
        choices=("", "iscas_epfl"),
        default="",
        help="run raw benchmark suite sources from zero removed gates",
    )
    parser.add_argument(
        "--include-complete",
        action="store_true",
        help="include circuits already marked complete in --seed-summary",
    )
    parser.add_argument(
        "--allow-worker-memory-overcommit",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="allow explicit worker count to exceed the conservative memory cap",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="use short deadline guards while preserving the native solver path",
    )
    args = parser.parse_args()

    if sum(bool(item) for item in (args.seed_summary, args.checkpoint_json, args.raw_suite)) > 1:
        raise RuntimeError(
            "--seed-summary, --checkpoint-json, and --raw-suite are mutually exclusive"
        )
    if args.raw_suite == "iscas_epfl":
        targets = _targets_from_raw_iscas_epfl_suite()
    elif args.checkpoint_json:
        targets = _targets_from_checkpoint_jsons(args.checkpoint_json)
    elif args.seed_summary:
        targets = _targets_from_summary(args.seed_summary, skip_complete=not args.include_complete)
    else:
        targets = _load_native_targets()
    if args.target:
        wanted = set(args.target)
        targets = [target for target in targets if target.key in wanted]
        missing = sorted(wanted - {target.key for target in targets})
        if missing:
            raise RuntimeError(f"target(s) not found: {', '.join(missing)}")
        if not targets:
            raise RuntimeError("no targets selected")
    deadline_reserve = 2.0 if args.smoke else 300.0
    unknown_task_guard = 10.0 if args.smoke else 900.0
    manifest = {
        "mode": "native_exact_tfo_only",
        "abc_preprocessing": False,
        "abc_role": "CEC verification only",
        "seconds": int(args.seconds),
        "workers": int(args.workers),
        "solver": args.solver,
        "order": "proof_reverse_portfolio",
        "budgets": [10000, 50000, 250000, 1000000, 5000000],
        "budget_growth": 2.0,
        "max_generated_budget": 40000000,
        "untried_microbatch": 16,
        "retry_microbatch": 1,
        "persistent_retry_tiers": int(args.persistent_retry_tiers),
        "worker_cache_entries": int(args.worker_cache_entries),
        "worker_memory_overcommit": bool(args.allow_worker_memory_overcommit),
        "deadline_reserve_seconds": deadline_reserve,
        "unknown_task_guard_seconds": unknown_task_guard,
        "smoke": bool(args.smoke),
        "seed_summary": os.path.abspath(args.seed_summary) if args.seed_summary else "",
        "checkpoint_jsons": [
            os.path.abspath(path) for path in args.checkpoint_json
        ],
        "raw_suite": args.raw_suite,
        "skip_complete_seed_targets": bool(args.seed_summary and not args.include_complete),
        "target_filter": sorted(args.target),
        "targets": [
            {
                "key": target.key,
                "source_path": os.path.abspath(target.source_path),
                "checkpoint_json": (
                    os.path.abspath(target.seed_checkpoint)
                    if target.seed_checkpoint
                    else ""
                ),
                "work_path": (
                    os.path.abspath(target.seed_work_path)
                    if target.seed_work_path
                    else ""
                ),
                "seed_removed": int(target.seed_removed),
                "gates": int(target.last_gates),
                "unresolved": int(target.last_unresolved),
                "frontier_origin": target.phase_tier,
            }
            for target in targets
        ],
    }
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "native_run_manifest.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    if args.dry_run:
        return 0

    if args.allow_worker_memory_overcommit:
        os.environ["ALG10_ALLOW_WORKER_MEMORY_OVERSUBSCRIBE"] = "1"
    else:
        os.environ.pop("ALG10_ALLOW_WORKER_MEMORY_OVERSUBSCRIBE", None)

    campaign_args = SimpleNamespace(
        output_dir=str(output_dir),
        seconds=int(args.seconds),
        jobs=int(args.workers),
        budgets="10000,50000,250000,1000000,5000000",
        budget_growth=2.0,
        max_generated_budget=40000000,
        microbatch_size=16,
        retry_microbatch_size=1,
        persistent_retry_tiers=int(args.persistent_retry_tiers),
        worker_cache_entries=int(args.worker_cache_entries),
        deadline_reserve_seconds=deadline_reserve,
        unknown_task_guard_seconds=unknown_task_guard,
        checkpoint_interval=60.0,
        max_targets=max(1, len(targets)),
        target_filter=",".join(args.target),
        checkpoint_dir=[],
        solver=args.solver,
        order="proof_reverse_portfolio",
        cec_timeout=180.0,
    )
    dynamic.run_dynamic_campaign(campaign_args, targets=targets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
