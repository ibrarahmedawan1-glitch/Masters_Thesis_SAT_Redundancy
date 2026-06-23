#!/usr/bin/env python3
"""Read-only probe for intra-circuit Alg10 SAT frontier sharding.

This script is deliberately diagnostic.  It freezes one circuit/work AAG,
splits candidate SAT checks across worker processes, and compares the result
against a serial run.  Workers never rewrite the AAG, never save checkpoints,
and never commit UNSAT candidates.  An UNSAT result here is only a proposal
that a future audited coordinator would need to recheck sequentially.

The default ``global`` engine shares one configurable full-circuit miter per
worker.  The ``tfo`` engine instead builds one exact, closure-audited TFO-slice
miter per candidate, which makes candidate checks independent and suitable for
parallel process sharding.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


Candidate = Tuple[int, int]
WorkItem = Tuple[int, int, int]

STATUS_SAT_REJECT = "SAT_REJECT"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_UNSAT_PROPOSED = "UNSAT_PROPOSED_ACCEPT"

DEFAULT_CHECKPOINT_DIR = "results_optimized/alg10_checkpoints_frontier_shard_probe"
DEFAULT_EXTRA_CHECKPOINT_DIRS = [
    "results_optimized/alg10_checkpoints_preflight_sin_untried_first_high_budget",
    "results_optimized/alg10_checkpoints_frontier_fixed_campaign",
    "results_optimized/alg10_checkpoints_best_protected_campaign",
    "results_optimized/alg10_checkpoints_best_unresolved_campaign",
    "results_optimized/alg10_checkpoints_global_strategy_div",
    "results_optimized/alg10_checkpoints_global_strategy_sqrt",
    "results_optimized/alg10_checkpoints_final_sat_strategy",
    "results_optimized/alg10_checkpoints_strict_audit",
    "results_optimized/alg10_checkpoints_resume_pool_presim",
]


@dataclass(frozen=True)
class Alg10Config:
    checkpoint_dir: str = DEFAULT_CHECKPOINT_DIR
    extra_checkpoint_dirs: Tuple[str, ...] = tuple(DEFAULT_EXTRA_CHECKPOINT_DIRS)
    checkpoint_select: str = "unresolved"
    frontier_order: str = "untried_first"
    solver: str = "cadical153"
    phase_mode: str = "none"
    engine: str = "global"
    worker_cache_entries: int = 0


def _validate_engine(engine: str) -> str:
    engine = str(engine).strip().lower()
    if engine not in {"global", "tfo"}:
        raise ValueError(f"unsupported frontier probe engine: {engine}")
    return engine


def _set_alg10_env(config: Alg10Config) -> None:
    os.environ["ALG10_CHECKPOINT_DIR"] = config.checkpoint_dir
    os.environ["ALG10_EXTRA_CHECKPOINT_DIRS"] = ",".join(config.extra_checkpoint_dirs)
    os.environ["ALG10_CHECKPOINT_SELECT"] = config.checkpoint_select
    os.environ["ALG10_RESET_CHECKPOINT"] = "0"
    os.environ["ALG10_PHASE_LOCAL_RESUME"] = "1"
    os.environ["ALG10_EXACT_FRONTIER_RESUME"] = "1"
    os.environ["ALG10_GLOBAL_FRONTIER_ORDER"] = config.frontier_order
    os.environ["ALG10_GLOBAL_SOLVER"] = config.solver
    os.environ["ALG10_GLOBAL_PHASE_MODE"] = config.phase_mode
    os.environ.setdefault("ALG10_AUDIT_ASSUMPTIONS", "1")


def _load_alg10(config: Alg10Config):
    """Import Alg10 after installing env-backed configuration."""
    _set_alg10_env(config)
    if "optimizer_alg10_tiered" in sys.modules:
        return importlib.reload(sys.modules["optimizer_alg10_tiered"])
    return importlib.import_module("optimizer_alg10_tiered")


def _load_alg10_worker(config: Alg10Config):
    """Load one immutable optimizer generation per worker configuration."""
    _set_alg10_env(config)
    signature = (
        config.frontier_order,
        config.solver,
        config.phase_mode,
        config.engine,
        config.worker_cache_entries,
    )
    module = sys.modules.get("optimizer_alg10_tiered")
    if module is None:
        module = importlib.import_module("optimizer_alg10_tiered")
    elif getattr(module, "_ALG10_WORKER_SIGNATURE", None) != signature:
        module = importlib.reload(module)
    module._ALG10_WORKER_SIGNATURE = signature
    return module


_WORKER_CIRCUIT_CACHE: "OrderedDict[Tuple[Any, ...], Dict[str, Any]]" = OrderedDict()


def clear_worker_circuit_cache() -> None:
    _WORKER_CIRCUIT_CACHE.clear()


def _worker_cache_key(work_path: str) -> Tuple[Any, ...]:
    stat = os.stat(work_path)
    return (
        os.path.abspath(work_path),
        int(stat.st_dev),
        int(stat.st_ino),
        int(stat.st_size),
        int(stat.st_mtime_ns),
    )


def _load_worker_circuit(opt, work_path: str, config: Alg10Config) -> Tuple[Dict[str, Any], bool]:
    cache_entries = max(0, int(getattr(config, "worker_cache_entries", 0) or 0))
    if cache_entries <= 0:
        parsed = opt.parse_aag(work_path)
        _, _, _, _, _, inputs, latches, outputs, gates_raw, _ = parsed
        sweep_roots = _sweep_roots(opt, latches, outputs)
        by_lhs, fanout = opt._fanout_graph(gates_raw)
        return {
            "parsed": parsed,
            "inputs": inputs,
            "latches": latches,
            "outputs": outputs,
            "gates_raw": gates_raw,
            "sweep_roots": sweep_roots,
            "by_lhs": by_lhs,
            "fanout": fanout,
        }, False

    key = _worker_cache_key(work_path)
    cached = _WORKER_CIRCUIT_CACHE.get(key)
    if cached is not None:
        _WORKER_CIRCUIT_CACHE.move_to_end(key)
        return cached, True

    parsed = opt.parse_aag(work_path)
    _, _, _, _, _, inputs, latches, outputs, gates_raw, _ = parsed
    sweep_roots = _sweep_roots(opt, latches, outputs)
    by_lhs, fanout = opt._fanout_graph(gates_raw)
    cached = {
        "parsed": parsed,
        "inputs": inputs,
        "latches": latches,
        "outputs": outputs,
        "gates_raw": gates_raw,
        "sweep_roots": sweep_roots,
        "by_lhs": by_lhs,
        "fanout": fanout,
    }
    _WORKER_CIRCUIT_CACHE[key] = cached
    while len(_WORKER_CIRCUIT_CACHE) > cache_entries:
        _WORKER_CIRCUIT_CACHE.popitem(last=False)
    return cached, False


def _as_abs(path: str) -> str:
    return path if os.path.isabs(path) else os.path.abspath(path)


def _checkpoint_work_path(data: Dict[str, Any]) -> Optional[str]:
    path = data.get("_checkpoint_work_path") or data.get("work_aag")
    if not path:
        json_path = data.get("_checkpoint_json_path")
        if json_path:
            path = os.path.splitext(json_path)[0] + ".work.aag"
    if not path:
        return None
    return _as_abs(str(path))


def _sweep_roots(opt, latches, outputs):
    roots = list(outputs)
    roots.extend(opt._parse_latch(latch)[1] for latch in latches)
    return roots


def _merge_tier_frontier(frontier: Dict[str, Any]) -> Tuple[List[Candidate], Dict[Candidate, int]]:
    pending = list(frontier.get("pending", []))
    escalated = list(frontier.get("escalated", []))
    merged: List[Candidate] = []
    seen = set()
    for idx, stuck_value in pending + escalated:
        cand = (int(idx), int(stuck_value))
        if cand not in seen:
            seen.add(cand)
            merged.append(cand)
    return merged, {}


def _ordered_candidates(
    opt,
    candidates: Sequence[Candidate],
    gates_raw: Sequence[Sequence[int]],
    max_budget_tried: Dict[Candidate, int],
    roots=None,
) -> List[Candidate]:
    if hasattr(opt, "_order_global_frontier"):
        return list(
            opt._order_global_frontier(
                candidates,
                gates_raw,
                max_budget_tried,
                roots=roots,
            )
        )
    return list(candidates)


def load_frontier(
    circuit_path: str,
    config: Alg10Config,
    limit: int = 0,
    use_checkpoint: bool = True,
    skip_already_tried: bool = False,
    budget: int = 0,
    checkpoint_json: str = "",
) -> Dict[str, Any]:
    """Load a frozen work AAG and candidate frontier without writing anything."""
    opt = _load_alg10(config)
    circuit_path = _as_abs(circuit_path)
    checkpoint = None
    explicit_checkpoint = bool(checkpoint_json)
    if use_checkpoint and checkpoint_json:
        with open(checkpoint_json, "r", encoding="utf-8") as f:
            checkpoint = json.load(f)
        checkpoint["_checkpoint_json_path"] = _as_abs(checkpoint_json)
        checkpoint["_checkpoint_source_dir"] = os.path.dirname(_as_abs(checkpoint_json))
    elif use_checkpoint:
        checkpoint = opt._load_checkpoint(circuit_path)

    checkpoint_json = ""
    checkpoint_source_dir = ""
    phase_tier = ""
    phase_valid = False
    history_engine = "global"
    max_budget_tried: Dict[Candidate, int] = {}

    if checkpoint:
        work_path = _checkpoint_work_path(checkpoint)
        if not work_path or not os.path.exists(work_path):
            checkpoint = None

    if checkpoint:
        work_path = _checkpoint_work_path(checkpoint)
        checkpoint_json = str(checkpoint.get("_checkpoint_json_path", ""))
        checkpoint_source_dir = str(checkpoint.get("_checkpoint_source_dir", ""))
        parsed = opt.parse_aag(work_path)
        _, _, _, _, _, inputs, latches, outputs, gates_raw, _ = parsed
        sweep_roots = _sweep_roots(opt, latches, outputs)
        phase = opt._valid_phase_resume_state(
            checkpoint.get("phase_resume"), work_path, len(gates_raw)
        )
        if phase and phase.get("tier") == "global":
            phase_valid = True
            phase_tier = "global"
            candidates = list(phase.get("candidates", []))
            max_budget_tried = dict(phase.get("max_budget_tried", {}))
            raw_phase = checkpoint.get("phase_resume") or {}
            history_engine = str(raw_phase.get("history_engine", "global"))
            if _validate_engine(config.engine) != history_engine:
                max_budget_tried = {}
            frontier_source = (
                "checkpoint_global_frontier_direct"
                if explicit_checkpoint
                else "checkpoint_global_frontier"
            )
        elif phase and phase.get("tier") in {"tfi", "window", "cone"}:
            phase_valid = True
            phase_tier = str(phase.get("tier", ""))
            candidates, max_budget_tried = _merge_tier_frontier(phase)
            frontier_source = (
                "checkpoint_tier_frontier_direct"
                if explicit_checkpoint
                else "checkpoint_tier_frontier"
            )
        else:
            candidates = opt._candidate_order(gates_raw, roots=sweep_roots)
            frontier_source = (
                "checkpoint_work_all_candidates_direct"
                if explicit_checkpoint
                else "checkpoint_work_all_candidates"
            )
        work_path = str(work_path)
    else:
        work_path = circuit_path
        parsed = opt.parse_aag(work_path)
        _, _, _, _, _, inputs, latches, outputs, gates_raw, _ = parsed
        sweep_roots = _sweep_roots(opt, latches, outputs)
        candidates = opt._candidate_order(gates_raw, roots=sweep_roots)
        frontier_source = "fresh_all_candidates"

    candidates = _ordered_candidates(
        opt,
        candidates,
        gates_raw,
        max_budget_tried,
        roots=sweep_roots,
    )
    available_before_budget = len(candidates)
    skipped_by_budget = 0
    if skip_already_tried and budget > 0:
        kept = []
        for cand in candidates:
            if budget <= max_budget_tried.get(cand, 0):
                skipped_by_budget += 1
            else:
                kept.append(cand)
        candidates = kept

    if limit and limit > 0:
        candidates = candidates[:limit]

    work_items: List[WorkItem] = [
        (ordinal, int(idx), int(stuck_value))
        for ordinal, (idx, stuck_value) in enumerate(candidates)
    ]
    return {
        "circuit_path": circuit_path,
        "work_path": work_path,
        "checkpoint_json": checkpoint_json,
        "checkpoint_source_dir": checkpoint_source_dir,
        "frontier_source": frontier_source,
        "phase_valid": phase_valid,
        "phase_tier": phase_tier,
        "history_engine": history_engine,
        "candidate_count_available": available_before_budget,
        "candidate_count_after_budget": len(candidates) + skipped_by_budget,
        "candidate_count_tested": len(candidates),
        "skipped_by_budget": skipped_by_budget,
        "work_items": work_items,
    }


def split_shards(items: Sequence[WorkItem], jobs: int) -> List[List[WorkItem]]:
    """Round-robin split for better load balance on uneven SAT instances."""
    jobs = max(1, int(jobs))
    shards: List[List[WorkItem]] = [[] for _ in range(jobs)]
    for pos, item in enumerate(items):
        shards[pos % jobs].append(item)
    return [shard for shard in shards if shard]


def _solver_conflicts(solver) -> int:
    try:
        return int(solver.accum_stats().get("conflicts", 0))
    except Exception:
        return 0


def _budget_targets(primary_budget: int, ladder: Sequence[int]) -> Tuple[int, ...]:
    targets = [int(value) for value in ladder if int(value) > 0]
    if not targets and int(primary_budget) > 0:
        targets = [int(primary_budget)]
    if not targets:
        return (0,)
    result: List[int] = []
    for target in targets:
        if not result or target > result[-1]:
            result.append(target)
    return tuple(result)


def _solve_tfo_ladder(opt, solver, miter_lit: int, targets: Sequence[int]) -> Tuple[Optional[bool], int, List[Dict[str, Any]]]:
    attempts: List[Dict[str, Any]] = []
    conflict_base = _solver_conflicts(solver)
    for target in targets:
        target = int(target)
        if target <= 0:
            started = time.perf_counter()
            raw = solver.solve(assumptions=[miter_lit])
            attempts.append(
                {
                    "target": 0,
                    "granted": 0,
                    "status": "SAT" if raw else "UNSAT",
                    "seconds": time.perf_counter() - started,
                    "conflicts": max(0, _solver_conflicts(solver) - conflict_base),
                }
            )
            return raw, 0, attempts
        consumed = max(0, _solver_conflicts(solver) - conflict_base)
        granted = max(0, target - consumed)
        started = time.perf_counter()
        result = opt._solve_limited_with_budget(solver, [miter_lit], granted)
        elapsed = time.perf_counter() - started
        consumed_after = max(0, _solver_conflicts(solver) - conflict_base)
        if result is True:
            status = "SAT"
        elif result is False:
            status = "UNSAT"
        else:
            status = "TIMEOUT"
        attempts.append(
            {
                "target": target,
                "granted": granted,
                "status": status,
                "seconds": elapsed,
                "conflicts": consumed_after,
            }
        )
        if result is not None:
            return result, target, attempts
    return None, int(targets[-1]) if targets else 0, attempts


def _solve_items(
    work_path: str,
    items: Sequence[WorkItem],
    budget: int,
    config: Alg10Config,
    audit_assumptions: bool,
    worker_id: int,
    budget_ladder: Sequence[int] = (),
) -> List[Dict[str, Any]]:
    opt = _load_alg10_worker(config)
    circuit, cache_hit = _load_worker_circuit(opt, work_path, config)
    inputs = circuit["inputs"]
    latches = circuit["latches"]
    gates_raw = circuit["gates_raw"]
    sweep_roots = circuit["sweep_roots"]
    engine = _validate_engine(config.engine)
    targets = _budget_targets(budget, budget_ladder)
    if engine == "tfo":
        by_lhs = circuit["by_lhs"]
        fanout = circuit["fanout"]
        results: List[Dict[str, Any]] = []
        for ordinal, idx, stuck_value in items:
            started = time.perf_counter()
            affected = opt._affected_roots_from_graph(
                by_lhs,
                fanout,
                sweep_roots,
                idx,
            )
            if not affected:
                results.append(
                    {
                        "ordinal": int(ordinal),
                        "idx": int(idx),
                        "stuck_value": int(stuck_value),
                        "status": STATUS_UNSAT_PROPOSED,
                        "seconds": time.perf_counter() - started,
                        "worker": int(worker_id),
                        "engine": engine,
                        "affected_roots": 0,
                        "good_cone_gates": 0,
                        "faulty_tfo_gates": 0,
                        "clauses": 0,
                        "structurally_unobservable": True,
                        "model_phase_updated": False,
                        "worker_cache_hit": bool(cache_hit),
                    }
                )
                continue

            good_cone = opt._fanin_indices_for_roots(
                gates_raw,
                affected,
                by_lhs=by_lhs,
            )
            tfo_slice = opt._observable_tfo_slice(
                fanout,
                idx,
                good_cone,
            )
            opt._audit_tfo_slice(
                by_lhs,
                fanout,
                affected,
                idx,
                good_cone,
                tfo_slice,
                gates_raw,
            )
            clauses, miter_lit, _shared = opt._build_single_fault_tfo_miter(
                inputs,
                latches,
                affected,
                gates_raw,
                idx,
                stuck_value,
                good_cone,
                tfo_slice,
            )
            with opt.Solver(name=config.solver, bootstrap_with=clauses) as solver:
                sat_result, budget_tried, attempts = _solve_tfo_ladder(
                    opt,
                    solver,
                    miter_lit,
                    targets,
                )
            if sat_result is True:
                status = STATUS_SAT_REJECT
            elif sat_result is False:
                status = STATUS_UNSAT_PROPOSED
            else:
                status = STATUS_TIMEOUT
            results.append(
                {
                    "ordinal": int(ordinal),
                    "idx": int(idx),
                    "stuck_value": int(stuck_value),
                    "status": status,
                    "seconds": time.perf_counter() - started,
                    "worker": int(worker_id),
                    "engine": engine,
                    "affected_roots": len(affected),
                    "good_cone_gates": len(good_cone),
                    "faulty_tfo_gates": len(tfo_slice),
                    "clauses": len(clauses),
                    "structurally_unobservable": False,
                    "model_phase_updated": False,
                    "worker_cache_hit": bool(cache_hit),
                    "budget_tried": int(budget_tried),
                    "budget_attempts": attempts,
                }
            )
        return results

    clauses, miter_lit, f0_lits, f1_lits = opt._build_fault_sweep_cnf(
        inputs, latches, sweep_roots, gates_raw
    )

    gate_count = len(gates_raw)
    control_state = [-lit for lit in f0_lits] + [-lit for lit in f1_lits]
    results: List[Dict[str, Any]] = []
    with opt.Solver(name=config.solver, bootstrap_with=clauses) as solver:
        opt._apply_global_initial_phases(solver, f0_lits, f1_lits)
        last_phase_model = None
        for ordinal, idx, stuck_value in items:
            pos, lit, opposite_pos, opposite_lit = opt._control_position(
                gate_count, idx, stuck_value, f0_lits, f1_lits
            )
            assumptions = control_state.copy()
            assumptions[pos] = lit
            assumptions[opposite_pos] = -opposite_lit
            assumptions.append(miter_lit)
            if audit_assumptions:
                opt._audit_global_assumptions(
                    assumptions,
                    gate_count,
                    f0_lits=f0_lits,
                    f1_lits=f1_lits,
                    candidate=(idx, stuck_value),
                    accepted={},
                    miter_lit=miter_lit,
                )

            opt._apply_global_model_phases(solver, last_phase_model)
            started = time.time()
            if budget > 0:
                solver.conf_budget(int(budget))
                sat_result = solver.solve_limited(assumptions=assumptions)
            else:
                sat_result = solver.solve(assumptions=assumptions)
            elapsed = time.time() - started

            model_used = False
            if sat_result is True:
                status = STATUS_SAT_REJECT
                if config.phase_mode in {"model", "controls_false_model"}:
                    last_phase_model = solver.get_model()
                    model_used = bool(last_phase_model)
            elif sat_result is False:
                status = STATUS_UNSAT_PROPOSED
            else:
                status = STATUS_TIMEOUT

            results.append(
                {
                    "ordinal": int(ordinal),
                    "idx": int(idx),
                    "stuck_value": int(stuck_value),
                    "status": status,
                    "seconds": elapsed,
                    "worker": int(worker_id),
                    "engine": engine,
                    "clauses": len(clauses),
                    "model_phase_updated": model_used,
                    "worker_cache_hit": bool(cache_hit),
                }
            )
    return results


def run_serial(
    work_path: str,
    items: Sequence[WorkItem],
    budget: int,
    config: Alg10Config,
    audit_assumptions: bool = True,
) -> Dict[str, Any]:
    started = time.time()
    results = _solve_items(work_path, items, budget, config, audit_assumptions, worker_id=0)
    results.sort(key=lambda item: item["ordinal"])
    return {"seconds": time.time() - started, "results": results}


def run_parallel(
    work_path: str,
    items: Sequence[WorkItem],
    budget: int,
    config: Alg10Config,
    jobs: int,
    audit_assumptions: bool = True,
) -> Dict[str, Any]:
    started = time.time()
    shards = split_shards(items, jobs)
    results: List[Dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=max(1, int(jobs))) as pool:
        futures = [
            pool.submit(
                _solve_items,
                work_path,
                shard,
                budget,
                config,
                audit_assumptions,
                worker_id + 1,
            )
            for worker_id, shard in enumerate(shards)
        ]
        for future in as_completed(futures):
            results.extend(future.result())
    results.sort(key=lambda item: item["ordinal"])
    return {"seconds": time.time() - started, "results": results, "shards": len(shards)}


def status_counts(results: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts = {STATUS_SAT_REJECT: 0, STATUS_TIMEOUT: 0, STATUS_UNSAT_PROPOSED: 0}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return counts


def compare_results(
    serial_results: Sequence[Dict[str, Any]],
    parallel_results: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    mismatches = []
    serial_by_key = {
        (item["idx"], item["stuck_value"]): item["status"] for item in serial_results
    }
    parallel_by_key = {
        (item["idx"], item["stuck_value"]): item["status"] for item in parallel_results
    }
    for key in sorted(set(serial_by_key) | set(parallel_by_key)):
        if serial_by_key.get(key) != parallel_by_key.get(key):
            mismatches.append(
                {
                    "idx": key[0],
                    "stuck_value": key[1],
                    "serial": serial_by_key.get(key),
                    "parallel": parallel_by_key.get(key),
                }
            )
    return {"match": not mismatches, "mismatches": mismatches}


def _write_json_atomic(path: str, data: Dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def _extra_dirs_from_args(values: Sequence[str]) -> Tuple[str, ...]:
    if not values:
        return tuple(DEFAULT_EXTRA_CHECKPOINT_DIRS)
    parts: List[str] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part:
                parts.append(part)
    return tuple(parts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only serial/parallel probe for one Alg10 SAT frontier."
    )
    parser.add_argument("circuit", help="Source .aag/.aig path used for checkpoint lookup")
    parser.add_argument("--limit", type=int, default=16, help="candidate checks to probe")
    parser.add_argument("--jobs", type=int, default=2, help="parallel worker processes")
    parser.add_argument("--budget", type=int, default=1000, help="SAT conflict budget")
    parser.add_argument("--solver", default="cadical153", help="PySAT solver name")
    parser.add_argument(
        "--engine",
        default="global",
        choices=["global", "tfo"],
        help="worker SAT encoding: shared full global miter or exact TFO slice",
    )
    parser.add_argument(
        "--phase-mode",
        default="none",
        choices=["none", "controls_false", "model", "controls_false_model"],
        help="initial/model phase mode for the probe",
    )
    parser.add_argument(
        "--order",
        default="untried_first",
        help="Alg10 global frontier order to apply before sharding",
    )
    parser.add_argument(
        "--checkpoint-dir",
        default=DEFAULT_CHECKPOINT_DIR,
        help="active checkpoint dir for lookup; the probe does not write there",
    )
    parser.add_argument(
        "--extra-checkpoint-dir",
        action="append",
        default=[],
        help="extra checkpoint dir(s), repeatable or comma-separated",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="ignore checkpoints and probe the source circuit directly",
    )
    parser.add_argument(
        "--checkpoint-json",
        default="",
        help="explicit checkpoint JSON to probe; validates its work frontier hash",
    )
    parser.add_argument(
        "--skip-already-tried",
        action="store_true",
        help="skip candidates whose checkpoint max tried budget is already >= --budget",
    )
    parser.add_argument(
        "--no-audit",
        action="store_true",
        help="disable assumption shape audit inside the probe",
    )
    parser.add_argument(
        "--parallel-only",
        action="store_true",
        help="skip serial comparison and run only the parallel shard probe",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="only load and print the selected frontier; do not solve SAT",
    )
    parser.add_argument("--json-out", default="", help="optional JSON report path")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config = Alg10Config(
        checkpoint_dir=args.checkpoint_dir,
        extra_checkpoint_dirs=_extra_dirs_from_args(args.extra_checkpoint_dir),
        checkpoint_select="unresolved",
        frontier_order=args.order,
        solver=args.solver,
        phase_mode=args.phase_mode,
        engine=args.engine,
    )
    frontier = load_frontier(
        args.circuit,
        config,
        limit=args.limit,
        use_checkpoint=not args.fresh,
        skip_already_tried=args.skip_already_tried,
        budget=args.budget,
        checkpoint_json=args.checkpoint_json,
    )
    items = frontier["work_items"]
    report: Dict[str, Any] = {
        "config": {
            "budget": args.budget,
            "jobs": args.jobs,
            "solver": args.solver,
            "engine": args.engine,
            "phase_mode": args.phase_mode,
            "frontier_order": args.order,
            "audit_assumptions": not args.no_audit,
            "parallel_only": args.parallel_only,
        },
        "frontier": {key: value for key, value in frontier.items() if key != "work_items"},
    }

    print(
        "Frontier:",
        frontier["frontier_source"],
        "phase=" + (frontier["phase_tier"] or "none"),
        f"available={frontier['candidate_count_available']}",
        f"tested={frontier['candidate_count_tested']}",
        f"work={frontier['work_path']}",
    )
    if frontier["checkpoint_json"]:
        print(f"Checkpoint: {frontier['checkpoint_json']}")

    if args.dry_run:
        if args.json_out:
            _write_json_atomic(args.json_out, report)
        return 0
    if not items:
        print("No candidates selected for the probe.")
        if args.json_out:
            _write_json_atomic(args.json_out, report)
        return 0

    audit = not args.no_audit
    serial = None
    if not args.parallel_only:
        serial = run_serial(frontier["work_path"], items, args.budget, config, audit)
        report["serial"] = {
            "seconds": serial["seconds"],
            "counts": status_counts(serial["results"]),
            "results": serial["results"],
        }
        print(
            "Serial:",
            f"{serial['seconds']:.3f}s",
            status_counts(serial["results"]),
        )

    parallel = run_parallel(frontier["work_path"], items, args.budget, config, args.jobs, audit)
    report["parallel"] = {
        "seconds": parallel["seconds"],
        "counts": status_counts(parallel["results"]),
        "shards": parallel["shards"],
        "results": parallel["results"],
    }
    print(
        "Parallel:",
        f"{parallel['seconds']:.3f}s",
        status_counts(parallel["results"]),
        f"shards={parallel['shards']}",
    )

    if serial is not None:
        comparison = compare_results(serial["results"], parallel["results"])
        report["comparison"] = comparison
        speedup = serial["seconds"] / parallel["seconds"] if parallel["seconds"] > 0 else 0.0
        report["speedup"] = speedup
        print(f"Match: {comparison['match']}  speedup={speedup:.2f}x")
        if comparison["mismatches"]:
            print("Mismatches:", comparison["mismatches"][:5])
    else:
        report["parallel_results"] = parallel["results"]

    if args.json_out:
        _write_json_atomic(args.json_out, report)

    if serial is not None and not report["comparison"]["match"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
