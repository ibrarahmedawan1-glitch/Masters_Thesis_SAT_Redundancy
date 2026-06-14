#!/usr/bin/env python3
"""Focused tests for the Alg10 parallel portfolio launcher."""

import argparse
import os
import tempfile

import alg10_parallel_portfolio as portfolio


def test_worker_timestamps_are_unique_and_safe():
    task = portfolio.Task("sin/untried", "benchmark_suites/epfl/epfl_arithmetic_sin.aag")
    first = portfolio._worker_timestamp("tag with spaces", task)
    second = portfolio._worker_timestamp("tag with spaces", task)
    assert first != second
    assert " " not in first
    assert "/" not in first
    assert "tag_with_spaces" in first
    assert "sin_untried" in first


def test_worker_env_is_isolated():
    task = portfolio.Task("sin", "benchmark_suites/epfl/epfl_arithmetic_sin.aag")
    timestamp = portfolio._worker_timestamp("unit", task)
    with tempfile.TemporaryDirectory() as tmp:
        extra = os.path.join(tmp, "extra")
        os.mkdir(extra)
        args = argparse.Namespace(
            seconds=123,
            budgets="1,2,3",
            extra_checkpoint_dir=[extra],
            include_finished_siblings=False,
            solver="cadical153",
            phase_mode="model",
            max_consec_timeouts=7,
        )
        env = portfolio.build_env(args, task, os.path.join(tmp, "ckpt"), [], timestamp)

    assert env["THESIS_RUN_TIMESTAMP"] == timestamp
    assert env["ALG10_TOTAL_SECONDS"] == "123"
    assert env["ALG10_BUDGETS"] == "1,2,3"
    assert env["ALG10_CHECKPOINT_SELECT"] == "unresolved"
    assert env["ALG10_PHASE_LOCAL_RESUME"] == "1"
    assert env["ALG10_EXACT_FRONTIER_RESUME"] == "1"
    assert env["ALG10_GLOBAL_MAX_CONSEC_TIMEOUTS"] == "7"
    assert extra in env["ALG10_EXTRA_CHECKPOINT_DIRS"]


def run_all():
    test_worker_timestamps_are_unique_and_safe()
    test_worker_env_is_isolated()
    print("alg10 parallel portfolio tests passed")


if __name__ == "__main__":
    run_all()
