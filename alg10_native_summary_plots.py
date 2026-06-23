#!/usr/bin/env python3
"""Generate charts comparing Alg10 native exact-TFO campaign summaries."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _num(value: object) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _int(value: object) -> int:
    return int(round(_num(value)))


def _short(name: str) -> str:
    for prefix in (
        "epfl_arithmetic_",
        "epfl_random_control_",
        "epfl_",
        "custom_",
    ):
        if name.startswith(prefix):
            return name[len(prefix) :]
    return name


def _load_summary(path: str | Path) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _targets(summary: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    return {str(item.get("key")): item for item in summary.get("targets", []) if item.get("key")}


def _totals(item: Mapping[str, Any]) -> Mapping[str, Any]:
    return item.get("totals", {}) or {}


def _rows(baseline: Mapping[str, Any], latest: Mapping[str, Any]) -> List[Dict[str, Any]]:
    base_targets = _targets(baseline)
    latest_targets = _targets(latest)
    rows = []
    for key in sorted(set(base_targets) | set(latest_targets)):
        base = base_targets.get(key, latest_targets.get(key, {}))
        cur = latest_targets.get(key, base)
        totals = _totals(cur)
        base_gates = _int(base.get("current_gates"))
        final_gates = _int(cur.get("current_gates"))
        base_removed = _int(base.get("removed"))
        final_removed = _int(cur.get("removed"))
        base_unresolved = _int(base.get("unresolved"))
        final_unresolved = _int(cur.get("unresolved"))
        rows.append(
            {
                "Circuit": key,
                "Circuit_Short": _short(key),
                "Baseline_Gates": base_gates,
                "Latest_Gates": final_gates,
                "Gate_Delta": final_gates - base_gates,
                "Baseline_Removed": base_removed,
                "Latest_Removed": final_removed,
                "New_Removed": final_removed - base_removed,
                "Baseline_Unresolved": base_unresolved,
                "Latest_Unresolved": final_unresolved,
                "Unresolved_Delta": final_unresolved - base_unresolved,
                "Generation": _int(cur.get("generation")),
                "Dispatches": _int(cur.get("dispatches")),
                "Worker_SAT_Reject": _int(totals.get("worker_sat_reject")),
                "Worker_Timeout": _int(totals.get("worker_timeout")),
                "Worker_UNSAT_Proposed": _int(totals.get("worker_unsat_proposed")),
                "Coordinator_UNSAT_Accept": _int(totals.get("coordinator_unsat_accept")),
                "CEC_Pass_Commits": _int(totals.get("cec_pass_commits")),
                "CEC_Failed_Commits": _int(totals.get("cec_failed_commits")),
                "Stale_Results": _int(totals.get("stale_results")),
                "Worker_Errors": _int(totals.get("worker_errors")),
                "Persistent_Retry_Tasks": _int(totals.get("persistent_retry_tasks")),
                "Status": cur.get("status", ""),
                "Next_Action": cur.get("next_action", ""),
            }
        )
    return rows


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fields: List[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _barh(ax: plt.Axes, labels: List[str], values: List[float], title: str, xlabel: str, color: str) -> None:
    if not labels:
        ax.text(0.5, 0.5, "No data", ha="center", va="center")
        ax.set_title(title)
        return
    ypos = list(range(len(labels)))
    ax.barh(ypos, values, color=color)
    ax.set_yticks(ypos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_title(title, fontsize=11)
    ax.set_xlabel(xlabel)
    for y, value in zip(ypos, values):
        if value:
            ax.text(value, y, f" {value:.0f}", va="center", fontsize=8)


def _save_reductions(rows: List[Mapping[str, Any]], out_dir: Path) -> None:
    ordered = sorted(rows, key=lambda row: _num(row["New_Removed"]), reverse=True)
    fig, ax = plt.subplots(figsize=(10, 5))
    _barh(
        ax,
        [str(row["Circuit_Short"]) for row in ordered],
        [_num(row["New_Removed"]) for row in ordered],
        "New verified removals in latest native run",
        "Gates removed",
        "#4C78A8",
    )
    fig.tight_layout()
    fig.savefig(out_dir / "01_new_verified_removals.png", dpi=180)
    plt.close(fig)


def _save_total_removed_with_increment(rows: List[Mapping[str, Any]], out_dir: Path) -> None:
    ordered = sorted(rows, key=lambda row: _num(row["Latest_Removed"]), reverse=True)
    labels = [str(row["Circuit_Short"]) for row in ordered]
    base_removed = [_num(row["Baseline_Removed"]) for row in ordered]
    new_removed = [max(0.0, _num(row["New_Removed"])) for row in ordered]
    y = list(range(len(ordered)))
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.barh(y, base_removed, color="#BAB0AC", label="removed before latest continuation")
    ax.barh(y, new_removed, left=base_removed, color="#4C78A8", label="additional in latest 6h run")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Verified gates removed")
    ax.set_title("Total verified removals, with latest increment highlighted")
    ax.legend()
    for pos, row in enumerate(ordered):
        total = _num(row["Latest_Removed"])
        delta = _num(row["New_Removed"])
        if delta > 0:
            label = f" {total:.0f} (+{delta:.0f})"
        else:
            label = f" {total:.0f}"
        ax.text(total, pos, label, va="center", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "00_total_removed_with_latest_increment.png", dpi=180)
    plt.close(fig)


def _save_unresolved(rows: List[Mapping[str, Any]], out_dir: Path) -> None:
    labels = [str(row["Circuit_Short"]) for row in rows]
    y = list(range(len(rows)))
    base = [_num(row["Baseline_Unresolved"]) for row in rows]
    latest = [_num(row["Latest_Unresolved"]) for row in rows]
    height = 0.38
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.barh([pos - height / 2 for pos in y], base, height=height, label="7h seed", color="#BAB0AC")
    ax.barh([pos + height / 2 for pos in y], latest, height=height, label="after 6h continuation", color="#F58518")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlabel("Unresolved candidates (log scale)")
    ax.set_title("Remaining frontier before and after latest run")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "02_unresolved_before_after.png", dpi=180)
    plt.close(fig)


def _save_worker_outcomes(rows: List[Mapping[str, Any]], out_dir: Path) -> None:
    labels = [str(row["Circuit_Short"]) for row in rows]
    sat = [_num(row["Worker_SAT_Reject"]) for row in rows]
    timeout = [_num(row["Worker_Timeout"]) for row in rows]
    unsat = [_num(row["Worker_UNSAT_Proposed"]) for row in rows]
    y = list(range(len(rows)))
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.barh(y, sat, color="#54A24B", label="SAT rejects")
    ax.barh(y, timeout, left=sat, color="#E45756", label="Timeouts")
    ax.barh(y, unsat, left=[a + b for a, b in zip(sat, timeout)], color="#4C78A8", label="UNSAT proposals")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlabel("Worker outcomes (log scale)")
    ax.set_title("Classification workload in latest native run")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "03_worker_outcomes.png", dpi=180)
    plt.close(fig)


def _save_health(baseline: Mapping[str, Any], latest: Mapping[str, Any], rows: List[Mapping[str, Any]], out_dir: Path) -> None:
    del baseline
    pool = latest.get("pool_metrics", {}) or {}
    metrics = {
        "Tasks completed": _int(pool.get("tasks_completed")),
        "CEC pass commits": sum(_int(row["CEC_Pass_Commits"]) for row in rows),
        "CEC failures": sum(_int(row["CEC_Failed_Commits"]) for row in rows),
        "Stale results": sum(_int(row["Stale_Results"]) for row in rows),
        "Worker errors": sum(_int(row["Worker_Errors"]) for row in rows),
        "Deadline skips": _int(pool.get("deadline_admission_skips")),
    }
    fig, ax = plt.subplots(figsize=(11, 5))
    labels = list(metrics)
    values = list(metrics.values())
    ax.bar(labels, values, color=["#4C78A8", "#54A24B", "#E45756", "#E45756", "#E45756", "#F58518"])
    ax.set_yscale("symlog")
    ax.set_title("Campaign health metrics")
    ax.set_ylabel("Count (symlog)")
    ax.tick_params(axis="x", labelrotation=25)
    for idx, value in enumerate(values):
        ax.text(idx, value, f"{value}", ha="center", va="bottom", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "04_campaign_health.png", dpi=180)
    plt.close(fig)


def _write_notes(
    baseline_path: Path,
    latest_path: Path,
    baseline: Mapping[str, Any],
    latest: Mapping[str, Any],
    rows: List[Mapping[str, Any]],
    out_dir: Path,
) -> None:
    pool = latest.get("pool_metrics", {}) or {}
    total_new = sum(_int(row["New_Removed"]) for row in rows)
    total_cec = sum(_int(row["CEC_Pass_Commits"]) for row in rows)
    total_failed = sum(_int(row["CEC_Failed_Commits"]) for row in rows)
    total_errors = sum(_int(row["Worker_Errors"]) for row in rows)
    total_stale = sum(_int(row["Stale_Results"]) for row in rows)
    lines = [
        "# Native Exact-TFO Summary Comparison",
        "",
        f"Baseline summary: `{baseline_path}`",
        f"Latest summary: `{latest_path}`",
        "",
        "## Key Metrics",
        "",
        f"- Baseline status: {baseline.get('status', '')}",
        f"- Latest status: {latest.get('status', '')}",
        f"- Latest elapsed seconds: {_num(latest.get('elapsed')):.1f}",
        f"- Latest worker utilization: {_num(pool.get('worker_utilization')) * 100:.1f}%",
        f"- Latest tasks completed: {_int(pool.get('tasks_completed'))}/{_int(pool.get('tasks_submitted'))}",
        f"- New verified removals vs baseline: {total_new}",
        f"- CEC pass commits: {total_cec}",
        f"- CEC failures: {total_failed}",
        f"- Worker errors: {total_errors}",
        f"- Stale results: {total_stale}",
        "",
        "## Generated Files",
        "",
        "- `native_summary_comparison.csv`",
        "- `native_run_key_metrics.csv`",
        "- `00_total_removed_with_latest_increment.png`",
        "- `01_new_verified_removals.png`",
        "- `02_unresolved_before_after.png`",
        "- `03_worker_outcomes.png`",
        "- `04_campaign_health.png`",
    ]
    (out_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_native_summary_plots(
    baseline_summary: str | Path,
    latest_summary: str | Path,
    out_dir: str | Path,
) -> Path:
    baseline_path = Path(baseline_summary)
    latest_path = Path(latest_summary)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    baseline = _load_summary(baseline_path)
    latest = _load_summary(latest_path)
    rows = _rows(baseline, latest)
    fields = list(rows[0].keys()) if rows else ["Circuit"]
    _write_csv(out / "native_summary_comparison.csv", rows, fields)

    pool = latest.get("pool_metrics", {}) or {}
    key_metrics = [
        {
            "Baseline_Summary": str(baseline_path),
            "Latest_Summary": str(latest_path),
            "Baseline_Status": baseline.get("status", ""),
            "Latest_Status": latest.get("status", ""),
            "Latest_Elapsed_s": _num(latest.get("elapsed")),
            "Latest_Dispatches": _int(latest.get("dispatches")),
            "Tasks_Completed": _int(pool.get("tasks_completed")),
            "Tasks_Submitted": _int(pool.get("tasks_submitted")),
            "Worker_Utilization": _num(pool.get("worker_utilization")),
            "Max_Active_Workers": _int(pool.get("max_active_workers")),
            "Proposal_Barriers_Completed": _int(pool.get("proposal_barriers_completed")),
            "Deadline_Admission_Skips": _int(pool.get("deadline_admission_skips")),
            "New_Verified_Removals": sum(_int(row["New_Removed"]) for row in rows),
            "CEC_Pass_Commits": sum(_int(row["CEC_Pass_Commits"]) for row in rows),
            "CEC_Failed_Commits": sum(_int(row["CEC_Failed_Commits"]) for row in rows),
            "Worker_Errors": sum(_int(row["Worker_Errors"]) for row in rows),
            "Stale_Results": sum(_int(row["Stale_Results"]) for row in rows),
        }
    ]
    _write_csv(out / "native_run_key_metrics.csv", key_metrics, list(key_metrics[0].keys()))
    _save_total_removed_with_increment(rows, out)
    _save_reductions(rows, out)
    _save_unresolved(rows, out)
    _save_worker_outcomes(rows, out)
    _save_health(baseline, latest, rows, out)
    _write_notes(baseline_path, latest_path, baseline, latest, rows, out)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_summary")
    parser.add_argument("latest_summary")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    out = generate_native_summary_plots(
        args.baseline_summary,
        args.latest_summary,
        args.out_dir,
    )
    print(out)


if __name__ == "__main__":
    main()
