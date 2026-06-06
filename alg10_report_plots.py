#!/usr/bin/env python3
"""Generate compact visual reports for Algorithm 10 CSV outputs."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _num(value: object) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(str(value).replace("%", "").strip())
    except Exception:
        return 0.0


def _int(value: object) -> int:
    return int(round(_num(value)))


def _short_circuit(name: str) -> str:
    stem = Path(str(name)).stem
    for prefix in (
        "planted_live_",
        "epfl_epfl_arithmetic_",
        "epfl_arithmetic_",
        "epfl_epfl_random_control_",
        "epfl_random_control_",
        "iscas_",
        "custom_",
        "external_",
    ):
        if stem.startswith(prefix):
            return stem[len(prefix) :]
    return stem


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _valid_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if row.get("Verify") not in {"SKIPPED", "ERROR", "SKIPPED_GATE_LIMIT"}
    ]


def _records(rows: Iterable[dict[str, str]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for row in rows:
        name = row.get("Circuit", "")
        rec = {
            "Circuit": name,
            "Circuit_Short": _short_circuit(name),
            "Type": row.get("Type", ""),
            "Verify": row.get("Verify", ""),
            "Removed": _int(row.get("Gates_Removed")),
            "New_Removed": _int(row.get("New_Removed_This_Run")),
            "Area_Saved_AND2": _int(row.get("Area_Saved_AND2")),
            "Unresolved": _int(row.get("SAT_Unresolved")),
            "Fault_Coverage": _num(row.get("Fault_Coverage_Lower_Bound%")),
            "SAT_Checks": _int(row.get("SAT_Checks")),
            "SAT_Rejects": _int(row.get("SAT_Query_SAT")),
            "UNSAT_Accepts": _int(row.get("SAT_Query_UNSAT")),
            "SAT_Timeouts": _int(row.get("SAT_Timeouts")),
            "T_Total": _num(row.get("T_Total(s)")),
            "T_SAT": _num(row.get("T_SAT(s)")),
            "TFI_UNSAT": _int(row.get("TFI_Query_UNSAT")),
            "Window_UNSAT": _int(row.get("Window_Query_UNSAT")),
            "Cone_UNSAT": _int(row.get("Cone_Query_UNSAT")),
            "Global_UNSAT": _int(row.get("Global_Query_UNSAT")),
            "TFI_Timeouts": _int(row.get("TFI_Timeouts")),
            "Window_Timeouts": _int(row.get("Window_Timeouts")),
            "Cone_Timeouts": _int(row.get("Cone_Timeouts")),
            "Global_Timeouts": _int(row.get("Global_Timeouts")),
            "PreSAT_Pruned": _int(row.get("PreSAT_Sim_Pruned")),
            "CEX_Pool_Pruned": _int(row.get("CEX_Pool_Replay_Pruned")),
            "CEX_Pruned": _int(row.get("CEX_Pruned")),
            "CEX_TFI_Pruned": _int(row.get("CEX_TFI_Pruned")),
            "Resume": _int(row.get("Checkpoint_Resume")),
            "Checkpoint_Start_Removed": _int(row.get("Checkpoint_Start_Removed_AND2")),
            "Checkpoint_Start_Unresolved": _int(row.get("Checkpoint_Start_Unresolved")),
            "Checkpoint_Unresolved_Delta": _int(row.get("Checkpoint_Unresolved_Delta")),
            "Abort": row.get("SAT_Abort_Reason", ""),
        }
        out.append(rec)
    return out


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)


def _write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _top(records: list[dict[str, object]], field: str, limit: int = 15) -> list[dict[str, object]]:
    return sorted(records, key=lambda row: _num(row.get(field)), reverse=True)[:limit]


def _barh(
    ax: plt.Axes,
    labels: list[str],
    values: list[float],
    title: str,
    xlabel: str,
    color: str,
) -> None:
    if not labels:
        ax.text(0.5, 0.5, "No data", ha="center", va="center")
        ax.set_title(title)
        return
    ypos = list(range(len(labels)))
    ax.barh(ypos, values, color=color)
    ax.set_yticks(ypos)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_title(title, fontsize=11)
    ax.set_xlabel(xlabel)
    for y, value in zip(ypos, values):
        if value:
            ax.text(value, y, f" {value:.0f}", va="center", fontsize=8)


def _save_dashboard(records: list[dict[str, object]], out_dir: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    removed = _top(records, "Removed", 12)
    unresolved = _top(records, "Unresolved", 12)
    tier_unsat = [
        ("TFI", sum(_int(row["TFI_UNSAT"]) for row in records)),
        ("Window", sum(_int(row["Window_UNSAT"]) for row in records)),
        ("Cone", sum(_int(row["Cone_UNSAT"]) for row in records)),
        ("Global", sum(_int(row["Global_UNSAT"]) for row in records)),
    ]
    tier_timeouts = [
        ("TFI", sum(_int(row["TFI_Timeouts"]) for row in records)),
        ("Window", sum(_int(row["Window_Timeouts"]) for row in records)),
        ("Cone", sum(_int(row["Cone_Timeouts"]) for row in records)),
        ("Global", sum(_int(row["Global_Timeouts"]) for row in records)),
    ]

    _barh(
        axes[0][0],
        [str(row["Circuit_Short"]) for row in removed],
        [_num(row["Removed"]) for row in removed],
        "Top verified reductions",
        "Gates removed",
        "#4C78A8",
    )
    _barh(
        axes[0][1],
        [str(row["Circuit_Short"]) for row in unresolved],
        [_num(row["Unresolved"]) for row in unresolved],
        "Largest unresolved frontiers",
        "SAT_Unresolved",
        "#F58518",
    )
    _barh(
        axes[1][0],
        [name for name, _ in tier_unsat],
        [value for _, value in tier_unsat],
        "UNSAT accepts by tier",
        "Proof events",
        "#54A24B",
    )
    _barh(
        axes[1][1],
        [name for name, _ in tier_timeouts],
        [value for _, value in tier_timeouts],
        "Timeouts by tier",
        "Timeout events",
        "#E45756",
    )
    fig.tight_layout()
    fig.savefig(out_dir / "01_alg10_dashboard.png", dpi=180)
    plt.close(fig)


def _save_circuit_views(records: list[dict[str, object]], out_dir: Path) -> None:
    top_removed = _top(records, "Removed", 20)
    top_unresolved = _top(records, "Unresolved", 20)

    fig, axes = plt.subplots(1, 2, figsize=(15, 7))
    _barh(
        axes[0],
        [str(row["Circuit_Short"]) for row in top_removed],
        [_num(row["Removed"]) for row in top_removed],
        "Redundancies found",
        "Gates removed",
        "#4C78A8",
    )
    _barh(
        axes[1],
        [str(row["Circuit_Short"]) for row in top_unresolved],
        [_num(row["Unresolved"]) for row in top_unresolved],
        "Remaining SAT frontier",
        "SAT_Unresolved",
        "#F58518",
    )
    fig.tight_layout()
    fig.savefig(out_dir / "02_circuit_reduction_and_unresolved.png", dpi=180)
    plt.close(fig)


def _save_coverage_time(records: list[dict[str, object]], out_dir: Path) -> None:
    coverage_rows = sorted(records, key=lambda row: _num(row["Fault_Coverage"]))[:20]
    time_rows = _top(records, "T_Total", 20)
    fig, axes = plt.subplots(1, 2, figsize=(15, 7))
    _barh(
        axes[0],
        [str(row["Circuit_Short"]) for row in coverage_rows],
        [_num(row["Fault_Coverage"]) for row in coverage_rows],
        "Lowest fault coverage lower bound",
        "Coverage %",
        "#72B7B2",
    )
    _barh(
        axes[1],
        [str(row["Circuit_Short"]) for row in time_rows],
        [_num(row["T_Total"]) for row in time_rows],
        "Slowest circuits",
        "Total seconds",
        "#B279A2",
    )
    fig.tight_layout()
    fig.savefig(out_dir / "03_coverage_and_runtime.png", dpi=180)
    plt.close(fig)


def _save_pruning(records: list[dict[str, object]], out_dir: Path) -> None:
    labels = ["Pre-SAT sim", "CEX pool replay", "SAT CEX replay", "TFI CEX skip"]
    values = [
        sum(_int(row["PreSAT_Pruned"]) for row in records),
        sum(_int(row["CEX_Pool_Pruned"]) for row in records),
        sum(_int(row["CEX_Pruned"]) for row in records),
        sum(_int(row["CEX_TFI_Pruned"]) for row in records),
    ]
    fig, ax = plt.subplots(figsize=(10, 5))
    _barh(ax, labels, values, "Rejection-only pruning workload reduction", "Candidates/events", "#59A14F")
    fig.tight_layout()
    fig.savefig(out_dir / "04_rejection_only_pruning.png", dpi=180)
    plt.close(fig)


def _save_resume(records: list[dict[str, object]], out_dir: Path) -> bool:
    if not any(_int(row["Resume"]) for row in records):
        return False
    new_rows = _top(records, "New_Removed", 15)
    delta_rows = sorted(records, key=lambda row: abs(_num(row["Checkpoint_Unresolved_Delta"])), reverse=True)[:15]
    fig, axes = plt.subplots(1, 2, figsize=(15, 7))
    _barh(
        axes[0],
        [str(row["Circuit_Short"]) for row in new_rows],
        [_num(row["New_Removed"]) for row in new_rows],
        "New removals after checkpoint resume",
        "New gates removed",
        "#4C78A8",
    )
    _barh(
        axes[1],
        [str(row["Circuit_Short"]) for row in delta_rows],
        [_num(row["Checkpoint_Unresolved_Delta"]) for row in delta_rows],
        "Unresolved delta from loaded checkpoint",
        "Start unresolved - current unresolved",
        "#F28E2B",
    )
    fig.tight_layout()
    fig.savefig(out_dir / "05_checkpoint_resume_progress.png", dpi=180)
    plt.close(fig)
    return True


def _write_notes(source_csv: Path, out_dir: Path, records: list[dict[str, object]], generated: list[str]) -> None:
    pass_count = sum(1 for row in records if row.get("Verify") == "PASS")
    total_removed = sum(_int(row["Removed"]) for row in records)
    total_new = sum(_int(row["New_Removed"]) for row in records)
    total_unresolved = sum(_int(row["Unresolved"]) for row in records)
    total_timeouts = sum(_int(row["SAT_Timeouts"]) for row in records)
    total_checks = sum(_int(row["SAT_Checks"]) for row in records)
    total_unsat = sum(_int(row["UNSAT_Accepts"]) for row in records)
    total_sat = sum(_int(row["SAT_Rejects"]) for row in records)

    lines = [
        "# Algorithm 10 Report Charts",
        "",
        f"Source CSV: `{source_csv}`",
        "",
        "## Key Metrics",
        "",
        f"- CEC PASS rows: {pass_count}/{len(records)}",
        f"- Total gates removed: {total_removed}",
        f"- New gates removed from checkpoints: {total_new}",
        f"- SAT unresolved remaining: {total_unresolved}",
        f"- SAT checks: {total_checks}",
        f"- SAT rejects: {total_sat}",
        f"- UNSAT accepts: {total_unsat}",
        f"- SAT timeouts: {total_timeouts}",
        "",
        "## Generated Files",
        "",
    ]
    lines.extend(f"- `{name}`" for name in generated)
    lines.extend(
        [
            "",
            "## Reading The Charts",
            "",
            "- `UNSAT accepts` are proof events that can commit replacements.",
            "- CEX, pre-sim, and CEX-pool numbers are rejection-only workload reductions.",
            "- `SAT_Unresolved` is a remaining frontier under the configured time and budget policy.",
            "- Resume charts use checkpoint columns; positive unresolved delta means the resumed run reduced the frontier.",
        ]
    )
    (out_dir / "README.md").write_text("\n".join(lines) + "\n")


def generate_alg10_report_plots(csv_path: str | Path, out_dir: str | Path | None = None) -> Path:
    source_csv = Path(csv_path)
    rows = _valid_rows(_read_csv(source_csv))
    records = _records(rows)
    if not records:
        raise ValueError(f"No plottable rows found in {source_csv}")

    target_dir = Path(out_dir) if out_dir else source_csv.with_suffix("").parent / f"{source_csv.stem}_charts"
    target_dir.mkdir(parents=True, exist_ok=True)

    circuit_fields = [
        "Circuit",
        "Circuit_Short",
        "Type",
        "Verify",
        "Removed",
        "New_Removed",
        "Unresolved",
        "Fault_Coverage",
        "SAT_Checks",
        "SAT_Rejects",
        "UNSAT_Accepts",
        "SAT_Timeouts",
        "T_Total",
        "TFI_UNSAT",
        "Window_UNSAT",
        "Cone_UNSAT",
        "Global_UNSAT",
        "TFI_Timeouts",
        "Window_Timeouts",
        "Cone_Timeouts",
        "Global_Timeouts",
        "PreSAT_Pruned",
        "CEX_Pool_Pruned",
        "CEX_Pruned",
        "Abort",
    ]
    _write_csv(target_dir / "summary_by_circuit.csv", records, circuit_fields)
    _write_csv(target_dir / "top_unresolved.csv", _top(records, "Unresolved", 25), circuit_fields)

    totals = [
        {
            "Circuits": len(records),
            "CEC_PASS": sum(1 for row in records if row.get("Verify") == "PASS"),
            "Removed": sum(_int(row["Removed"]) for row in records),
            "New_Removed": sum(_int(row["New_Removed"]) for row in records),
            "Unresolved": sum(_int(row["Unresolved"]) for row in records),
            "SAT_Checks": sum(_int(row["SAT_Checks"]) for row in records),
            "SAT_Rejects": sum(_int(row["SAT_Rejects"]) for row in records),
            "UNSAT_Accepts": sum(_int(row["UNSAT_Accepts"]) for row in records),
            "SAT_Timeouts": sum(_int(row["SAT_Timeouts"]) for row in records),
            "T_Total": sum(_num(row["T_Total"]) for row in records),
        }
    ]
    _write_csv(
        target_dir / "summary_key_metrics.csv",
        totals,
        list(totals[0].keys()),
    )

    generated = [
        "summary_key_metrics.csv",
        "summary_by_circuit.csv",
        "top_unresolved.csv",
        "01_alg10_dashboard.png",
        "02_circuit_reduction_and_unresolved.png",
        "03_coverage_and_runtime.png",
        "04_rejection_only_pruning.png",
    ]
    _save_dashboard(records, target_dir)
    _save_circuit_views(records, target_dir)
    _save_coverage_time(records, target_dir)
    _save_pruning(records, target_dir)
    if _save_resume(records, target_dir):
        generated.append("05_checkpoint_resume_progress.png")
    _write_notes(source_csv, target_dir, records, generated)
    return target_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Algorithm 10 charts from a thesis CSV.")
    parser.add_argument("csv", help="Path to an Algorithm 10 thesis CSV report")
    parser.add_argument("--out-dir", default=None, help="Optional output directory")
    args = parser.parse_args()
    out_dir = generate_alg10_report_plots(args.csv, args.out_dir)
    print(out_dir)


if __name__ == "__main__":
    main()
