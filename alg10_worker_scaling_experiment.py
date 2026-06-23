#!/usr/bin/env python3
"""Read-only fixed-frontier worker and microbatch scaling experiment."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import alg10_frontier_shard_probe as probe
import alg10_parallel_commit_coordinator as coordinator


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_ints(raw):
    return [int(value) for value in raw.split(",") if value.strip()]


def chunks(values, size):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def load_frontier(checkpoint_json, solver, worker_cache_entries):
    with open(checkpoint_json, "r", encoding="utf-8") as source:
        checkpoint = json.load(source)
    work_path = checkpoint.get("work_aag")
    if not work_path or not os.path.exists(work_path):
        raise ValueError("checkpoint work AAG is missing")

    config = coordinator.CoordinatorConfig(
        checkpoint_dir=os.path.dirname(checkpoint_json),
        solver=solver,
        worker_engine="tfo",
        recheck_engine="tfo",
        frontier_order="current",
        worker_cache_entries=max(0, int(worker_cache_entries)),
    )
    alg_config = coordinator._alg10_config(config)
    opt = probe._load_alg10(alg_config)
    candidates, _history = coordinator._frontier_from_state(
        opt,
        work_path,
        checkpoint.get("phase_resume"),
        history_engine="tfo",
    )
    return os.path.abspath(work_path), candidates, alg_config


def run_once(work_path, candidates, alg_config, budget, jobs, batch_size):
    batches = list(chunks(candidates, batch_size))
    started = time.perf_counter()
    results = []
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        futures = []
        for task_pos, batch in enumerate(batches):
            items = [
                (ordinal, int(idx), int(stuck_value))
                for ordinal, (idx, stuck_value) in enumerate(batch)
            ]
            futures.append(
                pool.submit(
                    probe._solve_items,
                    work_path,
                    items,
                    budget,
                    alg_config,
                    True,
                    task_pos % jobs + 1,
                )
            )
        for future in as_completed(futures):
            results.extend(future.result())
    elapsed = time.perf_counter() - started
    counts = probe.status_counts(results)
    classified = counts.get(probe.STATUS_SAT_REJECT, 0) + counts.get(
        probe.STATUS_UNSAT_PROPOSED,
        0,
    )
    return {
        "Elapsed_s": elapsed,
        "Tasks": len(batches),
        "Candidates": len(candidates),
        "Classified": classified,
        "SAT": counts.get(probe.STATUS_SAT_REJECT, 0),
        "UNSAT": counts.get(probe.STATUS_UNSAT_PROPOSED, 0),
        "Timeout": counts.get(probe.STATUS_TIMEOUT, 0),
        "Candidates_per_s": len(candidates) / elapsed if elapsed else 0.0,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Measure fixed exact-TFO work with alternate workers/batches."
    )
    parser.add_argument("--checkpoint-json", required=True)
    parser.add_argument("--budget", type=int, default=10000)
    parser.add_argument("--candidates", type=int, default=256)
    parser.add_argument("--workers", default="4,6,8")
    parser.add_argument("--batch-sizes", default="4,16")
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--solver", default="cadical153")
    parser.add_argument("--worker-cache-entries", type=int, default=0)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    work_path, frontier, alg_config = load_frontier(
        os.path.abspath(args.checkpoint_json),
        args.solver,
        args.worker_cache_entries,
    )
    selected = list(frontier[: max(1, args.candidates)])
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    detail_path = output_dir / "worker_scaling_detail.csv"
    metadata_path = output_dir / "worker_scaling_metadata.json"

    rows = []
    expected_counts = None
    for batch_size in parse_ints(args.batch_sizes):
        for jobs in parse_ints(args.workers):
            for repetition in range(1, args.repetitions + 1):
                result = run_once(
                    work_path,
                    selected,
                    alg_config,
                    args.budget,
                    jobs,
                    batch_size,
                )
                counts = (
                    result["SAT"],
                    result["UNSAT"],
                    result["Timeout"],
                )
                if expected_counts is None:
                    expected_counts = counts
                elif counts != expected_counts:
                    raise AssertionError(
                        f"classification mismatch: {counts} != {expected_counts}"
                    )
                row = {
                    "Workers": jobs,
                    "Batch_Size": batch_size,
                    "Repetition": repetition,
                    **result,
                }
                rows.append(row)
                print(
                    f"workers={jobs} batch={batch_size} rep={repetition} "
                    f"elapsed={result['Elapsed_s']:.3f}s "
                    f"rate={result['Candidates_per_s']:.2f}/s"
                )

    with detail_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with metadata_path.open("w", encoding="utf-8") as output:
        json.dump(
            {
                "checkpoint_json": os.path.abspath(args.checkpoint_json),
                "work_path": work_path,
                "work_sha256": sha256_file(work_path),
                "budget": args.budget,
                "candidate_count": len(selected),
                "workers": parse_ints(args.workers),
                "batch_sizes": parse_ints(args.batch_sizes),
                "repetitions": args.repetitions,
                "solver": args.solver,
                "worker_cache_entries": args.worker_cache_entries,
            },
            output,
            indent=2,
            sort_keys=True,
        )
    print(f"detail={detail_path}")
    print(f"metadata={metadata_path}")


if __name__ == "__main__":
    main()
