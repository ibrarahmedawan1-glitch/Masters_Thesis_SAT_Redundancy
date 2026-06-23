#!/usr/bin/env python3
"""Compare dynamic pooling and round-robin visits from fixed checkpoints."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import os
from pathlib import Path
from types import SimpleNamespace

import alg10_dynamic_tfo_pool_campaign as dynamic
import alg10_parallel_tfo_benchmark_campaign as benchmark


def parse_ints(raw):
    return tuple(int(value) for value in raw.split(",") if value.strip())


def load_target(checkpoint_json):
    parsed = benchmark._parse_campaign_checkpoint_target(
        os.path.abspath(checkpoint_json)
    )
    if parsed is None:
        raise ValueError(f"invalid checkpoint: {checkpoint_json}")
    return benchmark.TargetState(
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


def dynamic_args(args, output_dir):
    return SimpleNamespace(
        output_dir=str(output_dir),
        seconds=args.seconds,
        jobs=args.jobs,
        budgets=args.budgets,
        budget_growth=args.budget_growth,
        max_generated_budget=args.max_generated_budget,
        microbatch_size=args.batch_size,
        retry_microbatch_size=1,
        deadline_reserve_seconds=0.0,
        unknown_task_guard_seconds=0.0,
        checkpoint_interval=30.0,
        max_targets=len(args.checkpoint_json),
        target_filter="",
        checkpoint_dir=[],
        solver=args.solver,
        order=args.order,
        cec_timeout=args.cec_timeout,
    )


def round_robin_args(args, output_dir):
    return SimpleNamespace(
        output_dir=str(output_dir),
        seconds=args.seconds,
        slice_seconds=args.slice_seconds,
        jobs=args.jobs,
        budgets=args.budgets,
        budget_growth=args.budget_growth,
        max_generated_budget=args.max_generated_budget,
        batch_size=args.batch_size,
        max_targets=len(args.checkpoint_json),
        target_filter="",
        checkpoint_dir=[],
        solver=args.solver,
        order=args.order,
        cec_timeout=args.cec_timeout,
    )


def dynamic_row(summary, seed_removed):
    totals = {
        "SAT": 0,
        "UNSAT": 0,
        "Timeout": 0,
        "Commits": 0,
        "Removed": 0,
        "Worker_Errors": 0,
    }
    for target in summary["targets"]:
        item = target["totals"]
        totals["SAT"] += int(item["worker_sat_reject"])
        totals["UNSAT"] += int(item["worker_unsat_proposed"])
        totals["Timeout"] += int(item["worker_timeout"])
        totals["Commits"] += int(item["cec_pass_commits"])
        totals["Removed"] += max(
            0,
            int(target["removed"]) - int(seed_removed[target["key"]]),
        )
        totals["Worker_Errors"] += int(item["worker_errors"])
    candidate_results = totals["SAT"] + totals["UNSAT"] + totals["Timeout"]
    return {
        "Policy": "dynamic",
        "Elapsed_s": float(summary["elapsed"]),
        "Dispatches": int(summary["dispatches"]),
        "Utilization": float(
            summary.get("pool_metrics", {}).get("worker_utilization", 0.0)
        ),
        "Candidate_Results": candidate_results,
        "Results_per_s": candidate_results / float(summary["elapsed"]),
        **totals,
    }


def round_robin_row(summary, seed_gates):
    totals = {
        "SAT": 0,
        "UNSAT": 0,
        "Timeout": 0,
        "Commits": 0,
        "Removed": 0,
        "Worker_Errors": 0,
    }
    for record in summary["records"]:
        item = record.get("totals") or {}
        totals["SAT"] += int(item.get("worker_sat_reject", 0))
        totals["UNSAT"] += int(item.get("worker_unsat_proposed", 0))
        totals["Timeout"] += int(item.get("worker_timeout", 0))
        totals["Commits"] += int(item.get("cec_pass_commits", 0))
        totals["Worker_Errors"] += int(record.get("status") == "ERROR")
    totals["Removed"] = sum(
        max(0, int(seed_gates[target["key"]]) - int(target["last_gates"]))
        for target in summary["targets"]
    )
    candidate_results = totals["SAT"] + totals["UNSAT"] + totals["Timeout"]
    return {
        "Policy": "round_robin",
        "Elapsed_s": float(summary["elapsed"]),
        "Dispatches": len(summary["records"]),
        "Utilization": 0.0,
        "Candidate_Results": candidate_results,
        "Results_per_s": candidate_results / float(summary["elapsed"]),
        **totals,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Run both schedulers from identical explicit checkpoints."
    )
    parser.add_argument("--checkpoint-json", action="append", required=True)
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--slice-seconds", type=int, default=20)
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--budgets", default="10000")
    parser.add_argument("--budget-growth", type=float, default=2.0)
    parser.add_argument("--max-generated-budget", type=int, default=10000)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--solver", default="cadical153")
    parser.add_argument("--order", default="proof_reverse_portfolio")
    parser.add_argument("--cec-timeout", type=float, default=180.0)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    targets = [load_target(path) for path in args.checkpoint_json]
    seed_removed = {target.key: target.seed_removed for target in targets}
    seed_gates = {target.key: target.last_gates for target in targets}
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    dynamic_summary = dynamic.run_dynamic_campaign(
        dynamic_args(args, output_dir / "dynamic"),
        targets=copy.deepcopy(targets),
    )
    round_robin_summary = benchmark.run_campaign(
        round_robin_args(args, output_dir / "round_robin"),
        targets=copy.deepcopy(targets),
    )
    rows = [
        dynamic_row(dynamic_summary, seed_removed),
        round_robin_row(round_robin_summary, seed_gates),
    ]
    comparison = output_dir / "scheduler_policy_comparison.csv"
    with comparison.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (output_dir / "experiment_config.json").open(
        "w",
        encoding="utf-8",
    ) as output:
        json.dump(vars(args), output, indent=2, sort_keys=True)
    print(f"comparison={comparison}")


if __name__ == "__main__":
    main()
