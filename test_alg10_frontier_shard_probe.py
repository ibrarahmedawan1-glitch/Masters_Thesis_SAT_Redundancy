#!/usr/bin/env python3
"""Tests for the read-only Alg10 intra-circuit shard probe."""

import hashlib
import json
import os
import shutil
import tempfile

import alg10_frontier_shard_probe as probe


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_split_shards_is_complete_and_disjoint():
    items = [(ordinal, ordinal // 2, ordinal % 2) for ordinal in range(17)]
    shards = probe.split_shards(items, 4)
    flattened = [item for shard in shards for item in shard]
    assert sorted(flattened) == items
    assert len(flattened) == len(set(flattened))
    assert max(len(shard) for shard in shards) - min(len(shard) for shard in shards) <= 1


def test_fresh_serial_parallel_match_without_writes():
    src = os.path.abspath("benchmarks/c17.aag")
    before = sha256_file(src)
    with tempfile.TemporaryDirectory(prefix="alg10_probe_fresh_") as tmp:
        config = probe.Alg10Config(
            checkpoint_dir=os.path.join(tmp, "ckpt"),
            extra_checkpoint_dirs=(),
            frontier_order="current",
            solver="glucose4",
            phase_mode="none",
        )
        frontier = probe.load_frontier(src, config, limit=8, use_checkpoint=False)
        assert frontier["frontier_source"] == "fresh_all_candidates"
        assert frontier["candidate_count_tested"] == 8

        serial = probe.run_serial(frontier["work_path"], frontier["work_items"], 1000, config)
        parallel = probe.run_parallel(
            frontier["work_path"], frontier["work_items"], 1000, config, jobs=2
        )
        comparison = probe.compare_results(serial["results"], parallel["results"])
        assert comparison["match"], comparison
        assert len(serial["results"]) == 8
        assert len(parallel["results"]) == 8

    assert sha256_file(src) == before


def test_checkpoint_global_frontier_is_loaded_read_only():
    src = os.path.abspath("benchmarks/c17.aag")
    with tempfile.TemporaryDirectory(prefix="alg10_probe_ckpt_") as tmp:
        ckpt_dir = os.path.join(tmp, "ckpt")
        os.makedirs(ckpt_dir)
        work_path = os.path.join(tmp, "c17.work.aag")
        shutil.copyfile(src, work_path)

        config = probe.Alg10Config(
            checkpoint_dir=ckpt_dir,
            extra_checkpoint_dirs=(),
            frontier_order="current",
            solver="glucose4",
            phase_mode="none",
        )
        opt = probe._load_alg10(config)
        _, _, _, _, _, _, _, _, gates_raw, _ = opt.parse_aag(work_path)
        candidates = [[0, 0, 0], [1, 1, 100]]
        data = {
            "algorithm": "ALG10",
            "source_path": src,
            "source_sha256": sha256_file(src),
            "work_aag": work_path,
            "current_gates": len(gates_raw),
            "timestamp": 1.0,
            "telemetry": {"unresolved": len(candidates)},
            "phase_resume": {
                "schema": "alg10_global_frontier_v1",
                "tier": "global",
                "reason": "unit_test",
                "work_sha256": sha256_file(work_path),
                "gate_count": len(gates_raw),
                "candidates": candidates,
            },
        }
        checkpoint_json = os.path.join(ckpt_dir, "c17_unit.json")
        with open(checkpoint_json, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)

        before_json = sha256_file(checkpoint_json)
        before_work = sha256_file(work_path)
        frontier = probe.load_frontier(src, config, limit=10, use_checkpoint=True)
        assert frontier["frontier_source"] == "checkpoint_global_frontier"
        assert frontier["phase_valid"] is True
        assert frontier["phase_tier"] == "global"
        assert frontier["candidate_count_available"] == 2
        assert frontier["candidate_count_tested"] == 2
        assert frontier["work_items"] == [(0, 0, 0), (1, 1, 1)]

        parallel = probe.run_parallel(
            frontier["work_path"], frontier["work_items"], 1000, config, jobs=2
        )
        assert len(parallel["results"]) == 2
        assert sha256_file(checkpoint_json) == before_json
        assert sha256_file(work_path) == before_work


def test_unsat_results_are_labeled_as_proposals():
    src = os.path.abspath("benchmarks/c17.aag")
    with tempfile.TemporaryDirectory(prefix="alg10_probe_unsat_") as tmp:
        config = probe.Alg10Config(
            checkpoint_dir=os.path.join(tmp, "ckpt"),
            extra_checkpoint_dirs=(),
            frontier_order="current",
            solver="glucose4",
            phase_mode="none",
        )
        frontier = probe.load_frontier(src, config, limit=4, use_checkpoint=False)
        serial = probe.run_serial(frontier["work_path"], frontier["work_items"], 0, config)
        statuses = {item["status"] for item in serial["results"]}
        allowed = {
            probe.STATUS_SAT_REJECT,
            probe.STATUS_TIMEOUT,
            probe.STATUS_UNSAT_PROPOSED,
        }
        assert statuses.issubset(allowed)
        assert "UNSAT_ACCEPT" not in statuses


def run_all():
    test_split_shards_is_complete_and_disjoint()
    test_fresh_serial_parallel_match_without_writes()
    test_checkpoint_global_frontier_is_loaded_read_only()
    test_unsat_results_are_labeled_as_proposals()
    print("alg10 frontier shard probe tests passed")


if __name__ == "__main__":
    run_all()
