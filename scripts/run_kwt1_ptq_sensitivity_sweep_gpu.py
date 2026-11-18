#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GPU-enforced KWT-1 PTQ activation sensitivity sweep.

Place under <repo>/scripts and run from repo root. The original activation
validation script is never edited. GPU visibility is configured for each child
process, CPU-forcing lines are removed from generated copies, and each copy
asserts that TensorFlow can execute a matrix multiplication on GPU before the
model evaluation begins.
"""
from __future__ import annotations

import argparse
import os
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

# Remove known ways the original script may force TensorFlow to CPU.
CPU_MASK_PATTERNS = [
    re.compile(r"(?im)^[ \t]*.*CUDA_VISIBLE_DEVICES.*(?:['\"]-1['\"]|=\s*-1).*(?:\r?\n|$)"),
    re.compile(r"(?im)^[ \t]*tf\.config(?:\.experimental)?\.set_visible_devices\(\s*\[\s*\]\s*,\s*['\"]GPU['\"]\s*\).*?(?:\r?\n|$)"),
]

GPU_ENV_SNIPPET = '''\n# PTQ_GPU_ENFORCEMENT_BEGIN: do not remove\nimport os as _kwt_gpu_os\n_kwt_gpu_os.environ["CUDA_VISIBLE_DEVICES"] = _kwt_gpu_os.environ.get("KWT_GPU_DEVICE", "0")\n_kwt_gpu_os.environ["TF_FORCE_GPU_ALLOW_GROWTH"] = "true"\n# PTQ_GPU_ENFORCEMENT_END\n'''
GPU_CHECK_SNIPPET = '''\n# PTQ_GPU_RUNTIME_CHECK_BEGIN: fail early if this process cannot use GPU\n_kwt_gpu_devices = tf.config.list_physical_devices("GPU")\nprint("TensorFlow version:", tf.__version__, flush=True)\nprint("TensorFlow CUDA build:", tf.test.is_built_with_cuda(), flush=True)\nprint("Visible TensorFlow GPU devices:", _kwt_gpu_devices, flush=True)\nif not _kwt_gpu_devices:\n    raise RuntimeError("GPU was required for this PTQ experiment, but TensorFlow sees no GPU. Check CUDA_VISIBLE_DEVICES and the TensorFlow/CUDA installation.")\nfor _kwt_gpu in _kwt_gpu_devices:\n    try:\n        tf.config.experimental.set_memory_growth(_kwt_gpu, True)\n    except (AttributeError, RuntimeError):\n        pass\nwith tf.device("/GPU:0"):\n    _kwt_gpu_probe = tf.matmul(tf.ones((64, 64)), tf.ones((64, 64)))\n    _kwt_gpu_probe_value = _kwt_gpu_probe.numpy()\nprint("GPU matmul output device:", _kwt_gpu_probe.device, flush=True)\nif "GPU:" not in _kwt_gpu_probe.device.upper():\n    raise RuntimeError("TensorFlow listed a GPU but matrix multiplication did not execute on GPU: " + str(_kwt_gpu_probe.device))\ndel _kwt_gpu_probe, _kwt_gpu_probe_value\n# PTQ_GPU_RUNTIME_CHECK_END\n'''


def patch_threshold(source: str) -> tuple[str, int]:
    updated, count = THRESHOLD_ASSIGNMENT.subn(lambda m: m.group(1) + repr("abs_p99_est"), source)
    if count == 0:
        lines = updated.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if "abs_p999_est" in line and ("threshold" in line.lower() or "scale" in line.lower()):
                new, n = THRESHOLD_DEFAULT.subn(lambda m: m.group(1) + repr("abs_p99_est"), line)
                if n:
                    lines[i] = new
                    count += n
        updated = "".join(lines)
    if count == 0:
        raise RuntimeError("Cannot safely locate abs_p999_est threshold selector in the original validation script.")
    return updated, count


def patch_bits16(source: str) -> tuple[str, int]:
    updated, count = BITS_ASSIGNMENT.subn(lambda m: m.group(1) + "16", source)
    if count == 0:
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
        raise RuntimeError("Cannot safely locate signed activation bit-width setting (expected 8).")
    return updated, count


def strip_cpu_forcing(source: str) -> tuple[str, int]:
    n = 0
    updated = source
    for pattern in CPU_MASK_PATTERNS:
        updated, count = pattern.subn("# PTQ_GPU_SWEEP removed CPU-forcing line\n", updated)
        n += count
    return updated, n


def make_gpu_ready(source: str) -> tuple[str, dict]:
    updated, removed = strip_cpu_forcing(source)
    # Put CUDA environment settings immediately before the first top-level TF import.
    tf_import = re.search(r"(?m)^import tensorflow as tf\s*$", updated)
    if not tf_import:
        raise RuntimeError("Expected a top-level 'import tensorflow as tf' in the validation script; cannot safely enforce GPU mode.")
    updated = updated[:tf_import.start()] + GPU_ENV_SNIPPET.strip("\n") + "\n" + updated[tf_import.start():]
    # Inject the runtime check immediately after that import, so GPU failure is clear and early.
    tf_import = re.search(r"(?m)^import tensorflow as tf\s*$", updated)
    assert tf_import is not None
    end = tf_import.end()
    updated = updated[:end] + GPU_CHECK_SNIPPET + updated[end:]
    return updated, {"cpu_forcing_lines_removed": removed, "gpu_environment_injected": True, "runtime_gpu_check_injected": True}


def patch_both(source: str) -> tuple[str, str]:
    p99, n_thr = patch_threshold(source)
    p99_i16, n_bits = patch_bits16(p99)
    return p99_i16, f"threshold replacements={n_thr}, signed activation bit replacements={n_bits}"


def stream_run(command: list[str], log_path: Path, cwd: Path, env: dict[str, str]) -> int:
    print("\n$ " + subprocess.list2cmdline(command), flush=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(command, cwd=str(cwd), env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            log.write(line)
        return proc.wait()


def gpu_preflight(cwd: Path, env: dict[str, str]) -> int:
    probe = (
        "import tensorflow as tf\n"
        "print('TensorFlow version:', tf.__version__)\n"
        "print('TensorFlow CUDA build:', tf.test.is_built_with_cuda())\n"
        "g=tf.config.list_physical_devices('GPU')\n"
        "print('Visible TensorFlow GPU devices:', g)\n"
        "assert g, 'GPU required, but TensorFlow sees no GPU'\n"
        "[tf.config.experimental.set_memory_growth(x, True) for x in g]\n"
        "with tf.device('/GPU:0'):\n"
        " y=tf.matmul(tf.ones((64,64)), tf.ones((64,64)))\n"
        " z=y.numpy()\n"
        "print('GPU matmul output device:', y.device)\n"
        "assert 'GPU:' in y.device.upper(), 'matmul did not execute on GPU'\n"
    )
    print("\n=== GPU preflight (must pass before the sweep) ===", flush=True)
    return subprocess.call([sys.executable, "-c", probe], cwd=str(cwd), env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", default="scripts/validate_kwt1_ptq_activations.py",
                        help="Existing activation validation script, relative to repository root")
    parser.add_argument("--max-samples", type=int, default=512,
                        help="512 for screening; 0 for the complete validation partition")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--gpu", default="0", help="CUDA-visible physical GPU index, e.g. 0; default 0")
    parser.add_argument("--skip-baseline", action="store_true", help="Skip rerunning P99.9/INT8 baseline")
    parser.add_argument("--dry-run", action="store_true", help="Generate and inspect variants without inference")
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
        base_gpu_source, base_gpu_note = make_gpu_ready(source)
        p99_gpu_source, p99_gpu_note = make_gpu_ready(p99_source)
        i16_gpu_source, i16_gpu_note = make_gpu_ready(i16_source)
        combo_gpu_source, combo_gpu_note = make_gpu_ready(combo_source)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("No inference was started, and the original script remains unchanged.", file=sys.stderr)
        return 2

    variants = [
        ("p99_i8", scripts_dir / "_validate_kwt1_ptq_activations_p99_i8_gpu.py", p99_gpu_source,
         "INT8 signed activations, P99-derived threshold"),
        ("p999_i16", scripts_dir / "_validate_kwt1_ptq_activations_p999_i16_gpu.py", i16_gpu_source,
         "INT16 signed activations, P99.9-derived threshold"),
        ("p99_i16", scripts_dir / "_validate_kwt1_ptq_activations_p99_i16_gpu.py", combo_gpu_source,
         "INT16 signed activations, P99-derived threshold"),
    ]
    base_gpu_path = scripts_dir / "_validate_kwt1_ptq_activations_baseline_gpu.py"
    base_gpu_path.write_text(base_gpu_source, encoding="utf-8")
    for _, path, content, _ in variants:
        path.write_text(content, encoding="utf-8")

    out_root = repo_root / "testdata" / "ptq_sensitivity_sweep_gpu"
    out_root.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(args.gpu)
    env["KWT_GPU_DEVICE"] = str(args.gpu)
    env["TF_FORCE_GPU_ALLOW_GROWTH"] = "true"

    print(f"Original script: {script_path}")
    print("Original script unchanged: YES")
    print(f"CPU-forcing lines removed from generated baseline: {base_gpu_note['cpu_forcing_lines_removed']}")
    print(f"P99 threshold replacements: {n_p99}; INT16 bit-width replacements: {n_i16}")
    print(f"P99/INT16 combined patch: {combo_note}")
    print(f"CUDA_VISIBLE_DEVICES={env['CUDA_VISIBLE_DEVICES']}; TF_FORCE_GPU_ALLOW_GROWTH=true")
    print(f"Sweep output: {out_root}")

    if args.dry_run:
        print("DRY RUN: generated variants and checked source transformations; no GPU preflight or inference run.")
        for name, path, _, desc in [("baseline_p999_i8", base_gpu_path, base_gpu_source, "INT8/P99.9 baseline")] + variants:
            print(f"  {name}: {desc}; script={path}")
        return 0

    preflight_rc = gpu_preflight(repo_root, env)
    if preflight_rc != 0:
        print("ERROR: GPU preflight failed; sweep aborted before model evaluation.", file=sys.stderr)
        return preflight_rc or 3

    run_list = []
    if not args.skip_baseline:
        run_list.append(("baseline_p999_i8", base_gpu_path, "Original baseline: INT8 signed activations, P99.9 threshold"))
    run_list.extend((name, path, desc) for name, path, _, desc in variants)

    copied_names = ["kwt1_ptq_activation_validation_summary.csv",
                    "kwt1_ptq_activation_validation_predictions.csv",
                    "kwt1_ptq_activation_validation_manifest.json"]
    default_results = repo_root / "testdata" / "ptq_activation_validation"
    for name, script, desc in run_list:
        print(f"\n=== {name}: {desc} ===", flush=True)
        run_dir = out_root / name
        run_dir.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, str(script), "--max-samples", str(args.max_samples),
                   "--batch-size", str(args.batch_size)]
        rc = stream_run(command, run_dir / "stdout.log", repo_root, env)
        if rc != 0:
            print(f"ERROR: {name} exited with code {rc}; see {run_dir / 'stdout.log'}", file=sys.stderr)
            return rc
        if default_results.exists():
            for filename in copied_names:
                src = default_results / filename
                if src.exists():
                    shutil.copy2(src, run_dir / filename)
        (run_dir / "run_info.txt").write_text(
            f"experiment={name}\ndescription={desc}\nscript={script}\nmax_samples={args.max_samples}\n"
            f"batch_size={args.batch_size}\ngpu={args.gpu}\nreturn_code={rc}\n", encoding="utf-8")
        print(f"Saved experiment artifacts: {run_dir}", flush=True)

    print("\nSweep completed. Every generated run performed a GPU preflight and in-script GPU matmul check.")
    print(f"Compare summaries under: {out_root}")
    print("Reminder: threshold/bit-width arms still test activation groups independently; they are not an all-modules joint-quantization sign-off.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
