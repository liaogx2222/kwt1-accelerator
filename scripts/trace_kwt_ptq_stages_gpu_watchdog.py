#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Trace KWT PTQ validation stages on GPU without changing the target file.

Wraps model.load_weights, model.predict/predict_on_batch/evaluate and TF1 Session.run
with flushed begin/end markers. Does not enable verbose device-placement logging.
"""
from __future__ import annotations
import argparse
import faulthandler
import os
import runpy
import sys
import time
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--script', default='scripts/_validate_kwt1_ptq_activations_baseline_gpu.py')
    p.add_argument('--max-samples', type=int, default=32)
    p.add_argument('--batch-size', type=int, default=16)
    p.add_argument('--gpu', default='0')
    p.add_argument('--watchdog-seconds', type=int, default=15, help='Dump Python stack every N seconds while the target appears stuck; 0 disables.')
    args = p.parse_args()

    os.environ['CUDA_VISIBLE_DEVICES'] = str(args.gpu)
    os.environ['TF_FORCE_GPU_ALLOW_GROWTH'] = 'true'
    target = Path(args.script)
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()
    if not target.is_file():
        print('[TRACE] ERROR target script not found:', target, flush=True)
        return 2

    import tensorflow as tf
    print('[TRACE] TF version:', tf.__version__, flush=True)
    print('[TRACE] CUDA build:', tf.test.is_built_with_cuda(), flush=True)
    gpus = tf.config.list_physical_devices('GPU')
    print('[TRACE] Physical GPUs:', gpus, flush=True)
    if not tf.test.is_built_with_cuda() or not gpus:
        print('[TRACE] ABORT: TensorFlow sees no CUDA GPU', flush=True)
        return 3
    for gpu in gpus:
        try:
            tf.config.experimental.set_memory_growth(gpu, True)
        except (AttributeError, RuntimeError) as exc:
            print('[TRACE] memory-growth note:', exc, flush=True)

    # Wrap Keras model APIs. Keep messages flushed and bounded.
    model_cls = tf.keras.Model
    for method_name in ('load_weights', 'predict', 'predict_on_batch', 'evaluate'):
        original = getattr(model_cls, method_name, None)
        if original is None:
            continue
        def make_wrapper(name, orig):
            def wrapped(self, *m_args, **m_kwargs):
                arg_preview = ''
                if name == 'load_weights' and m_args:
                    arg_preview = ' source={!r}'.format(m_args[0])
                elif name in ('predict', 'predict_on_batch', 'evaluate') and m_args:
                    try:
                        shape = getattr(m_args[0], 'shape', None)
                        if shape is None and isinstance(m_args[0], (tuple, list)) and m_args[0]:
                            shape = getattr(m_args[0][0], 'shape', None)
                        arg_preview = ' input_shape={!r}'.format(shape)
                    except Exception:
                        pass
                t0 = time.perf_counter()
                print('[TRACE] {} BEGIN{} [model_id={}]'.format(name, arg_preview, id(self)), flush=True)
                try:
                    result = orig(self, *m_args, **m_kwargs)
                except BaseException as exc:
                    print('[TRACE] {} RAISED after {:.2f}s: {!r}'.format(name, time.perf_counter()-t0, exc), flush=True)
                    raise
                extra = ''
                try:
                    if hasattr(result, 'shape'):
                        extra = ' result_shape={!r}'.format(result.shape)
                except Exception:
                    pass
                print('[TRACE] {} END after {:.2f}s{}'.format(name, time.perf_counter()-t0, extra), flush=True)
                return result
            return wrapped
        setattr(model_cls, method_name, make_wrapper(method_name, original))

    # In TF 2.4 / graph mode, model execution often happens through Session.run.
    try:
        session_cls = tf.compat.v1.Session
        original_run = session_cls.run
        run_state = {'n': 0}
        def traced_run(self, *r_args, **r_kwargs):
            run_state['n'] += 1
            n = run_state['n']
            show = n <= 5 or n % 50 == 0
            t0 = time.perf_counter()
            if show:
                print('[TRACE] Session.run #{} BEGIN'.format(n), flush=True)
            try:
                result = original_run(self, *r_args, **r_kwargs)
            except BaseException as exc:
                print('[TRACE] Session.run #{} RAISED after {:.2f}s: {!r}'.format(n, time.perf_counter()-t0, exc), flush=True)
                raise
            dt = time.perf_counter() - t0
            if show or dt >= 1.0:
                print('[TRACE] Session.run #{} END after {:.3f}s'.format(n, dt), flush=True)
            return result
        session_cls.run = traced_run
    except Exception as exc:
        print('[TRACE] Could not wrap Session.run:', repr(exc), flush=True)

    sys.path.insert(0, str(target.parent))
    sys.path.insert(0, str(Path.cwd()))
    sys.argv = [str(target), '--max-samples', str(args.max_samples), '--batch-size', str(args.batch_size)]
    print('[TRACE] Starting target:', target, flush=True)
    print('[TRACE] Samples:', args.max_samples, 'batch_size:', args.batch_size, flush=True)
    print('[TRACE] Target source will not be modified.', flush=True)
    if args.watchdog_seconds > 0:
        print('[TRACE] Watchdog enabled: Python stack dump every {} seconds if still running.'.format(args.watchdog_seconds), flush=True)
        faulthandler.dump_traceback_later(args.watchdog_seconds, repeat=True, file=sys.stderr)
    try:
        runpy.run_path(str(target), run_name='__main__')
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        print('[TRACE] Target SystemExit:', code, flush=True)
        return code
    except BaseException as exc:
        print('[TRACE] UNHANDLED TARGET EXCEPTION:', repr(exc), flush=True)
        raise
    finally:
        if args.watchdog_seconds > 0:
            faulthandler.cancel_dump_traceback_later()
    print('[TRACE] TRACE FINISHED normally.', flush=True)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
