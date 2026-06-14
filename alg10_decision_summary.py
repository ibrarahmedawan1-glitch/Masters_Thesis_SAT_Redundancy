#!/usr/bin/env python3
"""Summarize Alg10 frontier-fixed decision runs.

The goal is to make the overnight decision mechanical: compare the latest row
for each relevant circuit against the corrected frontier baselines and flag
runs that did no new SAT work because all configured budgets were exhausted.
"""

from __future__ import annotations

import csv
import os
import sys


BASELINES = {
    "sin": 16,
    "div": 955,
    "sqrt": 368,
    "hyp": 946,
    "log2": 10764,
    "mem_ctrl": 8466,
    "voter": 0,
}

TARGETS = {
    "sin": 0,
    "div": 764,
    "sqrt": 331,
    "hyp": 851,
    "voter": 0,
}

DISPLAY = {
    "sin": "sin",
    "div": "div",
    "sqrt": "sqrt",
    "hyp": "hyp",
    "log2": "log2",
    "mem_ctrl": "mem_ctrl",
    "voter": "voter",
}


def _int(value, default=0):
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        return int(float(text.replace("%", "")))
    except ValueError:
        return default


def _float(value, default=0.0):
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        return float(text.replace("%", ""))
    except ValueError:
        return default


def circuit_key(name):
    lower = os.path.basename(name or "").lower()
    if "mem_ctrl" in lower:
        return "mem_ctrl"
    for key in ("log2", "sqrt", "hyp", "div", "sin", "voter"):
        if key in lower:
            return key
    return None


def latest_rows(path):
    rows = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = circuit_key(row.get("Circuit", ""))
            if key:
                rows[key] = row
    return rows


def verdict_for(key, row):
    unresolved = _int(row.get("SAT_Unresolved"))
    baseline = BASELINES.get(key)
    target = TARGETS.get(key)
    if key == "mem_ctrl":
        if unresolved < baseline:
            return "diagnostic improved"
        if unresolved == baseline:
            return "diagnostic unchanged"
        return "diagnostic worse/new seed"
    if key == "log2":
        if unresolved < baseline:
            return "improved"
        if unresolved == baseline:
            return "unchanged"
        return "worse/new seed"
    if target is not None and unresolved <= target:
        return "target met"
    if baseline is not None and unresolved < baseline:
        return "partial progress"
    return "missed"


def summarize_path(path):
    rows = latest_rows(path)
    if not rows:
        print(f"\n{path}: no tracked circuits found")
        return False

    print(f"\n{path}")
    print("-" * min(100, len(path)))
    print(
        "circuit      unresolved  baseline  delta   target    removed  new  "
        "checks  timeouts  skipped  exhausted  verify  verdict"
    )

    informative = False
    any_primary_progress = False
    all_skipped = True
    target_misses = []
    target_rows = 0

    for key in ("sin", "div", "sqrt", "hyp", "log2", "mem_ctrl", "voter"):
        row = rows.get(key)
        if not row:
            continue
        unresolved = _int(row.get("SAT_Unresolved"))
        baseline = BASELINES.get(key, 0)
        delta = baseline - unresolved
        target = TARGETS.get(key, "")
        removed = _int(row.get("Gates_Removed"))
        new_removed = _int(row.get("New_Removed_This_Run"))
        checks = _int(row.get("SAT_Checks"))
        timeouts = _int(row.get("SAT_Timeouts"))
        skipped = _int(row.get("Global_Budget_History_Skipped"))
        exhausted = _int(row.get("Global_Budget_History_Exhausted"))
        verify = row.get("Verify", "")
        verdict = verdict_for(key, row)

        if checks > 0 or new_removed > 0 or delta > 0:
            informative = True
        if checks > 0:
            all_skipped = False
        if key in {"sin", "div", "sqrt", "hyp"} and verdict in {
            "target met",
            "partial progress",
        }:
            any_primary_progress = True
        if target != "":
            target_rows += 1
            if unresolved > _int(target):
                target_misses.append(key)

        print(
            f"{DISPLAY[key]:<11} {unresolved:>10} {baseline:>9} {delta:>6} "
            f"{str(target):>8} {removed:>8} {new_removed:>4} {checks:>7} "
            f"{timeouts:>9} {skipped:>8} {exhausted:>10} {verify:>6}  {verdict}"
        )

    print("\nDecision:")
    if target_rows and not target_misses:
        print("  Already at target for the selected circuit rows.")
        return True
    if all_skipped and not informative:
        print(
            "  NOT INFORMATIVE: this run mostly loaded checkpoints and skipped "
            "already exhausted budgets."
        )
        print(
            "  Rerun with higher ALG10_BUDGETS, for example "
            "1000000,2000000,5000000."
        )
        return False

    if rows.get("sin") and _int(rows["sin"].get("SAT_Unresolved")) == 0:
        print("  Strong signal: sin reached zero unresolved.")
    if any_primary_progress:
        print("  Worth continuing: at least one finish-line circuit improved.")
        return True

    timeout_total = sum(_int(row.get("SAT_Timeouts")) for row in rows.values())
    check_total = sum(_int(row.get("SAT_Checks")) for row in rows.values())
    unsat_total = sum(_int(row.get("SAT_Query_UNSAT")) for row in rows.values())
    sat_total = sum(_int(row.get("SAT_Query_SAT")) for row in rows.values())
    if check_total and timeout_total >= max(1, int(0.8 * check_total)) and unsat_total == 0:
        print(
            "  Likely plateau: new SAT work was mostly timeouts and produced no "
            "UNSAT accepts."
        )
        return False

    if sat_total or unsat_total or check_total:
        print("  Mixed/diagnostic: inspect per-circuit rows before another long run.")
        return True

    print("  No clear signal.")
    return False


def main(argv):
    if len(argv) < 2:
        print("usage: venv/bin/python alg10_decision_summary.py REPORT.csv [REPORT2.csv ...]")
        return 2
    for path in argv[1:]:
        summarize_path(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
