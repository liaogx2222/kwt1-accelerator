#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run controlled PTQ threshold/activation-bit sweeps around the existing KWT-1 script.

Place this file at <repo>/scripts/run_kwt1_ptq_sensitivity_sweep.py.
It reads but never edits the original validate_kwt1_ptq_activations.py. Variant scripts
are copied beside the original to preserve the original script's path assumptions.
"""
from __future__ import annotations
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

THRESHOLD_ASSIGNMENT = re.compile(
    r"(?im)^([ \t]*(?:SCALE_THRESHOLD_SOURCE|scale_threshold_source|THRESHOLD_SOURCE|threshold_source)\s*=\s*)(['\"])abs_p999_est\2"
)
THRESHOLD_DEFAULT = re.compile(r"(?i)(default\s*=\s*)(['\"])abs_p999_est\2")
BITS_ASSIGNMENT = re.compile(
    r"(?im)^([ \t]*(?:SIGNED_ACTIVATION_BITS|signed_activation_bits|ACTIVATION_BITS|activation_bits|ACT_BITS|act_bits)\s*=\s*)8\b"
)


def patch_threshold(source: str) -> tuple[str, int]:
    updated, count = THRESHOLD_ASSIGNMENT.subn(lambda m: m.group(1) + repr("abs_p99_est"), source)
    if count == 0:
        # argparse may keep threshold source as a parser default instead of a module constant.
        lines = updated.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if "abs_p999_est" in line and ("threshold" in line.lower() or "scale" in line.lower()):
                new, n = THRESHOLD_DEFAULT.subn(lambda m: m.group(1) + repr("abs_p99_est"), line)
                if n:
                    lines[i] = new
                    count += n
        updated = "".join(lines)
    if count == 0:
        raise RuntimeError(
            "Cannot safely locate the abs_p999_est threshold selector in the existing script. "
            "No files were executed. Inspect the threshold-source assignment/default in "
            "scripts/validate_kwt1_ptq_activations.py and adapt THRESHOLD_ASSIGNMENT/THRESHOLD_DEFAULT."
        )
    return updated, count


def patch_bits16(source: str) -> tuple[str, int]:
    updated, count = BITS_ASSIGNMENT.subn(lambda m: m.group(1) + "16", source)
    if count == 0:
        # If the value comes from argparse, only change the default on a line specifically
        # declaring the activation-bit option; do not touch unrelated defaults of 8.
        lines = updated.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if ("--activation-bits" in line or "--signed-activation-bits" in line
                    or "activation_bits" in line.lower() or "act-bits" in line.lower()):
                new = re.sub(r"(?i)(default\s*=\s*)8\b", r"\g<1>16", line)
                if new != line:
                    lines[i] = new
                    count += 1
        updated = "".join(lines)
    if count == 0:
        raise RuntimeError(
            "Cannot safely locate the signed activation bit-width setting (expected 8). "
            "No files were executed. Inspect the activation-bits constant/argparse option in "
            "scripts/validate_kwt1_ptq_activations.py and adapt BITS_ASSIGNMENT."
        )
    return updated, count


def patch_both(source: str) -> tuple[str, str]:
    p99, n_thr = patch_threshold(source)
    p99_i16, n_bits = patch_bits16(p99)
    return p99_i16, f"threshold replacements={n_thr}, signed activation bit replacements={n_bits}"


def stream_run(command: list[str], log_path: Path, cwd: Path) -> int:
    print("\n$ " + subprocess.list2cmdline(command), flush=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(command, cwd=str(cwd), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, errors="replace",
                                bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            log.write(line)
        return proc.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", default="scripts/validate_kwt1_ptq_activations.py",
                        help="Existing activation validation script, relative to repo root by default")
    parser.add_argument("--max-samples", type=int, default=512,
                        help="512 for screening; 0 for the full validation partition")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--skip-baseline", action="store_true",
                        help="Skip rerunning the original INT8/abs_p999 baseline")
    parser.add_argument("--dry-run", action="store_true", help="Create/validate variants but do not run inference")
    args = parser.parse_args()

    script_path = Path(args.script)
    if not script_path.is_absolute():
        script_path = (Path.cwd() / script_path).resolve()
    if not script_path.is_file():
        print(f"ERROR: original validation script not found: {script_path}", file=sys.stderr)
        return 2

    scripts_dir = script_path.parent
    repo_root = scripts_dir.parent
    source = script_path.read_text(encoding="utf-8")
    try:
        p99_source, n_p99 = patch_threshold(source)
        i16_source, n_i16 = patch_bits16(source)
        combo_source, combo_note = patch_both(source)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("The original script has not been modified or executed.", file=sys.stderr)
        return 2

    variants = [
        ("p99_i8", scripts_dir / "_validate_kwt1_ptq_activations_p99_i8.py", p99_source,
         "INT8 signed activations, P99-derived threshold"),
        ("p999_i16", scripts_dir / "_validate_kwt1_ptq_activations_p999_i16.py", i16_source,
         "INT16 signed activations, P99.9-derived threshold"),
        ("p99_i16", scripts_dir / "_validate_kwt1_ptq_activations_p99_i16.py", combo_source,
         "INT16 signed activations, P99-derived threshold"),
    ]
    for _, path, content, _ in variants:
        path.write_text(content, encoding="utf-8")

    out_root = repo_root / "testdata" / "ptq_sensitivity_sweep"
    out_root.mkdir(parents=True, exist_ok=True)
    print(f"Original script: {script_path}")
    print("Original script unchanged: YES")
    print(f"P99 threshold selector replacement(s): {n_p99}")
    print(f"INT16 bit-width setting replacement(s): {n_i16}")
    print(f"Combined variant: {combo_note}")
    print(f"Sweep output: {out_root}")

    run_list = []
    if not args.skip_baseline:
        run_list.append(("baseline_p999_i8", script_path,
                         "Original baseline: INT8 signed activations, P99.9 threshold"))
    run_list.extend((name, path, desc) for name, path, _, desc in variants)
    if args.dry_run:
        print("DRY RUN: generated variants and validated source substitutions; inference not run.")
        for name, path, desc in run_list:
            print(f"  {name}: {desc}; script={path}")
        return 0

    copied_names = [
        "kwt1_ptq_activation_validation_summary.csv",
        "kwt1_ptq_activation_validation_predictions.csv",
        "kwt1_ptq_activation_validation_manifest.json",
    ]
    default_results = repo_root / "testdata" / "ptq_activation_validation"
    for name, script, desc in run_list:
        print(f"\n=== {name}: {desc} ===", flush=True)
        run_dir = out_root / name
        run_dir.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, str(script), "--max-samples", str(args.max_samples),
                   "--batch-size", str(args.batch_size)]
        rc = stream_run(command, run_dir / "stdout.log", repo_root)
        if rc != 0:
            print(f"ERROR: {name} exited with code {rc}; see {run_dir / 'stdout.log'}", file=sys.stderr)
            return rc
        if default_results.exists():
            for filename in copied_names:
                src = default_results / filename
                if src.exists():
                    shutil.copy2(src, run_dir / filename)
        manifest = run_dir / "run_info.txt"
        manifest.write_text(
            f"experiment={name}\ndescription={desc}\nscript={script}\n"
            f"max_samples={args.max_samples}\nbatch_size={args.batch_size}\nreturn_code={rc}\n",
            encoding="utf-8")
        print(f"Saved experiment artifacts: {run_dir}", flush=True)

    print("\nSweep completed.")
    print(f"Compare each experiment's summary CSV under: {out_root}")
    print("Important: each run changes one global setting (or both in the combined arm); "
          "activation-group rows remain independent tests, not a combined all-INT16 model.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
