#!/usr/bin/env python3
"""
Create meeting-ready plots for the current Algorithm 10 thesis results.

The script intentionally focuses on the latest SAT-side story:
  - fast vs deep verified reductions;
  - proof-tier contribution;
  - unresolved candidates after deep mode;
  - CEX pruning and CEX audit evidence.

It does not compare against ABC. That belongs in a separate baseline table.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns


OUT_DIR = Path("thesis_plots/alg10_current")

FAST_CSV = Path(
    "results_optimized/"
    "thesis_results_ALG10_alg10_fast_save_cex_window_real_suites_planted_2026-05-17_23-22-24.csv"
)
CLEAN_ABLATION_CSVS = [
    Path("results_optimized/sat_ablation_2026-05-17_19-18-58/sat_ablation_2026-05-17_19-18-58.csv"),
    Path("results_optimized/sat_ablation_2026-05-17_19-20-11/sat_ablation_2026-05-17_19-20-11.csv"),
    Path("results_optimized/sat_ablation_2026-05-17_19-22-44/sat_ablation_2026-05-17_19-22-44.csv"),
    Path("results_optimized/sat_ablation_2026-05-17_19-24-37/sat_ablation_2026-05-17_19-24-37.csv"),
    Path("results_optimized/sat_ablation_2026-05-17_19-27-31/sat_ablation_2026-05-17_19-27-31.csv"),
    Path("results_optimized/sat_ablation_2026-05-17_19-28-09/sat_ablation_2026-05-17_19-28-09.csv"),
]
DEEP_ISCAS_CSV = Path(
    "results_optimized/deep_clean_overnight_2026-05-18/"
    "sat_ablation_2026-05-18_03-22-57.csv"
)
DEEP_EPFL_CSV = Path(
    "results_optimized/deep_clean_overnight_epfl_remaining_run2_2026-05-18/"
    "sat_ablation_2026-05-18_03-29-06.csv"
)
AUDIT_CSVS = [
    Path("results_optimized/cex_audit_c7552/sat_ablation_2026-05-18_01-53-05.csv"),
    Path("results_optimized/cex_audit_sqrt/sat_ablation_2026-05-18_01-55-23.csv"),
]


NICE_NAMES = {
    "benchmarks/c432.aag": "c432",
    "benchmarks/c7552.aag": "c7552",
    "benchmarks/c6288.aag": "c6288",
    "benchmark_suites/epfl/epfl_arithmetic_sin.aag": "sin",
    "benchmark_suites/epfl/epfl_arithmetic_sqrt.aag": "sqrt",
    "benchmark_suites/epfl/epfl_arithmetic_div.aag": "div",
    "benchmark_suites/epfl/epfl_arithmetic_log2.aag": "log2",
    "benchmark_suites/epfl/epfl_random_control_mem_ctrl.aag": "mem_ctrl",
}


def safe_read(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def circuit_name(value: str) -> str:
    if value in NICE_NAMES:
        return NICE_NAMES[value]
    stem = Path(str(value)).stem
    for prefix in [
        "epfl_epfl_arithmetic_",
        "epfl_arithmetic_",
        "epfl_epfl_random_control_",
        "epfl_random_control_",
    ]:
        if stem.startswith(prefix):
            stem = stem[len(prefix) :]
            break
    return stem


def numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def col_or_zero(df: pd.DataFrame, *names: str) -> pd.Series:
    for name in names:
        if name in df.columns:
            return pd.to_numeric(df[name], errors="coerce").fillna(0)
    return pd.Series([0] * len(df), index=df.index)


def normalize_fast(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = pd.DataFrame()
    out["Circuit"] = df["Circuit"].map(circuit_name)
    out["Profile"] = "Fast broad run"
    out["Removed"] = col_or_zero(df, "Area_Saved_AND2", "Gates_Removed", "SAT_Induced_Removed_AND2", "Removed")
    out["Verify"] = df.get("Verify", "")
    out["SAT_Unresolved"] = col_or_zero(df, "SAT_Unresolved")
    out["T_Total"] = col_or_zero(df, "Total_Time_s", "T_Total", "Total")
    return out[out["Circuit"].isin(NICE_NAMES.values())]


def normalize_ablation(df: pd.DataFrame, profile: str) -> pd.DataFrame:
    if df.empty:
        return df
    out = pd.DataFrame()
    out["Circuit"] = df["Circuit"].map(circuit_name)
    out["Profile"] = profile
    out["Variant"] = df.get("Variant", "")
    out["Removed"] = col_or_zero(df, "Removed", "Area_Saved_AND2")
    out["Verify"] = df.get("Verify", "")
    out["SAT_Unresolved"] = col_or_zero(df, "SAT_Unresolved")
    out["T_Total"] = col_or_zero(df, "T_Total", "Total_Time_s", "Total")
    return out[out["Circuit"].isin(NICE_NAMES.values())]


def load_deep() -> pd.DataFrame:
    frames = []
    for path in [DEEP_ISCAS_CSV, DEEP_EPFL_CSV]:
        df = safe_read(path)
        if not df.empty:
            df["Source_CSV"] = str(path)
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    deep = pd.concat(frames, ignore_index=True)
    if "Verify" in deep.columns:
        deep = deep[deep["Verify"].eq("PASS")].copy()
    deep["Circuit_Short"] = deep["Circuit"].map(circuit_name)
    numeric(
        deep,
        [
            "Removed",
            "Area_Saved_AND2",
            "T_Total",
            "T_SAT",
            "SAT_Unresolved",
            "TFI_Query_UNSAT",
            "Window_Query_UNSAT",
            "Cone_Query_UNSAT",
            "Global_Query_UNSAT",
            "CEX_Pruned",
            "CEX_TFI_Pruned",
            "SAT_Checks",
            "SAT_Timeouts",
        ],
    )
    return deep


def load_best_clean_ablation() -> pd.DataFrame:
    frames = []
    for path in CLEAN_ABLATION_CSVS:
        df = normalize_ablation(safe_read(path), "Best clean short ablation")
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    rows = pd.concat(frames, ignore_index=True)
    rows = rows[rows["Verify"].eq("PASS")]
    rows = rows.sort_values(["Circuit", "Removed", "T_Total"], ascending=[True, False, True])
    return rows.groupby("Circuit", as_index=False).head(1)


def save_bar(data: pd.DataFrame, x: str, y: str, hue: str | None, title: str, path: Path, ylabel: str) -> None:
    plt.figure(figsize=(11, 6))
    ax = sns.barplot(data=data, x=x, y=y, hue=hue, palette="viridis")
    ax.set_title(title)
    ax.set_xlabel("")
    ax.set_ylabel(ylabel)
    ax.tick_params(axis="x", rotation=30)
    for container in ax.containers:
        ax.bar_label(container, fmt="%.0f", fontsize=8)
    plt.tight_layout()
    plt.savefig(path, dpi=200)
    plt.close()


def make_plots() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid")

    deep = load_deep()
    if deep.empty:
        raise SystemExit("No deep CSV rows found.")

    fast = normalize_fast(safe_read(FAST_CSV))
    short_best = load_best_clean_ablation()

    compare_frames = []
    if not fast.empty:
        compare_frames.append(fast[["Circuit", "Profile", "Removed"]])
    if not short_best.empty:
        compare_frames.append(short_best[["Circuit", "Profile", "Removed"]])
    compare_frames.append(
        pd.DataFrame(
            {
                "Circuit": deep["Circuit_Short"],
                "Removed": deep["Removed"],
                "Profile": "Clean deep profile",
            }
        )
    )
    compare = pd.concat(compare_frames, ignore_index=True)
    compare = compare[compare["Circuit"].isin(["c432", "c7552", "c6288", "sin", "sqrt", "div", "log2", "mem_ctrl"])]
    compare["Circuit"] = pd.Categorical(
        compare["Circuit"],
        categories=["c432", "c7552", "c6288", "sin", "sqrt", "div", "log2", "mem_ctrl"],
        ordered=True,
    )
    compare.to_csv(OUT_DIR / "summary_removed_fast_short_deep.csv", index=False)
    save_bar(
        compare,
        "Circuit",
        "Removed",
        "Profile",
        "Verified stuck-at removals: fast/short/deep",
        OUT_DIR / "01_removed_fast_short_deep.png",
        "AND gates removed",
    )

    tier = deep[["Circuit_Short", "TFI_Query_UNSAT", "Window_Query_UNSAT", "Cone_Query_UNSAT", "Global_Query_UNSAT"]].copy()
    tier = tier.rename(
        columns={
            "TFI_Query_UNSAT": "TFI constancy",
            "Window_Query_UNSAT": "Audited window",
            "Cone_Query_UNSAT": "Exact cone",
            "Global_Query_UNSAT": "Global miter",
        }
    )
    tier_long = tier.melt(id_vars="Circuit_Short", var_name="Proof tier", value_name="UNSAT commits")
    tier_long.to_csv(OUT_DIR / "summary_deep_tier_commits.csv", index=False)
    save_bar(
        tier_long,
        "Circuit_Short",
        "UNSAT commits",
        "Proof tier",
        "Deep mode: accepted candidates by SAT proof tier",
        OUT_DIR / "02_deep_tier_commits.png",
        "UNSAT commitments",
    )

    unresolved = deep[["Circuit_Short", "SAT_Unresolved", "SAT_Checks", "SAT_Timeouts"]].copy()
    unresolved.to_csv(OUT_DIR / "summary_deep_unresolved.csv", index=False)
    plt.figure(figsize=(11, 6))
    ax = sns.barplot(data=unresolved, x="Circuit_Short", y="SAT_Unresolved", color="#4c78a8")
    ax.set_title("Deep mode remaining unresolved candidates")
    ax.set_xlabel("")
    ax.set_ylabel("SAT_Unresolved")
    ax.tick_params(axis="x", rotation=30)
    for container in ax.containers:
        ax.bar_label(container, fmt="%.0f", fontsize=8)
    plt.tight_layout()
    plt.savefig(OUT_DIR / "03_deep_unresolved.png", dpi=200)
    plt.close()

    cex = deep[["Circuit_Short", "CEX_Pruned", "CEX_TFI_Pruned"]].copy()
    cex_long = cex.melt(id_vars="Circuit_Short", var_name="CEX pruning type", value_name="Candidates")
    cex_long.to_csv(OUT_DIR / "summary_deep_cex_pruning.csv", index=False)
    save_bar(
        cex_long,
        "Circuit_Short",
        "Candidates",
        "CEX pruning type",
        "Deep mode: CEX-pruned candidates",
        OUT_DIR / "04_deep_cex_pruning.png",
        "Candidates pruned",
    )

    audit_frames = []
    for path in AUDIT_CSVS:
        df = safe_read(path)
        if not df.empty:
            audit_frames.append(df)
    if audit_frames:
        audit = pd.concat(audit_frames, ignore_index=True)
        audit["Circuit_Short"] = audit["Circuit"].map(circuit_name)
        numeric(
            audit,
            [
                "CEX_Audit_Checked",
                "CEX_Audit_SAT",
                "CEX_Audit_False_Prunes",
                "CEX_Audit_Timeouts",
                "CEX_Audit_Skipped",
                "CEX_Pruned",
                "Removed",
                "T_Total",
            ],
        )
        audit[
            [
                "Circuit_Short",
                "Removed",
                "CEX_Audit_Checked",
                "CEX_Audit_SAT",
                "CEX_Audit_False_Prunes",
                "CEX_Audit_Timeouts",
                "CEX_Audit_Skipped",
                "T_Total",
            ]
        ].to_csv(OUT_DIR / "summary_cex_audit.csv", index=False)

        audit_long = audit.melt(
            id_vars="Circuit_Short",
            value_vars=["CEX_Audit_SAT", "CEX_Audit_False_Prunes", "CEX_Audit_Timeouts"],
            var_name="Audit result",
            value_name="Count",
        )
        save_bar(
            audit_long,
            "Circuit_Short",
            "Count",
            "Audit result",
            "CEX recall audit outcomes",
            OUT_DIR / "05_cex_audit_outcomes.png",
            "Audit checks",
        )

    write_meeting_notes(deep, compare)


def write_meeting_notes(deep: pd.DataFrame, compare: pd.DataFrame) -> None:
    deep_rows = deep.sort_values("Circuit_Short")
    total_removed = int(deep_rows["Removed"].sum())
    pass_count = int(deep_rows["Verify"].eq("PASS").sum()) if "Verify" in deep_rows.columns else len(deep_rows)
    lines = [
        "# Algorithm 10 Meeting Notes",
        "",
        "## Current Claim",
        "",
        "Algorithm 10 is a correctness-gated SAT pipeline for combinational AIG stuck-at constant redundancy removal. "
        "Accepted replacements require SAT UNSAT proof in one of the proof tiers and final ABC CEC PASS. "
        "Simulation/CEX pruning is rejection-only.",
        "",
        "## Deep Run Summary",
        "",
        f"- Deep rows analyzed: {len(deep_rows)}; CEC PASS rows: {pass_count}/{len(deep_rows)}.",
        f"- Total verified AND removals in the clean deep rows: {total_removed}.",
        "- ISCAS c432/c7552/c6288 reached SAT_Unresolved=0 in the clean deep run.",
        "- EPFL rows still hit time budgets, so they are not exhaustive completion claims.",
        "",
        "## Per-Circuit Deep Results",
        "",
        "| Circuit | Removed | TFI UNSAT | Window UNSAT | Unresolved | CEC |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for _, row in deep_rows.iterrows():
        lines.append(
            f"| {row['Circuit_Short']} | {int(row['Removed'])} | "
            f"{int(row['TFI_Query_UNSAT'])} | {int(row['Window_Query_UNSAT'])} | "
            f"{int(row['SAT_Unresolved'])} | {row.get('Verify', '')} |"
        )
    lines.extend(
        [
            "",
            "## How To Explain Checkpoints",
            "",
            "- `sat_ablation_experiments.py` uses `ALG10_RESET_CHECKPOINT=1`, so each row is a clean run from the benchmark.",
            "- Algorithm 10 checkpoints save the last safe optimized AAG, not an exact unresolved-candidate queue.",
            "- A resume run starts from the last safe optimized circuit and sweeps again; it does not literally continue at candidate 180/179.",
            "",
            "## Safe Wording",
            "",
            "- Say: fully resolved under the current single-gate stuck-at replacement model when `SAT_Unresolved=0`.",
            "- Do not say: fully optimized circuit, optimal reduction, or no possible redundancy exists.",
            "- Say: EPFL deep rows found more verified reductions but still have unresolved candidates under the time budget.",
            "",
            "## Suggested Meeting Ask",
            "",
            "Ask whether to prioritize: (1) ABC baseline comparison, (2) adaptive tier routing / CEX scan reduction, "
            "or (3) candidate ordering experiments. The SAT encoding itself should stay stable unless a proof audit fails.",
            "",
            "## Generated Files",
            "",
        ]
    )
    for path in sorted(OUT_DIR.glob("*.png")):
        lines.append(f"- `{path}`")
    for path in sorted(OUT_DIR.glob("summary_*.csv")):
        lines.append(f"- `{path}`")
    (OUT_DIR / "MEETING_NOTES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    make_plots()
    print(f"Saved professor pack in {OUT_DIR}")
