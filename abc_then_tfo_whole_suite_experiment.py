#!/usr/bin/env python3
"""Run ABC baselines, then SAT/TFO residual search on CEC-passed ABC outputs.

The experiment order is:

1. Run selected ABC synthesis flows on the original benchmark suite.
2. Keep only ABC outputs whose direct ABC CEC result is PASS.
3. Run the native exact-TFO residual campaign on those CEC-passed outputs.

This wrapper exists so thesis comparison runs do not accidentally run SAT/TFO
on an ABC output that failed equivalence checking.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

import abc_baseline_runner as abc_runner


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_FLOWS = [
    "strash",
    "balance",
    "rewrite",
    "refactor",
    "dc2",
    "dch",
    "fraig",
    "resyn2",
    "resyn2x2",
    "dc2_fraig",
    "dch_resyn2",
]


def _csv(raw: str) -> List[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _run(cmd: List[str]) -> None:
    print("\n[run]", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)


def _latest_detail_csv(baseline_dir: Path) -> Path:
    detail = sorted(baseline_dir.glob("abc_baseline_*.csv"))
    detail = [path for path in detail if "summary_by_flow" not in path.name and "best_by_circuit" not in path.name]
    if not detail:
        raise RuntimeError(f"no ABC detail CSV found in {baseline_dir}")
    return detail[-1]


def _latest_summary_csv(baseline_dir: Path) -> Path | None:
    summaries = sorted(baseline_dir.glob("abc_baseline_summary_by_flow_*.csv"))
    return summaries[-1] if summaries else None


def _latest_best_csv(baseline_dir: Path) -> Path | None:
    best = sorted(baseline_dir.glob("abc_baseline_best_by_circuit_*.csv"))
    return best[-1] if best else None


def _copy_cec_pass_outputs(detail_csv: Path, output_root: Path, flows: Iterable[str]) -> Path:
    pass_root = output_root / "abc_cec_pass_outputs"
    if pass_root.exists():
        shutil.rmtree(pass_root)
    pass_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "abc_cec_pass_manifest.csv"
    wanted = set(flows)
    kept_rows = []

    with detail_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("Flow") not in wanted:
                continue
            if row.get("Status") != "OK" or row.get("Verify") != "PASS":
                continue
            output_path = Path(row.get("Output_Path", ""))
            if not output_path.exists():
                continue
            flow_dir = pass_root / row["Flow"]
            flow_dir.mkdir(parents=True, exist_ok=True)
            dst = flow_dir / output_path.name
            shutil.copy2(output_path, dst)
            kept = dict(row)
            kept["Filtered_Output_Path"] = str(dst)
            kept_rows.append(kept)

    if kept_rows:
        with manifest_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(kept_rows[0]))
            writer.writeheader()
            writer.writerows(kept_rows)

    print(f"[filter] CEC-passed ABC outputs: {len(kept_rows)}")
    print(f"[filter] root: {pass_root}")
    print(f"[filter] manifest: {manifest_path}")
    return pass_root


def _nonempty_flows(pass_root: Path, flows: Iterable[str]) -> List[str]:
    available = []
    for flow in flows:
        if list((pass_root / flow).glob("*.aag")):
            available.append(flow)
    return available


def _read_csv(path: Path | None) -> List[dict]:
    if not path or not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_meeting_summary(output_root: Path, baseline_dir: Path, post_dir: Path | None) -> None:
    summary_csv = _latest_summary_csv(baseline_dir)
    best_csv = _latest_best_csv(baseline_dir)
    post_summary = post_dir / "post_abc_residual_summary.csv" if post_dir else None
    abc_rows = _read_csv(summary_csv)
    best_rows = _read_csv(best_csv)
    post_rows = _read_csv(post_summary)

    lines = [
        "# ABC Then SAT/TFO Whole-Suite Experiment",
        "",
        f"- ABC baseline directory: `{baseline_dir}`",
        f"- CEC-passed ABC outputs: `{output_root / 'abc_cec_pass_outputs'}`",
    ]
    if post_dir:
        lines.append(f"- Post-ABC residual directory: `{post_dir}`")
    lines.extend(
        [
            "",
            "## ABC Flow Summary",
            "",
            "| Flow | Rows | OK | CEC PASS | CEC Fail/Other | Timeout/Error | Area Saved AND2 | Area Reduction | ABC Time Total |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in abc_rows:
        lines.append(
            "| {Flow} | {Rows} | {OK} | {CEC_PASS} | {CEC_FAIL_OR_OTHER} | {Timeout_or_Error} | {Area_Saved_AND2} | {Area_Red%} | {T_ABC_Total(s)} |".format(
                **row
            )
        )

    if best_rows:
        lines.extend(
            [
                "",
                "## Best ABC Flow By Circuit",
                "",
                "| Circuit | Best Area Flow | Original Gates | Best Area AND2 | Saved AND2 |",
                "| --- | --- | ---: | ---: | ---: |",
            ]
        )
        for row in best_rows:
            lines.append(
                "| {Circuit} | {Best_Area_Flow} | {Original_Gates} | {Best_Area_AND2} | {Best_Area_Saved_AND2} |".format(
                    **row
                )
            )

    if post_rows:
        lines.extend(
            [
                "",
                "## Residual SAT/TFO After ABC",
                "",
                "| ABC Flow | Circuits | Residual Removed | Remaining Obligations | SAT Reject | Timeout | CEC Pass Commits | Worker Errors |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in post_rows:
            remaining = row.get("Remaining_Obligations", "")
            lines.append(
                "| {Flow} | {Circuits} | {Residual_Gates_Removed} | "
                f"{remaining} | "
                "{SAT_Reject} | {Timeout} | {CEC_Pass_Commits} | {Worker_Errors} |".format(
                    **row
                )
            )

    lines.extend(
        [
            "",
            "## Interpretation Guardrails",
            "",
            "- Use only `Verify=PASS` ABC rows in thesis tables.",
            "- Report ABC CEC failures and timeouts separately; they are not valid area-comparison rows.",
            "- ABC is a broader synthesis baseline; the SAT/TFO tool is a semantic stuck-at redundancy remover.",
            "- Residual removals after ABC are evidence of complementarity, not a claim that SAT/TFO is a better general optimizer.",
        ]
    )
    out = output_root / "MEETING_SUMMARY.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[summary] {out}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run ABC baselines and then SAT/TFO residual search on CEC-passed ABC outputs."
    )
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        help="Input file or directory. Repeatable. Defaults to benchmarks and benchmark_suites/epfl.",
    )
    parser.add_argument(
        "--flows",
        default=",".join(DEFAULT_FLOWS),
        help=f"Comma-separated ABC flows. Available: {', '.join(sorted(abc_runner.FLOW_SCRIPTS))}",
    )
    parser.add_argument("--output-root", default="")
    parser.add_argument("--abc-timeout", type=float, default=300.0)
    parser.add_argument("--cec-timeout", type=float, default=120.0)
    parser.add_argument("--max-circuits", type=int, default=0)
    parser.add_argument("--filter", default="")
    parser.add_argument("--skip-abc", action="store_true")
    parser.add_argument("--baseline-dir", default="")
    parser.add_argument("--skip-residual", action="store_true")
    parser.add_argument("--seconds-per-flow", type=int, default=120)
    parser.add_argument("--jobs", type=int, default=12)
    parser.add_argument("--budgets", default="10000")
    parser.add_argument("--max-generated-budget", type=int, default=10000)
    parser.add_argument("--microbatch-size", type=int, default=4)
    parser.add_argument("--retry-microbatch-size", type=int, default=1)
    parser.add_argument("--deadline-reserve-seconds", type=float, default=5.0)
    parser.add_argument("--unknown-task-guard-seconds", type=float, default=10.0)
    parser.add_argument("--solver", default="cadical153")
    parser.add_argument("--order", default="proof_reverse_portfolio")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    flows = _csv(args.flows)
    unknown = [flow for flow in flows if flow not in abc_runner.FLOW_SCRIPTS]
    if unknown:
        raise SystemExit(f"unknown ABC flow(s): {', '.join(unknown)}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path(args.output_root or f"results_optimized/abc_then_tfo_whole_suite_{stamp}")
    if not output_root.is_absolute():
        output_root = REPO_ROOT / output_root
    output_root.mkdir(parents=True, exist_ok=True)

    baseline_dir = Path(args.baseline_dir) if args.baseline_dir else output_root / "abc_baselines_original"
    if not baseline_dir.is_absolute():
        baseline_dir = REPO_ROOT / baseline_dir

    inputs = args.input or ["benchmarks", "benchmark_suites/epfl"]
    if not args.skip_abc:
        cmd = [
            sys.executable,
            "abc_baseline_runner.py",
            "--output-dir",
            str(baseline_dir),
            "--flows",
            ",".join(flows),
            "--timeout",
            str(args.abc_timeout),
            "--cec-timeout",
            str(args.cec_timeout),
            "--reference-csv",
            "none",
        ]
        for item in inputs:
            cmd.extend(["--input", item])
        if args.max_circuits:
            cmd.extend(["--max-circuits", str(args.max_circuits)])
        if args.filter:
            cmd.extend(["--filter", args.filter])
        _run(cmd)
    elif not baseline_dir.exists():
        raise SystemExit(f"--skip-abc requires existing --baseline-dir: {baseline_dir}")

    detail_csv = _latest_detail_csv(baseline_dir)
    pass_root = _copy_cec_pass_outputs(detail_csv, output_root, flows)
    residual_flows = _nonempty_flows(pass_root, flows)
    post_dir = None
    if args.skip_residual:
        print("[post-abc] skipped")
    elif not residual_flows:
        print("[post-abc] skipped: no CEC-passed ABC outputs")
    else:
        post_dir = output_root / "post_abc_residual"
        cmd = [
            sys.executable,
            "post_abc_residual_tfo_experiment.py",
            "--baseline-root",
            str(pass_root),
            "--flows",
            ",".join(residual_flows),
            "--output-dir",
            str(post_dir),
            "--seconds-per-flow",
            str(args.seconds_per_flow),
            "--jobs",
            str(args.jobs),
            "--budgets",
            args.budgets,
            "--max-generated-budget",
            str(args.max_generated_budget),
            "--microbatch-size",
            str(args.microbatch_size),
            "--retry-microbatch-size",
            str(args.retry_microbatch_size),
            "--deadline-reserve-seconds",
            str(args.deadline_reserve_seconds),
            "--unknown-task-guard-seconds",
            str(args.unknown_task_guard_seconds),
            "--solver",
            args.solver,
            "--order",
            args.order,
            "--cec-timeout",
            str(args.cec_timeout),
        ]
        _run(cmd)

    _write_meeting_summary(output_root, baseline_dir, post_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
