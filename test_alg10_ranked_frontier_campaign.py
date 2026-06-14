#!/usr/bin/env python3
"""Tests for ranked Alg10 frontier campaign selection."""

import json
import os
import shutil
import tempfile

import alg10_ranked_frontier_campaign as campaign


def write_aag(path, gates):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="ascii") as f:
        f.write(f"aag {gates + 2} 2 0 1 {gates}\n")
        f.write("2\n")
        f.write("4\n")
        f.write("2\n")
        lhs = 6
        for _ in range(gates):
            f.write(f"{lhs} 2 4\n")
            lhs += 2
        f.write("c\nfixture\n")


def write_checkpoint(directory, name, source, work, unresolved, current_gates, candidates):
    os.makedirs(directory, exist_ok=True)
    data = {
        "algorithm": "ALG10",
        "source_path": source,
        "source_sha256": campaign.sha256_file(source),
        "work_aag": work,
        "current_gates": current_gates,
        "timestamp": float(unresolved),
        "status": "TIME_BUDGET_CHECKPOINT",
        "telemetry": {"unresolved": unresolved},
        "phase_resume": {
            "schema": "alg10_global_frontier_v1",
            "tier": "global",
            "reason": "unit",
            "work_sha256": campaign.sha256_file(work),
            "gate_count": current_gates,
            "candidates": candidates,
        },
    }
    path = os.path.join(directory, name + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    return path


def test_rank_targets_prefers_low_unresolved_then_high_removed():
    targets = [
        campaign.FrontierTarget("b", "b.json", "b.work", "b.aag", 10, 10, 10, 7, 20, 13, "global", "", 1.0),
        campaign.FrontierTarget("a", "a.json", "a.work", "a.aag", 5, 5, 5, 1, 20, 19, "global", "", 1.0),
        campaign.FrontierTarget("c", "c.json", "c.work", "c.aag", 10, 10, 10, 9, 20, 11, "global", "", 1.0),
    ]
    ranked = campaign.rank_targets(targets, filters=(), dedupe=False)
    assert [target.key for target in ranked] == ["a", "c", "b"]


def test_load_ranked_targets_dedupes_best_checkpoint_read_only():
    with tempfile.TemporaryDirectory(prefix="alg10_ranked_campaign_") as tmp:
        src = os.path.join(tmp, "custom_epfl_arithmetic_sin.aag")
        work_best = os.path.join(tmp, "sin_best.work.aag")
        work_worse = os.path.join(tmp, "sin_worse.work.aag")
        write_aag(src, 8)
        write_aag(work_best, 5)
        write_aag(work_worse, 4)

        ckpt = os.path.join(tmp, "ckpt")
        best_json = write_checkpoint(
            ckpt,
            "best",
            src,
            work_best,
            unresolved=3,
            current_gates=5,
            candidates=[[0, 0, 0], [1, 0, 0], [2, 0, 0]],
        )
        worse_json = write_checkpoint(
            ckpt,
            "worse",
            src,
            work_worse,
            unresolved=8,
            current_gates=4,
            candidates=[[0, 0, 0]] * 8,
        )

        targets = campaign.load_ranked_targets([ckpt], filters=("sin",), max_targets=10)
        assert len(targets) == 1
        assert targets[0].json_path == os.path.abspath(best_json)
        assert targets[0].unresolved == 3
        assert targets[0].removed == 3
        assert campaign.sha256_file(best_json) == campaign.sha256_file(best_json)
        assert os.path.exists(worse_json)


def run_all():
    test_rank_targets_prefers_low_unresolved_then_high_removed()
    test_load_ranked_targets_dedupes_best_checkpoint_read_only()
    print("alg10 ranked frontier campaign tests passed")


if __name__ == "__main__":
    run_all()
