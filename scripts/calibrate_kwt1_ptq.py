#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Calibrate KWT-1 PTQ candidates using the TRAINING partition only.

No weights are updated. This script runs the frozen FP32 checkpoint on a deterministic
subset of the training split, collects internal activation statistics, and emits candidate
symmetric INT8/INT16 scales. Dense kernels also get per-output-channel INT8 scale candidates.
The testing partition is deliberately never accessed. Validation-based accuracy experiments
should be run separately after these training-only candidates are generated.
"""
import argparse
import csv
import json
import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import tensorflow as tensorflow

# The repository uses TF1 graph/session APIs with TensorFlow 2.4.
tensorflow.compat.v1.disable_eager_execution()

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from kws_streaming.layers.compat import tf  # noqa: E402
# Match the import order and model constructor used by eval_kwt1_reference.py.
# Importing model_train_eval first also avoids the repository's model import cycle.
from kws_streaming.train import model_train_eval as _official_entry  # noqa: E402,F401
from kws_streaming.models import kws_transformer  # noqa: E402
from kws_streaming.data import input_data  # noqa: E402
from kws_streaming.models.transformer_utils import KWSTransformer  # noqa: E402


class TensorStats:
    """Streaming exact min/max/mean/std plus reservoir-estimated abs percentiles."""

    def __init__(self, name, rng, reservoir_size=100000):
        self.name = name
        self.rng = rng
        self.reservoir_size = int(reservoir_size)
        self.count = 0
        self.nonfinite = 0
        self.minimum = np.inf
        self.maximum = -np.inf
        self.sum_value = 0.0
        self.sum_square = 0.0
        self.reservoir = np.empty((0,), dtype=np.float32)
        self.reservoir_seen = 0

    def _reservoir_update(self, sampled_abs):
        values = np.asarray(sampled_abs, dtype=np.float32).reshape(-1)
        if values.size == 0:
            return

        cap = self.reservoir_size
        seen_before = self.reservoir_seen
        pos = 0
        if self.reservoir.size < cap:
            take = min(cap - self.reservoir.size, values.size)
            if take:
                self.reservoir = np.concatenate((self.reservoir, values[:take]))
                pos = take

        if pos < values.size:
            # Vectorized Algorithm R: choose a replacement index uniformly from
            # [0, number_of_values_seen_so_far); replace only if it falls in the reservoir.
            indices_seen = seen_before + np.arange(pos + 1, values.size + 1, dtype=np.int64)
            slots = (self.rng.random(values.size - pos) * indices_seen).astype(np.int64)
            replace = slots < cap
            if np.any(replace):
                self.reservoir[slots[replace]] = values[pos:][replace]
        self.reservoir_seen += values.size

    def update(self, batch_values, real_n, batch_size):
        arr = np.asarray(batch_values)[:real_n]
        flat = arr.reshape(-1)
        finite_mask = np.isfinite(flat)
        self.nonfinite += int(flat.size - np.count_nonzero(finite_mask))
        values = flat[finite_mask]
        if values.size == 0:
            return

        self.count += int(values.size)
        self.minimum = min(self.minimum, float(np.min(values)))
        self.maximum = max(self.maximum, float(np.max(values)))
        self.sum_value += float(np.sum(values, dtype=np.float64))
        values64 = values.astype(np.float64, copy=False)
        self.sum_square += float(np.sum(values64 * values64, dtype=np.float64))

        # Take a bounded random sample from each batch, proportional to real samples
        # (rather than padded rows); reservoir sampling combines batches uniformly.
        target = max(128, int(2048 * real_n / max(1, batch_size)))
        take = min(target, values.size)
        if take == values.size:
            sample = np.abs(values).astype(np.float32, copy=False)
        else:
            idx = self.rng.integers(0, values.size, size=take)
            sample = np.abs(values[idx]).astype(np.float32, copy=False)
        self._reservoir_update(sample)

    def record(self):
        if self.count == 0:
            mean = std = float("nan")
            p99 = p999 = float("nan")
        else:
            mean = self.sum_value / self.count
            variance = max(0.0, self.sum_square / self.count - mean * mean)
            std = math.sqrt(variance)
            if self.reservoir.size:
                p99, p999 = np.quantile(self.reservoir, [0.99, 0.999]).tolist()
            else:
                p99 = p999 = float("nan")
        return {
            "tensor": self.name,
            "element_count": self.count,
            "nonfinite_count": self.nonfinite,
            "min": self.minimum if self.count else float("nan"),
            "max": self.maximum if self.count else float("nan"),
            "max_abs": max(abs(self.minimum), abs(self.maximum)) if self.count else float("nan"),
            "mean": mean,
            "std": std,
            "abs_p99_est": float(p99),
            "abs_p999_est": float(p999),
            "percentile_sample_count": int(self.reservoir.size),
        }


class ChannelStats:
    """Streaming channel statistics for [batch, time, channel] tensors."""

    def __init__(self, name, channels):
        self.name = name
        self.channels = int(channels)
        self.count = np.zeros(channels, dtype=np.int64)
        self.nonfinite = np.zeros(channels, dtype=np.int64)
        self.minimum = np.full(channels, np.inf, dtype=np.float64)
        self.maximum = np.full(channels, -np.inf, dtype=np.float64)
        self.sum_value = np.zeros(channels, dtype=np.float64)
        self.sum_square = np.zeros(channels, dtype=np.float64)

    def update(self, batch_values, real_n):
        arr = np.asarray(batch_values)[:real_n]
        if arr.ndim != 3 or arr.shape[-1] != self.channels:
            return
        finite = np.isfinite(arr)
        counts = np.sum(finite, axis=(0, 1), dtype=np.int64)
        self.count += counts
        self.nonfinite += np.sum(~finite, axis=(0, 1), dtype=np.int64)

        # Given all tested activations are expected to be finite, nanmin/nanmax also
        # preserve useful range reporting if one bad value appears.
        safe = np.where(finite, arr, np.nan)
        with np.errstate(all="ignore"):
            mins = np.nanmin(safe, axis=(0, 1))
            maxs = np.nanmax(safe, axis=(0, 1))
        valid = counts > 0
        self.minimum[valid] = np.minimum(self.minimum[valid], mins[valid])
        self.maximum[valid] = np.maximum(self.maximum[valid], maxs[valid])
        safe64 = np.where(finite, arr, 0.0).astype(np.float64, copy=False)
        self.sum_value += np.sum(safe64, axis=(0, 1), dtype=np.float64)
        self.sum_square += np.sum(safe64 * safe64, axis=(0, 1), dtype=np.float64)

    def records(self):
        out = []
        for ch in range(self.channels):
            n = int(self.count[ch])
            mean = self.sum_value[ch] / n if n else float("nan")
            variance = max(0.0, self.sum_square[ch] / n - mean * mean) if n else float("nan")
            lo = float(self.minimum[ch]) if n else float("nan")
            hi = float(self.maximum[ch]) if n else float("nan")
            out.append({
                "tensor": self.name,
                "channel": ch,
                "element_count": n,
                "nonfinite_count": int(self.nonfinite[ch]),
                "min": lo,
                "max": hi,
                "max_abs": max(abs(lo), abs(hi)) if n else float("nan"),
                "mean": mean,
                "std": math.sqrt(variance) if n else float("nan"),
            })
        return out


def to_logits(pred):
    if isinstance(pred, (list, tuple)):
        if len(pred) != 1:
            raise RuntimeError(f"Expected one logits output, got {len(pred)} outputs")
        pred = pred[0]
    return np.asarray(pred)


def labels_to_ids(labels):
    labels = np.asarray(labels)
    if labels.ndim > 1:
        return np.argmax(labels, axis=-1).astype(np.int64)
    return labels.reshape(-1).astype(np.int64)


def build_internal_graph(model, feature_layer, transformer):
    """Build a shared-weight graph exposing internals without altering official source."""
    features_model = tf.keras.Model(
        inputs=model.input,
        outputs=feature_layer.output,
        name="kwt_mfcc_features_for_internal_capture",
    )
    features = features_model.output
    x = transformer.patch_proj(features)
    batch_size_tensor = tf.shape(x)[0]
    class_emb = tf.broadcast_to(
        transformer.class_emb, [batch_size_tensor, 1, transformer.d_model]
    )
    x = tf.concat([class_emb, x], axis=1)
    x = x + transformer.pos_emb

    names = []
    tensors = []

    def add(name, value):
        names.append(name)
        tensors.append(value)

    add("encoder_input", x)

    for layer_idx, block in enumerate(transformer.enc_layers):
        prefix = f"layer_{layer_idx:02d}"
        att = block.att
        q = att.query_dense(x)
        k = att.key_dense(x)
        v = att.value_dense(x)
        add(prefix + "/q_projection", q)
        add(prefix + "/k_projection", k)
        add(prefix + "/v_projection", v)

        qh = att.separate_heads(q, batch_size_tensor)
        kh = att.separate_heads(k, batch_size_tensor)
        vh = att.separate_heads(v, batch_size_tensor)
        score_heads = tf.matmul(qh, kh, transpose_b=True)
        dim_key = tf.cast(tf.shape(kh)[-1], tf.float32)
        scaled_heads = score_heads / tf.math.sqrt(dim_key)
        weight_heads = tf.nn.softmax(scaled_heads, axis=-1)
        context_heads = tf.matmul(weight_heads, vh)
        add(prefix + "/attention_score_raw", tf.squeeze(score_heads, axis=1))
        add(prefix + "/attention_score_scaled", tf.squeeze(scaled_heads, axis=1))
        add(prefix + "/attention_softmax", tf.squeeze(weight_heads, axis=1))

        context = tf.transpose(context_heads, perm=[0, 2, 1, 3])
        context = tf.reshape(context, (batch_size_tensor, -1, transformer.d_model))
        add(prefix + "/attention_context", context)
        attn_projected = att.combine_heads(context)
        add(prefix + "/attention_output_projection", attn_projected)

        residual1 = x + block.dropout1(attn_projected, training=False)
        add(prefix + "/residual1_sum", residual1)
        norm1 = block.layernorm1(residual1)
        add(prefix + "/layernorm1_output", norm1)

        ffn_dense1 = block.ffn.layers[0](norm1)
        add(prefix + "/ffn_dense1_output", ffn_dense1)
        gelu = block.ffn.layers[1](ffn_dense1)
        add(prefix + "/gelu_output", gelu)
        ffn_dense2 = block.ffn.layers[2](gelu)
        add(prefix + "/ffn_dense2_output", ffn_dense2)

        residual2 = norm1 + block.dropout2(ffn_dense2, training=False)
        add(prefix + "/residual2_sum", residual2)
        x = block.layernorm2(residual2)
        add(prefix + "/layernorm2_output", x)

    logits = model.layers[-1](x[:, 0, :])
    add("manual_logits", logits)
    capture_model = tf.keras.Model(
        inputs=model.input,
        outputs=tensors,
        name="kwt_internal_capture_all_layers",
    )
    return capture_model, names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=16,
                        help="Inference batch size; smaller uses less RAM (default: 16).")
    parser.add_argument("--reservoir-size", type=int, default=100000,
                        help="Max values sampled per tensor for abs-percentile estimates.")
    parser.add_argument("--data-dir", default=None,
                        help="Dataset directory (default: <repo>/data2).")
    parser.add_argument("--model-dir", default=None,
                        help="Model directory (default: <repo>/models_data_v2_12_labels/kwt1).")
    parser.add_argument("--output-dir", default=None,
                        help="Output directory (default: <repo>/testdata/ptq_calibration).")
    parser.add_argument("--max-samples", type=int, default=2048,
                        help="Training samples for calibration; 0 means the entire training split.")
    parser.add_argument("--check-only", action="store_true",
                        help="Process only the first 80 training samples as a smoke check; do not write output files.")
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be >= 1")
    if args.reservoir_size < 1000:
        parser.error("--reservoir-size must be >= 1000")
    if args.max_samples < 0:
        parser.error("--max-samples must be >= 0; use 0 for the entire training split")

    data_dir = Path(args.data_dir).resolve() if args.data_dir else REPO_DIR / "data2"
    model_dir = Path(args.model_dir).resolve() if args.model_dir else REPO_DIR / "models_data_v2_12_labels" / "kwt1"
    output_dir = Path(args.output_dir).resolve() if args.output_dir else REPO_DIR / "testdata" / "ptq_calibration"
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = model_dir / "best_weights"
    flags_file = model_dir / "flags.json"

    if not data_dir.exists():
        raise FileNotFoundError(f"Dataset directory not found: {data_dir}")
    if not flags_file.exists():
        raise FileNotFoundError(f"Model flags not found: {flags_file}")
    if not Path(str(checkpoint) + ".index").exists():
        raise FileNotFoundError(f"Checkpoint index not found: {checkpoint}.index")

    with flags_file.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.update({
        "data_dir": str(data_dir),
        "data_url": "",
        "train_dir": str(model_dir),
        "training": False,
        "batch_size": args.batch_size,
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
    flags = SimpleNamespace(**cfg)

    rng = np.random.default_rng(20261017)
    stats = {}
    channel_stats = {}
    predictions = []
    label_names = None
    official_manual_diff = None
    tested = 0
    official_correct_check = 0
    manual_correct_check = 0
    prediction_mismatch_check = 0

    # Session/Graph/global_variables_initializer are TF1 APIs. The repo's
    # `kws_streaming.layers.compat.tf` is TF2-compatible and intentionally has no
    # top-level Session attribute, so call these APIs through compat.v1.
    tf1 = tensorflow.compat.v1
    graph = tf1.Graph()
    with graph.as_default():
        with tf1.Session(graph=graph) as sess:
            # Keep Keras model.predict and AudioProcessor's graph ops in the same session.
            try:
                tf.keras.backend.set_session(sess)
            except AttributeError:
                tensorflow.compat.v1.keras.backend.set_session(sess)

            processor = input_data.AudioProcessor(flags)
            model = kws_transformer.model(flags)

            # IMPORTANT: mirror eval_kwt1_reference.py exactly. In this project,
            # model.load_weights() is the verified restore path for best_weights.
            sess.run(tf1.global_variables_initializer())
            status = model.load_weights(str(checkpoint))
            status.assert_existing_objects_matched()
            status.expect_partial()
            if hasattr(status, "run_restore_ops"):
                status.run_restore_ops()

            feature_layers = [layer for layer in model.layers
                              if layer.__class__.__name__ == "SpeechFeatures"]
            transformers = [layer for layer in model.layers if isinstance(layer, KWSTransformer)]
            if len(feature_layers) != 1 or len(transformers) != 1:
                names = [(layer.name, layer.__class__.__name__) for layer in model.layers]
                raise RuntimeError(
                    "Expected one top-level SpeechFeatures and one KWSTransformer layer; "
                    f"found feature_layers={len(feature_layers)}, transformers={len(transformers)}, "
                    f"model_layers={names}"
                )
            transformer = transformers[0]
            if transformer.num_layers != 12 or transformer.d_model != 64:
                raise RuntimeError(
                    f"Unexpected transformer config: layers={transformer.num_layers}, "
                    f"d_model={transformer.d_model}"
                )

            capture_model, tensor_names = build_internal_graph(model, feature_layers[0], transformer)
            for name in tensor_names:
                stats[name] = TensorStats(name, rng, args.reservoir_size)

            # The per-channel report applies to vector activations, excluding 99x99 attention maps.
            channel_exclude = ("attention_score", "attention_softmax")

            total = int(processor.set_size("training"))
            if total <= 0:
                raise RuntimeError("AudioProcessor training set is empty")
            if args.check_only:
                process_limit = min(total, 80)
            elif args.max_samples == 0:
                process_limit = total
            else:
                process_limit = min(total, args.max_samples)
            label_names = list(getattr(processor, "words_list", []))
            if not label_names:
                label_names = ["_silence_", "_unknown_"] + flags.wanted_words.split(",")

            print(f"Checkpoint: {checkpoint}")
            print(f"Data directory: {data_dir}")
            print(f"TRAINING partition size: {total}")
            print(f"Training samples to process this run: {process_limit}")
            print("Testing partition access: DISABLED")
            print(f"Batch size: {args.batch_size}")
            print(f"Capture tensors: {len(tensor_names)}")

            for offset in range(0, process_limit, args.batch_size):
                real_n = min(args.batch_size, process_limit - offset)
                batch_x, batch_y = processor.get_data(
                    real_n, offset, flags,
                    0.0, 0.0, 0, "training", 0.0, 0.0, sess
                )
                batch_x = np.asarray(batch_x)
                y_ids = labels_to_ids(batch_y)
                if real_n < args.batch_size:
                    pad_n = args.batch_size - real_n
                    pad_x = np.repeat(batch_x[-1:], pad_n, axis=0)
                    batch_x_model = np.concatenate((batch_x, pad_x), axis=0)
                else:
                    batch_x_model = batch_x

                outputs = capture_model.predict(batch_x_model, batch_size=args.batch_size, verbose=0)
                if not isinstance(outputs, (list, tuple)):
                    outputs = [outputs]
                if len(outputs) != len(tensor_names):
                    raise RuntimeError(f"Capture output mismatch: {len(outputs)} vs {len(tensor_names)}")

                output_map = dict(zip(tensor_names, outputs))
                manual_logits = np.asarray(output_map["manual_logits"])[:real_n]
                pred_ids = np.argmax(manual_logits, axis=-1).astype(np.int64)
                for i in range(real_n):
                    true_id = int(y_ids[i])
                    pred_id = int(pred_ids[i])
                    true_name = label_names[true_id] if 0 <= true_id < len(label_names) else str(true_id)
                    pred_name = label_names[pred_id] if 0 <= pred_id < len(label_names) else str(pred_id)
                    predictions.append({
                        "training_offset": offset + i,
                        "true_label_id": true_id,
                        "true_label": true_name,
                        "predicted_label_id": pred_id,
                        "predicted_label": pred_name,
                        "correct": int(true_id == pred_id),
                    })

                # Compare with official model output to validate our internal graph.
                if args.check_only or offset == 0:
                    official = to_logits(
                        model.predict(batch_x_model, batch_size=args.batch_size, verbose=0)
                    )[:real_n]
                    diff = float(np.max(np.abs(official - manual_logits)))
                    official_manual_diff = (
                        diff if official_manual_diff is None
                        else max(official_manual_diff, diff)
                    )
                    official_pred = np.argmax(official, axis=-1).astype(np.int64)
                    manual_pred = np.argmax(manual_logits, axis=-1).astype(np.int64)
                    official_correct_check += int(np.sum(official_pred == y_ids))
                    manual_correct_check += int(np.sum(manual_pred == y_ids))
                    prediction_mismatch_check += int(np.sum(official_pred != manual_pred))
                    if args.check_only:
                        print(
                            f"[CHECK] offset={offset}, n={real_n}, "
                            f"official_acc={np.mean(official_pred == y_ids):.4f}, "
                            f"manual_acc={np.mean(manual_pred == y_ids):.4f}, "
                            f"logit_diff={diff:.8g}"
                        )

                for name, values in output_map.items():
                    arr = np.asarray(values)
                    stats[name].update(arr, real_n, args.batch_size)
                    if (arr.ndim == 3 and name not in channel_exclude
                            and not name.endswith("logits")):
                        channels = int(arr.shape[-1])
                        if name not in channel_stats:
                            channel_stats[name] = ChannelStats(name, channels)
                        channel_stats[name].update(arr, real_n)

                tested += real_n
                if tested % (args.batch_size * 10) == 0 or tested == process_limit:
                    print(f"Processed {tested}/{process_limit} samples")

            # Snapshot the loaded weights for scale candidates before the graph closes.
            weight_variable_names = [v.name for v in model.trainable_variables]
            weight_variable_values = sess.run(model.trainable_variables)

            if args.check_only:
                denom = max(1, tested)
                print("\nCHECK-ONLY SUMMARY (training partition; no files written)")
                print(f"Samples checked: {tested}")
                print(f"Official accuracy on this training subset (diagnostic only): {official_correct_check / denom:.4%}")
                print(f"Manual accuracy on this training subset (diagnostic only): {manual_correct_check / denom:.4%}")
                print(f"Prediction mismatches: {prediction_mismatch_check}")
                print(f"Maximum official-vs-manual logit difference: {official_manual_diff}")
                if (official_manual_diff is not None and official_manual_diff < 1e-5
                        and prediction_mismatch_check == 0):
                    print("CHECK RESULT: PASS; run calibration without --check-only.")
                else:
                    print("CHECK RESULT: FAIL; do not use calibration outputs.")
                return

    # Write outputs after the session closes.
    stats_path = output_dir / "kwt1_ptq_training_activation_stats.csv"
    channel_path = output_dir / "kwt1_ptq_training_channel_stats.csv"
    predictions_path = output_dir / "kwt1_ptq_training_predictions.csv"
    activation_candidates_path = output_dir / "kwt1_ptq_activation_scale_candidates.csv"
    weight_stats_path = output_dir / "kwt1_ptq_weight_stats.csv"
    weight_scales_path = output_dir / "kwt1_ptq_weight_scales.json"
    manifest_path = output_dir / "kwt1_ptq_calibration_manifest.json"

    stat_records = [stats[name].record() for name in tensor_names]
    with stats_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(stat_records[0].keys()))
        writer.writeheader()
        writer.writerows(stat_records)

    channel_records = []
    for name in tensor_names:
        if name in channel_stats:
            channel_records.extend(channel_stats[name].records())
    with channel_path.open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["tensor", "channel", "element_count", "nonfinite_count", "min", "max",
                  "max_abs", "mean", "std"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(channel_records)

    with predictions_path.open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["training_offset", "true_label_id", "true_label", "predicted_label_id",
                  "predicted_label", "correct"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(predictions)

    correct_n = sum(row["correct"] for row in predictions)
    accuracy = correct_n / len(predictions) if predictions else float("nan")

    # Generate candidate scales from TRAINING activation statistics only.
    candidate_rows = []
    for rec in stat_records:
        name = str(rec["tensor"])
        if name == "manual_logits":
            # The classification head is evaluated in software and is not accelerator work.
            continue
        if name.endswith("attention_score_raw"):
            # This is QK^T accumulator data; keep INT32 in the first implementation.
            candidate_rows.append({
                "tensor": name, "role": "qk_dot_accumulator", "format": "INT32_ACCUM",
                "threshold_source": "none", "clip_threshold": "", "qmin": "", "qmax": "",
                "scale": "", "step": "", "estimated_tail_fraction": "",
                "calibration_partition": "training", "calibration_samples": tested,
                "note": "Keep as wide accumulator; do not quantize raw score in baseline."
            })
            continue
        if name.endswith("attention_softmax"):
            # Probability is nonnegative and bounded in [0, 1]; include unsigned candidates.
            for bits, qmax in ((8, 255), (16, 65535)):
                scale = 1.0 / qmax
                candidate_rows.append({
                    "tensor": name, "role": "softmax_probability", "format": f"UINT{bits}",
                    "threshold_source": "fixed_probability_domain", "clip_threshold": 1.0,
                    "qmin": 0, "qmax": qmax, "scale": scale, "step": scale,
                    "estimated_tail_fraction": 0.0, "calibration_partition": "training",
                    "calibration_samples": tested,
                    "note": "Fixed [0,1] probability range; validate row-sum and accuracy on validation split."
                })
            continue
        for bits, qmax in ((8, 127), (16, 32767)):
            for src, tail in (("abs_p99_est", 0.01), ("abs_p999_est", 0.001), ("max_abs", 0.0)):
                try:
                    threshold = float(rec[src])
                except (TypeError, ValueError):
                    continue
                if not np.isfinite(threshold) or threshold <= 0:
                    threshold = 1e-12
                scale = threshold / qmax
                candidate_rows.append({
                    "tensor": name, "role": "signed_activation", "format": f"INT{bits}",
                    "threshold_source": src, "clip_threshold": threshold, "qmin": -qmax,
                    "qmax": qmax, "scale": scale, "step": scale,
                    "estimated_tail_fraction": tail if tail else 0.0,
                    "calibration_partition": "training", "calibration_samples": tested,
                    "note": "Percentiles are reservoir estimates; max_abs candidate avoids clipping."
                })
    with activation_candidates_path.open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["tensor", "role", "format", "threshold_source", "clip_threshold", "qmin", "qmax",
                  "scale", "step", "estimated_tail_fraction", "calibration_partition",
                  "calibration_samples", "note"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(candidate_rows)

    # Per-output-channel INT8 scales for Dense kernels; other parameters use per-tensor scales.
    weight_records = []
    weight_scale_json = {"method": "symmetric INT8; Dense kernels per-output-channel, other parameters per-tensor",
                         "calibration_source": "frozen pretrained checkpoint; no training or test examples used",
                         "variables": []}
    for var_name, raw in zip(weight_variable_names, weight_variable_values):
        arr = np.asarray(raw, dtype=np.float64)
        abs_arr = np.abs(arr)
        max_abs = float(np.max(abs_arr)) if arr.size else 0.0
        scale_tensor = max(max_abs / 127.0, 1e-12)
        is_kernel = ("kernel" in var_name.lower()) and arr.ndim >= 2
        per_out_max = None
        per_out_scale = None
        if is_kernel:
            reduce_axes = tuple(range(arr.ndim - 1))
            per_out_max = np.max(abs_arr, axis=reduce_axes)
            per_out_scale = np.maximum(per_out_max / 127.0, 1e-12)
        row = {
            "variable": var_name, "shape": json.dumps(list(arr.shape)), "rank": arr.ndim,
            "element_count": int(arr.size), "min": float(np.min(arr)) if arr.size else 0.0,
            "max": float(np.max(arr)) if arr.size else 0.0, "max_abs": max_abs,
            "mean": float(np.mean(arr)) if arr.size else 0.0,
            "std": float(np.std(arr)) if arr.size else 0.0,
            "int8_per_tensor_scale": scale_tensor,
            "quantization_axis": -1 if is_kernel else "per_tensor",
            "int8_per_output_channel_scales": json.dumps(per_out_scale.tolist()) if is_kernel else ""
        }
        weight_records.append(row)
        weight_scale_json["variables"].append({
            "name": var_name, "shape": list(arr.shape), "max_abs": max_abs,
            "scheme": "per_output_channel" if is_kernel else "per_tensor",
            "axis": -1 if is_kernel else None,
            "int8_scale": per_out_scale.tolist() if is_kernel else scale_tensor,
            "note": "Candidate only; bias scale depends on preceding activation scale."
        })
    with weight_stats_path.open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["variable", "shape", "rank", "element_count", "min", "max", "max_abs", "mean", "std",
                  "int8_per_tensor_scale", "quantization_axis", "int8_per_output_channel_scales"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(weight_records)
    with weight_scales_path.open("w", encoding="utf-8") as f:
        json.dump(weight_scale_json, f, indent=2, ensure_ascii=False)
    nonfinite_total = sum(rec["nonfinite_count"] for rec in stat_records)
    manifest = {
        "checkpoint": str(checkpoint),
        "data_dir": str(data_dir),
        "model_config": {
            "num_layers": int(flags.num_layers),
            "d_model": int(flags.d_model),
            "heads": int(flags.heads),
            "mlp_dim": int(flags.mlp_dim),
            "attention_type": str(flags.attention_type),
            "prenorm": bool(flags.prenorm),
            "approximate_gelu": bool(flags.approximate_gelu),
            "batch_size": int(args.batch_size),
        },
        "calibration_partition": "training",
        "testing_partition_accessed": False,
        "training_partition_size": int(total),
        "training_samples_processed": int(tested),
        "calibration_sample_limit": int(args.max_samples),
        "internal_tensors_analyzed": len(tensor_names),
        "nonfinite_values_across_analyzed_tensors": int(nonfinite_total),
        "manual_vs_official_max_abs_logit_difference_first_batch": official_manual_diff,
        "manual_logits_training_subset_accuracy_diagnostic_only": float(accuracy),
        "correct_predictions": int(correct_n),
        "percentile_method": (
            "abs_p99_est and abs_p999_est are estimated from a bounded uniform reservoir "
            f"of up to {args.reservoir_size} absolute activation values per tensor; "
            "min/max/mean/std and nonfinite counts are accumulated over all analyzed elements."
        ),
        "raw_intermediate_tensors_saved": False,
        "outputs": {
            "activation_stats_csv": str(stats_path),
            "channel_stats_csv": str(channel_path),
            "training_predictions_csv_diagnostic_only": str(predictions_path),
            "activation_scale_candidates_csv": str(activation_candidates_path),
            "weight_stats_csv": str(weight_stats_path),
            "weight_scales_json": str(weight_scales_path),
        },
    }
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print("\nSummary")
    print(f"Training samples processed for calibration: {tested}/{total}")
    print("Testing partition accessed: NO")
    print(f"Internal tensors analyzed: {len(tensor_names)}")
    print(f"Manual-vs-official max abs logit diff (first batch): {official_manual_diff}")
    print(f"Training subset accuracy (diagnostic only): {accuracy * 100:.4f}% ({correct_n}/{len(predictions)})")
    print(f"Non-finite tensor values observed: {nonfinite_total}")
    print(f"Activation stats CSV: {stats_path}")
    print(f"Activation scale candidates CSV: {activation_candidates_path}")
    print(f"Weight stats CSV: {weight_stats_path}")
    print(f"Weight scales JSON: {weight_scales_path}")
    print(f"Per-channel activation stats CSV: {channel_path}")
    print(f"Manifest: {manifest_path}")
    if tested == process_limit and nonfinite_total == 0 and official_manual_diff is not None and official_manual_diff < 1e-4:
        print("PTQ calibration statistics: PASS (candidates are not accuracy-validated yet)")
    else:
        print("PTQ calibration statistics: CHECK WARNINGS / COUNTS")


if __name__ == "__main__":
    main()
