#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnostic launcher: trace real TF1-style graph op placement in KWT validation.
Run from the keyword-transformer repo root. Uses the generated baseline validation
script by default and limits work to 32 validation samples unless overridden.
"""
from __future__ import annotations
import argparse
import os
import runpy
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--script', default='scripts/_validate_kwt1_ptq_activations_baseline_gpu.py',
                   help='Target validation script (default: generated GPU baseline variant)')
    p.add_argument('--max-samples', type=int, default=32,
                   help='Use a small diagnostic batch; default 32')
    p.add_argument('--batch-size', type=int, default=16)
    p.add_argument('--gpu', default='0')
    args = p.parse_args()

    os.environ['CUDA_VISIBLE_DEVICES'] = str(args.gpu)
    os.environ['TF_FORCE_GPU_ALLOW_GROWTH'] = 'true'
    target = Path(args.script)
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()
    if not target.is_file():
        print('ERROR: target script not found:', target, file=sys.stderr)
        return 2

    import tensorflow as tf
    print('TF version:', tf.__version__, flush=True)
    print('CUDA build:', tf.test.is_built_with_cuda(), flush=True)
    gpus = tf.config.list_physical_devices('GPU')
    print('Physical GPUs:', gpus, flush=True)
    if not tf.test.is_built_with_cuda() or not gpus:
        print('ERROR: TensorFlow has no visible GPU; trace aborted.', file=sys.stderr)
        return 3
    for gpu in gpus:
        try:
            tf.config.experimental.set_memory_growth(gpu, True)
        except (AttributeError, RuntimeError) as e:
            print('Memory growth note:', e, flush=True)

    # Enable operation-level placement diagnostics, including TF1 graph/session mode.
    try:
        tf.debugging.set_log_device_placement(True)
    except Exception as e:
        print('set_log_device_placement note:', repr(e), flush=True)
    try:
        OriginalSession = tf.compat.v1.Session

        class PlacementLoggingSession(OriginalSession):
            def __init__(self, *s_args, **s_kwargs):
                config = s_kwargs.get('config')
                config_pos = len(s_args) >= 3
                if config is None and config_pos:
                    config = s_args[2]
                if config is None:
                    config = tf.compat.v1.ConfigProto()
                config.log_device_placement = True
                # Don't change the target script's device policy beyond enabling logs.
                if config_pos:
                    s_args = list(s_args)
                    s_args[2] = config
                    s_args = tuple(s_args)
                else:
                    s_kwargs['config'] = config
                super().__init__(*s_args, **s_kwargs)

        tf.compat.v1.Session = PlacementLoggingSession
        tf.Session = PlacementLoggingSession
        print('Session log_device_placement: ENABLED', flush=True)
    except Exception as e:
        print('WARNING: could not instrument TF1 Session:', repr(e), flush=True)

    sys.path.insert(0, str(target.parent))
    sys.path.insert(0, str(Path.cwd()))
    sys.argv = [str(target), '--max-samples', str(args.max_samples),
                '--batch-size', str(args.batch_size)]
    print('Tracing target:', target, flush=True)
    print('Diagnostic samples:', args.max_samples, '; batch size:', args.batch_size, flush=True)
    print('IMPORTANT: placement logs are verbose; this is a diagnostic run, not a timing benchmark.', flush=True)

    # Preserve the prior standard validation outputs; this short trace is diagnostic only.
    result_dir = Path.cwd() / 'testdata' / 'ptq_activation_validation'
    preserve_names = [
        'kwt1_ptq_activation_validation_summary.csv',
        'kwt1_ptq_activation_validation_predictions.csv',
        'kwt1_ptq_activation_validation_manifest.json',
    ]
    saved = {}
    for name in preserve_names:
        path = result_dir / name
        saved[name] = path.read_bytes() if path.is_file() else None
    exit_code = 0
    try:
        runpy.run_path(str(target), run_name='__main__')
    except SystemExit as exc:
        exit_code = int(exc.code) if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        if exit_code:
            raise
    finally:
        for name, content in saved.items():
            path = result_dir / name
            if content is None:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            else:
                result_dir.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        print('Existing default activation-validation CSV/manifest outputs restored.', flush=True)
    print('TRACE FINISHED. Search the log for MatMul/BatchMatMul and device:GPU:0.', flush=True)
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
