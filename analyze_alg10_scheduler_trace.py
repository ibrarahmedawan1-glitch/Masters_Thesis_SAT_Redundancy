#!/usr/bin/env python3
"""Replay recorded dynamic-pool timings under alternative scheduling policies."""

from __future__ import annotations

import argparse
import csv
import glob
import heapq
import json
import os
from pathlib import Path


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = min(len(ordered) - 1, int((len(ordered) - 1) * fraction))
    return float(ordered[position])


def load_tasks(campaign_dir):
    tasks = {}
    pattern = os.path.join(campaign_dir, "*", "pool_events.jsonl")
    for path in sorted(glob.glob(pattern)):
        key = os.path.basename(os.path.dirname(path))
        circuit_tasks = []
        with open(path, "r", encoding="utf-8") as source:
            for line in source:
                event = json.loads(line)
                if event.get("event") != "WORKER_RESULT":
                    continue
                results = event.get("results") or []
                candidate_seconds = [
                    max(0.0, float(item.get("seconds", 0.0) or 0.0))
                    for item in results
                ]
                if not candidate_seconds:
                    continue
                elapsed = max(
                    sum(candidate_seconds),
                    float(event.get("seconds", 0.0) or 0.0),
                )
                overhead = max(0.0, elapsed - sum(candidate_seconds))
                circuit_tasks.append(
                    {
                        "candidate_seconds": candidate_seconds,
                        "overhead": overhead,
                    }
                )
        if circuit_tasks:
            tasks[key] = circuit_tasks
    return tasks


def rebatch(circuit_tasks, batch_size):
    durations = []
    for task in circuit_tasks:
        values = task["candidate_seconds"]
        overhead = task["overhead"]
        for start in range(0, len(values), batch_size):
            durations.append(overhead + sum(values[start : start + batch_size]))
    return durations


def list_schedule(durations, workers):
    slots = [0.0 for _ in range(workers)]
    heapq.heapify(slots)
    for duration in durations:
        available = heapq.heappop(slots)
        heapq.heappush(slots, available + duration)
    return max(slots, default=0.0)


def dynamic_makespan(tasks_by_circuit, workers):
    merged = []
    positions = {key: 0 for key in tasks_by_circuit}
    while True:
        added = False
        for key in sorted(tasks_by_circuit):
            position = positions[key]
            if position >= len(tasks_by_circuit[key]):
                continue
            merged.append(tasks_by_circuit[key][position])
            positions[key] = position + 1
            added = True
        if not added:
            break
    return list_schedule(merged, workers)


def round_robin_makespan(tasks_by_circuit, workers):
    return sum(
        list_schedule(tasks_by_circuit[key], workers)
        for key in sorted(tasks_by_circuit)
    )


def analyze(campaign_dir, batch_sizes, worker_counts):
    recorded = load_tasks(campaign_dir)
    rows = []
    for batch_size in batch_sizes:
        rebatched = {
            key: rebatch(tasks, batch_size)
            for key, tasks in recorded.items()
        }
        for workers in worker_counts:
            dynamic = dynamic_makespan(rebatched, workers)
            round_robin = round_robin_makespan(rebatched, workers)
            rows.append(
                {
                    "Batch_Size": batch_size,
                    "Workers": workers,
                    "Tasks": sum(len(values) for values in rebatched.values()),
                    "Candidate_Work_s": round(
                        sum(
                            sum(task["candidate_seconds"])
                            for tasks in recorded.values()
                            for task in tasks
                        ),
                        6,
                    ),
                    "Estimated_Dynamic_s": round(dynamic, 6),
                    "Estimated_Round_Robin_s": round(round_robin, 6),
                    "Dynamic_Speedup": round(round_robin / dynamic, 4)
                    if dynamic
                    else 0.0,
                }
            )

    circuit_rows = []
    for key, tasks in sorted(recorded.items()):
        task_seconds = [
            task["overhead"] + sum(task["candidate_seconds"])
            for task in tasks
        ]
        candidate_seconds = [
            value for task in tasks for value in task["candidate_seconds"]
        ]
        prior_wait = [
            sum(task["candidate_seconds"][:position])
            for task in tasks
            for position in range(len(task["candidate_seconds"]))
        ]
        circuit_rows.append(
            {
                "Circuit": key,
                "Recorded_Tasks": len(tasks),
                "Candidates": len(candidate_seconds),
                "Task_P50_s": round(percentile(task_seconds, 0.50), 6),
                "Task_P95_s": round(percentile(task_seconds, 0.95), 6),
                "Task_Max_s": round(max(task_seconds), 6),
                "Candidate_P95_s": round(percentile(candidate_seconds, 0.95), 6),
                "Candidate_Max_s": round(max(candidate_seconds), 6),
                "Mean_Prior_In_Batch_Wait_s": round(
                    sum(prior_wait) / len(prior_wait),
                    6,
                ),
            }
        )
    return rows, circuit_rows


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_ints(raw):
    return [int(value) for value in raw.split(",") if value.strip()]


def main():
    parser = argparse.ArgumentParser(
        description="Replay Alg10 worker-result traces under alternate batching."
    )
    parser.add_argument("campaign_dir")
    parser.add_argument("--batch-sizes", default="1,4,16")
    parser.add_argument("--workers", default="4,6,8")
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()

    batch_sizes = parse_ints(args.batch_sizes)
    worker_counts = parse_ints(args.workers)
    rows, circuit_rows = analyze(
        os.path.abspath(args.campaign_dir),
        batch_sizes,
        worker_counts,
    )
    output_dir = Path(args.output_dir or args.campaign_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    schedule_path = output_dir / "scheduler_trace_replay.csv"
    circuit_path = output_dir / "scheduler_trace_circuits.csv"
    write_csv(schedule_path, rows)
    write_csv(circuit_path, circuit_rows)

    print("Scheduler trace replay")
    for row in rows:
        print(
            f"  batch={row['Batch_Size']:>2} workers={row['Workers']} "
            f"dynamic={row['Estimated_Dynamic_s']:.1f}s "
            f"round_robin={row['Estimated_Round_Robin_s']:.1f}s "
            f"speedup={row['Dynamic_Speedup']:.2f}x"
        )
    print(f"  schedule={schedule_path}")
    print(f"  circuits={circuit_path}")


if __name__ == "__main__":
    main()
