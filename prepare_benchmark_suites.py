#!/usr/bin/env python3
"""
Prepare reusable AAG benchmark suites for the thesis pipeline.

This script does one-time conversion/copying into `benchmark_suites/`.
`main.py` then copies prepared `.aag` files from that directory into each
fresh dataset run, next to the generated fuzz circuits and existing ISCAS
benchmarks.

Supported inputs:
- local EPFL `.aig` files under `epfl_benchmarks/`;
- IWLS 2005 mapped Verilog netlists;
- optional external directories containing `.aig`, `.aag`, `.v`, or `.blif` files.
"""

import argparse
import csv
import os
import shlex
import shutil
import subprocess

from abc_utils import normalize_aag_symbols, to_ascii_aag


DEFAULT_EPFL_DIR = "epfl_benchmarks"
DEFAULT_OUT_DIR = "benchmark_suites"


def _safe_name(path):
    name = os.path.splitext(os.path.basename(path))[0]
    safe = []
    for ch in name.lower():
        safe.append(ch if ch.isalnum() else "_")
    return "".join(safe).strip("_") or "circuit"


def _parse_aag_stats(path):
    try:
        with open(path, "r", encoding="ascii", errors="ignore") as f:
            header = f.readline().strip().split()
        if len(header) < 6 or header[0] != "aag":
            return None
        M, I, L, O, A = map(int, header[1:6])
        return {"M": M, "I": I, "L": L, "O": O, "A": A, "Area_AND2": A}
    except Exception:
        return None


def _record(rows, suite, source, target, status, note=""):
    stats = _parse_aag_stats(target) if status == "OK" else None
    rows.append(
        {
            "Suite": suite,
            "Source": source,
            "Target": target,
            "Status": status,
            "Inputs": stats["I"] if stats else "",
            "Latches": stats["L"] if stats else "",
            "Outputs": stats["O"] if stats else "",
            "Gates": stats["A"] if stats else "",
            "Area_AND2": stats["Area_AND2"] if stats else "",
            "Bytes": os.path.getsize(target) if status == "OK" and os.path.exists(target) else "",
            "Note": note,
        }
    )


def _prepare_aig(source, target, force=False):
    if os.path.exists(target) and not force:
        return "OK", "already exists"
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if to_ascii_aag(source, target, comment="Prepared benchmark suite"):
        return "OK", "converted aig to aag"
    return "ERROR", "aig conversion failed"


def _prepare_aag(source, target, force=False):
    if os.path.exists(target) and not force:
        return "OK", "already exists"
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copy(source, target)
    if normalize_aag_symbols(target, comment="Prepared benchmark suite"):
        return "OK", "copied and normalized aag"
    return "ERROR", "copied file is not valid aag"


def _prepare_verilog(
    source,
    target,
    force=False,
    library_files=None,
    include_dirs=None,
    top=None,
    timeout=180,
):
    if os.path.exists(target) and not force:
        return "OK", "already exists"
    if shutil.which("yosys") is None:
        return "ERROR", "yosys not found"

    os.makedirs(os.path.dirname(target), exist_ok=True)
    log_path = target + ".log"
    read_parts = []
    include_opt = " ".join(f"-I{shlex.quote(path)}" for path in (include_dirs or []))
    for lib in library_files or []:
        read_parts.append(f"read_verilog -sv {include_opt} {shlex.quote(lib)}")
    read_parts.append(f"read_verilog -sv {include_opt} {shlex.quote(source)}")
    hierarchy = f"hierarchy -check -top {shlex.quote(top)}" if top else "hierarchy -check -auto-top"
    script = "; ".join(
        read_parts
        + [
            hierarchy,
            "proc",
            "opt",
            "flatten",
            "opt",
            "techmap",
            "opt",
            "abc -g AND",
            f"write_aiger -ascii {shlex.quote(target)}",
        ]
    )
    with open(log_path, "w", encoding="utf-8") as log:
        try:
            result = subprocess.run(
                ["yosys", "-p", script],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return "ERROR", f"yosys timed out; see {log_path}"
    if result.returncode != 0:
        return "ERROR", f"yosys failed; see {log_path}"
    if normalize_aag_symbols(target, comment="Prepared Verilog benchmark suite"):
        return "OK", "synthesized verilog to aag"
    return "ERROR", "yosys output is not valid aag"


def _prepare_blif(source, target, force=False, timeout=180):
    if os.path.exists(target) and not force:
        return "OK", "already exists"
    if shutil.which("yosys") is None:
        return "ERROR", "yosys not found"

    os.makedirs(os.path.dirname(target), exist_ok=True)
    log_path = target + ".log"
    script = (
        f"read_blif {shlex.quote(source)}; "
        "hierarchy -check -auto-top; proc; opt; techmap; opt; abc -g AND; "
        f"write_aiger -ascii {shlex.quote(target)}"
    )
    with open(log_path, "w", encoding="utf-8") as log:
        try:
            result = subprocess.run(
                ["yosys", "-p", script],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return "ERROR", f"yosys timed out; see {log_path}"
    if result.returncode != 0:
        return "ERROR", f"yosys failed; see {log_path}"
    if normalize_aag_symbols(target, comment="Prepared BLIF benchmark suite"):
        return "OK", "converted blif to aag"
    return "ERROR", "yosys output is not valid aag"


def prepare_epfl(epfl_dir, out_dir, force=False):
    rows = []
    if not os.path.exists(epfl_dir):
        return rows

    for root, _, files in os.walk(epfl_dir):
        category = os.path.basename(root)
        for filename in sorted(files):
            if not filename.endswith(".aig"):
                continue
            source = os.path.join(root, filename)
            target_name = f"epfl_{category}_{_safe_name(filename)}.aag"
            target = os.path.join(out_dir, "epfl", target_name)
            status, note = _prepare_aig(source, target, force=force)
            _record(rows, "EPFL", source, target, status, note)
    return rows


def prepare_iwls2005(iwls_dir, out_dir, force=False, timeout=180):
    rows = []
    if not iwls_dir or not os.path.exists(iwls_dir):
        return rows

    library = os.path.join(iwls_dir, "library", "GSCLib_3.0.v")
    library_files = [library] if os.path.exists(library) else []
    include_dirs = [os.path.dirname(library)] if library_files else []

    for family in ("faraday", "itc99", "gaisler", "opencores", "iscas"):
        netlist_dir = os.path.join(iwls_dir, family, "netlist")
        if not os.path.isdir(netlist_dir):
            continue
        for filename in sorted(os.listdir(netlist_dir)):
            if not filename.endswith(".v"):
                continue
            source = os.path.join(netlist_dir, filename)
            target_name = f"iwls2005_{family}_{_safe_name(filename)}.aag"
            target = os.path.join(out_dir, "iwls2005", target_name)
            status, note = _prepare_verilog(
                source,
                target,
                force=force,
                library_files=library_files,
                include_dirs=include_dirs,
                timeout=timeout,
            )
            _record(rows, "IWLS2005", source, target, status, note)

    blif_dir = os.path.join(iwls_dir, "iscas", "blif")
    if os.path.isdir(blif_dir):
        for filename in sorted(os.listdir(blif_dir)):
            if not filename.endswith(".blif"):
                continue
            source = os.path.join(blif_dir, filename)
            target_name = f"iwls2005_iscas_blif_{_safe_name(filename)}.aag"
            target = os.path.join(out_dir, "iwls2005", target_name)
            status, note = _prepare_blif(source, target, force=force, timeout=timeout)
            _record(rows, "IWLS2005", source, target, status, note)

    return rows


def prepare_external(extra_dirs, out_dir, force=False):
    rows = []
    for extra_dir in extra_dirs:
        if not os.path.exists(extra_dir):
            continue
        for root, _, files in os.walk(extra_dir):
            rel = os.path.relpath(root, extra_dir)
            prefix = "" if rel == "." else rel.replace(os.sep, "_") + "_"
            for filename in sorted(files):
                if not (
                    filename.endswith(".aig")
                    or filename.endswith(".aag")
                    or filename.endswith(".v")
                    or filename.endswith(".blif")
                ):
                    continue
                source = os.path.join(root, filename)
                target_name = f"external_{prefix}{_safe_name(filename)}.aag"
                target = os.path.join(out_dir, "external", target_name)
                if filename.endswith(".aig"):
                    status, note = _prepare_aig(source, target, force=force)
                elif filename.endswith(".v"):
                    status, note = _prepare_verilog(source, target, force=force)
                elif filename.endswith(".blif"):
                    status, note = _prepare_blif(source, target, force=force)
                else:
                    status, note = _prepare_aag(source, target, force=force)
                _record(rows, "External", source, target, status, note)
    return rows


def write_manifest(rows, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    manifest = os.path.join(out_dir, "manifest.csv")
    fieldnames = [
        "Suite",
        "Source",
        "Target",
        "Status",
        "Inputs",
        "Latches",
        "Outputs",
        "Gates",
        "Area_AND2",
        "Bytes",
        "Note",
    ]
    with open(manifest, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epfl-dir", default=DEFAULT_EPFL_DIR)
    parser.add_argument("--iwls2005-dir", default="")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--extra-src", action="append", default=[], help="additional directory with .aig/.aag files")
    parser.add_argument("--yosys-timeout", type=int, default=180)
    parser.add_argument("--force", action="store_true", help="re-convert files even if target exists")
    args = parser.parse_args()

    rows = []
    rows.extend(prepare_epfl(args.epfl_dir, args.out_dir, force=args.force))
    rows.extend(
        prepare_iwls2005(
            args.iwls2005_dir,
            args.out_dir,
            force=args.force,
            timeout=args.yosys_timeout,
        )
    )
    rows.extend(prepare_external(args.extra_src, args.out_dir, force=args.force))
    manifest = write_manifest(rows, args.out_dir)

    ok = sum(1 for row in rows if row["Status"] == "OK")
    err = sum(1 for row in rows if row["Status"] != "OK")
    print(f"[DONE] Prepared {ok} benchmark files, {err} errors.")
    print(f"[DONE] Manifest: {manifest}")


if __name__ == "__main__":
    main()
