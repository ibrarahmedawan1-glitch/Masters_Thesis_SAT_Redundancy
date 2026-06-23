#!/usr/bin/env python3
"""Read-only PySAT assumption-reuse audit experiment.

This experiment compares two encodings on one frozen AAG generation:

* ``tfo``: the current production-style exact TFO miter, rebuilt per candidate.
* ``global``: one persistent full-circuit fault-sweep miter, queried with
  PySAT assumptions for each candidate.

The global path is deliberately treated as experimental.  It never rewrites an
AAG and never commits a candidate.  A global UNSAT result is considered useful
only if the exact TFO audit agrees.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import alg10_frontier_shard_probe as probe


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "results_optimized"
PHASE_MODES = ("none", "controls_false", "model", "controls_false_model")

DETAIL_FIELDS = [
    "circuit",
    "variant",
    "phase_mode",
    "candidate_ordinal",
    "gate",
    "sa",
    "status",
    "family",
    "seconds",
    "clauses",
    "worker_cache_hit",
    "model_phase_updated",
    "tfo_status",
    "tfo_family",
    "agreement",
]


@dataclass(frozen=True)
class ExperimentConfig:
    circuit: str
    limit: int = 16
    solver: str = "cadical153"
    frontier_order: str = "current"
    global_budget: int = 1000
    audit_budget: int = 0
    phase_modes: Tuple[str, ...] = ("none",)
    checkpoint_dir: str = "results_optimized/alg10_checkpoints_pysat_assumption_reuse"
    use_checkpoint: bool = False
    checkpoint_json: str = ""
    strict: bool = True


def parse_csv_words(raw: str) -> Tuple[str, ...]:
    values = tuple(part.strip().lower() for part in str(raw).split(",") if part.strip())
    bad = [value for value in values if value not in PHASE_MODES]
    if bad:
        raise ValueError(f"unsupported phase mode(s): {bad}; choose from {PHASE_MODES}")
    return values or ("none",)


def status_family(status: str) -> str:
    if status == probe.STATUS_SAT_REJECT:
        return "SAT"
    if status == probe.STATUS_UNSAT_PROPOSED:
        return "UNSAT"
    if status == probe.STATUS_TIMEOUT:
        return "TIMEOUT"
    if str(status).startswith("ERROR"):
        return "ERROR"
    return str(status)


def candidate_key(item: Mapping[str, Any]) -> Tuple[int, int]:
    return int(item["idx"]), int(item["stuck_value"])


def indexed(results: Sequence[Mapping[str, Any]]) -> Dict[Tuple[int, int], Mapping[str, Any]]:
    return {candidate_key(item): item for item in results}


def status_counts(results: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    counts = Counter(status_family(str(item.get("status", ""))) for item in results)
    return {name: int(counts.get(name, 0)) for name in ("SAT", "UNSAT", "TIMEOUT", "ERROR")}


def _sum_result_seconds(results: Sequence[Mapping[str, Any]]) -> float:
    return sum(float(item.get("seconds", 0.0) or 0.0) for item in results)


def compare_against_tfo(
    global_results: Sequence[Mapping[str, Any]],
    tfo_results: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Compare resolved global answers with exact TFO audit answers.

    SAT/UNSAT disagreement is a hard mismatch.  A global UNSAT with a TFO
    timeout is not accepted either; it is reported as unaudited because this
    experiment should never use a persistent global result as a removal proof
    unless exact TFO agrees.
    """

    by_global = indexed(global_results)
    by_tfo = indexed(tfo_results)
    mismatches: List[Dict[str, Any]] = []
    unaudited_unsat: List[Dict[str, Any]] = []
    agreements = 0
    resolved_global = 0

    for key in sorted(set(by_global) | set(by_tfo)):
        global_item = by_global.get(key)
        tfo_item = by_tfo.get(key)
        if global_item is None or tfo_item is None:
            mismatches.append(
                {
                    "gate": key[0],
                    "sa": key[1],
                    "global": None if global_item is None else global_item.get("status"),
                    "tfo": None if tfo_item is None else tfo_item.get("status"),
                    "reason": "missing_candidate",
                }
            )
            continue

        global_family = status_family(str(global_item.get("status", "")))
        tfo_family = status_family(str(tfo_item.get("status", "")))
        if global_family in {"SAT", "UNSAT"}:
            resolved_global += 1

        if global_family in {"SAT", "UNSAT"} and tfo_family in {"SAT", "UNSAT"}:
            if global_family == tfo_family:
                agreements += 1
            else:
                mismatches.append(
                    {
                        "gate": key[0],
                        "sa": key[1],
                        "global": global_item.get("status"),
                        "tfo": tfo_item.get("status"),
                        "reason": "resolved_status_disagreement",
                    }
                )
        elif global_family == "UNSAT":
            unaudited_unsat.append(
                {
                    "gate": key[0],
                    "sa": key[1],
                    "global": global_item.get("status"),
                    "tfo": tfo_item.get("status"),
                    "reason": "global_unsat_without_exact_tfo_agreement",
                }
            )

    return {
        "resolved_global": resolved_global,
        "resolved_agreements": agreements,
        "mismatches": mismatches,
        "unaudited_unsat": unaudited_unsat,
        "strict_ok": not mismatches and not unaudited_unsat,
    }


def _probe_config(config: ExperimentConfig, *, engine: str, phase_mode: str = "none") -> probe.Alg10Config:
    return probe.Alg10Config(
        checkpoint_dir=config.checkpoint_dir,
        extra_checkpoint_dirs=(),
        checkpoint_select="unresolved",
        frontier_order=config.frontier_order,
        solver=config.solver,
        phase_mode=phase_mode,
        engine=engine,
        worker_cache_entries=0,
    )


def _run_probe(
    work_path: str,
    items: Sequence[probe.WorkItem],
    budget: int,
    config: probe.Alg10Config,
) -> Dict[str, Any]:
    started = time.perf_counter()
    run = probe.run_serial(work_path, items, budget, config, audit_assumptions=True)
    wall = time.perf_counter() - started
    results = list(run["results"])
    return {
        "seconds": float(run.get("seconds", wall)),
        "outer_wall_seconds": wall,
        "result_seconds": _sum_result_seconds(results),
        "setup_seconds_estimate": max(0.0, float(run.get("seconds", wall)) - _sum_result_seconds(results)),
        "results": results,
        "counts": status_counts(results),
    }


def run_experiment(config: ExperimentConfig) -> Dict[str, Any]:
    circuit_path = str(Path(config.circuit).resolve())
    tfo_config = _probe_config(config, engine="tfo")
    frontier = probe.load_frontier(
        circuit_path,
        tfo_config,
        limit=config.limit,
        use_checkpoint=config.use_checkpoint or bool(config.checkpoint_json),
        checkpoint_json=config.checkpoint_json,
    )
    work_path = str(frontier["work_path"])
    items = list(frontier["work_items"])

    tfo_audit = _run_probe(work_path, items, config.audit_budget, tfo_config)

    variants = []
    for phase_mode in config.phase_modes:
        global_config = _probe_config(config, engine="global", phase_mode=phase_mode)
        global_run = _run_probe(work_path, items, config.global_budget, global_config)
        comparison = compare_against_tfo(global_run["results"], tfo_audit["results"])
        variants.append(
            {
                "variant": "global_persistent_assumptions",
                "phase_mode": phase_mode,
                "budget": int(config.global_budget),
                "seconds": global_run["seconds"],
                "outer_wall_seconds": global_run["outer_wall_seconds"],
                "result_seconds": global_run["result_seconds"],
                "setup_seconds_estimate": global_run["setup_seconds_estimate"],
                "counts": global_run["counts"],
                "comparison_to_tfo": comparison,
                "results": global_run["results"],
            }
        )

    report = {
        "schema": "pysat_assumption_reuse_experiment_v1",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "config": {
            "circuit": circuit_path,
            "limit": int(config.limit),
            "solver": config.solver,
            "frontier_order": config.frontier_order,
            "global_budget": int(config.global_budget),
            "audit_budget": int(config.audit_budget),
            "phase_modes": list(config.phase_modes),
            "checkpoint_dir": config.checkpoint_dir,
            "use_checkpoint": bool(config.use_checkpoint),
            "checkpoint_json": config.checkpoint_json,
            "strict": bool(config.strict),
        },
        "frontier": frontier,
        "tfo_audit": {
            "variant": "exact_tfo_audit",
            "budget": int(config.audit_budget),
            "seconds": tfo_audit["seconds"],
            "outer_wall_seconds": tfo_audit["outer_wall_seconds"],
            "result_seconds": tfo_audit["result_seconds"],
            "setup_seconds_estimate": tfo_audit["setup_seconds_estimate"],
            "counts": tfo_audit["counts"],
            "results": tfo_audit["results"],
        },
        "variants": variants,
    }
    report["strict_ok"] = all(
        variant["comparison_to_tfo"]["strict_ok"] for variant in variants
    )
    return report


def _detail_rows(report: Mapping[str, Any]) -> Iterable[Dict[str, Any]]:
    circuit = os.path.basename(str(report["config"]["circuit"]))
    tfo_by_key = indexed(report["tfo_audit"]["results"])
    for item in report["tfo_audit"]["results"]:
        yield {
            "circuit": circuit,
            "variant": "exact_tfo_audit",
            "phase_mode": "none",
            "candidate_ordinal": item.get("ordinal", ""),
            "gate": item.get("idx", ""),
            "sa": item.get("stuck_value", ""),
            "status": item.get("status", ""),
            "family": status_family(str(item.get("status", ""))),
            "seconds": item.get("seconds", ""),
            "clauses": item.get("clauses", ""),
            "worker_cache_hit": item.get("worker_cache_hit", ""),
            "model_phase_updated": item.get("model_phase_updated", ""),
            "tfo_status": item.get("status", ""),
            "tfo_family": status_family(str(item.get("status", ""))),
            "agreement": "self",
        }

    for variant in report["variants"]:
        comparison = variant["comparison_to_tfo"]
        mismatch_keys = {
            (int(item["gate"]), int(item["sa"])) for item in comparison["mismatches"]
        }
        unaudited_keys = {
            (int(item["gate"]), int(item["sa"])) for item in comparison["unaudited_unsat"]
        }
        for item in variant["results"]:
            key = candidate_key(item)
            tfo_item = tfo_by_key.get(key, {})
            global_family = status_family(str(item.get("status", "")))
            tfo_family = status_family(str(tfo_item.get("status", "")))
            if key in mismatch_keys:
                agreement = "mismatch"
            elif key in unaudited_keys:
                agreement = "unaudited_unsat"
            elif global_family in {"SAT", "UNSAT"} and global_family == tfo_family:
                agreement = "resolved_agree"
            else:
                agreement = "not_resolved"
            yield {
                "circuit": circuit,
                "variant": variant["variant"],
                "phase_mode": variant["phase_mode"],
                "candidate_ordinal": item.get("ordinal", ""),
                "gate": item.get("idx", ""),
                "sa": item.get("stuck_value", ""),
                "status": item.get("status", ""),
                "family": status_family(str(item.get("status", ""))),
                "seconds": item.get("seconds", ""),
                "clauses": item.get("clauses", ""),
                "worker_cache_hit": item.get("worker_cache_hit", ""),
                "model_phase_updated": item.get("model_phase_updated", ""),
                "tfo_status": tfo_item.get("status", ""),
                "tfo_family": tfo_family,
                "agreement": agreement,
            }


def write_report(report: Mapping[str, Any], output_dir: Path | str) -> Dict[str, str]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "summary.json"
    csv_path = output_dir / "candidate_details.csv"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DETAIL_FIELDS)
        writer.writeheader()
        writer.writerows(_detail_rows(report))
    return {"summary_json": str(json_path), "candidate_details_csv": str(csv_path)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("circuit", help="input AAG circuit")
    parser.add_argument("--limit", type=int, default=16, help="candidate sample limit")
    parser.add_argument("--solver", default="cadical153", help="PySAT solver name")
    parser.add_argument(
        "--frontier-order",
        default="current",
        help="Alg10 candidate ordering for the frozen frontier",
    )
    parser.add_argument(
        "--global-budget",
        type=int,
        default=1000,
        help="conflict budget per persistent global assumption query; 0 is unbounded",
    )
    parser.add_argument(
        "--audit-budget",
        type=int,
        default=0,
        help="exact TFO audit conflict budget; 0 is unbounded",
    )
    parser.add_argument(
        "--phase-modes",
        default="none",
        help="comma-separated PySAT phase modes to test",
    )
    parser.add_argument(
        "--checkpoint-dir",
        default="results_optimized/alg10_checkpoints_pysat_assumption_reuse",
        help="read-only Alg10 checkpoint directory setting",
    )
    parser.add_argument("--use-checkpoint", action="store_true", help="load Alg10 checkpoint if found")
    parser.add_argument("--checkpoint-json", default="", help="explicit checkpoint JSON to freeze")
    parser.add_argument(
        "--output-dir",
        default="",
        help="directory for summary.json and candidate_details.csv",
    )
    parser.add_argument(
        "--no-strict",
        action="store_true",
        help="do not fail process on mismatch or unaudited global UNSAT",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    phase_modes = parse_csv_words(args.phase_modes)
    config = ExperimentConfig(
        circuit=args.circuit,
        limit=max(0, int(args.limit)),
        solver=args.solver,
        frontier_order=args.frontier_order,
        global_budget=max(0, int(args.global_budget)),
        audit_budget=max(0, int(args.audit_budget)),
        phase_modes=phase_modes,
        checkpoint_dir=args.checkpoint_dir,
        use_checkpoint=bool(args.use_checkpoint),
        checkpoint_json=args.checkpoint_json,
        strict=not args.no_strict,
    )
    report = run_experiment(config)
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = DEFAULT_OUTPUT_ROOT / f"pysat_assumption_reuse_{stamp}"
    paths = write_report(report, output_dir)

    print(f"Circuit: {report['config']['circuit']}")
    print(f"Candidates: {report['frontier']['candidate_count_tested']}")
    print(
        "Exact TFO audit:",
        report["tfo_audit"]["counts"],
        f"{report['tfo_audit']['seconds']:.3f}s",
    )
    for variant in report["variants"]:
        comp = variant["comparison_to_tfo"]
        print(
            f"Global persistent ({variant['phase_mode']}):",
            variant["counts"],
            f"{variant['seconds']:.3f}s",
            "mismatches=",
            len(comp["mismatches"]),
            "unaudited_unsat=",
            len(comp["unaudited_unsat"]),
        )
    print(f"Wrote {paths['summary_json']}")
    print(f"Wrote {paths['candidate_details_csv']}")
    if config.strict and not report["strict_ok"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
