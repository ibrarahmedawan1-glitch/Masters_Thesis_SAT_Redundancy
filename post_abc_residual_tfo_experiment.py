#!/usr/bin/env python3
"""Measure exact TFO redundancy remaining after CEC-passed ABC flows."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import alg10_dynamic_tfo_pool_campaign as dynamic
import alg10_parallel_tfo_benchmark_campaign as benchmark
import optimizer_alg10_tiered as alg10


DEFAULT_BASELINE_ROOT = (
    "results_optimized/feedback_validation_20260615/"
    "abc_baselines_recovered/aag_outputs"
)


def _parse_csv(raw: str) -> List[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _target(flow: str, path: Path) -> benchmark.TargetState:
    gates = int(alg10.parse_aag(str(path))[4])
    return benchmark.TargetState(
        key=f"{flow}_{path.stem}",
        source_path=str(path.resolve()),
        seed_checkpoint="",
        seed_work_path=str(path.resolve()),
        seed_unresolved=2 * gates,
        seed_removed=0,
        phase_tier="fresh_post_abc",
        last_unresolved=2 * gates,
        last_gates=gates,
    )


def _campaign_args(args: argparse.Namespace, output_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(
        output_dir=str(output_dir),
        seconds=int(args.seconds_per_flow),
        jobs=int(args.jobs),
        budgets=args.budgets,
        budget_growth=float(args.budget_growth),
        max_generated_budget=int(args.max_generated_budget),
        microbatch_size=int(args.microbatch_size),
        retry_microbatch_size=int(args.retry_microbatch_size),
        deadline_reserve_seconds=float(args.deadline_reserve_seconds),
        unknown_task_guard_seconds=float(args.unknown_task_guard_seconds),
        checkpoint_interval=float(args.checkpoint_interval),
        max_targets=0,
        target_filter="",
        checkpoint_dir=[],
        solver=args.solver,
        order=args.order,
        cec_timeout=float(args.cec_timeout),
        persistent_retry_tiers=int(args.persistent_retry_tiers),
        worker_cache_entries=int(args.worker_cache_entries),
    )


def _result_rows(flow: str, summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for target in summary["targets"]:
        totals = target["totals"]
        classified = (
            int(totals["worker_sat_reject"])
            + int(totals["worker_timeout"])
            + int(totals["worker_unsat_proposed"])
        )
        rows.append(
            {
                "Flow": flow,
                "Circuit": target["key"].removeprefix(flow + "_"),
                "Starting_Gates": int(target["initial_gates"]),
                "Final_Gates": int(target["current_gates"]),
                "Residual_Gates_Removed": int(target["removed"]),
                "Candidate_Results": classified,
                "SAT_Reject": int(totals["worker_sat_reject"]),
                "UNSAT_Proposed": int(totals["worker_unsat_proposed"]),
                "Timeout": int(totals["worker_timeout"]),
                "Coordinator_UNSAT_Accept": int(
                    totals["coordinator_unsat_accept"]
                ),
                "CEC_Pass_Commits": int(totals["cec_pass_commits"]),
                "CEC_Failed_Commits": int(totals["cec_failed_commits"]),
                "Worker_Errors": int(totals["worker_errors"]),
                "Remaining_Obligations": int(target["unresolved"]),
                "Status": target["status"],
                "Output": target["output"],
            }
        )
    return rows


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run fresh exact-TFO campaigns on existing CEC-passed ABC outputs."
        )
    )
    parser.add_argument("--baseline-root", default=DEFAULT_BASELINE_ROOT)
    parser.add_argument("--flows", default="dc2,fraig")
    parser.add_argument("--circuits", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seconds-per-flow", type=int, default=180)
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--budgets", default="10000")
    parser.add_argument("--budget-growth", type=float, default=2.0)
    parser.add_argument("--max-generated-budget", type=int, default=10000)
    parser.add_argument("--microbatch-size", type=int, default=4)
    parser.add_argument("--retry-microbatch-size", type=int, default=1)
    parser.add_argument("--deadline-reserve-seconds", type=float, default=15.0)
    parser.add_argument("--unknown-task-guard-seconds", type=float, default=60.0)
    parser.add_argument("--checkpoint-interval", type=float, default=30.0)
    parser.add_argument("--solver", default="cadical153")
    parser.add_argument("--order", default="proof_reverse_portfolio")
    parser.add_argument("--cec-timeout", type=float, default=180.0)
    parser.add_argument("--persistent-retry-tiers", type=int, default=1)
    parser.add_argument("--worker-cache-entries", type=int, default=0)
    args = parser.parse_args()

    baseline_root = Path(args.baseline_root).resolve()
    output_root = Path(args.output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    circuit_filters = _parse_csv(args.circuits)
    all_rows: List[Dict[str, Any]] = []
    campaign_summaries: Dict[str, Any] = {}

    config = {
        "baseline_root": str(baseline_root),
        "flows": _parse_csv(args.flows),
        "circuits": circuit_filters,
        "seconds_per_flow": args.seconds_per_flow,
        "jobs": args.jobs,
        "budgets": args.budgets,
        "max_generated_budget": args.max_generated_budget,
        "microbatch_size": args.microbatch_size,
        "retry_microbatch_size": args.retry_microbatch_size,
        "deadline_reserve_seconds": args.deadline_reserve_seconds,
        "unknown_task_guard_seconds": args.unknown_task_guard_seconds,
        "solver": args.solver,
        "order": args.order,
        "persistent_retry_tiers": args.persistent_retry_tiers,
        "worker_cache_entries": args.worker_cache_entries,
    }
    with (output_root / "experiment_config.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(config, handle, indent=2, sort_keys=True)

    for flow in config["flows"]:
        flow_root = baseline_root / flow
        paths = sorted(flow_root.glob("*.aag"))
        if circuit_filters:
            paths = [
                path
                for path in paths
                if any(token in path.name for token in circuit_filters)
            ]
        if not paths:
            raise RuntimeError(f"no AAG outputs found for flow {flow}: {flow_root}")
        targets = [_target(flow, path) for path in paths]
        summary = dynamic.run_dynamic_campaign(
            _campaign_args(args, output_root / flow),
            targets=targets,
        )
        campaign_summaries[flow] = summary
        all_rows.extend(_result_rows(flow, summary))

    _write_csv(output_root / "post_abc_residual_detail.csv", all_rows)
    aggregate = []
    for flow in config["flows"]:
        rows = [row for row in all_rows if row["Flow"] == flow]
        aggregate.append(
            {
                "Flow": flow,
                "Circuits": len(rows),
                "Starting_Gates": sum(row["Starting_Gates"] for row in rows),
                "Final_Gates": sum(row["Final_Gates"] for row in rows),
                "Residual_Gates_Removed": sum(
                    row["Residual_Gates_Removed"] for row in rows
                ),
                "Candidate_Results": sum(
                    row["Candidate_Results"] for row in rows
                ),
                "SAT_Reject": sum(row["SAT_Reject"] for row in rows),
                "UNSAT_Proposed": sum(row["UNSAT_Proposed"] for row in rows),
                "Timeout": sum(row["Timeout"] for row in rows),
                "CEC_Pass_Commits": sum(
                    row["CEC_Pass_Commits"] for row in rows
                ),
                "Worker_Errors": sum(row["Worker_Errors"] for row in rows),
                "Remaining_Obligations": sum(
                    row["Remaining_Obligations"] for row in rows
                ),
                "Elapsed_s": float(campaign_summaries[flow]["elapsed"]),
            }
        )
    _write_csv(output_root / "post_abc_residual_summary.csv", aggregate)
    with (output_root / "campaign_summaries.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(campaign_summaries, handle, indent=2, sort_keys=True)

    print(json.dumps(aggregate, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
