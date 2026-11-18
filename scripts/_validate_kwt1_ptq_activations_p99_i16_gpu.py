#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""KWT-1 validation-only activation fake-quant sensitivity experiment.

Uses the frozen pretrained checkpoint and training-only PTQ scale candidates.
Weights are fixed to symmetric per-output-channel INT8 for the 12 encoder blocks;
then one activation group at a time is fake-quantized (quantize/dequantize) while
all other activations and operations remain FP32. This is a sensitivity screen,
not full integer inference or RTL sign-off.

Validation partition only. No training, gradients, optimizer steps, testing split
access, or checkpoint writes.
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

# PTQ_GPU_SWEEP removed CPU-forcing line
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np
import tensorflow as tensorflow

tensorflow.compat.v1.disable_eager_execution()

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from kws_streaming.layers.compat import tf  # noqa: E402
from kws_streaming.train import model_train_eval as _official_entry  # noqa: E402,F401
from kws_streaming.models import kws_transformer  # noqa: E402
from kws_streaming.data import input_data  # noqa: E402
from kws_streaming.models.transformer_utils import KWSTransformer  # noqa: E402


SIGNED_GROUPS = {
    "input": {"encoder_input"},
    "qkv": {"q_projection", "k_projection", "v_projection"},
    "scores": {"attention_score_scaled"},
    "context": {"attention_context", "attention_output_projection"},
    "residual": {"residual1_sum", "residual2_sum"},
    "norm": {"layernorm1_output", "layernorm2_output"},
    "ffn": {"ffn_dense1_output", "gelu_output", "ffn_dense2_output"},
}
ALLOWED_GROUPS = set(SIGNED_GROUPS) | {"softmax"}


def labels_to_ids(labels):
    labels = np.asarray(labels)
    if labels.ndim > 1:
        return np.argmax(labels, axis=-1).astype(np.int64)
    return labels.reshape(-1).astype(np.int64)


def to_logits(pred):
    if isinstance(pred, (list, tuple)):
        if len(pred) != 1:
            raise RuntimeError("Expected exactly one logits output, got {} outputs".format(len(pred)))
        pred = pred[0]
    return np.asarray(pred, dtype=np.float32)


def build_flags(model_dir, data_dir, batch_size):
    with (model_dir / "flags.json").open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.update({
        "data_dir": str(data_dir), "data_url": "", "train_dir": str(model_dir),
        "training": False, "train": 0, "batch_size": int(batch_size),
        "return_softmax": 0, "background_frequency": 0.0, "background_volume": 0.0,
        "time_shift_ms": 0.0, "sp_time_shift_ms": 0.0, "resample": 0.0,
        "pick_deterministically": True, "distill_teacher_json": "",
        "prenorm": False, "approximate_gelu": False,
    })
    return SimpleNamespace(**cfg)


def is_weight_target(name, arr, encoder_variable_names):
    low = name.lower()
    if name not in encoder_variable_names:
        return False
    if any(token in low for token in ("bias", "/beta", "beta:", "/gamma", "gamma:", "layernorm", "layer_normalization")):
        return False
    return "kernel" in low and np.asarray(arr).ndim >= 2


def fake_quant_weight_per_output_channel(arr, bits=8):
    arr64 = np.asarray(arr, dtype=np.float64)
    qmax = (1 << (bits - 1)) - 1
    if arr64.ndim < 2 or arr64.size == 0:
        scale = max(float(np.max(np.abs(arr64))) / qmax, 1e-12) if arr64.size else 1.0
        q = np.clip(np.rint(arr64 / scale), -qmax, qmax)
        return (q * scale).astype(np.asarray(arr).dtype, copy=False)
    reduce_axes = tuple(range(arr64.ndim - 1))
    max_abs = np.max(np.abs(arr64), axis=reduce_axes, keepdims=True)
    scale = np.maximum(max_abs / qmax, 1e-12)
    q = np.clip(np.rint(arr64 / scale), -qmax, qmax)
    return (q * scale).astype(np.asarray(arr).dtype, copy=False)


def load_activation_scales(path, threshold_source, signed_bits):
    if not path.is_file():
        raise FileNotFoundError("Training calibration candidates not found: {}".format(path))
    rows = {}
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = row.get("tensor", "")
            fmt = row.get("format", "")
            source = row.get("threshold_source", "")
            if fmt == "INT8" and source == threshold_source:
                try:
                    threshold = float(row["clip_threshold"])
                except (ValueError, TypeError, KeyError):
                    continue
                if np.isfinite(threshold) and threshold > 0:
                    rows[name] = threshold
    if not rows:
        raise RuntimeError("No INT8 activation thresholds found for threshold_source={!r} in {}".format(
            threshold_source, path))
    qmax = (1 << (signed_bits - 1)) - 1
    return {name: threshold / qmax for name, threshold in rows.items()}


def build_activation_model(model, transformer, selected_group, scale_map, activation_bits, softmax_bits):
    """Build a shared-weight Keras graph with one activation group fake-quantized."""
    from kws_streaming.models.transformer_utils import KWSTransformer as _KWT  # noqa: F811
    if not isinstance(transformer, _KWT):
        raise TypeError("Expected KWSTransformer")

    feature_layers = [layer for layer in model.layers if layer.__class__.__name__ == "SpeechFeatures"]
    if len(feature_layers) != 1:
        raise RuntimeError("Expected one top-level SpeechFeatures layer; found {}".format(len(feature_layers)))
    features_model = tf.keras.Model(inputs=model.input, outputs=feature_layers[0].output,
                                    name="kwt_ptq_activation_feature_tap")
    features = features_model.output
    x = transformer.patch_proj(features)
    batch_size_tensor = tf.shape(x)[0]
    class_emb = tf.broadcast_to(transformer.class_emb, [batch_size_tensor, 1, transformer.d_model])
    x = tf.concat([class_emb, x], axis=1)
    x = x + transformer.pos_emb

    def quantize(name, tensor):
        if selected_group is None:
            return tensor
        short_name = name.split("/", 1)[-1]
        should_quantize = short_name in SIGNED_GROUPS.get(selected_group, set())
        if selected_group == "softmax" and short_name == "attention_softmax":
            qmax = (1 << softmax_bits) - 1
            step = 1.0 / qmax
            clipped = tf.clip_by_value(tensor, 0.0, 1.0)
            return tf.round(clipped / step) * step
        if not should_quantize:
            return tensor
        if name not in scale_map:
            raise KeyError("Missing training-calibrated scale for activation tensor {!r}".format(name))
        step = float(scale_map[name])
        threshold = step * ((1 << (activation_bits - 1)) - 1)
        clipped = tf.clip_by_value(tensor, -threshold, threshold)
        return tf.round(clipped / step) * step

    x = quantize("encoder_input", x)
    for layer_idx, block in enumerate(transformer.enc_layers):
        prefix = "layer_{:02d}".format(layer_idx)
        att = block.att
        q = quantize(prefix + "/q_projection", att.query_dense(x))
        k = quantize(prefix + "/k_projection", att.key_dense(x))
        v = quantize(prefix + "/v_projection", att.value_dense(x))

        qh = att.separate_heads(q, batch_size_tensor)
        kh = att.separate_heads(k, batch_size_tensor)
        vh = att.separate_heads(v, batch_size_tensor)
        score_heads = tf.matmul(qh, kh, transpose_b=True)
        dim_key = tf.cast(tf.shape(kh)[-1], tensorflow.float32)
        scaled_heads = score_heads / tf.math.sqrt(dim_key)
        scaled_heads = quantize(prefix + "/attention_score_scaled", scaled_heads)
        weight_heads = tf.nn.softmax(scaled_heads, axis=-1)
        weight_heads = quantize(prefix + "/attention_softmax", weight_heads)
        context_heads = tf.matmul(weight_heads, vh)

        context = tf.transpose(context_heads, perm=[0, 2, 1, 3])
        context = tf.reshape(context, (batch_size_tensor, -1, transformer.d_model))
        context = quantize(prefix + "/attention_context", context)
        attn_projected = att.combine_heads(context)
        attn_projected = quantize(prefix + "/attention_output_projection", attn_projected)

        residual1 = x + block.dropout1(attn_projected, training=False)
        residual1 = quantize(prefix + "/residual1_sum", residual1)
        norm1 = block.layernorm1(residual1)
        norm1 = quantize(prefix + "/layernorm1_output", norm1)

        ffn_dense1 = block.ffn.layers[0](norm1)
        ffn_dense1 = quantize(prefix + "/ffn_dense1_output", ffn_dense1)
        gelu = block.ffn.layers[1](ffn_dense1)
        gelu = quantize(prefix + "/gelu_output", gelu)
        ffn_dense2 = block.ffn.layers[2](gelu)
        ffn_dense2 = quantize(prefix + "/ffn_dense2_output", ffn_dense2)

        residual2 = norm1 + block.dropout2(ffn_dense2, training=False)
        residual2 = quantize(prefix + "/residual2_sum", residual2)
        x = block.layernorm2(residual2)
        x = quantize(prefix + "/layernorm2_output", x)

    logits = model.layers[-1](x[:, 0, :])
    name = "kwt_manual_fp32_reference" if selected_group is None else "kwt_ptq_activation_{}".format(selected_group)
    return tf.keras.Model(inputs=model.input, outputs=logits, name=name)


def get_validation_batch(processor, flags, sess, batch_size):
    x, y = processor.get_data(batch_size, 0, flags, 0.0, 0.0, 0, "validation", 0.0, 0.0, sess)
    return np.asarray(x), labels_to_ids(y)


def run_partition(infer_model, processor, flags, sess, total, batch_size, max_samples, group_name):
    limit = total if max_samples == 0 else min(total, max_samples)
    logits_all, labels_all = [], []
    for offset in range(0, limit, batch_size):
        real_n = min(batch_size, limit - offset)
        bx, by = processor.get_data(real_n, offset, flags, 0.0, 0.0, 0, "validation", 0.0, 0.0, sess)
        bx = np.asarray(bx)
        by = labels_to_ids(by)
        if real_n < batch_size:
            bx_model = np.concatenate([bx, np.repeat(bx[-1:], batch_size - real_n, axis=0)], axis=0)
        else:
            bx_model = bx
        out = to_logits(infer_model.predict(bx_model, batch_size=batch_size, verbose=0))[:real_n]
        logits_all.append(out)
        labels_all.append(by[:real_n])
        done = offset + real_n
        if done % (batch_size * 20) == 0 or done == limit:
            print("  {}: {}/{} samples".format(group_name, done, limit))
    return np.concatenate(logits_all, axis=0), np.concatenate(labels_all, axis=0), limit


def metrics_row(scheme, logits, labels, fp_logits, fp_pred, fp_acc, base_pred=None, base_acc=None):
    pred = np.argmax(logits, axis=-1)
    diff = logits.astype(np.float64) - fp_logits.astype(np.float64)
    acc = float(np.mean(pred == labels)) if labels.size else float("nan")
    finite_count = int(np.count_nonzero(np.isfinite(logits)))
    row = {
        "scheme": scheme,
        "partition": "validation",
        "samples": int(labels.size),
        "fp32_accuracy": fp_acc,
        "quant_accuracy": acc,
        "accuracy_drop_vs_fp32_pp": (fp_acc - acc) * 100.0,
        "prediction_agreement_vs_fp32": float(np.mean(pred == fp_pred)) if labels.size else float("nan"),
        "logit_rmse_vs_fp32": float(np.sqrt(np.mean(diff * diff))) if diff.size else float("nan"),
        "logit_mae_vs_fp32": float(np.mean(np.abs(diff))) if diff.size else float("nan"),
        "logit_max_abs_error_vs_fp32": float(np.max(np.abs(diff))) if diff.size else float("nan"),
        "nonfinite_logit_count": int(logits.size - finite_count),
        "testing_partition_accessed": False,
    }
    if base_pred is not None and base_acc is not None:
        row["accuracy_drop_vs_w8_channel_pp"] = (base_acc - acc) * 100.0
        row["prediction_agreement_vs_w8_channel"] = float(np.mean(pred == base_pred)) if labels.size else float("nan")
    else:
        row["accuracy_drop_vs_w8_channel_pp"] = 0.0
        row["prediction_agreement_vs_w8_channel"] = 1.0
    return row, pred


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--model-dir", default=None)
    ap.add_argument("--calibration-csv", default=None,
                    help="Training-only kwt1_ptq_activation_scale_candidates.csv")
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--max-samples", type=int, default=512,
                    help="Validation sample limit; 0 means full validation partition.")
    ap.add_argument("--groups", default="input,qkv,scores,softmax,context,residual,norm,ffn",
                    help="Comma-separated activation groups: {}".format(",".join(sorted(ALLOWED_GROUPS))))
    ap.add_argument("--threshold-source", choices=["abs_p99_est", "abs_p999_est", "max_abs"], default='abs_p99_est')
    ap.add_argument("--activation-bits", type=int, choices=[8, 16], default=16,
                    help="Signed activation fake-quant bit width.")
    ap.add_argument("--softmax-bits", type=int, choices=[8, 16], default=16,
                    help="Unsigned Softmax probability fake-quant bit width (default 16 for cautious first pass).")
    args = ap.parse_args()
    if args.batch_size < 1 or args.max_samples < 0:
        ap.error("--batch-size must be >=1 and --max-samples must be >=0")
    groups = [g.strip().lower() for g in args.groups.split(",") if g.strip()]
    bad = [g for g in groups if g not in ALLOWED_GROUPS]
    if bad:
        ap.error("Unknown groups {}. Allowed: {}".format(bad, sorted(ALLOWED_GROUPS)))
    if len(set(groups)) != len(groups):
        ap.error("Please specify each activation group only once")

    data_dir = Path(args.data_dir).resolve() if args.data_dir else REPO_DIR / "data2"
    model_dir = Path(args.model_dir).resolve() if args.model_dir else REPO_DIR / "models_data_v2_12_labels" / "kwt1"
    default_cal_dir = REPO_DIR / "testdata" / "ptq_calibration"
    calibration_csv = Path(args.calibration_csv).resolve() if args.calibration_csv else default_cal_dir / "kwt1_ptq_activation_scale_candidates.csv"
    output_dir = Path(args.output_dir).resolve() if args.output_dir else REPO_DIR / "testdata" / "ptq_activation_validation"
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = model_dir / "best_weights"
    if not data_dir.is_dir():
        raise FileNotFoundError("Dataset directory not found: {}".format(data_dir))
    if not (model_dir / "flags.json").is_file():
        raise FileNotFoundError("Model flags not found: {}".format(model_dir / "flags.json"))
    if not Path(str(checkpoint) + ".index").is_file():
        raise FileNotFoundError("Checkpoint index not found: {}.index".format(checkpoint))

    scale_map = load_activation_scales(calibration_csv, args.threshold_source, args.activation_bits)
    flags = build_flags(model_dir, data_dir, args.batch_size)
    tf1 = tensorflow.compat.v1
    graph = tf1.Graph()
    results, prediction_rows = [], []

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

            transformers = [layer for layer in model.layers if isinstance(layer, KWSTransformer)]
            if len(transformers) != 1 or len(transformers[0].enc_layers) != 12:
                raise RuntimeError("Expected exactly one 12-layer KWSTransformer")
            transformer = transformers[0]
            variable_names = [v.name for v in model.weights]
            encoder_variable_names = {v.name for block in transformer.enc_layers for v in block.weights}
            original_weights = [np.asarray(w).copy() for w in model.get_weights()]
            if len(variable_names) != len(original_weights):
                raise RuntimeError("Model variable/weight count mismatch")
            quantizable_count = sum(is_weight_target(n, w, encoder_variable_names)
                                    for n, w in zip(variable_names, original_weights))
            if quantizable_count != 72:
                raise RuntimeError("Expected 72 encoder matrix kernels; found {}. Check model/variable matching.".format(quantizable_count))

            activation_models = {
                group: build_activation_model(model, transformer, group, scale_map,
                                              args.activation_bits, args.softmax_bits)
                for group in groups
            }
            manual_fp_model = build_activation_model(model, transformer, None, scale_map,
                                                     args.activation_bits, args.softmax_bits)

            total = int(processor.set_size("validation"))
            if total <= 0:
                raise RuntimeError("Validation partition is empty")
            process_limit = total if args.max_samples == 0 else min(total, args.max_samples)
            label_names = list(getattr(processor, "words_list", []))
            if not label_names:
                label_names = ["_silence_", "_unknown_"] + flags.wanted_words.split(",")

            print("Checkpoint: {}".format(checkpoint))
            print("Calibration scales: {}".format(calibration_csv))
            print("Scale threshold source: {}".format(args.threshold_source))
            print("Validation partition size: {}".format(total))
            print("Samples evaluated this run: {}".format(process_limit))
            print("Testing partition accessed: NO")
            print("Encoder matrix kernels quantized to W8_CHANNEL: {}".format(quantizable_count))
            print("Activation bits: signed INT{}; Softmax UINT{}".format(args.activation_bits, args.softmax_bits))
            print("Activation groups: {}".format(",".join(groups)))

            # Sanity-check manually reconstructed graph against official model before changing weights.
            first_x, _ = get_validation_batch(processor, flags, sess, args.batch_size)
            official_first = to_logits(model.predict(first_x, batch_size=args.batch_size, verbose=0))
            manual_first = to_logits(manual_fp_model.predict(first_x, batch_size=args.batch_size, verbose=0))
            manual_diff = float(np.max(np.abs(official_first - manual_first)))
            print("Manual-vs-official max abs logit diff (first batch): {:.8g}".format(manual_diff))
            if not np.isfinite(manual_diff) or manual_diff > 1e-4:
                raise RuntimeError("Manual graph does not match the official model; stop activation evaluation")

            # FP32 reference.
            model.set_weights(original_weights)
            fp_logits, labels, processed = run_partition(
                model, processor, flags, sess, total, args.batch_size, args.max_samples, "FP32")
            fp_pred = np.argmax(fp_logits, axis=-1)
            fp_acc = float(np.mean(fp_pred == labels))
            fp_row, _ = metrics_row("FP32", fp_logits, labels, fp_logits, fp_pred, fp_acc)
            fp_row.update({"activation_group": "none", "activation_quantization": "none", "weight_quantization": "FP32"})
            results.append(fp_row)
            print("FP32 validation accuracy: {:.4%} ({}/{})".format(fp_acc, int(np.sum(fp_pred == labels)), len(labels)))

            # Fixed W8 per-output-channel matrix-kernel baseline.
            w8_weights = []
            for name, arr in zip(variable_names, original_weights):
                if is_weight_target(name, arr, encoder_variable_names):
                    w8_weights.append(fake_quant_weight_per_output_channel(arr, 8))
                else:
                    w8_weights.append(np.asarray(arr).copy())
            model.set_weights(w8_weights)
            w8_logits, w8_labels, _ = run_partition(
                model, processor, flags, sess, total, args.batch_size, args.max_samples, "W8_CHANNEL")
            if not np.array_equal(labels, w8_labels):
                raise RuntimeError("Validation label order differs between runs")
            w8_pred = np.argmax(w8_logits, axis=-1)
            w8_acc = float(np.mean(w8_pred == labels))
            w8_row, _ = metrics_row("W8_CHANNEL", w8_logits, labels, fp_logits, fp_pred, fp_acc)
            w8_row.update({"activation_group": "none", "activation_quantization": "none", "weight_quantization": "INT8 per-output-channel"})
            results.append(w8_row)
            print("W8_CHANNEL baseline accuracy: {:.4%}; drop={:+.4f} pp".format(w8_acc, (fp_acc - w8_acc) * 100.0))

            # Each experiment quantizes one activation group on top of the same W8 weight baseline.
            for group in groups:
                model.set_weights(w8_weights)
                group_model = activation_models[group]
                q_logits, q_labels, _ = run_partition(
                    group_model, processor, flags, sess, total, args.batch_size, args.max_samples,
                    "ACT_{}_I{}_U{}".format(group.upper(), args.activation_bits, args.softmax_bits))
                if not np.array_equal(labels, q_labels):
                    raise RuntimeError("Validation label order changed for activation group {}".format(group))
                scheme = "W8_CHANNEL_ACT_{}_SINT{}_SOFTMAX_UINT{}".format(
                    group.upper(), args.activation_bits, args.softmax_bits)
                row, q_pred = metrics_row(scheme, q_logits, labels, fp_logits, fp_pred, fp_acc,
                                          base_pred=w8_pred, base_acc=w8_acc)
                row.update({
                    "activation_group": group,
                    "activation_quantization": "fake-quant/dequant; training calibration scale; {}-bit".format(
                        args.softmax_bits if group == "softmax" else args.activation_bits),
                    "weight_quantization": "INT8 per-output-channel encoder matrix kernels",
                    "threshold_source": args.threshold_source,
                    "calibration_partition": "training",
                    "calibration_csv": str(calibration_csv),
                })
                results.append(row)
                print("{} accuracy: {:.4%}; drop_vs_FP32={:+.4f} pp; extra_drop_vs_W8={:+.4f} pp; agree_FP32={:.4%}; RMSE={:.6g}".format(
                    scheme, row["quant_accuracy"], row["accuracy_drop_vs_fp32_pp"],
                    row["accuracy_drop_vs_w8_channel_pp"], row["prediction_agreement_vs_fp32"],
                    row["logit_rmse_vs_fp32"]))
                for i, label_id in enumerate(labels):
                    pred_id = int(q_pred[i])
                    prediction_rows.append({
                        "sample_offset": i,
                        "true_label_id": int(label_id),
                        "true_label": label_names[int(label_id)] if 0 <= int(label_id) < len(label_names) else str(int(label_id)),
                        "fp32_predicted_id": int(fp_pred[i]),
                        "w8_channel_predicted_id": int(w8_pred[i]),
                        "scheme": scheme,
                        "quant_predicted_id": pred_id,
                        "quant_predicted_label": label_names[pred_id] if 0 <= pred_id < len(label_names) else str(pred_id),
                        "fp32_correct": int(fp_pred[i] == label_id),
                        "w8_channel_correct": int(w8_pred[i] == label_id),
                        "quant_correct": int(pred_id == label_id),
                        "prediction_matches_fp32": int(pred_id == fp_pred[i]),
                        "prediction_matches_w8_channel": int(pred_id == w8_pred[i]),
                    })

            # Restore weights in-memory; checkpoint on disk is never modified.
            model.set_weights(original_weights)

    summary_path = output_dir / "kwt1_ptq_activation_validation_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8-sig") as f:
        fields = []
        for record in results:
            for key in record.keys():
                if key not in fields:
                    fields.append(key)
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)
    pred_path = output_dir / "kwt1_ptq_activation_validation_predictions.csv"
    with pred_path.open("w", newline="", encoding="utf-8-sig") as f:
        fields = list(prediction_rows[0].keys()) if prediction_rows else []
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(prediction_rows)
    manifest = {
        "checkpoint": str(checkpoint),
        "partition": "validation",
        "testing_partition_accessed": False,
        "validation_partition_size": total,
        "samples_evaluated": int(processed),
        "activation_groups": groups,
        "activation_bits": int(args.activation_bits),
        "softmax_bits": int(args.softmax_bits),
        "threshold_source": args.threshold_source,
        "calibration_partition": "training",
        "calibration_csv": str(calibration_csv),
        "weight_scheme": "symmetric INT8 per-output-channel fake quantization of 72 matrix kernels in the 12 encoder blocks; bias and LayerNorm affine parameters FP32",
        "method": "single-group activation fake quantization/dequantization on top of W8_CHANNEL weight baseline; all other math FP32; sensitivity experiment only, not RTL sign-off",
        "manual_vs_official_max_abs_logit_diff_first_batch": manual_diff,
        "no_training_or_gradient_updates": True,
        "outputs": {"summary_csv": str(summary_path), "predictions_csv": str(pred_path)},
    }
    manifest_path = output_dir / "kwt1_ptq_activation_validation_manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print("\nSummary")
    print("Validation samples processed: {}/{}".format(processed, total))
    print("Testing partition accessed: NO")
    print("FP32 validation accuracy: {:.4%}".format(fp_acc))
    print("Summary CSV: {}".format(summary_path))
    print("Per-sample predictions CSV: {}".format(pred_path))
    print("Manifest: {}".format(manifest_path))
    print("NOTE: Results isolate individual activation groups; they are not full integer inference or final sign-off.")


if __name__ == "__main__":
    main()
