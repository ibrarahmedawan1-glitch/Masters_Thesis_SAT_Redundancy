#!/usr/bin/env python3
"""Tests for the PySAT persistent-assumption audit experiment."""

import hashlib
import os
import tempfile

import alg10_frontier_shard_probe as probe
import pysat_assumption_reuse_experiment as exp


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_status_family_normalizes_probe_statuses():
    assert exp.status_family(probe.STATUS_SAT_REJECT) == "SAT"
    assert exp.status_family(probe.STATUS_UNSAT_PROPOSED) == "UNSAT"
    assert exp.status_family(probe.STATUS_TIMEOUT) == "TIMEOUT"


def test_persistent_assumption_global_agrees_with_exact_tfo_on_full_c17_frontier():
    src = os.path.abspath("benchmarks/c17.aag")
    before = sha256_file(src)
    with tempfile.TemporaryDirectory(prefix="pysat_assumption_reuse_") as tmp:
        report = exp.run_experiment(
            exp.ExperimentConfig(
                circuit=src,
                limit=0,
                solver="glucose4",
                global_budget=0,
                audit_budget=0,
                phase_modes=("none", "controls_false", "model"),
                checkpoint_dir=os.path.join(tmp, "ckpt"),
                use_checkpoint=False,
            )
        )
        assert report["strict_ok"], report
        assert report["frontier"]["frontier_source"] == "fresh_all_candidates"
        assert report["frontier"]["candidate_count_tested"] > 0
        for variant in report["variants"]:
            comparison = variant["comparison_to_tfo"]
            assert comparison["mismatches"] == []
            assert comparison["unaudited_unsat"] == []
            assert comparison["resolved_global"] == report["frontier"]["candidate_count_tested"]
    assert sha256_file(src) == before


def test_global_assumption_audit_catches_control_tamper():
    src = os.path.abspath("benchmarks/c17.aag")
    with tempfile.TemporaryDirectory(prefix="pysat_assumption_reuse_audit_") as tmp:
        config = probe.Alg10Config(
            checkpoint_dir=os.path.join(tmp, "ckpt"),
            extra_checkpoint_dirs=(),
            frontier_order="current",
            solver="glucose4",
            phase_mode="none",
            engine="global",
        )
        opt = probe._load_alg10(config)
        parsed = opt.parse_aag(src)
        _, _, _, _, _, inputs, latches, outputs, gates_raw, _ = parsed
        roots = outputs + [opt._parse_latch(latch)[1] for latch in latches]
        clauses, miter_lit, f0_lits, f1_lits = opt._build_fault_sweep_cnf(
            inputs,
            latches,
            roots,
            gates_raw,
        )
        del clauses
        gate_count = len(gates_raw)
        idx, stuck_value = 0, 0
        pos, lit, opposite_pos, opposite_lit = opt._control_position(
            gate_count,
            idx,
            stuck_value,
            f0_lits,
            f1_lits,
        )
        assumptions = [-lit0 for lit0 in f0_lits] + [-lit1 for lit1 in f1_lits]
        assumptions[pos] = lit
        assumptions[opposite_pos] = -opposite_lit
        assumptions.append(miter_lit)
        opt._audit_global_assumptions(
            assumptions,
            gate_count,
            f0_lits=f0_lits,
            f1_lits=f1_lits,
            candidate=(idx, stuck_value),
            accepted={},
            miter_lit=miter_lit,
        )

        corrupted = assumptions.copy()
        corrupted[opposite_pos] = opposite_lit
        try:
            opt._audit_global_assumptions(
                corrupted,
                gate_count,
                f0_lits=f0_lits,
                f1_lits=f1_lits,
                candidate=(idx, stuck_value),
                accepted={},
                miter_lit=miter_lit,
            )
        except AssertionError:
            pass
        else:
            raise AssertionError("corrupted global assumption vector was not rejected")


def test_report_writer_emits_json_and_csv():
    src = os.path.abspath("benchmarks/c17.aag")
    with tempfile.TemporaryDirectory(prefix="pysat_assumption_reuse_report_") as tmp:
        report = exp.run_experiment(
            exp.ExperimentConfig(
                circuit=src,
                limit=4,
                solver="glucose4",
                global_budget=0,
                audit_budget=0,
                phase_modes=("none",),
                checkpoint_dir=os.path.join(tmp, "ckpt"),
                use_checkpoint=False,
            )
        )
        paths = exp.write_report(report, os.path.join(tmp, "report"))
        assert os.path.exists(paths["summary_json"])
        assert os.path.exists(paths["candidate_details_csv"])


def run_all():
    test_status_family_normalizes_probe_statuses()
    test_persistent_assumption_global_agrees_with_exact_tfo_on_full_c17_frontier()
    test_global_assumption_audit_catches_control_tamper()
    test_report_writer_emits_json_and_csv()
    print("PySAT assumption reuse experiment tests passed")


if __name__ == "__main__":
    run_all()
