#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Validation-only KWT-1 PTQ experiment for encoder-kernel fake quantization.

Runs the official frozen checkpoint on the VALIDATION partition only. It compares:
  FP32 reference
  W8_TENSOR: symmetric fake-INT8, one scale per encoder matrix kernel
  W8_CHANNEL: symmetric fake-INT8, per-output-channel scales for encoder kernels
  W16_CHANNEL: symmetric fake-INT16, per-output-channel scales for encoder kernels

Only the twelve encoder blocks are quantized. The offline input projection/embeddings and
the official software classification head remain FP32, matching the competition boundary.
Biases, LayerNorm affine parameters, all activations, and nonlinear operations remain FP32.
This measures encoder weight-quantization sensitivity only, not full integer inference.
No training, gradient updates, testing-partition access, or checkpoint writes occur.
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np
import tensorflow as tensorflow

tensorflow.compat.v1.disable_eager_execution()

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

# Import order matches the verified KWT-1 inference/export scripts in this project.
from kws_streaming.layers.compat import tf  # noqa: E402
from kws_streaming.train import model_train_eval as _official_entry  # noqa: E402,F401
from kws_streaming.models import kws_transformer  # noqa: E402
from kws_streaming.data import input_data  # noqa: E402


def labels_to_ids(labels):
    labels = np.asarray(labels)
    if labels.ndim > 1:
        return np.argmax(labels, axis=-1).astype(np.int64)
    return labels.reshape(-1).astype(np.int64)


def to_logits(pred):
    if isinstance(pred, (list, tuple)):
        if len(pred) != 1:
            raise RuntimeError("Expected a single logits output, got {} outputs".format(len(pred)))
        pred = pred[0]
    return np.asarray(pred, dtype=np.float32)


def is_weight_target(name, arr, encoder_variable_names):
    """Target matrix-like kernel variables belonging to encoder blocks only."""
    low = name.lower()
    if name not in encoder_variable_names:
        return False
    if any(token in low for token in ("bias", "/beta", "beta:", "/gamma", "gamma:", "layernorm", "layer_normalization")):
        return False
    return "kernel" in low and arr.ndim >= 2


def fake_quant_symmetric(arr, bits, per_channel):
    arr64 = np.asarray(arr, dtype=np.float64)
    qmax = (1 << (bits - 1)) - 1  # signed symmetric range: [-127,127] or [-32767,32767]
    if arr64.size == 0:
        return np.asarray(arr).copy(), np.asarray(1.0), 0.0
    if per_channel and arr64.ndim >= 2:
        reduce_axes = tuple(range(arr64.ndim - 1))
        max_abs = np.max(np.abs(arr64), axis=reduce_axes, keepdims=True)
        scale = np.maximum(max_abs / qmax, 1e-12)
    else:
        max_abs = float(np.max(np.abs(arr64)))
        scale = np.asarray(max(max_abs / qmax, 1e-12), dtype=np.float64)
    q = np.clip(np.rint(arr64 / scale), -qmax, qmax)
    dequant = q * scale
    mse = float(np.mean(np.square(dequant - arr64)))
    return dequant.astype(np.asarray(arr).dtype, copy=False), np.asarray(scale), mse


def make_scheme(original_weights, variable_names, encoder_variable_names, scheme):
    if scheme == "FP32":
        return [np.asarray(w).copy() for w in original_weights], [], 0.0
    bits = 8 if scheme.startswith("W8") else 16
    per_channel = scheme.endswith("CHANNEL")
    out = []
    quantized = []
    total_sq_err = 0.0
    total_n = 0
    for name, raw in zip(variable_names, original_weights):
        arr = np.asarray(raw)
        if is_weight_target(name, arr, encoder_variable_names):
            deq, scale, mse = fake_quant_symmetric(arr, bits, per_channel)
            out.append(deq)
            quantized.append({
                "variable": name,
                "shape": list(arr.shape),
                "bits": bits,
                "scheme": "per_output_channel" if per_channel and arr.ndim >= 2 else "per_tensor",
                "scale_count": int(scale.size),
                "max_abs": float(np.max(np.abs(arr))) if arr.size else 0.0,
                "mse": mse,
            })
            total_sq_err += mse * arr.size
            total_n += arr.size
        else:
            # Keep bias and normalization affine parameters high precision in this experiment.
            out.append(arr.copy())
    global_mse = total_sq_err / max(1, total_n)
    return out, quantized, global_mse


def build_flags(model_dir, data_dir, batch_size):
    flags_file = model_dir / "flags.json"
    with flags_file.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.update({
        "data_dir": str(data_dir),
        "data_url": "",
        "train_dir": str(model_dir),
        "training": False,
        "train": 0,
        "batch_size": int(batch_size),
        "return_softmax": 0,
        "background_frequency": 0.0,
        "background_volume": 0.0,
        "time_shift_ms": 0.0,
        "sp_time_shift_ms": 0.0,
        "resample": 0.0,
        "pick_deterministically": True,
        "distill_teacher_json": "",
        "prenorm": False,
        "approximate_gelu": False,
    })
    return SimpleNamespace(**cfg)


def run_model_partition(model, processor, flags, sess, mode, total, batch_size, max_samples, label_names):
    process_limit = total if max_samples == 0 else min(total, max_samples)
    logits_all = []
    labels_all = []
    for offset in range(0, process_limit, batch_size):
        real_n = min(batch_size, process_limit - offset)
        batch_x, batch_y = processor.get_data(
            real_n, offset, flags,
            0.0, 0.0, 0, mode, 0.0, 0.0, sess
        )
        batch_x = np.asarray(batch_x)
        y_ids = labels_to_ids(batch_y)
        # Pad final batch for models whose input signatures require fixed batches.
        if real_n < batch_size:
            pad_n = batch_size - real_n
            batch_x_model = np.concatenate([batch_x, np.repeat(batch_x[-1:], pad_n, axis=0)], axis=0)
        else:
            batch_x_model = batch_x
        batch_logits = to_logits(model.predict(batch_x_model, batch_size=batch_size, verbose=0))[:real_n]
        if batch_logits.ndim != 2:
            raise RuntimeError("Expected [batch, classes] logits; got shape {}".format(batch_logits.shape))
        logits_all.append(batch_logits)
        labels_all.append(y_ids[:real_n])
        if (offset + real_n) % (batch_size * 20) == 0 or offset + real_n == process_limit:
            print("  {}: {}/{} samples".format(mode, offset + real_n, process_limit))
    logits = np.concatenate(logits_all, axis=0) if logits_all else np.zeros((0, 0), np.float32)
    labels = np.concatenate(labels_all, axis=0) if labels_all else np.zeros((0,), np.int64)
    return logits, labels, process_limit


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--model-dir", default=None)
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--max-samples", type=int, default=512,
                    help="Validation sample limit; 0 evaluates the complete validation partition.")
    ap.add_argument("--schemes", default="W8_TENSOR,W8_CHANNEL,W16_CHANNEL",
                    help="Comma-separated subset of W8_TENSOR,W8_CHANNEL,W16_CHANNEL.")
    args = ap.parse_args()
    if args.batch_size < 1 or args.max_samples < 0:
        ap.error("--batch-size must be >=1 and --max-samples must be >=0")

    data_dir = Path(args.data_dir).resolve() if args.data_dir else REPO_DIR / "data2"
    model_dir = Path(args.model_dir).resolve() if args.model_dir else REPO_DIR / "models_data_v2_12_labels" / "kwt1"
    output_dir = Path(args.output_dir).resolve() if args.output_dir else REPO_DIR / "testdata" / "ptq_validation"
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = model_dir / "best_weights"
    if not data_dir.is_dir():
        raise FileNotFoundError("Dataset directory not found: {}".format(data_dir))
    if not (model_dir / "flags.json").is_file():
        raise FileNotFoundError("Model flags not found: {}".format(model_dir / "flags.json"))
    if not Path(str(checkpoint) + ".index").is_file():
        raise FileNotFoundError("Checkpoint index not found: {}.index".format(checkpoint))

    schemes = [s.strip().upper() for s in args.schemes.split(",") if s.strip()]
    allowed = {"W8_TENSOR", "W8_CHANNEL", "W16_CHANNEL"}
    bad = [s for s in schemes if s not in allowed]
    if bad:
        ap.error("Unknown schemes {}. Allowed: {}".format(bad, sorted(allowed)))

    flags = build_flags(model_dir, data_dir, args.batch_size)
    tf1 = tensorflow.compat.v1
    graph = tf1.Graph()
    results = []
    sample_rows = []
    weight_details = {}

    with graph.as_default():
        with tf1.Session(graph=graph) as sess:
            try:
                tf.keras.backend.set_session(sess)
            except AttributeError:
                tensorflow.compat.v1.keras.backend.set_session(sess)

            processor = input_data.AudioProcessor(flags)
            model = kws_transformer.model(flags)
            sess.run(tf1.global_variables_initializer())
            status = model.load_weights(str(checkpoint))
            if hasattr(status, "assert_existing_objects_matched"):
                status.assert_existing_objects_matched()
            if hasattr(status, "expect_partial"):
                status.expect_partial()
            if hasattr(status, "run_restore_ops"):
                status.run_restore_ops()

            mode = "validation"
            total = int(processor.set_size(mode))
            if total <= 0:
                raise RuntimeError("AudioProcessor validation partition is empty")
            process_limit = total if args.max_samples == 0 else min(total, args.max_samples)
            label_names = list(getattr(processor, "words_list", []))
            if not label_names:
                label_names = ["_silence_", "_unknown_"] + flags.wanted_words.split(",")
            variable_names = [v.name for v in model.weights]
            from kws_streaming.models.transformer_utils import KWSTransformer
            transformers = [layer for layer in model.layers if isinstance(layer, KWSTransformer)]
            if len(transformers) != 1 or len(transformers[0].enc_layers) != 12:
                raise RuntimeError("Expected exactly one 12-layer KWSTransformer")
            encoder_variable_names = {v.name for block in transformers[0].enc_layers for v in block.weights}
            original_weights = [np.asarray(w).copy() for w in model.get_weights()]
            quantizable_count = sum(
                1 for n, w in zip(variable_names, original_weights)
                if is_weight_target(n, w, encoder_variable_names)
            )
            if quantizable_count == 0:
                raise RuntimeError(
                    "No encoder matrix kernels matched the quantization filter; "
                    "inspect model variable names before trusting results."
                )
            if len(variable_names) != len(original_weights):
                raise RuntimeError("Model variable/weight count mismatch: {} vs {}".format(
                    len(variable_names), len(original_weights)))

            print("Checkpoint: {}".format(checkpoint))
            print("Validation partition size: {}".format(total))
            print("Samples evaluated this run: {}".format(process_limit))
            print("Testing partition accessed: NO")
            print("Parameter arrays: {}".format(len(original_weights)))
            print("Encoder variable arrays: {}".format(len(encoder_variable_names)))
            print("Quantizable encoder matrix kernels: {}".format(quantizable_count))

            # FP32 reference on exactly the same validation samples.
            model.set_weights(original_weights)
            fp_logits, labels, processed = run_model_partition(
                model, processor, flags, sess, mode, total, args.batch_size,
                args.max_samples, label_names)
            fp_pred = np.argmax(fp_logits, axis=-1)
            fp_acc = float(np.mean(fp_pred == labels)) if labels.size else float("nan")
            print("FP32 validation accuracy: {:.4%} ({}/{})".format(
                fp_acc, int(np.sum(fp_pred == labels)), int(labels.size)))

            for scheme in schemes:
                quant_weights, details, weight_mse = make_scheme(
                    original_weights, variable_names, encoder_variable_names, scheme)
                model.set_weights(quant_weights)
                q_logits, q_labels, q_processed = run_model_partition(
                    model, processor, flags, sess, mode, total, args.batch_size,
                    args.max_samples, label_names)
                if not np.array_equal(labels, q_labels):
                    raise RuntimeError("Validation label sequence changed between runs; refusing comparison")
                q_pred = np.argmax(q_logits, axis=-1)
                acc = float(np.mean(q_pred == labels)) if labels.size else float("nan")
                diff = q_logits.astype(np.float64) - fp_logits.astype(np.float64)
                record = {
                    "scheme": scheme,
                    "partition": "validation",
                    "samples": int(q_processed),
                    "fp32_accuracy": fp_acc,
                    "quant_accuracy": acc,
                    "accuracy_drop_percentage_points": (fp_acc - acc) * 100.0,
                    "prediction_agreement_with_fp32": float(np.mean(q_pred == fp_pred)) if labels.size else float("nan"),
                    "logit_rmse": float(np.sqrt(np.mean(diff * diff))) if diff.size else float("nan"),
                    "logit_mae": float(np.mean(np.abs(diff))) if diff.size else float("nan"),
                    "logit_max_abs_error": float(np.max(np.abs(diff))) if diff.size else float("nan"),
                    "quantized_parameter_arrays": len(details),
                    "quantized_parameter_elements": int(sum(np.prod(d["shape"]) for d in details)),
                    "weight_quantization_global_mse": weight_mse,
                    "nonfinite_logits": int(np.size(q_logits) - np.count_nonzero(np.isfinite(q_logits))),
                    "testing_partition_accessed": False,
                    "quantized_region": "12 encoder blocks only",
                    "activation_quantization": "none; FP32",
                    "bias_layernorm_affine": "kept FP32",
                    "offline_input_projection_and_embeddings": "kept FP32",
                    "software_classification_head": "kept FP32",
                }
                results.append(record)
                weight_details[scheme] = details
                print("{} accuracy: {:.4%}; drop={:+.4f} pp; agree={:.4%}; logit_rmse={:.6g}".format(
                    scheme, acc, (fp_acc - acc) * 100.0,
                    record["prediction_agreement_with_fp32"], record["logit_rmse"]))
                for i in range(len(labels)):
                    sample_rows.append({
                        "sample_offset": i,
                        "true_label_id": int(labels[i]),
                        "true_label": label_names[int(labels[i])] if 0 <= int(labels[i]) < len(label_names) else str(int(labels[i])),
                        "fp32_predicted_id": int(fp_pred[i]),
                        "fp32_predicted_label": label_names[int(fp_pred[i])] if 0 <= int(fp_pred[i]) < len(label_names) else str(int(fp_pred[i])),
                        "scheme": scheme,
                        "quant_predicted_id": int(q_pred[i]),
                        "quant_predicted_label": label_names[int(q_pred[i])] if 0 <= int(q_pred[i]) < len(label_names) else str(int(q_pred[i])),
                        "fp32_correct": int(fp_pred[i] == labels[i]),
                        "quant_correct": int(q_pred[i] == labels[i]),
                        "prediction_matches_fp32": int(q_pred[i] == fp_pred[i]),
                    })

            # Restore checkpoint values in memory before exiting.
            model.set_weights(original_weights)

    summary_csv = output_dir / "kwt1_ptq_weight_validation_summary.csv"
    with summary_csv.open("w", newline="", encoding="utf-8-sig") as f:
        fields = list(results[0].keys()) if results else []
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)

    sample_csv = output_dir / "kwt1_ptq_weight_validation_predictions.csv"
    with sample_csv.open("w", newline="", encoding="utf-8-sig") as f:
        fields = list(sample_rows[0].keys()) if sample_rows else []
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sample_rows)

    details_json = output_dir / "kwt1_ptq_weight_validation_quantized_variables.json"
    with details_json.open("w", encoding="utf-8") as f:
        json.dump(weight_details, f, indent=2, ensure_ascii=False)

    manifest = {
        "checkpoint": str(checkpoint),
        "partition": "validation",
        "testing_partition_accessed": False,
        "validation_partition_size": total,
        "samples_evaluated": int(processed),
        "batch_size": int(args.batch_size),
        "fp32_validation_accuracy": fp_acc,
        "schemes": schemes,
        "method": "fake quantization/dequantization of matrix kernels inside the 12 encoder blocks only; offline input projection/embeddings and software classifier remain FP32; activations, biases and LayerNorm affine parameters remain FP32",
        "no_training_or_gradient_updates": True,
        "outputs": {
            "summary_csv": str(summary_csv),
            "predictions_csv": str(sample_csv),
            "quantized_variable_details_json": str(details_json),
        },
    }
    manifest_path = output_dir / "kwt1_ptq_weight_validation_manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print("\nSummary")
    print("Validation samples processed: {}/{}".format(processed, total))
    print("Testing partition accessed: NO")
    print("FP32 validation accuracy: {:.4%}".format(fp_acc))
    print("Summary CSV: {}".format(summary_csv))
    print("Per-sample predictions CSV: {}".format(sample_csv))
    print("Variable details JSON: {}".format(details_json))
    print("Manifest: {}".format(manifest_path))
    print("NOTE: Weight-only results are a sensitivity baseline, not full integer inference or final sign-off.")


if __name__ == "__main__":
    main()
