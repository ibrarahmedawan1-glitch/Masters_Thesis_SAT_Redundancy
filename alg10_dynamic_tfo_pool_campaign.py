#!/usr/bin/env python3
"""Dynamic cross-circuit TFO worker pool with transactional commits.

Workers classify immutable candidate microbatches from any ready circuit. A
single scheduler owns every circuit state. When a worker becomes free, it pulls
the next reason-aware microbatch from the global queue. UNSAT proposals stop
new dispatches for that circuit until all tasks on the same generation finish,
then the scheduler performs the existing sequential recheck and CEC-gated
commit. Other circuits continue using the shared workers during that barrier.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import alg10_frontier_shard_probe as probe
import alg10_parallel_commit_coordinator as coordinator
import alg10_parallel_tfo_benchmark_campaign as benchmark
from abc_utils import run_abc_cec


Candidate = Tuple[int, int]
SOURCE_FILES = (
    "optimizer_alg10_tiered.py",
    "alg10_frontier_shard_probe.py",
    "alg10_parallel_commit_coordinator.py",
    "alg10_dynamic_tfo_pool_campaign.py",
)


@dataclass
class PoolCircuitState:
    key: str
    source_path: str
    seed_checkpoint: str
    seed_work_path: str
    phase_tier: str
    root: str
    checkpoint_dir: str
    work_path: str
    output_path: str
    events_path: str
    config: coordinator.CoordinatorConfig
    alg_config: probe.Alg10Config
    candidates: List[Candidate]
    history: Dict[Candidate, int]
    initial_gates: int
    current_gates: int
    generation: int = 0
    inflight: Set[Candidate] = field(default_factory=set)
    proposals: List[Dict[str, Any]] = field(default_factory=list)
    commit_inflight: bool = False
    timing: Dict[Candidate, Tuple[int, float]] = field(default_factory=dict)
    visits: int = 0
    dispatches: int = 0
    last_dispatch_seq: int = 0
    complete: bool = False
    failed: bool = False
    status: str = "READY"
    last_abort_reason: str = ""
    next_action: str = "CONTINUE_FRONTIER"
    last_checkpoint_time: float = 0.0
    started_at: float = 0.0
    first_dispatch_at: float = 0.0
    last_activity_at: float = 0.0
    completed_at: float = 0.0
    totals: Dict[str, int] = field(
        default_factory=lambda: {
            "worker_sat_reject": 0,
            "worker_timeout": 0,
            "worker_unsat_proposed": 0,
            "coordinator_sat_reject": 0,
            "coordinator_timeout": 0,
            "coordinator_unsat_accept": 0,
            "cec_pass_commits": 0,
            "cec_failed_commits": 0,
            "stale_results": 0,
            "worker_errors": 0,
            "worker_cache_hits": 0,
            "worker_cache_misses": 0,
            "persistent_retry_tasks": 0,
        }
    )


@dataclass(frozen=True)
class PoolTask:
    key: str
    generation: int
    snapshot_sha256: str
    budget: int
    candidates: Tuple[Candidate, ...]
    reason: str
    submitted: float
    worker_slot: int
    budget_targets: Tuple[int, ...] = ()


@dataclass(frozen=True)
class ProposalTask:
    key: str
    generation: int
    snapshot_sha256: str
    submitted: float


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


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_manifest() -> Dict[str, str]:
    root = os.path.dirname(os.path.abspath(__file__))
    return {
        name: _sha256_file(os.path.join(root, name))
        for name in SOURCE_FILES
    }


def next_budget(
    previous: int,
    budgets: Sequence[int],
    budget_growth: float,
    max_generated_budget: int,
) -> int:
    previous = max(0, int(previous))
    configured = sorted({int(value) for value in budgets if int(value) > 0})
    for budget in configured:
        if budget > previous:
            return budget
    if not configured or budget_growth <= 1.0:
        return 0
    base = max(previous, configured[-1])
    generated = max(base + 1, int(base * float(budget_growth) + 0.999999))
    if max_generated_budget > 0:
        generated = min(generated, int(max_generated_budget))
        if generated <= previous:
            return 0
    return generated


def candidate_reason(previous: int) -> str:
    return "UNTRIED" if int(previous) <= 0 else "TIMEOUT_RETRY"


def _candidate_priority(state: PoolCircuitState, candidate: Candidate) -> Tuple[int, int]:
    previous = int(state.history.get(candidate, 0))
    return (0 if previous <= 0 else 1, previous)


def select_candidate_batch(
    state: PoolCircuitState,
    microbatch_size: int,
    worker_count: int,
    retry_microbatch_size: int = 1,
) -> Tuple[int, List[Candidate], str]:
    if state.complete or state.failed or state.proposals or state.commit_inflight:
        return 0, [], ""
    available = [
        candidate
        for candidate in state.candidates
        if candidate not in state.inflight
    ]
    if not available:
        return 0, [], ""
    available.sort(key=lambda candidate: _candidate_priority(state, candidate))
    first = available[0]
    previous = int(state.history.get(first, 0))
    budget = next_budget(
        previous,
        state.config.budgets,
        state.config.budget_growth,
        state.config.max_generated_budget,
    )
    if budget <= 0:
        return 0, [], ""
    same_tier = [
        candidate
        for candidate in available
        if next_budget(
            int(state.history.get(candidate, 0)),
            state.config.budgets,
            state.config.budget_growth,
            state.config.max_generated_budget,
        )
        == budget
    ]
    if previous > 0:
        batch_limit = max(1, retry_microbatch_size)
    else:
        batch_limit = (
            1
            if len(available) <= max(1, worker_count)
            else max(1, microbatch_size)
        )
    return budget, same_tier[:batch_limit], candidate_reason(previous)


def select_ready_circuit(
    states: Sequence[PoolCircuitState],
    microbatch_size: int,
    worker_count: int,
    retry_microbatch_size: int = 1,
    excluded_keys: Sequence[str] = (),
) -> Optional[PoolCircuitState]:
    excluded = set(excluded_keys)
    ready = []
    for state in states:
        if state.key in excluded:
            continue
        budget, batch, reason = select_candidate_batch(
            state,
            microbatch_size,
            worker_count,
            retry_microbatch_size,
        )
        if not batch or budget <= 0:
            continue
        reason_rank = 0 if reason == "UNTRIED" else 1
        ready.append(
            (
                len(state.inflight),
                reason_rank,
                state.last_dispatch_seq,
                state.key,
                state,
            )
        )
    return min(ready, default=None, key=lambda item: item[:-1])[-1] if ready else None


def _estimated_candidate_seconds(
    state: PoolCircuitState,
    candidate: Candidate,
    budget: int,
) -> Optional[float]:
    sample = state.timing.get(candidate)
    if sample is not None:
        previous_budget, seconds = sample
        scale = max(1.0, float(budget) / max(1, int(previous_budget)))
        return max(0.001, float(seconds) * scale)
    estimates = [
        max(0.001, float(seconds))
        * max(1.0, float(budget) / max(1, int(previous_budget)))
        for previous_budget, seconds in state.timing.values()
        if int(previous_budget) > 0 and float(seconds) >= 0
    ]
    return max(estimates) if estimates else None


def _fit_batch_to_deadline(
    state: PoolCircuitState,
    budget: int,
    candidates: Sequence[Candidate],
    remaining_seconds: float,
    reserve_seconds: float,
    unknown_guard_seconds: float,
) -> List[Candidate]:
    available = float(remaining_seconds) - max(0.0, float(reserve_seconds))
    if available <= 0:
        return []
    estimates = [
        _estimated_candidate_seconds(state, candidate, budget)
        for candidate in candidates
    ]
    if any(estimate is None for estimate in estimates):
        if remaining_seconds <= max(0.0, float(unknown_guard_seconds)):
            return []
        return list(candidates)

    fitted: List[Candidate] = []
    estimated_total = 0.0
    for candidate, estimate in zip(candidates, estimates):
        assert estimate is not None
        if estimated_total + estimate > available:
            break
        fitted.append(candidate)
        estimated_total += estimate
    return fitted


def _estimated_proposal_seconds(
    state: PoolCircuitState,
) -> Optional[float]:
    estimates = []
    for proposal in state.proposals:
        candidate = (int(proposal["idx"]), int(proposal["stuck_value"]))
        budget = int(proposal.get("budget", 0) or 0)
        estimate = _estimated_candidate_seconds(state, candidate, budget)
        if estimate is None:
            try:
                seconds = float(proposal.get("seconds", 0) or 0)
            except (TypeError, ValueError):
                return None
            if seconds <= 0:
                return None
            recheck_budget = max(0, int(state.config.recheck_budget or 0))
            if budget > 0 and recheck_budget > budget:
                scale = float(recheck_budget) / float(budget)
            else:
                scale = 1.0
            estimate = max(0.001, seconds) * max(1.0, scale)
        estimates.append(estimate)
    return sum(estimates)


def _load_timing_hints(
    target: benchmark.TargetState,
    work_sha256: str,
) -> Dict[Candidate, Tuple[int, float]]:
    paths = []
    checkpoint_dir = os.path.dirname(target.seed_checkpoint)
    if os.path.basename(checkpoint_dir) == "checkpoints":
        paths.append(os.path.join(os.path.dirname(checkpoint_dir), "generations.jsonl"))
    hints: Dict[Candidate, Tuple[int, float]] = {}
    for path in paths:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    if record.get("snapshot_sha256") != work_sha256:
                        continue
                    budget = int(record.get("budget", 0) or 0)
                    for item in record.get("worker_results", []):
                        candidate = (int(item["idx"]), int(item["stuck_value"]))
                        seconds = float(item.get("seconds", 0) or 0)
                        previous = hints.get(candidate)
                        if previous is None or budget >= previous[0]:
                            hints[candidate] = (budget, seconds)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return hints


def _state_paths(root: str, key: str) -> Dict[str, str]:
    circuit_root = os.path.join(root, key)
    return {
        "root": circuit_root,
        "checkpoint_dir": os.path.join(circuit_root, "checkpoints"),
        "work": os.path.join(circuit_root, "current.work.aag"),
        "output": os.path.join(circuit_root, key + ".aag"),
        "events": os.path.join(circuit_root, "pool_events.jsonl"),
    }


def _normalized_deferred_proposals(
    phase_state: Optional[Dict[str, Any]],
    candidates: Sequence[Candidate],
) -> List[Dict[str, Any]]:
    if not isinstance(phase_state, dict):
        return []
    valid_candidates = set(candidates)
    proposals = []
    seen: Set[Candidate] = set()
    for raw in phase_state.get("deferred_proposals", []):
        if not isinstance(raw, dict):
            return []
        try:
            candidate = (int(raw["idx"]), int(raw["stuck_value"]))
            budget = max(0, int(raw.get("budget", 0) or 0))
            ordinal = int(raw.get("ordinal", len(proposals)))
        except (KeyError, TypeError, ValueError):
            return []
        if candidate not in valid_candidates or candidate in seen:
            return []
        seen.add(candidate)
        proposal = dict(raw)
        proposal["ordinal"] = ordinal
        proposal["idx"] = candidate[0]
        proposal["stuck_value"] = candidate[1]
        proposal["status"] = probe.STATUS_UNSAT_PROPOSED
        proposal["budget"] = budget
        proposals.append(proposal)
    proposals.sort(key=lambda item: int(item.get("ordinal", 0)))
    return proposals


def _serialized_deferred_proposals(state: PoolCircuitState) -> List[Dict[str, Any]]:
    proposals = []
    candidate_set = set(state.candidates)
    seen: Set[Candidate] = set()
    for raw in state.proposals:
        try:
            candidate = (int(raw["idx"]), int(raw["stuck_value"]))
        except (KeyError, TypeError, ValueError):
            continue
        if candidate not in candidate_set or candidate in seen:
            continue
        seen.add(candidate)
        proposal = dict(raw)
        proposal["ordinal"] = int(proposal.get("ordinal", len(proposals)))
        proposal["idx"] = candidate[0]
        proposal["stuck_value"] = candidate[1]
        proposal["status"] = probe.STATUS_UNSAT_PROPOSED
        proposal["budget"] = max(0, int(proposal.get("budget", 0) or 0))
        proposals.append(proposal)
    proposals.sort(key=lambda item: int(item.get("ordinal", 0)))
    return proposals


def _retry_frontier_summary(state: PoolCircuitState) -> Dict[str, Any]:
    next_budget_counts: Dict[str, int] = {}
    retry_candidates = 0
    exhausted = 0
    max_tried = 0
    for candidate in state.candidates:
        tried = max(0, int(state.history.get(candidate, 0) or 0))
        if tried > 0:
            retry_candidates += 1
            max_tried = max(max_tried, tried)
        budget = next_budget(
            tried,
            state.config.budgets,
            state.config.budget_growth,
            state.config.max_generated_budget,
        )
        if budget <= 0:
            exhausted += 1
            key = "exhausted"
        else:
            key = str(int(budget))
        next_budget_counts[key] = next_budget_counts.get(key, 0) + 1
    return {
        "untried": max(0, len(state.candidates) - retry_candidates),
        "retry": retry_candidates,
        "exhausted": exhausted,
        "max_budget_tried": max_tried,
        "next_budget_counts": next_budget_counts,
    }


def _initialize_state(
    target: benchmark.TargetState,
    root: str,
    args: argparse.Namespace,
) -> PoolCircuitState:
    paths = _state_paths(root, target.key)
    os.makedirs(paths["checkpoint_dir"], exist_ok=True)
    seed_checkpoint = target.seed_checkpoint
    if target.phase_tier == "verified_output":
        seed_checkpoint = benchmark._materialize_verified_output_seed(
            target,
            paths["checkpoint_dir"],
            args.cec_timeout,
        )
    config = coordinator.CoordinatorConfig(
        checkpoint_dir=paths["checkpoint_dir"],
        checkpoint_select="gates",
        jobs=1,
        budgets=coordinator._parse_budgets(args.budgets),
        batch_size=max(1, args.microbatch_size),
        max_seconds=float(args.seconds),
        max_generations=1_000_000,
        solver=args.solver,
        frontier_order=args.order,
        worker_engine="tfo",
        recheck_engine="tfo",
        recheck_budget=max(0, args.max_generated_budget),
        continue_until_deadline=True,
        budget_growth=args.budget_growth,
        max_generated_budget=max(0, args.max_generated_budget),
        checkpoint_json=seed_checkpoint,
        cec_timeout=args.cec_timeout,
        worker_cache_entries=max(0, int(getattr(args, "worker_cache_entries", 0))),
    )
    alg_config = coordinator._alg10_config(config)
    opt = probe._load_alg10(alg_config)
    checkpoint = coordinator._load_checkpoint_data(
        target.source_path,
        opt,
        seed_checkpoint,
    )
    if checkpoint:
        checkpoint_work = (
            checkpoint.get("_checkpoint_work_path")
            or checkpoint.get("work_aag")
        )
        shutil.copyfile(checkpoint_work, paths["work"])
        phase_state = checkpoint.get("phase_resume")
    else:
        shutil.copyfile(target.source_path, paths["work"])
        phase_state = None
    candidates, history = coordinator._frontier_from_state(
        opt,
        paths["work"],
        phase_state,
        history_engine="tfo",
    )
    initial_gates = opt.parse_aag(target.source_path)[4]
    current_gates = opt.parse_aag(paths["work"])[4]
    valid_phase = opt._valid_phase_resume_state(phase_state, paths["work"], current_gates)
    deferred_proposals = (
        _normalized_deferred_proposals(phase_state, candidates)
        if valid_phase and valid_phase.get("tier") == "global"
        else []
    )
    timing = _load_timing_hints(target, _sha256_file(paths["work"]))
    state = PoolCircuitState(
        key=target.key,
        source_path=os.path.abspath(target.source_path),
        seed_checkpoint=os.path.abspath(seed_checkpoint) if seed_checkpoint else "",
        seed_work_path=os.path.abspath(target.seed_work_path),
        phase_tier=target.phase_tier,
        root=paths["root"],
        checkpoint_dir=paths["checkpoint_dir"],
        work_path=paths["work"],
        output_path=paths["output"],
        events_path=paths["events"],
        config=config,
        alg_config=alg_config,
        candidates=candidates,
        history=history,
        proposals=deferred_proposals,
        timing=timing,
        initial_gates=initial_gates,
        current_gates=current_gates,
        status="READY_WITH_DEFERRED_PROPOSALS" if deferred_proposals else "READY",
        last_abort_reason="DEFERRED_PROPOSALS_RESUMED" if deferred_proposals else "",
        next_action="RESUME_SERIAL_RECHECK" if deferred_proposals else "CONTINUE_FRONTIER",
        started_at=time.time(),
        last_activity_at=time.time(),
    )
    _persist_state(state, "DYNAMIC_POOL_INITIALIZED")
    return state


def _load_opt(state: PoolCircuitState):
    return probe._load_alg10(coordinator._alg10_config(state.config))


def _persist_state(state: PoolCircuitState, reason: str) -> str:
    opt = _load_opt(state)
    phase_state = (
        coordinator._phase_state(
            opt,
            state.work_path,
            state.candidates,
            state.history,
            reason,
            history_engine="tfo",
        )
        if state.candidates
        else None
    )
    if phase_state is not None and state.proposals:
        phase_state["deferred_proposals"] = _serialized_deferred_proposals(state)
        phase_state["deferred_proposal_reason"] = reason
    telemetry = {
        "unresolved": len(state.candidates),
        "parallel_generations": state.generation,
        "parallel_worker_sat_reject": state.totals["worker_sat_reject"],
        "parallel_worker_timeout": state.totals["worker_timeout"],
        "parallel_worker_unsat_proposed": state.totals["worker_unsat_proposed"],
        "parallel_coordinator_unsat_accept": state.totals[
            "coordinator_unsat_accept"
        ],
        "parallel_cec_pass_commits": state.totals["cec_pass_commits"],
        "parallel_cec_failed_commits": state.totals["cec_failed_commits"],
        "dynamic_pool_dispatches": state.dispatches,
        "dynamic_pool_inflight": len(state.inflight),
        "dynamic_pool_deferred_proposals": len(state.proposals),
        "dynamic_pool_reason": reason,
    }
    checkpoint = opt._save_checkpoint(
        state.source_path,
        state.work_path,
        telemetry,
        reason,
        phase_state,
    )
    shutil.copyfile(state.work_path, state.output_path)
    state.last_checkpoint_time = time.time()
    return checkpoint


def _state_summary(state: PoolCircuitState) -> Dict[str, Any]:
    terminal_at = state.completed_at if state.completed_at > 0 else 0.0
    active_until = terminal_at or state.last_activity_at or time.time()
    started_at = state.started_at or 0.0
    first_dispatch_at = state.first_dispatch_at or 0.0
    return {
        "key": state.key,
        "source_path": state.source_path,
        "seed_checkpoint": state.seed_checkpoint,
        "phase_tier": state.phase_tier,
        "status": state.status,
        "last_abort_reason": state.last_abort_reason,
        "next_action": state.next_action,
        "generation": state.generation,
        "initial_gates": state.initial_gates,
        "current_gates": state.current_gates,
        "removed": max(0, state.initial_gates - state.current_gates),
        "unresolved": len(state.candidates),
        "inflight": len(state.inflight),
        "proposals_waiting": len(state.proposals),
        "retry_frontier": _retry_frontier_summary(state),
        "commit_inflight": state.commit_inflight,
        "dispatches": state.dispatches,
        "complete": state.complete,
        "failed": state.failed,
        "totals": dict(state.totals),
        "started_at": started_at,
        "first_dispatch_at": first_dispatch_at,
        "last_activity_at": state.last_activity_at,
        "completed_at": terminal_at,
        "elapsed_seconds": max(0.0, active_until - started_at)
        if started_at > 0
        else 0.0,
        "dispatch_span_seconds": max(0.0, active_until - first_dispatch_at)
        if first_dispatch_at > 0
        else 0.0,
        "output": os.path.abspath(state.output_path),
        "checkpoint_dir": os.path.abspath(state.checkpoint_dir),
    }


def _worker_items(candidates: Sequence[Candidate]) -> List[Tuple[int, int, int]]:
    return [
        (ordinal, int(candidate[0]), int(candidate[1]))
        for ordinal, candidate in enumerate(candidates)
    ]


def _retry_budget_targets(
    state: PoolCircuitState,
    budget: int,
    candidates: Sequence[Candidate],
    reason: str,
    persistent_retry_tiers: int,
) -> Tuple[int, ...]:
    if reason != "TIMEOUT_RETRY" or persistent_retry_tiers <= 1 or len(candidates) != 1:
        return (int(budget),)
    targets = [int(budget)]
    previous = int(budget)
    while len(targets) < persistent_retry_tiers:
        nxt = next_budget(
            previous,
            state.config.budgets,
            state.config.budget_growth,
            state.config.max_generated_budget,
        )
        if nxt <= previous:
            break
        targets.append(int(nxt))
        previous = int(nxt)
    return tuple(targets)


def _dispatch_task(
    pool: ProcessPoolExecutor,
    state: PoolCircuitState,
    budget: int,
    candidates: Sequence[Candidate],
    reason: str,
    worker_slot: int,
    budget_targets: Sequence[int] = (),
) -> Tuple[Future, PoolTask]:
    snapshot = _sha256_file(state.work_path)
    targets = tuple(int(value) for value in budget_targets if int(value) > 0)
    if not targets:
        targets = (int(budget),)
    now = time.time()
    task = PoolTask(
        key=state.key,
        generation=state.generation,
        snapshot_sha256=snapshot,
        budget=int(budget),
        candidates=tuple(candidates),
        reason=reason,
        submitted=now,
        worker_slot=worker_slot,
        budget_targets=targets,
    )
    state.inflight.update(candidates)
    state.dispatches += 1
    if state.first_dispatch_at <= 0:
        state.first_dispatch_at = now
    state.last_activity_at = now
    state.status = "CLASSIFYING"
    state.last_abort_reason = reason
    state.next_action = (
        "CONTINUE_FRONTIER" if reason == "UNTRIED" else "INCREASE_BUDGET"
    )
    future = pool.submit(
        probe._solve_items,
        state.work_path,
        _worker_items(candidates),
        int(budget),
        state.alg_config,
        True,
        worker_slot,
        targets,
    )
    return future, task


def _handle_worker_result(
    state: PoolCircuitState,
    task: PoolTask,
    results: Sequence[Dict[str, Any]],
) -> None:
    if (
        state.generation != task.generation
        or _sha256_file(state.work_path) != task.snapshot_sha256
    ):
        state.totals["stale_results"] += len(results)
        state.inflight.difference_update(task.candidates)
        state.last_activity_at = time.time()
        return

    rejected: Set[Candidate] = set()
    state.last_activity_at = time.time()
    for item in results:
        candidate = (int(item["idx"]), int(item["stuck_value"]))
        state.inflight.discard(candidate)
        seconds = float(item.get("seconds", 0) or 0)
        result_budget = int(item.get("budget_tried", 0) or task.budget)
        state.timing[candidate] = (result_budget, seconds)
        if item.get("worker_cache_hit"):
            state.totals["worker_cache_hits"] += 1
        else:
            state.totals["worker_cache_misses"] += 1
        status = str(item["status"])
        if status == probe.STATUS_SAT_REJECT:
            state.totals["worker_sat_reject"] += 1
            rejected.add(candidate)
            state.last_abort_reason = "SAT_REJECT"
            state.next_action = "CONTINUE_FRONTIER"
        elif status == probe.STATUS_TIMEOUT:
            state.totals["worker_timeout"] += 1
            state.history[candidate] = max(
                state.history.get(candidate, 0),
                result_budget,
            )
            state.last_abort_reason = "SAT_TIMEOUT"
            state.next_action = "INCREASE_BUDGET"
        elif status == probe.STATUS_UNSAT_PROPOSED:
            state.totals["worker_unsat_proposed"] += 1
            proposal = dict(item)
            proposal["budget"] = result_budget
            state.proposals.append(proposal)
            state.last_abort_reason = "UNSAT_PROPOSAL"
            state.next_action = "SERIAL_RECHECK"
    if rejected:
        state.candidates = [
            candidate for candidate in state.candidates if candidate not in rejected
        ]
    _append_jsonl(
        state.events_path,
        {
            "event": "WORKER_RESULT",
            "time": time.time(),
            "generation": state.generation,
            "budget": task.budget,
            "budget_targets": list(task.budget_targets),
            "reason": task.reason,
            "worker_slot": task.worker_slot,
            "seconds": time.time() - task.submitted,
            "candidates": [list(candidate) for candidate in task.candidates],
            "results": list(results),
        },
    )


def _run_proposal_barrier(
    source_path: str,
    work_path: str,
    proposals: Sequence[Dict[str, Any]],
    config: coordinator.CoordinatorConfig,
    expected_sha256: str,
) -> Dict[str, Any]:
    opt = probe._load_alg10(coordinator._alg10_config(config))
    snapshot = opt._sha256_file(work_path)
    if snapshot != expected_sha256:
        raise RuntimeError("proposal barrier received a stale work AAG")
    recheck = coordinator._serial_recheck(work_path, proposals, config)
    transaction = {"committed": False, "verify": "NOT_RUN", "verify_time": 0.0}
    if recheck["accepted"]:
        transaction = coordinator._cec_transaction(
            source_path,
            work_path,
            recheck["accepted"],
            opt,
            config.cec_timeout,
        )
    return {
        "snapshot_sha256": snapshot,
        "recheck": recheck,
        "transaction": transaction,
        "current_gates": opt.parse_aag(work_path)[4],
    }


def _apply_proposal_barrier(
    state: PoolCircuitState,
    task: ProposalTask,
    result: Dict[str, Any],
) -> None:
    if (
        task.generation != state.generation
        or task.snapshot_sha256 != result["snapshot_sha256"]
    ):
        state.totals["stale_results"] += len(state.proposals)
        state.proposals = []
        state.commit_inflight = False
        state.last_activity_at = time.time()
        return

    state.last_activity_at = time.time()
    opt = _load_opt(state)
    recheck = result["recheck"]
    transaction = result["transaction"]
    for item in recheck["results"]:
        if item["status"] == "UNSAT_ACCEPT":
            state.totals["coordinator_unsat_accept"] += 1
        elif item["status"] == "SAT_REJECT":
            state.totals["coordinator_sat_reject"] += 1
        elif item["status"] == "TIMEOUT":
            state.totals["coordinator_timeout"] += 1

    if recheck["accepted"]:
        if transaction["committed"]:
            state.totals["cec_pass_commits"] += 1
            state.generation += 1
            state.current_gates = int(result["current_gates"])
            state.candidates, state.history = coordinator._frontier_from_state(
                opt,
                state.work_path,
                None,
                history_engine="tfo",
            )
            state.timing = {}
            state.last_abort_reason = "CEC_PASSED_COMMIT"
            state.next_action = "REGENERATE_FRONTIER"
            state.status = "READY"
        else:
            state.totals["cec_failed_commits"] += 1
            state.failed = True
            state.status = "CEC_FAILED_ROLLBACK"
            state.last_abort_reason = "CEC_FAILED_ROLLBACK"
            state.next_action = "STOP_AND_AUDIT"
            if state.completed_at <= 0:
                state.completed_at = time.time()
    else:
        rejected = {
            (int(item["idx"]), int(item["stuck_value"]))
            for item in recheck["results"]
            if item["status"] in {"SAT_REJECT", "STALE_SAME_GATE"}
        }
        for item in recheck["results"]:
            if item["status"] == "TIMEOUT":
                candidate = (int(item["idx"]), int(item["stuck_value"]))
                proposal_budget = next(
                    (
                        int(proposal.get("budget", 0))
                        for proposal in state.proposals
                        if int(proposal["idx"]) == candidate[0]
                        and int(proposal["stuck_value"]) == candidate[1]
                    ),
                    0,
                )
                state.history[candidate] = max(
                    state.history.get(candidate, 0),
                    proposal_budget,
                )
        state.candidates = [
            candidate for candidate in state.candidates if candidate not in rejected
        ]
        state.status = "READY"
        state.last_abort_reason = "SERIAL_RECHECK_REJECT"
        state.next_action = "CONTINUE_FRONTIER"

    state.proposals = []
    state.commit_inflight = False
    _append_jsonl(
        state.events_path,
        {
            "event": "PROPOSAL_BARRIER",
            "time": time.time(),
            "generation_before": task.generation,
            "snapshot_sha256": task.snapshot_sha256,
            "recheck": recheck,
            "transaction": transaction,
            "current_gates": state.current_gates,
            "unresolved": len(state.candidates),
        },
    )
    _persist_state(state, state.last_abort_reason)


def _finalize_proposals(state: PoolCircuitState) -> None:
    if not state.proposals or state.inflight or state.commit_inflight:
        return
    task = ProposalTask(
        key=state.key,
        generation=state.generation,
        snapshot_sha256=_sha256_file(state.work_path),
        submitted=time.time(),
    )
    state.commit_inflight = True
    result = _run_proposal_barrier(
        state.source_path,
        state.work_path,
        tuple(state.proposals),
        state.config,
        task.snapshot_sha256,
    )
    _apply_proposal_barrier(state, task, result)


def _mark_terminal_states(states: Sequence[PoolCircuitState]) -> None:
    for state in states:
        if state.failed or state.inflight or state.proposals or state.commit_inflight:
            continue
        if not state.candidates:
            state.complete = True
            state.status = "COMPLETE"
            state.last_abort_reason = "COMPLETE"
            state.next_action = "COMPLETE"
            if state.completed_at <= 0:
                state.completed_at = time.time()
            state.last_activity_at = state.completed_at
            continue
        if all(
            next_budget(
                state.history.get(candidate, 0),
                state.config.budgets,
                state.config.budget_growth,
                state.config.max_generated_budget,
            )
            <= 0
            for candidate in state.candidates
        ):
            state.status = "UNRESOLVED_BUDGETS_EXHAUSTED"
            state.last_abort_reason = "BUDGET_CAP"
            state.next_action = "RAISE_BUDGET_CAP"
            if state.completed_at <= 0:
                state.completed_at = time.time()
            state.last_activity_at = state.completed_at


def _campaign_summary(
    states: Sequence[PoolCircuitState],
    started: float,
    deadline: float,
    hardware: Dict[str, int],
    status: str,
    dispatch_seq: int,
    pool_metrics: Dict[str, Any],
    source_manifest: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    elapsed = max(0.0, time.time() - started)
    worker_capacity = elapsed * max(1, int(hardware["selected"]))
    busy_seconds = float(pool_metrics.get("worker_busy_seconds", 0.0)) + float(
        pool_metrics.get("proposal_barrier_busy_seconds", 0.0)
    )
    return {
        "started": started,
        "deadline": deadline,
        "finished": time.time(),
        "elapsed": elapsed,
        "status": status,
        "source_manifest": source_manifest or {},
        "hardware": hardware,
        "dispatches": dispatch_seq,
        "pool_metrics": {
            **pool_metrics,
            "worker_capacity_seconds": worker_capacity,
            "worker_utilization": (
                min(1.0, busy_seconds / worker_capacity)
                if worker_capacity > 0
                else 0.0
            ),
        },
        "targets": [_state_summary(state) for state in states],
    }


def run_dynamic_campaign(
    args: argparse.Namespace,
    targets: Optional[Sequence[benchmark.TargetState]] = None,
) -> Dict[str, Any]:
    hardware = benchmark.resolve_worker_count(args.jobs)
    jobs = hardware["selected"]
    if targets is None:
        filters = tuple(
            part.strip()
            for part in args.target_filter.split(",")
            if part.strip()
        )
        targets = benchmark.discover_best_targets(
            filters,
            args.max_targets,
            args.checkpoint_dir,
        )
    if not targets:
        raise RuntimeError("no targets available for the dynamic TFO pool")

    root = os.path.abspath(args.output_dir)
    os.makedirs(root, exist_ok=True)
    summary_path = os.path.join(root, "summary.json")
    campaign_events = os.path.join(root, "pool_events.jsonl")
    retry_microbatch_size = max(
        1,
        int(getattr(args, "retry_microbatch_size", 1)),
    )
    deadline_reserve_seconds = max(
        0.0,
        float(getattr(args, "deadline_reserve_seconds", 0.0)),
    )
    unknown_task_guard_seconds = max(
        0.0,
        float(getattr(args, "unknown_task_guard_seconds", 0.0)),
    )
    persistent_retry_tiers = max(
        1,
        int(getattr(args, "persistent_retry_tiers", 1)),
    )
    states = [_initialize_state(target, root, args) for target in targets]
    source_manifest = _source_manifest()
    states_by_key = {state.key: state for state in states}
    started = time.time()
    deadline = started + float(args.seconds)
    dispatch_seq = 0
    future_tasks: Dict[Future, PoolTask] = {}
    proposal_tasks: Dict[Future, ProposalTask] = {}
    deadline_admission_blocked_keys: Set[str] = set()
    pool_metrics: Dict[str, Any] = {
        "tasks_submitted": 0,
        "tasks_completed": 0,
        "proposal_barriers_submitted": 0,
        "proposal_barriers_completed": 0,
        "proposal_barriers_deferred": 0,
        "worker_busy_seconds": 0.0,
        "proposal_barrier_busy_seconds": 0.0,
        "deadline_admission_skips": 0,
        "max_active_workers": 0,
        "dispatch_reason_counts": {
            "UNTRIED": 0,
            "TIMEOUT_RETRY": 0,
        },
    }
    status = "RUNNING"
    last_summary_write = 0.0
    summary_heartbeat_seconds = max(
        1.0,
        min(30.0, float(getattr(args, "checkpoint_interval", 30.0))),
    )

    print(
        "Dynamic TFO pool:",
        f"workers={jobs}",
        f"physical={hardware['physical_cores']}",
        f"logical={hardware['logical_cores']}",
        f"targets={len(states)}",
    )

    with (
        ProcessPoolExecutor(max_workers=jobs) as pool,
        ProcessPoolExecutor(max_workers=1) as commit_pool,
    ):
        while time.time() < deadline:
            if _source_manifest() != source_manifest:
                status = "SOURCE_CHANGED_CHECKPOINT"
                break
            _mark_terminal_states(states)

            for state in states:
                if (
                    proposal_tasks
                    or len(future_tasks) + len(proposal_tasks) >= jobs
                ):
                    break
                if (
                    not state.proposals
                    or state.inflight
                    or state.commit_inflight
                    or state.failed
                ):
                    continue
                remaining = max(0.0, deadline - time.time())
                proposal_estimate = _estimated_proposal_seconds(state)
                proposal_fits = (
                    remaining > deadline_reserve_seconds
                    and (
                        proposal_estimate is not None
                        and proposal_estimate
                        <= remaining - deadline_reserve_seconds
                    )
                )
                if not proposal_fits:
                    if state.status != "PROPOSAL_DEFERRED_DEADLINE":
                        pool_metrics["proposal_barriers_deferred"] += 1
                    state.status = "PROPOSAL_DEFERRED_DEADLINE"
                    state.last_abort_reason = "PROPOSAL_DEFERRED_DEADLINE"
                    state.next_action = "RESUME_SERIAL_RECHECK"
                    continue
                task = ProposalTask(
                    key=state.key,
                    generation=state.generation,
                    snapshot_sha256=_sha256_file(state.work_path),
                    submitted=time.time(),
                )
                state.commit_inflight = True
                state.status = "SERIAL_RECHECK"
                future = commit_pool.submit(
                    _run_proposal_barrier,
                    state.source_path,
                    state.work_path,
                    tuple(state.proposals),
                    state.config,
                    task.snapshot_sha256,
                )
                proposal_tasks[future] = task
                pool_metrics["proposal_barriers_submitted"] += 1
                pool_metrics["max_active_workers"] = max(
                    int(pool_metrics["max_active_workers"]),
                    len(future_tasks) + len(proposal_tasks),
                )

            deadline_blocked = set()
            while (
                len(future_tasks) + len(proposal_tasks) < jobs
                and time.time() < deadline
            ):
                state = select_ready_circuit(
                    states,
                    args.microbatch_size,
                    jobs,
                    retry_microbatch_size,
                    deadline_blocked,
                )
                if state is None:
                    break
                budget, batch, reason = select_candidate_batch(
                    state,
                    args.microbatch_size,
                    jobs,
                    retry_microbatch_size,
                )
                if not batch:
                    break
                budget_targets = _retry_budget_targets(
                    state,
                    budget,
                    batch,
                    reason,
                    persistent_retry_tiers,
                )
                admission_budget = max(budget_targets) if budget_targets else budget
                batch = _fit_batch_to_deadline(
                    state,
                    admission_budget,
                    batch,
                    max(0.0, deadline - time.time()),
                    deadline_reserve_seconds,
                    unknown_task_guard_seconds,
                )
                if not batch:
                    deadline_blocked.add(state.key)
                    if state.key not in deadline_admission_blocked_keys:
                        pool_metrics["deadline_admission_skips"] += 1
                        deadline_admission_blocked_keys.add(state.key)
                    continue
                deadline_admission_blocked_keys.discard(state.key)
                dispatch_seq += 1
                state.last_dispatch_seq = dispatch_seq
                worker_slot = (dispatch_seq - 1) % jobs + 1
                future, task = _dispatch_task(
                    pool,
                    state,
                    budget,
                    batch,
                    reason,
                    worker_slot,
                    budget_targets,
                )
                if len(budget_targets) > 1:
                    state.totals["persistent_retry_tasks"] += 1
                future_tasks[future] = task
                pool_metrics["tasks_submitted"] += 1
                pool_metrics["max_active_workers"] = max(
                    int(pool_metrics["max_active_workers"]),
                    len(future_tasks) + len(proposal_tasks),
                )
                pool_metrics["dispatch_reason_counts"][reason] = (
                    int(pool_metrics["dispatch_reason_counts"].get(reason, 0)) + 1
                )
                _append_jsonl(
                    campaign_events,
                    {
                        "event": "DISPATCH",
                        "time": time.time(),
                        "dispatch": dispatch_seq,
                        "target": state.key,
                        "generation": state.generation,
                        "budget": budget,
                        "budget_targets": list(budget_targets),
                        "reason": reason,
                        "batch_size": len(batch),
                        "active_workers": len(future_tasks) + len(proposal_tasks),
                    },
                )

            if not future_tasks and not proposal_tasks:
                _mark_terminal_states(states)
                if all(
                    state.complete
                    or state.failed
                    or state.status == "UNRESOLVED_BUDGETS_EXHAUSTED"
                    for state in states
                ):
                    status = "NO_RUNNABLE_WORK"
                    break
                now = time.time()
                if now - last_summary_write >= summary_heartbeat_seconds:
                    _write_json_atomic(
                        summary_path,
                        _campaign_summary(
                            states,
                            started,
                            deadline,
                            hardware,
                            "RUNNING",
                            dispatch_seq,
                            pool_metrics,
                            source_manifest,
                        ),
                    )
                    last_summary_write = now
                time.sleep(0.05)
                continue

            done, _pending = wait(
                tuple(future_tasks) + tuple(proposal_tasks),
                timeout=min(1.0, max(0.0, deadline - time.time())),
                return_when=FIRST_COMPLETED,
            )
            for future in [item for item in done if item in proposal_tasks]:
                task = proposal_tasks.pop(future)
                state = states_by_key[task.key]
                pool_metrics["proposal_barriers_completed"] += 1
                pool_metrics["proposal_barrier_busy_seconds"] += max(
                    0.0,
                    time.time() - task.submitted,
                )
                try:
                    result = future.result()
                    _apply_proposal_barrier(state, task, result)
                except Exception as exc:
                    state.commit_inflight = False
                    state.failed = True
                    state.status = "PROPOSAL_BARRIER_ERROR"
                    state.last_abort_reason = f"{type(exc).__name__}: {exc}"
                    state.next_action = "STOP_AND_AUDIT"
                    state.totals["worker_errors"] += 1
                    if state.completed_at <= 0:
                        state.completed_at = time.time()
                    state.last_activity_at = state.completed_at
                    _append_jsonl(
                        state.events_path,
                        {
                            "event": "PROPOSAL_BARRIER_ERROR",
                            "time": time.time(),
                            "task": asdict(task),
                            "error": state.last_abort_reason,
                        },
                    )
            for future in done:
                if future not in future_tasks:
                    continue
                task = future_tasks.pop(future)
                state = states_by_key[task.key]
                pool_metrics["tasks_completed"] += 1
                pool_metrics["worker_busy_seconds"] += max(
                    0.0,
                    time.time() - task.submitted,
                )
                try:
                    results = future.result()
                except Exception as exc:
                    state.inflight.difference_update(task.candidates)
                    state.failed = True
                    state.status = "WORKER_ERROR"
                    state.last_abort_reason = f"{type(exc).__name__}: {exc}"
                    state.next_action = "STOP_AND_AUDIT"
                    state.totals["worker_errors"] += 1
                    if state.completed_at <= 0:
                        state.completed_at = time.time()
                    state.last_activity_at = state.completed_at
                    _append_jsonl(
                        state.events_path,
                        {
                            "event": "WORKER_ERROR",
                            "time": time.time(),
                            "task": asdict(task),
                            "error": state.last_abort_reason,
                        },
                    )
                    continue
                _handle_worker_result(state, task, results)
                if (
                    time.time() - state.last_checkpoint_time
                    >= args.checkpoint_interval
                    and not state.inflight
                    and not state.proposals
                ):
                    _persist_state(state, state.last_abort_reason or "POOL_PROGRESS")

            _write_json_atomic(
                summary_path,
                _campaign_summary(
                    states,
                    started,
                    deadline,
                    hardware,
                    "RUNNING",
                    dispatch_seq,
                    pool_metrics,
                    source_manifest,
                ),
            )
            last_summary_write = time.time()

        if time.time() >= deadline:
            status = "DRAINING_AT_DEADLINE"
        while future_tasks or proposal_tasks:
            done, _pending = wait(
                tuple(future_tasks) + tuple(proposal_tasks),
                return_when=FIRST_COMPLETED,
            )
            for future in [item for item in done if item in proposal_tasks]:
                task = proposal_tasks.pop(future)
                state = states_by_key[task.key]
                pool_metrics["proposal_barriers_completed"] += 1
                pool_metrics["proposal_barrier_busy_seconds"] += max(
                    0.0,
                    time.time() - task.submitted,
                )
                try:
                    result = future.result()
                    _apply_proposal_barrier(state, task, result)
                except Exception as exc:
                    state.commit_inflight = False
                    state.failed = True
                    state.status = "PROPOSAL_BARRIER_ERROR"
                    state.last_abort_reason = f"{type(exc).__name__}: {exc}"
                    state.next_action = "STOP_AND_AUDIT"
                    state.totals["worker_errors"] += 1
                    if state.completed_at <= 0:
                        state.completed_at = time.time()
                    state.last_activity_at = state.completed_at
            for future in done:
                if future not in future_tasks:
                    continue
                task = future_tasks.pop(future)
                state = states_by_key[task.key]
                pool_metrics["tasks_completed"] += 1
                pool_metrics["worker_busy_seconds"] += max(
                    0.0,
                    time.time() - task.submitted,
                )
                try:
                    results = future.result()
                    _handle_worker_result(state, task, results)
                except Exception as exc:
                    state.inflight.difference_update(task.candidates)
                    state.failed = True
                    state.status = "WORKER_ERROR"
                    state.last_abort_reason = f"{type(exc).__name__}: {exc}"
                    state.next_action = "STOP_AND_AUDIT"
                    state.totals["worker_errors"] += 1
                    if state.completed_at <= 0:
                        state.completed_at = time.time()
                    state.last_activity_at = state.completed_at

    finalize_proposals = (
        time.time() < deadline
        and status not in {"DRAINING_AT_DEADLINE", "SOURCE_CHANGED_CHECKPOINT"}
    )
    for state in states:
        if finalize_proposals:
            _finalize_proposals(state)
        _mark_terminal_states([state])
        if (
            not state.complete
            and not state.failed
            and state.status != "UNRESOLVED_BUDGETS_EXHAUSTED"
        ):
            state.status = "TIME_BUDGET_CHECKPOINT"
            if state.completed_at <= 0:
                state.completed_at = time.time()
            state.last_activity_at = state.completed_at
        _persist_state(state, state.status)
        verify, _seconds, _output = run_abc_cec(
            state.source_path,
            state.output_path,
            timeout=args.cec_timeout,
        )
        if verify != "PASS":
            state.failed = True
            state.status = "FINAL_CEC_FAILED"
            state.last_abort_reason = "FINAL_CEC_FAILED"
            state.next_action = "STOP_AND_AUDIT"
            if state.completed_at <= 0:
                state.completed_at = time.time()
            state.last_activity_at = state.completed_at

    if all(state.complete for state in states):
        status = "ALL_TARGETS_COMPLETE"
    elif any(state.failed for state in states):
        status = "FINISHED_WITH_FAILURES"
    elif status == "DRAINING_AT_DEADLINE":
        status = "TIME_BUDGET_COMPLETE"
    summary = _campaign_summary(
        states,
        started,
        deadline,
        hardware,
        status,
        dispatch_seq,
        pool_metrics,
        source_manifest,
    )
    _write_json_atomic(summary_path, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dynamic reason-aware cross-circuit exact-TFO worker pool."
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seconds", type=int, default=21600)
    parser.add_argument(
        "--jobs",
        type=int,
        default=0,
        help="global worker processes; 0 uses the hardware-safe physical-core count",
    )
    parser.add_argument("--budgets", default="10000,50000,250000,1000000,5000000")
    parser.add_argument("--budget-growth", type=float, default=2.0)
    parser.add_argument("--max-generated-budget", type=int, default=0)
    parser.add_argument("--microbatch-size", type=int, default=16)
    parser.add_argument(
        "--retry-microbatch-size",
        type=int,
        default=1,
        help="candidate count per timeout-retry task",
    )
    parser.add_argument(
        "--persistent-retry-tiers",
        type=int,
        default=1,
        help="number of increasing timeout-retry budgets to solve in one persistent worker task",
    )
    parser.add_argument(
        "--worker-cache-entries",
        type=int,
        default=0,
        help="per-process parsed circuit/gate graph cache entries",
    )
    parser.add_argument(
        "--deadline-reserve-seconds",
        type=float,
        default=300.0,
        help="reserve final wall time for checkpointing and CEC",
    )
    parser.add_argument(
        "--unknown-task-guard-seconds",
        type=float,
        default=900.0,
        help="do not dispatch tasks without timing evidence inside this final window",
    )
    parser.add_argument("--checkpoint-interval", type=float, default=60.0)
    parser.add_argument("--max-targets", type=int, default=6)
    parser.add_argument(
        "--target-filter",
        default=",".join(benchmark.DEFAULT_FILTERS),
    )
    parser.add_argument("--checkpoint-dir", action="append", default=[])
    parser.add_argument("--solver", default="cadical153")
    parser.add_argument("--order", default="proof_reverse_portfolio")
    parser.add_argument("--cec-timeout", type=float, default=180.0)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    run_dynamic_campaign(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
