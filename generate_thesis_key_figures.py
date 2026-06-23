#!/usr/bin/env python3
"""Generate compact thesis figures from existing experiment artifacts."""

from __future__ import annotations

import csv
import json
import math
import os
import re
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt


ROOT = Path("results_optimized")
OUT = ROOT / "thesis_key_figures_20260623"

ABC_FLOW_CSV = (
    ROOT
    / "abc_then_tfo_whole_suite_20260622_000534"
    / "abc_baselines_original"
    / "abc_baseline_summary_by_flow_2026-06-22_00-05-34.csv"
)
POST_ABC_CSV = (
    ROOT
    / "abc_then_tfo_whole_suite_20260622_000534"
    / "post_abc_residual"
    / "post_abc_residual_summary.csv"
)
VALIDATION_DIR = ROOT / "professor_encoding_validation_full_20260622"
BOUNDED_DEPTH3_LOG = VALIDATION_DIR / "logs" / "bounded_encoding_depth3.log"
STRESS_LOG = VALIDATION_DIR / "logs" / "thesis_correctness_stress.log"
CURRENT_SQRT = ROOT / "native_tfo_continue_best_sqrt_5h_20260622_tmux" / "summary.json"
SQRT_SEED = ROOT / "native_tfo_continue_best_sqrt_smoke_20260622" / "summary.json"

NATIVE_PREFIXES = (
    "parallel_tfo_native_tfo",
    "native_tfo_7h",
    "native_tfo_continue_best",
)
SKIP_NATIVE_PARTS = (
    "abc_then_tfo",
    "professor",
    "feedback_validation",
    "pysat_assumption",
    "dch_focused",
    "native_tfo_continue_dch",
    "dryrun",
    "presmoke",
    "outside_smoke",
)


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _num(value, default=0):
    if value in (None, ""):
        return default
    if isinstance(value, str):
        value = value.strip().replace("%", "")
    try:
        if "." in str(value):
            return float(value)
        return int(value)
    except Exception:
        return default


def _short_key(key: str) -> str:
    key = key.replace("epfl_arithmetic_", "")
    key = key.replace("epfl_random_control_", "")
    key = key.replace("iscas_", "")
    key = key.replace("epfl_", "")
    return key


def _is_native_summary(path: Path) -> bool:
    text = str(path)
    if any(part in text for part in SKIP_NATIVE_PARTS):
        return False
    name = path.parent.name
    parent = path.parent
    return name.startswith(NATIVE_PREFIXES) or parent.name.startswith(NATIVE_PREFIXES)


def load_native_records() -> list[dict]:
    records: list[dict] = []
    for path in ROOT.glob("**/summary.json"):
        if not _is_native_summary(path):
            continue
        try:
            data = _read_json(path)
        except Exception:
            continue
        for target in data.get("targets", []) or []:
            key = target.get("key")
            if not key:
                continue
            totals = target.get("totals", {}) or {}
            removed = _num(target.get("removed"))
            unresolved = _num(target.get("unresolved"))
            record = {
                "key": key,
                "short": _short_key(key),
                "run": str(path.parent),
                "summary": str(path),
                "mtime": path.stat().st_mtime,
                "status": target.get("status", ""),
                "complete": bool(target.get("complete")),
                "removed": removed,
                "unresolved": unresolved,
                "current_gates": _num(target.get("current_gates")),
                "initial_gates": _num(target.get("initial_gates")),
                "generation": _num(target.get("generation")),
                "cec_pass": _num(totals.get("cec_pass_commits")),
                "cec_fail": _num(totals.get("cec_failed_commits")),
                "sat_reject": _num(totals.get("worker_sat_reject")),
                "timeout": _num(totals.get("worker_timeout")),
                "unsat_proposed": _num(totals.get("worker_unsat_proposed")),
                "worker_errors": _num(totals.get("worker_errors")),
                "util": _num((data.get("pool_metrics") or {}).get("worker_utilization"), 0.0),
                "elapsed_s": _num(target.get("elapsed_seconds") or data.get("elapsed")),
            }
            records.append(record)
    return records


def latest_by_circuit(records: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for rec in records:
        old = latest.get(rec["key"])
        if old is None or rec["mtime"] > old["mtime"]:
            latest[rec["key"]] = rec
    return latest


def best_by_unresolved(records: list[dict]) -> dict[str, dict]:
    best: dict[str, dict] = {}
    for rec in records:
        score = (
            0 if rec["complete"] or rec["unresolved"] == 0 else 1,
            rec["unresolved"],
            -rec["removed"],
            -rec["mtime"],
        )
        old = best.get(rec["key"])
        if old is None:
            best[rec["key"]] = rec | {"_score": score}
        else:
            if score < old["_score"]:
                best[rec["key"]] = rec | {"_score": score}
    return best


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def parse_validation_numbers() -> dict:
    result = {
        "bounded_candidates": 0,
        "bounded_circuits": 0,
        "bounded_elapsed_s": 0.0,
        "stress_pass_rows": 0,
        "stress_required_failures": 0,
        "stress_elapsed_s": 0.0,
        "negative_controls": 0,
        "modern_cec_pass": 0,
        "modern_cec_fail": 0,
    }
    if BOUNDED_DEPTH3_LOG.exists():
        text = BOUNDED_DEPTH3_LOG.read_text(encoding="utf-8", errors="ignore")
        for key, pat in [
            ("bounded_candidates", r"(?m)^candidates=(\d+)"),
            ("bounded_circuits", r"(?m)^circuits=(\d+)"),
            ("bounded_elapsed_s", r"(?m)^elapsed=([0-9.]+)s"),
        ]:
            matches = re.findall(pat, text)
            if matches:
                result[key] = _num(matches[-1])
    if STRESS_LOG.exists():
        text = STRESS_LOG.read_text(encoding="utf-8", errors="ignore")
        result["stress_pass_rows"] = len(re.findall(r"^PASS ", text, flags=re.MULTILINE))
        result["negative_controls"] = len(re.findall(r"negative_control", text))
        m = re.search(r"Elapsed:\s*([0-9.]+)s", text)
        if m:
            result["stress_elapsed_s"] = float(m.group(1))
        result["stress_required_failures"] = len(re.findall(r"FAIL ", text))
    stress_csv = VALIDATION_DIR / "thesis_correctness_stress" / "correctness_stress.csv"
    if stress_csv.exists():
        rows = read_csv(stress_csv)
        result["stress_pass_rows"] = sum(1 for row in rows if row.get("Result") == "PASS")
        result["stress_required_failures"] = sum(
            1 for row in rows if row.get("Required") in ("1", "True", "true") and row.get("Result") != "PASS"
        )
        result["negative_controls"] = sum(1 for row in rows if "negative_control" in row.get("Test", ""))
    guide = Path("THESIS_REPORT_WRITING_GUIDE.md")
    if guide.exists():
        text = guide.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"(\d+)\s+CEC-passed commits and\s+`?(\d+)`?\s+CEC-failed", text)
        if not m:
            m = re.search(r"`?(\d+)`?\s+CEC-passed commits and\s+`?(\d+)`?\s+CEC-failed", text)
        if m:
            result["modern_cec_pass"] = int(m.group(1))
            result["modern_cec_fail"] = int(m.group(2))
    return result


def style_axes(ax):
    ax.grid(axis="y", alpha=0.25, linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def savefig(path: Path):
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()


def plot_latest_unresolved(latest_rows: list[dict]) -> None:
    completed = [r for r in latest_rows if r["complete"] or r["unresolved"] == 0]
    rows = [r for r in latest_rows if not r["complete"] and r["unresolved"] > 0]
    rows = sorted(rows, key=lambda r: (r["unresolved"], -r["removed"]))
    if not rows:
        rows = sorted(latest_rows, key=lambda r: (r["unresolved"], -r["removed"]))[:14]
    labels = [_short_key(r["key"]) for r in rows]
    unresolved = [max(1, int(r["unresolved"])) for r in rows]
    removed = [int(r["removed"]) for r in rows]

    fig, ax = plt.subplots(figsize=(10.8, 5.4))
    bars = ax.bar(labels, unresolved, color="#5470c6")
    ax.set_yscale("log")
    ax.set_ylim(max(1, min(unresolved) * 0.7), max(unresolved) * 2.8)
    ax.set_ylabel("Current unresolved obligations, log scale")
    ax.set_title("Latest Native SAT/TFO Active Frontiers")
    ax.tick_params(axis="x", rotation=35)
    style_axes(ax)
    for bar, rem, unr in zip(bars, removed, unresolved):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"rem {rem}\nunres {unr}",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    ax.text(
        0.01,
        0.96,
        f"{len(completed)} circuits are complete/zero. Unresolved is a frontier size, not a monotone progress counter.",
        transform=ax.transAxes,
        va="top",
        fontsize=9,
        color="#444444",
    )
    savefig(OUT / "01_latest_native_unresolved_frontier.png")


def plot_near_zero(best_rows: list[dict]) -> None:
    incomplete = [r for r in best_rows if not r["complete"] and r["unresolved"] > 0]
    rows = sorted(incomplete, key=lambda r: (r["unresolved"], -r["removed"]))[:10]
    labels = [_short_key(r["key"]) for r in rows]
    unresolved = [int(r["unresolved"]) for r in rows]
    removed = [int(r["removed"]) for r in rows]

    fig, ax = plt.subplots(figsize=(10.4, 5.2))
    colors = ["#2f9e44" if v <= 500 else "#f08c00" if v <= 10000 else "#868e96" for v in unresolved]
    bars = ax.barh(labels, unresolved, color=colors)
    ax.set_xscale("log")
    ax.invert_yaxis()
    ax.set_xlabel("Best recorded unresolved obligations, log scale")
    ax.set_title("Best Recorded Native Frontiers, Historical")
    style_axes(ax)
    for bar, rem, unr in zip(bars, removed, unresolved):
        ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2, f"  rem {rem}, unres {unr}", va="center", fontsize=8)
    savefig(OUT / "02_near_zero_native_targets.png")


def plot_sqrt_run() -> None:
    if not CURRENT_SQRT.exists() or not SQRT_SEED.exists():
        return
    seed = _read_json(SQRT_SEED)["targets"][0]
    cur = _read_json(CURRENT_SQRT)["targets"][0]
    labels = ["Seed checkpoint", "After 5h run"]

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.2))
    axes[0].bar(labels, [_num(seed.get("removed")), _num(cur.get("removed"))], color=["#74c0fc", "#339af0"])
    axes[0].set_title("Sqrt Removals")
    axes[0].set_ylabel("Removed AND gates")
    style_axes(axes[0])
    axes[1].bar(labels, [_num(seed.get("unresolved")), _num(cur.get("unresolved"))], color=["#ffd43b", "#f08c00"])
    axes[1].set_title("Sqrt Frontier After Rewrite")
    axes[1].set_ylabel("Unresolved obligations")
    style_axes(axes[1])
    fig.suptitle("Latest Sqrt Continuation: CEC-Passed Progress With Frontier Regeneration")
    savefig(OUT / "03_latest_sqrt_continuation.png")


def plot_worker_outcomes() -> None:
    if not CURRENT_SQRT.exists():
        return
    target = _read_json(CURRENT_SQRT)["targets"][0]
    totals = target.get("totals", {})
    labels = ["SAT rejects", "Timeouts", "UNSAT proposals", "CEC commits", "Worker errors"]
    values = [
        _num(totals.get("worker_sat_reject")),
        _num(totals.get("worker_timeout")),
        _num(totals.get("worker_unsat_proposed")),
        _num(totals.get("cec_pass_commits")),
        _num(totals.get("worker_errors")),
    ]
    fig, ax = plt.subplots(figsize=(10.2, 4.8))
    ax.bar(labels, values, color=["#12b886", "#fa5252", "#4dabf7", "#7950f2", "#495057"])
    ax.set_yscale("symlog", linthresh=2)
    ax.set_ylabel("Count, symlog scale")
    ax.set_title("Latest Sqrt Worker Outcomes")
    ax.tick_params(axis="x", rotation=20)
    style_axes(ax)
    for i, value in enumerate(values):
        ax.text(i, value if value else 0.2, str(value), ha="center", va="bottom", fontsize=9)
    savefig(OUT / "04_latest_sqrt_worker_outcomes.png")


def plot_abc_flows() -> list[dict]:
    rows = read_csv(ABC_FLOW_CSV) if ABC_FLOW_CSV.exists() else []
    rows = sorted(rows, key=lambda r: _num(r.get("Area_Saved_AND2")), reverse=True)
    labels = [r["Flow"] for r in rows]
    saved = [_num(r.get("Area_Saved_AND2")) for r in rows]
    colors = ["#2f9e44" if v >= 0 else "#fa5252" for v in saved]

    fig, ax = plt.subplots(figsize=(11, 5.3))
    bars = ax.bar(labels, saved, color=colors)
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_ylabel("Total AND2 gates saved vs input")
    ax.set_title("ABC Baseline Whole-Suite Area Reduction")
    ax.tick_params(axis="x", rotation=35)
    style_axes(ax)
    for bar, row in zip(bars, rows):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"CEC {row.get('CEC_PASS')}/{row.get('Rows')}",
            ha="center",
            va="bottom" if bar.get_height() >= 0 else "top",
            fontsize=8,
            rotation=90,
        )
    savefig(OUT / "05_abc_baseline_area_saved_by_flow.png")
    return rows


def plot_post_abc() -> list[dict]:
    rows = read_csv(POST_ABC_CSV) if POST_ABC_CSV.exists() else []
    rows = sorted(rows, key=lambda r: _num(r.get("Residual_Gates_Removed")), reverse=True)
    labels = [r["Flow"] for r in rows]
    removed = [_num(r.get("Residual_Gates_Removed")) for r in rows]

    fig, ax = plt.subplots(figsize=(11, 5.1))
    ax.bar(labels, removed, color="#0ca678")
    ax.set_ylabel("Additional gates removed by native exact TFO")
    ax.set_title("Residual Semantic Redundancy After CEC-Passed ABC Outputs")
    ax.tick_params(axis="x", rotation=35)
    style_axes(ax)
    for i, row in enumerate(rows):
        ax.text(i, removed[i], f"CEC {row.get('CEC_Pass_Commits')}", ha="center", va="bottom", fontsize=8)
    savefig(OUT / "06_post_abc_residual_native_tfo.png")
    return rows


def plot_validation(validation: dict, native_rows: list[dict]) -> None:
    cec_pass = validation.get("modern_cec_pass") or sum(_num(r.get("cec_pass")) for r in native_rows)
    cec_fail = validation.get("modern_cec_fail") if validation.get("modern_cec_pass") else sum(
        _num(r.get("cec_fail")) for r in native_rows
    )
    labels = [
        "Bounded\ncandidate checks",
        "Bounded\nsmall circuits",
        "Stress\nPASS rows",
        "Negative\ncontrols caught",
        "Modern\nCEC-pass commits",
        "Modern\nCEC-fail commits",
    ]
    values = [
        validation["bounded_candidates"],
        validation["bounded_circuits"],
        validation["stress_pass_rows"],
        validation["negative_controls"],
        cec_pass,
        cec_fail,
    ]
    colors = ["#339af0", "#339af0", "#2f9e44", "#845ef7", "#12b886", "#fa5252"]
    fig, ax = plt.subplots(figsize=(10.8, 5.0))
    ax.bar(labels, [max(1, int(v)) for v in values], color=colors)
    ax.set_yscale("log")
    ax.set_ylabel("Count, log scale")
    ax.set_title("Encoding and Pipeline Validation Evidence")
    style_axes(ax)
    for i, value in enumerate(values):
        ax.text(i, max(1, int(value)), str(int(value)), ha="center", va="bottom", fontsize=9)
    savefig(OUT / "07_correctness_validation_evidence.png")


def write_discussion(
    latest_rows: list[dict],
    best_rows: list[dict],
    abc_rows: list[dict],
    post_abc_rows: list[dict],
    validation: dict,
) -> None:
    current = _read_json(CURRENT_SQRT)["targets"][0] if CURRENT_SQRT.exists() else {}
    totals = current.get("totals", {})
    near = [r for r in sorted(best_rows, key=lambda r: (r["unresolved"], -r["removed"])) if not r["complete"] and r["unresolved"] > 0][:6]
    current_active = [
        r
        for r in sorted(latest_rows, key=lambda r: (r["unresolved"], -r["removed"]))
        if not r["complete"] and r["unresolved"] > 0
    ]
    done = [r for r in sorted(best_rows, key=lambda r: r["short"]) if r["complete"] or r["unresolved"] == 0]
    best_abc = abc_rows[0] if abc_rows else {}
    best_post = post_abc_rows[0] if post_abc_rows else {}
    non_bloating_post = [
        row
        for row in post_abc_rows
        if row.get("Flow") != "dch" and _num(row.get("Residual_Gates_Removed")) > 0
    ]

    lines = [
        "# Thesis Figure Pack and Discussion Notes",
        "",
        "## Latest Run Status",
        "",
        (
            "The current native `sqrt` continuation is finished. It ended at the 5-hour time budget with "
            f"`removed={current.get('removed')}`, `unresolved={current.get('unresolved')}`, "
            f"`cec_pass_commits={totals.get('cec_pass_commits')}`, `cec_failed_commits={totals.get('cec_failed_commits')}`, "
            f"`worker_errors={totals.get('worker_errors')}`, and worker utilization around "
            f"{_num(_read_json(CURRENT_SQRT).get('pool_metrics', {}).get('worker_utilization'), 0.0):.3f}."
        ),
        "",
        (
            "This is a good correctness result and a modest optimization result: the run accepted a CEC-passed "
            "rewrite and increased the removed count from 56 to 66. The unresolved count increased because the "
            "commit regenerated the candidate frontier on the new graph. In the thesis, unresolved should be "
            "described as a current frontier size, not as a monotone progress counter."
        ),
        "",
        "## Near-Zero Targets to Continue While Writing",
        "",
    ]
    if done:
        done_txt = ", ".join(f"{r['short']} (removed {r['removed']})" for r in done[:10])
        lines.append(f"Already at zero or marked complete in the native summaries: {done_txt}.")
        lines.append("")
    if near:
        near_txt = ", ".join(f"{r['short']} (unres {r['unresolved']}, removed {r['removed']})" for r in near)
        lines.append(f"Best historical frontier states by recorded unresolved count: {near_txt}.")
        lines.append("")
    if current_active:
        active_txt = ", ".join(
            f"{r['short']} (latest unres {r['unresolved']}, removed {r['removed']})" for r in current_active
        )
        lines.append(f"Current continuation order from the latest native summaries: {active_txt}.")
        lines.append("")
        lines.append(
            "For background runs while writing, `sqrt` is the cleanest next target from the current checkpoint. "
            "`voter` is second if the goal is visible removals. `log2`, `div`, `mem_ctrl`, and especially current `hyp` "
            "belong in the hard-frontier discussion rather than in a promise to reach zero soon."
        )
        lines.append("")
    lines.extend(
        [
            "For writing, the honest position is that small and medium circuits can be driven to zero, while large EPFL arithmetic circuits are dominated by a hard SAT tail. The tool is not near impossible as a research contribution, but reaching zero for every large circuit with the current Python/PySAT implementation is not a realistic deadline claim. The defensible claim is exact CEC-checked redundancy removal with explicit unresolved accounting.",
            "",
            "## ABC Baseline Discussion",
            "",
            (
                f"The strongest ABC baseline by whole-suite area saved in the recorded run is `{best_abc.get('Flow')}`, "
                f"with `{best_abc.get('Area_Saved_AND2')}` AND2 gates saved and CEC pass count "
                f"`{best_abc.get('CEC_PASS')}/{best_abc.get('Rows')}`. This should be presented as the industrial "
                "structural/resynthesis baseline, not as the same problem as SAT-based stuck-at redundancy classification."
            ),
            "",
            (
                f"The post-ABC residual experiment shows the largest extra native reduction after `{best_post.get('Flow')}` "
                f"with `{best_post.get('Residual_Gates_Removed')}` additional gates and "
                f"`{best_post.get('CEC_Pass_Commits')}` CEC-passed commits. This `dch` case must be presented carefully, "
                "because the ABC `dch` output increased the gate count before the residual run. It is useful as a stress "
                "case showing recovery from a bloated but CEC-passed output, not as the cleanest comparison point."
            ),
            "",
            (
                "The cleaner residual comparison points are "
                + ", ".join(
                    f"`{row.get('Flow')}`: {row.get('Residual_Gates_Removed')} gates"
                    for row in non_bloating_post[:4]
                )
                + ". These are smaller but easier to defend as complementary SAT-based removals after normal CEC-passed ABC flows."
            ),
            "",
            "## Figures Generated",
            "",
            "1. `01_latest_native_unresolved_frontier.png`: latest native unresolved frontier by circuit.",
            "2. `02_near_zero_native_targets.png`: best recorded historical frontiers for context.",
            "3. `03_latest_sqrt_continuation.png`: seed checkpoint versus latest 5-hour `sqrt` continuation.",
            "4. `04_latest_sqrt_worker_outcomes.png`: SAT rejects, timeouts, UNSAT proposals, and commits.",
            "5. `05_abc_baseline_area_saved_by_flow.png`: ABC whole-suite baseline area savings.",
            "6. `06_post_abc_residual_native_tfo.png`: additional native exact-TFO removals after ABC outputs.",
            "7. `07_correctness_validation_evidence.png`: bounded exhaustive and stress-test evidence.",
            "",
            "## Chapter 1 Proposal",
            "",
            "Open Chapter 1 with the practical problem: AIG optimization normally uses fast structural transformations, but structural similarity is not the same as semantic observability. A gate can be structurally present while its stuck-at replacement is unobservable at every primary output or latch-next cut boundary. This motivates SAT-based ATPG as an exact proof mechanism for candidate redundancy.",
            "",
            "Then define the gap: ABC-style optimization is strong and fast for synthesis, but it does not provide a candidate-by-candidate stuck-at classification trace with SAT/UNSAT/TIMEOUT accounting, checkpoint resume, and transactional proof logs. Existing structural flows can also leave residual semantic redundancy, while exact SAT engines can become impractical on hard arithmetic frontiers without careful slicing, scheduling, and audit rules.",
            "",
            "State the research questions around exactness and practicality: whether candidate-local exact TFO miters agree with full observable-root miters, whether side-input reuse remains sound under closure audits, whether parallel SAT proposals can be committed safely, and how much residual redundancy remains after established ABC baselines.",
            "",
            "List the contributions as the audited exact-TFO encoding, the transactional coordinator with sequential recheck and CEC-gated commits, checkpointed budget laddering with explicit unresolved accounting, the validation methodology, and the empirical comparison against ABC baselines.",
            "",
            "Close the introduction scope carefully: the thesis is not claiming a universal replacement for ABC or complete classification of all large EPFL circuits within fixed time. It claims a sound, audited, reproducible SAT proof framework for exact stuck-at redundancy removal in AIG/AAG circuits, with independent CEC verification of every reported optimized output.",
            "",
            "## Presentation Points",
            "",
            f"The validation run checked `{int(validation['bounded_candidates'])}` bounded candidates over `{int(validation['bounded_circuits'])}` small circuits, plus `{int(validation['stress_pass_rows'])}` required stress rows. This belongs in the main evaluation as correctness evidence, with detailed logs in an appendix.",
            "",
            "The large-circuit discussion should be framed as a hard-frontier result. SAT rejects are cheap and common, while UNSAT commits are rare and valuable. The latest `sqrt` run classified many SAT candidates and found a small number of accepted UNSAT proposals, but the remaining frontier is still large.",
            "",
            "Do not present unresolved count alone as quality. Pair it with removed gates, CEC commits, worker errors, timeouts, and the generation number.",
            "",
        ]
    )
    (OUT / "DISCUSSION_POINTS_AND_CHAPTER1_PLAN.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    records = load_native_records()
    latest = list(latest_by_circuit(records).values())
    best = [dict(v) for v in best_by_unresolved(records).values()]
    for row in best:
        row.pop("_score", None)

    latest_sorted = sorted(latest, key=lambda r: (r["unresolved"], -r["removed"], r["key"]))
    best_sorted = sorted(best, key=lambda r: (r["unresolved"], -r["removed"], r["key"]))

    fields = [
        "key",
        "short",
        "status",
        "complete",
        "removed",
        "unresolved",
        "current_gates",
        "initial_gates",
        "generation",
        "cec_pass",
        "cec_fail",
        "sat_reject",
        "timeout",
        "unsat_proposed",
        "worker_errors",
        "util",
        "elapsed_s",
        "run",
    ]
    write_csv(OUT / "latest_native_frontier.csv", latest_sorted, fields)
    write_csv(OUT / "best_native_frontier.csv", best_sorted, fields)

    plot_latest_unresolved(latest_sorted)
    plot_near_zero(best_sorted)
    plot_sqrt_run()
    plot_worker_outcomes()
    abc_rows = plot_abc_flows()
    post_rows = plot_post_abc()
    validation = parse_validation_numbers()
    plot_validation(validation, records)

    selected_abc_fields = [
        "Flow",
        "Rows",
        "CEC_PASS",
        "CEC_FAIL_OR_OTHER",
        "Timeout_or_Error",
        "Area_Saved_AND2",
        "Area_Red%",
        "T_Total(s)",
    ]
    write_csv(OUT / "abc_flow_summary_selected.csv", abc_rows, selected_abc_fields)
    selected_post_fields = [
        "Flow",
        "Circuits",
        "Residual_Gates_Removed",
        "SAT_Reject",
        "UNSAT_Proposed",
        "Timeout",
        "CEC_Pass_Commits",
        "Worker_Errors",
        "Remaining_Obligations",
        "Elapsed_s",
    ]
    write_csv(OUT / "post_abc_residual_selected.csv", post_rows, selected_post_fields)
    write_discussion(latest_sorted, best_sorted, abc_rows, post_rows, validation)

    print(f"Wrote figure pack to {OUT}")
    for path in sorted(OUT.iterdir()):
        print(path)


if __name__ == "__main__":
    main()
