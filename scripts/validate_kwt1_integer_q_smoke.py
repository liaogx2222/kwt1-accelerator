#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Integer-only smoke test for KWT-1 layer-0 Q projection.

This script is for the frozen pretrained KWT-1 checkpoint. It does not train,
modify, or save the checkpoint, and it only reads the validation partition.

Implemented arithmetic:
  * activation: symmetric INT8 quantization using training-calibrated scale
  * weights: symmetric INT8 per-output-channel quantization
  * dot product and bias: INT32
  * requantization: integer Q31 multiplier, integer shift, ties-to-even rounding

Scope limitation:
  This validates one Dense kernel only. The complete Transformer still requires
  explicit integer implementations for attention score/context, softmax,
  residual arithmetic, LayerNorm, GELU, input projection, and classifier head.
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace


import os
import numpy as np
import tensorflow as tensorflow
if hasattr(
    tensorflow.config.experimental,
    "enable_tensor_float_32_execution",
):
    tensorflow.config.experimental.enable_tensor_float_32_execution(False)
# Keep the existing GPU configuration; do not force CPU execution.
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

tensorflow.compat.v1.disable_eager_execution()

# Locate the repository root when this file is stored under <repo>/scripts/.
REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

# Match the import order of the working PTQ validation script.
from kws_streaming.layers.compat import tf  # noqa: E402
from kws_streaming.train import model_train_eval as _official_entry  # noqa: E402,F401
from kws_streaming.models import kws_transformer  # noqa: E402
from kws_streaming.data import input_data  # noqa: E402
from kws_streaming.models.transformer_utils import KWSTransformer  # noqa: E402

def read_flags(flags_path, data_dir):
    """Load the frozen model flags and override only the local dataset path."""
    with open(flags_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise TypeError("Expected flags.json to contain a JSON object")
    
    cfg["data_dir"] = str(data_dir)

    # Compatibility fields missing from this checkpoint's flags.json.
    # Values must match the frozen KWT-1 architecture.
    cfg.setdefault("distill_teacher_json", "")
    cfg.setdefault("prenorm", False)
    cfg.setdefault("approximate_gelu", False)

    return SimpleNamespace(**cfg)


def read_activation_scale(csv_path, tensor_name):
    """Read one training-calibrated INT8 activation scale."""
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = csv.DictReader(f)
        matches = [
            row for row in rows
            if row.get("tensor") == tensor_name
            and row.get("format") == "INT8"
            and row.get("threshold_source") == "abs_p999_est"
        ]

    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one INT8 abs_p999_est scale for {!r}; found {}"
            .format(tensor_name, len(matches))
        )

    scale = float(matches[0]["scale"])
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid activation scale for {}: {}".format(tensor_name, scale))
    return scale


def round_divide_pow2_ties_even(values, shift):
    """Divide signed integers by 2**shift, rounding nearest, ties-to-even.

    Uses int64 internally. A negative shift represents an exact left shift.
    """
    values = np.asarray(values, dtype=np.int64)
    shift = int(shift)

    if shift < 0:
        left = -shift
        if left >= 63:
            raise OverflowError("Left shift too large for int64: {}".format(left))
        return values << left
    if shift == 0:
        return values.copy()
    if np.any(values == np.iinfo(np.int64).min):
        raise OverflowError("Cannot take abs(INT64_MIN)")
    if shift == 63:
        # The divisor is 2**63. Quotient is always zero for int64 inputs;
        # values strictly above half round to +/-1, exact ties round to even 0.
        magnitude = np.abs(values)
        round_up = magnitude > (1 << 62)
        return np.where(round_up & (values < 0), -1,
                        np.where(round_up & (values > 0), 1, 0)).astype(np.int64)
    if shift > 63:
        return np.zeros_like(values, dtype=np.int64)

    divisor = 1 << shift
    if np.any(values == np.iinfo(np.int64).min):
        raise OverflowError("Cannot take abs(INT64_MIN)")
    magnitude = np.abs(values)
    quotient = magnitude // divisor
    remainder = magnitude % divisor
    half = divisor // 2

    increment = (remainder > half) | ((remainder == half) & ((quotient & 1) != 0))
    rounded_magnitude = quotient + increment.astype(np.int64)
    return np.where(values < 0, -rounded_magnitude, rounded_magnitude)


def make_q31_multiplier(real_multiplier):
    """Represent positive real multipliers by signed Q31 mantissa + shift.

    This is an OFFLINE parameter-generation routine; inference uses only the
    resulting integer multiplier and shift. Representation is approximately:
        real_multiplier ~= multiplier_q31 / 2**shift
    """
    real_multiplier = np.asarray(real_multiplier, dtype=np.float64)
    if np.any(~np.isfinite(real_multiplier)) or np.any(real_multiplier <= 0):
        raise ValueError("All real multipliers must be finite and positive")

    mantissa, exponent = np.frexp(real_multiplier)
    multiplier = np.rint(mantissa * (1 << 31)).astype(np.int64)
    exponent = exponent.astype(np.int64)

    # frexp mantissa lies in [0.5, 1). Rounding can produce exactly 2**31;
    # renormalize it to 2**30 and increment the exponent.
    carry = multiplier == (1 << 31)
    multiplier[carry] >>= 1
    exponent[carry] += 1

    if np.any(multiplier <= 0) or np.any(multiplier > (1 << 31) - 1):
        raise RuntimeError("Q31 multiplier is out of signed 32-bit range")

    shifts = 31 - exponent
    return multiplier, shifts


def error_metrics(actual, reference):
    """Compute scalar error statistics for two equal-shape arrays."""
    actual = np.asarray(actual, dtype=np.float64)
    reference = np.asarray(reference, dtype=np.float64)
    if actual.shape != reference.shape:
        raise ValueError("Shape mismatch: {} vs {}".format(actual.shape, reference.shape))
    diff = actual - reference
    return {
        "max_abs_error": float(np.max(np.abs(diff))) if diff.size else 0.0,
        "mae": float(np.mean(np.abs(diff))) if diff.size else 0.0,
        "rmse": float(np.sqrt(np.mean(np.square(diff)))) if diff.size else 0.0,
    }


def build_q_tap_model(model, transformer):
    """Build taps for actual encoder input and layer-0 query Dense output."""
    feature_layers = [
        layer for layer in model.layers
        if layer.__class__.__name__ == "SpeechFeatures"
    ]
    if len(feature_layers) != 1:
        raise RuntimeError(
            "Expected one top-level SpeechFeatures layer; found {}"
            .format(len(feature_layers))
        )

    features_model = tf.keras.Model(
        inputs=model.input,
        outputs=feature_layers[0].output,
        name="kwt_integer_q_smoke_features",
    )
    features = features_model.output

    x = transformer.patch_proj(features)
    dynamic_batch = tf.shape(x)[0]
    class_emb = tf.broadcast_to(
        transformer.class_emb,
        [dynamic_batch, 1, transformer.d_model],
    )
    encoder_input = tf.concat([class_emb, x], axis=1)
    encoder_input = encoder_input + transformer.pos_emb

    q_dense = transformer.enc_layers[0].att.query_dense
    q_output = q_dense(encoder_input)

    tap_model = tf.keras.Model(
        inputs=model.input,
        outputs=[encoder_input, q_output],
        name="kwt_integer_q_projection_taps",
    )
    return tap_model, q_dense


def collect_validation_taps(tap_model, processor, flags, sess,
                            total, batch_size, max_samples):
    """Collect only the requested leading samples from validation partition."""
    process_limit = total if max_samples == 0 else min(total, max_samples)
    if process_limit <= 0:
        raise RuntimeError("Validation partition has no samples to process")

    enc_batches = []
    q_batches = []
    for offset in range(0, process_limit, batch_size):
        real_n = min(batch_size, process_limit - offset)
        batch_x, _ = processor.get_data(
            real_n, offset, flags,
            0.0, 0.0, 0, "validation", 0.0, 0.0, sess
        )
        batch_x = np.asarray(batch_x)
        if real_n < batch_size:
            pad_n = batch_size - real_n
            batch_x_model = np.concatenate(
                [batch_x, np.repeat(batch_x[-1:], pad_n, axis=0)], axis=0
            )
        else:
            batch_x_model = batch_x

        enc_float, q_float = tap_model.predict(
            batch_x_model, batch_size=batch_size, verbose=0
        )
        enc_batches.append(np.asarray(enc_float[:real_n], dtype=np.float32))
        q_batches.append(np.asarray(q_float[:real_n], dtype=np.float32))

        done = offset + real_n
        print("  validation taps: {}/{} samples".format(done, process_limit))

    return np.concatenate(enc_batches, axis=0), np.concatenate(q_batches, axis=0)


def load_q_weight_scale(weight_json_path, kernel_name, kernel):
    """Load and verify the per-output-channel scales for the actual Q kernel."""
    with open(weight_json_path, "r", encoding="utf-8") as f:
        weight_data = json.load(f)

    matches = [
        item for item in weight_data.get("variables", [])
        if item.get("name") == kernel_name
    ]
    if len(matches) != 1:
        all_kernels = [
            item.get("name", "") for item in weight_data.get("variables", [])
            if item.get("scheme") == "per_output_channel"
        ]
        raise RuntimeError(
            "Cannot uniquely map actual Q kernel {!r} to weight-scale JSON. "
            "First matrix-kernel names: {}"
            .format(kernel_name, all_kernels[:8])
        )

    item = matches[0]
    if item.get("scheme") != "per_output_channel":
        raise RuntimeError("Q kernel is not per-output-channel quantized in JSON")

    weight_scale = np.asarray(item.get("int8_scale"), dtype=np.float64).reshape(-1)
    if kernel.ndim != 2 or weight_scale.shape != (kernel.shape[1],):
        raise RuntimeError(
            "Kernel / weight-scale shape mismatch: {} / {}"
            .format(kernel.shape, weight_scale.shape)
        )

    # The calibration file uses max(abs(weight), axis=0) / 127.
    calculated = np.maximum(np.max(np.abs(kernel.astype(np.float64)), axis=0) / 127.0, 1e-12)
    if not np.allclose(calculated, weight_scale, rtol=1e-5, atol=1e-12):
        delta = float(np.max(np.abs(calculated - weight_scale)))
        raise RuntimeError(
            "Stored scales do not match loaded Q kernel; max scale difference={}".format(delta)
        )
    return weight_scale


def run_integer_q_projection_smoke(model, transformer, processor, flags, sess,
                                   validation_total, batch_size, max_samples,
                                   output_dir, calibration_dir):
    """Execute and report actual INT8 x INT8 -> INT32 Q Dense arithmetic."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    activation_csv = calibration_dir / "kwt1_ptq_activation_scale_candidates.csv"
    weight_json = calibration_dir / "kwt1_ptq_weight_scales.json"
    for path in (activation_csv, weight_json):
        if not path.is_file():
            raise FileNotFoundError("Calibration artifact not found: {}".format(path))

    input_scale = read_activation_scale(activation_csv, "encoder_input")
    output_scale = read_activation_scale(activation_csv, "layer_00/q_projection")

    tap_model, q_dense = build_q_tap_model(model, transformer)
    enc_float, q_float = collect_validation_taps(
        tap_model, processor, flags, sess,
        validation_total, batch_size, max_samples,
    )

    dense_weights = q_dense.get_weights()
    if len(dense_weights) not in (1, 2):
        raise RuntimeError("Unexpected query Dense weight count: {}".format(len(dense_weights)))
    kernel = np.asarray(dense_weights[0], dtype=np.float64)
    bias = (
        np.asarray(dense_weights[1], dtype=np.float64)
        if len(dense_weights) == 2
        else np.zeros(kernel.shape[-1], dtype=np.float64)
    )
    kernel_name = q_dense.kernel.name
    weight_scale = load_q_weight_scale(weight_json, kernel_name, kernel)

    # Quantize input and trained kernel into real signed INT8 tensors.
    input_unclipped = np.rint(enc_float.astype(np.float64) / input_scale)
    q_input = np.clip(input_unclipped, -127, 127).astype(np.int8)
    q_kernel = np.clip(
        np.rint(kernel / weight_scale.reshape(1, -1)), -127, 127
    ).astype(np.int8)

    # INT32 bias uses each output channel's accumulator scale sx * sw[channel].
    bias_scale = input_scale * weight_scale
    q_bias_64 = np.rint(bias / bias_scale).astype(np.int64)
    i32 = np.iinfo(np.int32)
    if np.any(q_bias_64 < i32.min) or np.any(q_bias_64 > i32.max):
        raise OverflowError("Quantized bias does not fit INT32")
    q_bias = q_bias_64.astype(np.int32)

    # NumPy int32 matmul accumulates these 64-term dot products safely in INT32.
    accumulator_no_bias = np.matmul(
        q_input.astype(np.int32), q_kernel.astype(np.int32)
    )
    accumulator64 = accumulator_no_bias.astype(np.int64) + q_bias.astype(np.int64)
    if np.any(accumulator64 < i32.min) or np.any(accumulator64 > i32.max):
        raise OverflowError("INT32 accumulator plus bias overflowed")
    accumulator = accumulator64.astype(np.int32)

    # Requantize acc * (sx * sw[channel] / sy) using only integer runtime math.
    real_multiplier = bias_scale / output_scale
    multiplier_q31, shift = make_q31_multiplier(real_multiplier)
    requantized = np.empty(accumulator.shape, dtype=np.int64)
    for channel in range(kernel.shape[1]):
        # Current KWT-1 dimensions make this product safely fit int64.
        product = accumulator[..., channel].astype(np.int64) * multiplier_q31[channel]
        requantized[..., channel] = round_divide_pow2_ties_even(
            product, int(shift[channel])
        )

    q_output = np.clip(requantized, -127, 127).astype(np.int8)
    int_dequant = q_output.astype(np.float32) * np.float32(output_scale)

    # Reference A: FP32 Q dense output; Reference B: FP32 output fake-quantized
    # to the same calibrated output scale. The integer result is NOT expected
    # to match the original FP32 result bit-for-bit.
    q_float_codes_unclipped = np.rint(q_float.astype(np.float64) / output_scale)
    q_float_codes = np.clip(q_float_codes_unclipped, -127, 127).astype(np.int8)
    float_fake_quant = q_float_codes.astype(np.float32) * np.float32(output_scale)

    metrics = {
        "scope": "layer-0 Q projection only",
        "partition": "validation",
        "testing_partition_accessed": False,
        "validation_samples_processed": int(enc_float.shape[0]),
        "q_kernel_name": kernel_name,
        "q_kernel_shape": list(kernel.shape),
        "encoder_input_shape": list(enc_float.shape),
        "q_projection_shape": list(q_float.shape),
        "input_scale": float(input_scale),
        "output_scale": float(output_scale),
        "weight_scale_min": float(np.min(weight_scale)),
        "weight_scale_max": float(np.max(weight_scale)),
        "q31_multiplier_min": int(np.min(multiplier_q31)),
        "q31_multiplier_max": int(np.max(multiplier_q31)),
        "right_shift_min": int(np.min(shift)),
        "right_shift_max": int(np.max(shift)),
        "input_clipping_fraction": float(np.mean(np.abs(input_unclipped) > 127)),
        "output_saturation_fraction": float(np.mean((requantized < -127) | (requantized > 127))),
        "integer_dequant_vs_float_q": error_metrics(int_dequant, q_float),
        "integer_dequant_vs_float_fake_quant": error_metrics(int_dequant, float_fake_quant),
        "integer_code_agreement_vs_float_fake_quant": float(np.mean(q_output == q_float_codes)),
        "integer_accumulator_dtype": str(accumulator.dtype),
        "integer_activation_dtype": str(q_input.dtype),
        "integer_weight_dtype": str(q_kernel.dtype),
        "integer_bias_dtype": str(q_bias.dtype),
        "requantization": "Q31 multiplier + power-of-two shift; signed ties-to-even",
        "note": (
            "One Dense kernel smoke test only; not full integer Transformer inference or RTL sign-off. "
            "Offline Q31 parameters are computed with float64; runtime requantization is integer arithmetic."
        ),
    }

    npz_path = output_dir / "kwt1_q_projection_integer_smoke.npz"
    np.savez_compressed(
        npz_path,
        encoder_input_float=enc_float,
        q_projection_float=q_float,
        input_scale=np.float64(input_scale),
        output_scale=np.float64(output_scale),
        q_input_int8=q_input,
        q_kernel_int8=q_kernel,
        weight_scale=weight_scale,
        bias_int32=q_bias,
        accumulator_without_bias_int32=accumulator_no_bias,
        accumulator_with_bias_int32=accumulator,
        multiplier_q31=multiplier_q31,
        right_shift=shift,
        q_projection_int8=q_output,
        q_projection_dequantized=int_dequant,
        q_projection_float_fake_quant=float_fake_quant,
    )
    metrics_path = output_dir / "kwt1_q_projection_integer_smoke_metrics.json"
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    print("\n========== Integer Q projection smoke test ==========")
    print("Partition: validation")
    print("Testing partition accessed: NO")
    print("Samples processed: {}".format(enc_float.shape[0]))
    print("Q kernel: {}".format(kernel_name))
    print("Q kernel shape: {}".format(kernel.shape))
    print("Input scale: {:.12g}".format(input_scale))
    print("Output scale: {:.12g}".format(output_scale))
    print("Input clipping fraction: {:.6%}".format(metrics["input_clipping_fraction"]))
    print("Output saturation fraction: {:.6%}".format(metrics["output_saturation_fraction"]))
    print("INT dequant vs FP32 Q: {}".format(metrics["integer_dequant_vs_float_q"]))
    print("INT dequant vs FP fake-quant Q: {}".format(metrics["integer_dequant_vs_float_fake_quant"]))
    print("Integer vs fake-quant code agreement: {:.4%}".format(
        metrics["integer_code_agreement_vs_float_fake_quant"]
    ))
    print("NPZ: {}".format(npz_path))
    print("Metrics: {}".format(metrics_path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=None,
                        help="Dataset root; defaults to <repo>/data2")
    parser.add_argument("--model-dir", default=None,
                        help="Frozen model directory; defaults to models_data_v2_12_labels/kwt1")
    parser.add_argument("--calibration-dir", default=None,
                        help="Calibration artifacts; defaults to testdata/ptq_calibration")
    parser.add_argument("--output-dir", default=None,
                        help="Output directory; defaults to testdata/ptq_integer_smoke")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-samples", type=int, default=16,
                        help="Validation samples to process; 0 means the full validation partition")
    args = parser.parse_args()

    if args.batch_size <= 0:
        parser.error("--batch-size must be positive")
    if args.max_samples < 0:
        parser.error("--max-samples must be >= 0")

    data_dir = Path(args.data_dir).resolve() if args.data_dir else REPO_DIR / "data2"
    model_dir = (
        Path(args.model_dir).resolve()
        if args.model_dir else REPO_DIR / "models_data_v2_12_labels" / "kwt1"
    )
    calibration_dir = (
        Path(args.calibration_dir).resolve()
        if args.calibration_dir else REPO_DIR / "testdata" / "ptq_calibration"
    )
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir else REPO_DIR / "testdata" / "ptq_integer_smoke"
    )
    checkpoint = model_dir / "best_weights"
    flags_path = model_dir / "flags.json"

    if not data_dir.is_dir():
        raise FileNotFoundError("Dataset directory not found: {}".format(data_dir))
    if not flags_path.is_file():
        raise FileNotFoundError("Model flags not found: {}".format(flags_path))
    if not Path(str(checkpoint) + ".index").is_file():
        raise FileNotFoundError("Checkpoint index not found: {}.index".format(checkpoint))

    # KWS Streaming 2.4 / TensorFlow 2.4 uses TF1-style graph/session execution.
    tf.compat.v1.disable_eager_execution()
    tf1 = tf.compat.v1
    flags = read_flags(flags_path, data_dir)
    # The graph has a fixed batch dimension. Match it to the smoke-test batch size.
    flags.batch_size = args.batch_size
    print("Model graph batch size:", flags.batch_size)

    print("Checkpoint: {}".format(checkpoint))
    print("Data directory: {}".format(data_dir))
    print("Calibration directory: {}".format(calibration_dir))
    print("Batch size: {}".format(args.batch_size))
    print("Requested validation samples: {}".format(
        "all" if args.max_samples == 0 else args.max_samples
    ))
    print("Testing partition will not be accessed.")

    # Session-based loading follows the same pattern as the existing PTQ script.
    with tf1.Session() as sess:
        try:
            tf1.keras.backend.set_session(sess)
        except (AttributeError, RuntimeError):
            pass

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

        transformers = [
            layer for layer in model.layers if isinstance(layer, KWSTransformer)
        ]
        if len(transformers) != 1 or len(transformers[0].enc_layers) != 12:
            raise RuntimeError("Expected exactly one 12-layer KWSTransformer")

        total = int(processor.set_size("validation"))
        if total <= 0:
            raise RuntimeError("AudioProcessor validation partition is empty")
        print("Validation partition size: {}".format(total))

        run_integer_q_projection_smoke(
            model=model,
            transformer=transformers[0],
            processor=processor,
            flags=flags,
            sess=sess,
            validation_total=total,
            batch_size=args.batch_size,
            max_samples=args.max_samples,
            output_dir=output_dir,
            calibration_dir=calibration_dir,
        )


if __name__ == "__main__":
    main()
