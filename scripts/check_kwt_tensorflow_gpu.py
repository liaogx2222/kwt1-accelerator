# -*- coding: utf-8 -*-
"""Diagnose TensorFlow GPU visibility/runtime on Windows, without masking GPUs."""
import os
import sys
import platform
import traceback

print("=== Python / environment ===")
print("Python:", sys.version.replace("\n", " "))
print("Executable:", sys.executable)
print("Platform:", platform.platform())
print("CONDA_PREFIX:", os.environ.get("CONDA_PREFIX", "<unset>"))
print("CUDA_VISIBLE_DEVICES:", os.environ.get("CUDA_VISIBLE_DEVICES", "<unset>"))
print("TF_CPP_MIN_LOG_LEVEL:", os.environ.get("TF_CPP_MIN_LOG_LEVEL", "<unset>"))

print("\n=== CUDA-related PATH entries ===")
for entry in os.environ.get("PATH", "").split(os.pathsep):
    low = entry.lower()
    if "cuda" in low or "cudnn" in low or ("anaconda" in low and ("kwt_ref" in low or "library\\bin" in low)):
        print(entry)

print("\n=== TensorFlow import / build ===")
try:
    import tensorflow as tf
    print("TensorFlow version:", tf.__version__)
    try:
        print("Built with CUDA:", tf.test.is_built_with_cuda())
    except Exception as e:
        print("Built with CUDA: query failed:", repr(e))
    try:
        print("Build info:", tf.sysconfig.get_build_info())
    except Exception as e:
        print("Build info unavailable:", repr(e))
    try:
        gpus = tf.config.list_physical_devices("GPU")
        print("Physical GPU devices:", gpus)
    except Exception as e:
        print("GPU enumeration failed:", repr(e))
        gpus = []

    if gpus:
        print("\n=== Hard GPU execution test ===")
        try:
            # Do not silently place unsupported work on the CPU.
            tf.config.set_soft_device_placement(False)
            with tf.device("/GPU:0"):
                a = tf.random.uniform((1024, 1024), dtype=tf.float32)
                b = tf.random.uniform((1024, 1024), dtype=tf.float32)
                c = tf.matmul(a, b)
            value = c.numpy()[0, 0]
            print("MatMul tensor device:", c.device)
            print("MatMul sample value:", float(value))
            if "GPU:0" not in c.device.upper():
                print("RESULT: GPU listed, but MatMul did not execute on GPU.")
            else:
                print("RESULT: GPU enumeration and MatMul both passed.")
        except Exception:
            print("RESULT: GPU listed, but hard GPU MatMul failed:")
            traceback.print_exc()
    else:
        print("\nRESULT: TensorFlow currently sees no GPU device.")
        print("Check CUDA_VISIBLE_DEVICES, TensorFlow build, and CUDA/cuDNN DLL compatibility.")
except Exception:
    print("TensorFlow import failed:")
    traceback.print_exc()

print("\n=== Installed package versions ===")
try:
    from importlib import metadata
    for name in ("tensorflow", "tensorflow-gpu", "tensorflow-intel", "keras", "numpy"):
        try:
            print(name + ":", metadata.version(name))
        except metadata.PackageNotFoundError:
            print(name + ": not installed as this distribution name")
except Exception as e:
    print("Package version lookup failed:", repr(e))
