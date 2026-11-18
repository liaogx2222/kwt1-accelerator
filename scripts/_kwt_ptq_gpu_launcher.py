#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run one KWT validation variant only after checking TensorFlow GPU visibility."""
import os
import runpy
import sys
from pathlib import Path

# The parent process sets KWT_GPU_DEVICE before this Python process starts.
os.environ["CUDA_VISIBLE_DEVICES"] = os.environ.get("KWT_GPU_DEVICE", "0")
os.environ["TF_FORCE_GPU_ALLOW_GROWTH"] = "true"

if len(sys.argv) < 2:
    raise SystemExit("Usage: _kwt_ptq_gpu_launcher.py TARGET_SCRIPT [TARGET_ARGS...]")
target = Path(sys.argv[1]).resolve()
target_args = sys.argv[2:]
if not target.is_file():
    raise SystemExit("Target validation script not found: " + str(target))

import tensorflow as tf
print("GPU launcher TensorFlow version:", tf.__version__, flush=True)
print("GPU launcher CUDA build:", tf.test.is_built_with_cuda(), flush=True)
physical_gpus = tf.config.list_physical_devices("GPU")
print("GPU launcher visible devices:", physical_gpus, flush=True)
if not tf.test.is_built_with_cuda() or not physical_gpus:
    raise SystemExit("GPU-required validation aborted: TensorFlow cannot see a CUDA GPU.")
for gpu in physical_gpus:
    try:
        tf.config.experimental.set_memory_growth(gpu, True)
    except (AttributeError, RuntimeError) as exc:
        print("Memory-growth note:", str(exc), flush=True)

# Keep imports and relative project paths compatible with direct script execution.
sys.path.insert(0, str(target.parent))
sys.path.insert(0, str(Path.cwd()))
sys.argv = [str(target)] + target_args
print("Executing validation script on a TensorFlow process with GPU visible:", target, flush=True)
runpy.run_path(str(target), run_name="__main__")
