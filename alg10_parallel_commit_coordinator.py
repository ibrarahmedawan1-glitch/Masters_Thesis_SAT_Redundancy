#!/usr/bin/env python3
"""Transactional parallel frontier coordinator for Algorithm 10.

Worker processes classify candidates on one immutable AAG generation. Only the
coordinator may mutate the circuit. At the generation barrier it serially
rechecks proposed UNSAT candidates in one cumulative solver context, rebuilds
the AAG, requires full CEC PASS, checkpoints the accepted generation, and then
refreshes the frontier because gate indices may have changed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import alg10_frontier_shard_probe as probe
from abc_utils import run_abc_cec


Candidate = Tuple[int, int]


@dataclass(frozen=True)
class CoordinatorConfig:
    checkpoint_dir: str
    extra_checkpoint_dirs: Tuple[str, ...] = ()
    jobs: int = 3
    budgets: Tuple[int, ...] = (1000, 5000, 20000)
    batch_size: int = 16
    max_seconds: float = 3600.0
    max_generations: int = 100
    solver: str = "cadical153"
    phase_mode: str = "none"
    frontier_order: str = "untried_first"
    recheck_budget: int = 0
    checkpoint_json: str = ""
    audit_assumptions: bool = True
    cec_timeout: float = 60.0


def _parse_budgets(raw: str) -> Tuple[int, ...]:
    values = tuple(int(part.strip()) for part in raw.split(",") if part.strip())
    if not values or any(value <= 0 for value in values):
        raise ValueError("budgets must contain at least one positive integer")
    return values


def _write_json_atomic(path: str, data: Dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def _append_jsonl(path: str, data: Dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, sort_keys=True) + "\n")


def _alg10_config(config: CoordinatorConfig) -> probe.Alg10Config:
    os.environ["ALG10_BUDGETS"] = ",".join(str(value) for value in config.budgets)
    return probe.Alg10Config(
        checkpoint_dir=config.checkpoint_dir,
        extra_checkpoint_dirs=config.extra_checkpoint_dirs,
        checkpoint_select="unresolved",
        frontier_order=config.frontier_order,
        solver=config.solver,
        phase_mode=config.phase_mode,
    )


def _load_checkpoint_data(
    source_path: str,
    opt,
    explicit_json: str,
) -> Optional[Dict[str, Any]]:
    if explicit_json:
        with open(explicit_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["_checkpoint_json_path"] = os.path.abspath(explicit_json)
        work_path = data.get("work_aag") or os.path.splitext(explicit_json)[0] + ".work.aag"
        data["_checkpoint_work_path"] = os.path.abspath(work_path)
    else:
        data = opt._load_checkpoint(source_path)
    if not data:
        return None
    if data.get("source_sha256") != opt._sha256_file(source_path):
        raise ValueError("checkpoint source hash does not match the requested circuit")
    work_path = data.get("_checkpoint_work_path") or data.get("work_aag")
    if not work_path or not os.path.exists(work_path):
        raise ValueError("checkpoint work AAG is missing")
    return data


def _frontier_from_state(opt, work_path: str, phase_state) -> Tuple[List[Candidate], Dict[Candidate, int]]:
    _, _, _, _, _, _, latches, outputs, gates_raw, _ = opt.parse_aag(work_path)
    valid = opt._valid_phase_resume_state(phase_state, work_path, len(gates_raw))
    if valid and valid.get("tier") == "global":
        candidates = list(valid.get("candidates", []))
        history = dict(valid.get("max_budget_tried", {}))
    elif valid and valid.get("tier") in {"tfi", "window", "cone"}:
        candidates = list(valid.get("pending", [])) + list(valid.get("escalated", []))
        history = {}
    else:
        roots = probe._sweep_roots(opt, latches, outputs)
        candidates = opt._candidate_order(gates_raw, roots=roots)
        history = {}
    candidates = list(opt._order_global_frontier(candidates, gates_raw, history))
    return candidates, history


def _phase_state(
    opt,
    work_path: str,
    candidates: Sequence[Candidate],
    history: Dict[Candidate, int],
    reason: str,
):
    state = {
        "schema": "alg10_global_frontier_v1",
        "tier": "global",
        "reason": reason,
        "candidate_order": opt.CANDIDATE_ORDER,
        "sat_budgets": list(opt.SAT_BUDGETS),
        "candidates": opt._candidate_budget_list_for_resume(candidates, history),
    }
    state["work_sha256"] = opt._sha256_file(work_path)
    state["gate_count"] = opt.parse_aag(work_path)[4]
    return state


def _serial_recheck(
    work_path: str,
    proposals: Sequence[Dict[str, Any]],
    config: CoordinatorConfig,
) -> Dict[str, Any]:
    alg_config = _alg10_config(config)
    opt = probe._load_alg10(alg_config)
    _, _, _, _, _, inputs, latches, outputs, gates_raw, _ = opt.parse_aag(work_path)
    roots = probe._sweep_roots(opt, latches, outputs)
    clauses, miter_lit, f0_lits, f1_lits = opt._build_fault_sweep_cnf(
        inputs, latches, roots, gates_raw
    )
    gate_count = len(gates_raw)
    control_state = [-lit for lit in f0_lits] + [-lit for lit in f1_lits]
    accepted: Dict[int, int] = {}
    results: List[Dict[str, Any]] = []

    with opt.Solver(name=config.solver, bootstrap_with=clauses) as solver:
        opt._apply_global_initial_phases(solver, f0_lits, f1_lits)
        for proposal in sorted(proposals, key=lambda item: item["ordinal"]):
            idx = int(proposal["idx"])
            stuck_value = int(proposal["stuck_value"])
            started = time.time()
            if idx in accepted:
                status = "STALE_SAME_GATE"
            else:
                pos, lit, opposite_pos, opposite_lit = opt._control_position(
                    gate_count, idx, stuck_value, f0_lits, f1_lits
                )
                assumptions = control_state.copy()
                assumptions[pos] = lit
                assumptions[opposite_pos] = -opposite_lit
                assumptions.append(miter_lit)
                if config.audit_assumptions:
                    opt._audit_global_assumptions(
                        assumptions,
                        gate_count,
                        f0_lits=f0_lits,
                        f1_lits=f1_lits,
                        candidate=(idx, stuck_value),
                        accepted=accepted,
                        miter_lit=miter_lit,
                    )
                if config.recheck_budget > 0:
                    solver.conf_budget(config.recheck_budget)
                    sat_result = solver.solve_limited(assumptions=assumptions)
                else:
                    sat_result = solver.solve(assumptions=assumptions)
                if sat_result is False:
                    status = "UNSAT_ACCEPT"
                    accepted[idx] = stuck_value
                    control_state[pos] = lit
                    control_state[opposite_pos] = -opposite_lit
                    solver.add_clause([lit])
                    solver.add_clause([-opposite_lit])
                elif sat_result is True:
                    status = "SAT_REJECT"
                else:
                    status = "TIMEOUT"
            results.append(
                {
                    "ordinal": int(proposal["ordinal"]),
                    "idx": idx,
                    "stuck_value": stuck_value,
                    "status": status,
                    "seconds": time.time() - started,
                }
            )
    return {"accepted": accepted, "results": results}


def _cec_transaction(
    source_path: str,
    current_work: str,
    accepted: Dict[int, int],
    opt,
    cec_timeout: float,
) -> Dict[str, Any]:
    parsed_header, symbols, gates_raw = opt._parse_current(current_work)
    working_gates = opt._apply_accepts(gates_raw, accepted)
    candidate_path = current_work + ".candidate"
    final_gates = opt._write_strashed(
        candidate_path,
        parsed_header,
        working_gates,
        symbols,
        "Alg10 Parallel Coordinator Commit",
    )
    verify, verify_time, _ = run_abc_cec(
        source_path,
        candidate_path,
        timeout=cec_timeout,
    )
    if verify != "PASS":
        try:
            os.remove(candidate_path)
        except OSError:
            pass
        return {"committed": False, "verify": verify, "verify_time": verify_time}
    os.replace(candidate_path, current_work)
    return {
        "committed": True,
        "verify": verify,
        "verify_time": verify_time,
        "final_gates": final_gates,
    }


def run_coordinator(
    source_path: str,
    output_path: str,
    config: CoordinatorConfig,
    report_path: str = "",
    jsonl_path: str = "",
) -> Dict[str, Any]:
    source_path = os.path.abspath(source_path)
    output_path = os.path.abspath(output_path)
    os.makedirs(config.checkpoint_dir, exist_ok=True)
    output_parent = os.path.dirname(output_path)
    if output_parent:
        os.makedirs(output_parent, exist_ok=True)

    alg_config = _alg10_config(config)
    opt = probe._load_alg10(alg_config)
    checkpoint = _load_checkpoint_data(source_path, opt, config.checkpoint_json)
    started = time.time()
    deadline = started + config.max_seconds if config.max_seconds > 0 else None
    report_path = report_path or output_path + ".parallel_coordinator.json"
    jsonl_path = jsonl_path or output_path + ".parallel_coordinator.jsonl"

    with tempfile.TemporaryDirectory(prefix="alg10_parallel_commit_") as tmp:
        current_work = os.path.join(tmp, "current.aag")
        if checkpoint:
            shutil.copyfile(
                checkpoint.get("_checkpoint_work_path") or checkpoint["work_aag"],
                current_work,
            )
            phase_state = checkpoint.get("phase_resume")
            telemetry = dict(checkpoint.get("telemetry", {}))
        else:
            shutil.copyfile(source_path, current_work)
            phase_state = None
            telemetry = {}

        initial_gates = opt.parse_aag(source_path)[4]
        records: List[Dict[str, Any]] = []
        totals = {
            "worker_sat_reject": 0,
            "worker_timeout": 0,
            "worker_unsat_proposed": 0,
            "coordinator_sat_reject": 0,
            "coordinator_timeout": 0,
            "coordinator_unsat_accept": 0,
            "cec_pass_commits": 0,
            "cec_failed_commits": 0,
        }
        status = "RUNNING"

        for generation in range(1, max(1, config.max_generations) + 1):
            if deadline is not None and time.time() >= deadline:
                status = "TIME_BUDGET_CHECKPOINT"
                break

            snapshot_hash = opt._sha256_file(current_work)
            candidates, history = _frontier_from_state(opt, current_work, phase_state)
            phase_state = None
            selected_budget = 0
            eligible: List[Candidate] = []
            for budget in config.budgets:
                eligible = [
                    candidate
                    for candidate in candidates
                    if budget > history.get(candidate, 0)
                ]
                if eligible:
                    selected_budget = budget
                    break
            if not eligible:
                status = "UNRESOLVED_BUDGETS_EXHAUSTED" if candidates else "COMPLETE"
                telemetry["unresolved"] = len(candidates)
                phase_state = (
                    _phase_state(opt, current_work, candidates, history, status)
                    if candidates
                    else None
                )
                break

            batch = eligible[: max(1, config.batch_size)]
            work_items = [
                (ordinal, idx, stuck_value)
                for ordinal, (idx, stuck_value) in enumerate(batch)
            ]
            wave_started = time.time()
            parallel = probe.run_parallel(
                current_work,
                work_items,
                selected_budget,
                alg_config,
                config.jobs,
                audit_assumptions=config.audit_assumptions,
            )
            if opt._sha256_file(current_work) != snapshot_hash:
                raise RuntimeError("coordinator work AAG changed during a worker generation")

            worker_counts = probe.status_counts(parallel["results"])
            totals["worker_sat_reject"] += worker_counts.get(probe.STATUS_SAT_REJECT, 0)
            totals["worker_timeout"] += worker_counts.get(probe.STATUS_TIMEOUT, 0)
            totals["worker_unsat_proposed"] += worker_counts.get(probe.STATUS_UNSAT_PROPOSED, 0)
            proposals = [
                item
                for item in parallel["results"]
                if item["status"] == probe.STATUS_UNSAT_PROPOSED
            ]
            recheck = _serial_recheck(current_work, proposals, config)
            for item in recheck["results"]:
                if item["status"] == "UNSAT_ACCEPT":
                    totals["coordinator_unsat_accept"] += 1
                elif item["status"] == "SAT_REJECT":
                    totals["coordinator_sat_reject"] += 1
                elif item["status"] == "TIMEOUT":
                    totals["coordinator_timeout"] += 1

            transaction = {"committed": False, "verify": "NOT_RUN", "verify_time": 0.0}
            accepted = recheck["accepted"]
            cec_failed = False
            if accepted:
                transaction = _cec_transaction(
                    source_path,
                    current_work,
                    accepted,
                    opt,
                    config.cec_timeout,
                )
                if transaction["committed"]:
                    totals["cec_pass_commits"] += 1
                    candidates = []
                    history = {}
                    phase_state = None
                else:
                    totals["cec_failed_commits"] += 1
                    accepted = {}
                    cec_failed = True

            if not accepted:
                rejected = {
                    (int(item["idx"]), int(item["stuck_value"]))
                    for item in parallel["results"]
                    if item["status"] == probe.STATUS_SAT_REJECT
                }
                rejected.update(
                    (int(item["idx"]), int(item["stuck_value"]))
                    for item in recheck["results"]
                    if item["status"] == "SAT_REJECT"
                )
                for item in parallel["results"]:
                    candidate = (int(item["idx"]), int(item["stuck_value"]))
                    if item["status"] == probe.STATUS_TIMEOUT:
                        history[candidate] = max(history.get(candidate, 0), selected_budget)
                for item in recheck["results"]:
                    candidate = (int(item["idx"]), int(item["stuck_value"]))
                    if item["status"] == "TIMEOUT":
                        history[candidate] = max(history.get(candidate, 0), selected_budget)
                candidates = [candidate for candidate in candidates if candidate not in rejected]
                phase_state = _phase_state(
                    opt,
                    current_work,
                    candidates,
                    history,
                    "PARALLEL_CLASSIFICATION_CHECKPOINT",
                )

            current_gates = opt.parse_aag(current_work)[4]
            telemetry.update(
                {
                    "unresolved": len(candidates) if not accepted else 2 * current_gates,
                    "parallel_generations": generation,
                    "parallel_worker_sat_reject": totals["worker_sat_reject"],
                    "parallel_worker_timeout": totals["worker_timeout"],
                    "parallel_worker_unsat_proposed": totals["worker_unsat_proposed"],
                    "parallel_coordinator_unsat_accept": totals["coordinator_unsat_accept"],
                    "parallel_cec_pass_commits": totals["cec_pass_commits"],
                    "parallel_cec_failed_commits": totals["cec_failed_commits"],
                }
            )
            checkpoint_status = (
                "PARALLEL_CEC_COMMIT"
                if transaction["committed"]
                else "PARALLEL_CLASSIFICATION_CHECKPOINT"
            )
            checkpoint_saved = opt._save_checkpoint(
                source_path,
                current_work,
                telemetry,
                checkpoint_status,
                phase_state,
            )
            record = {
                "generation": generation,
                "snapshot_sha256": snapshot_hash,
                "budget": selected_budget,
                "batch_size": len(batch),
                "worker_seconds": parallel["seconds"],
                "worker_counts": worker_counts,
                "worker_results": parallel["results"],
                "coordinator_results": recheck["results"],
                "accepted": [[idx, value] for idx, value in sorted(accepted.items())],
                "transaction": transaction,
                "current_gates": current_gates,
                "checkpoint": checkpoint_saved,
                "elapsed": time.time() - started,
                "wave_seconds": time.time() - wave_started,
            }
            records.append(record)
            _append_jsonl(jsonl_path, record)
            if cec_failed:
                status = "CEC_FAILED_ROLLBACK"
                break

        else:
            status = "MAX_GENERATIONS_REACHED"

        shutil.copyfile(current_work, output_path)
        final_verify, final_verify_time, _ = run_abc_cec(
            source_path,
            output_path,
            timeout=config.cec_timeout,
        )
        final_gates = opt.parse_aag(output_path)[4]
        if final_verify != "PASS":
            raise RuntimeError(f"final coordinator output failed CEC: {final_verify}")

        frontier_unresolved = opt._phase_resume_unresolved_count(phase_state)
        if frontier_unresolved is not None:
            telemetry["unresolved"] = frontier_unresolved
        elif status == "COMPLETE":
            telemetry["unresolved"] = 0
        else:
            telemetry["unresolved"] = max(
                int(telemetry.get("unresolved", 0) or 0),
                2 * final_gates,
            )
        opt._save_checkpoint(source_path, current_work, telemetry, status, phase_state)

    summary = {
        "source": source_path,
        "output": output_path,
        "status": status,
        "started": started,
        "finished": time.time(),
        "elapsed": time.time() - started,
        "initial_gates": initial_gates,
        "final_gates": final_gates,
        "removed": max(0, initial_gates - final_gates),
        "final_verify": final_verify,
        "final_verify_time": final_verify_time,
        "totals": totals,
        "records": records,
        "config": asdict(config),
        "jsonl": os.path.abspath(jsonl_path),
    }
    _write_json_atomic(report_path, summary)
    return summary


def _extra_dirs(values: Sequence[str]) -> Tuple[str, ...]:
    result: List[str] = []
    for value in values:
        result.extend(part.strip() for part in value.split(",") if part.strip())
    return tuple(result)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parallel Alg10 worker queue with a single CEC-gated commit coordinator."
    )
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--checkpoint-dir", required=True)
    parser.add_argument("--extra-checkpoint-dir", action="append", default=[])
    parser.add_argument("--checkpoint-json", default="")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--budgets", default="1000,5000,20000")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--seconds", type=float, default=3600)
    parser.add_argument("--max-generations", type=int, default=100)
    parser.add_argument("--solver", default="cadical153")
    parser.add_argument(
        "--phase-mode",
        default="none",
        choices=["none", "controls_false", "model", "controls_false_model"],
    )
    parser.add_argument("--order", default="untried_first")
    parser.add_argument("--recheck-budget", type=int, default=0)
    parser.add_argument("--cec-timeout", type=float, default=60)
    parser.add_argument("--report", default="")
    parser.add_argument("--jsonl", default="")
    parser.add_argument("--no-audit", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config = CoordinatorConfig(
        checkpoint_dir=args.checkpoint_dir,
        extra_checkpoint_dirs=_extra_dirs(args.extra_checkpoint_dir),
        jobs=max(1, args.jobs),
        budgets=_parse_budgets(args.budgets),
        batch_size=max(1, args.batch_size),
        max_seconds=args.seconds,
        max_generations=max(1, args.max_generations),
        solver=args.solver,
        phase_mode=args.phase_mode,
        frontier_order=args.order,
        recheck_budget=max(0, args.recheck_budget),
        checkpoint_json=args.checkpoint_json,
        audit_assumptions=not args.no_audit,
        cec_timeout=max(0.1, args.cec_timeout),
    )
    summary = run_coordinator(
        args.source,
        args.output,
        config,
        report_path=args.report,
        jsonl_path=args.jsonl,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
