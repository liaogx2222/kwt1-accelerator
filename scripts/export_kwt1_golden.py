#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Export fixed real test samples and all KWT-1 encoder-layer outputs.

Run from the repository root with the project's kwt_ref environment:
    python scripts/export_kwt1_golden.py --num-samples 32

The script never trains or modifies the checkpoint. It writes:
    testdata/kwt1_golden_32.npz
    testdata/kwt1_golden_32_manifest.json
"""

import os
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import tensorflow.compat.v1 as tf

tf.disable_v2_behavior()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--num-samples", type=int, default=32)
    parser.add_argument("--batch-size", type=int, default=100,
                        help="Keep consistent with KWT-1 model's fixed batch dimension.")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))

    model_dir = repo / "models_data_v2_12_labels" / "kwt1"
    data_dir = repo / "data2"
    ckpt = model_dir / "best_weights"
    out_dir = repo / "testdata"
    out_npz = out_dir / "kwt1_golden_{}.npz".format(args.num_samples)
    out_json = out_dir / "kwt1_golden_{}_manifest.json".format(args.num_samples)

    if not (model_dir / "flags.json").is_file():
        raise FileNotFoundError("Missing model config: {}".format(model_dir / "flags.json"))
    if not Path(str(ckpt) + ".index").is_file():
        raise FileNotFoundError("Missing checkpoint index: {}.index".format(ckpt))
    if not data_dir.is_dir():
        raise FileNotFoundError("Missing Speech Commands dataset: {}".format(data_dir))
    if args.num_samples <= 0:
        raise ValueError("--num-samples must be positive")
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")

    with open(model_dir / "flags.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Inference-only settings aligned with eval_kwt1_reference.py.
    cfg.update({
        "data_dir": str(data_dir),
        "data_url": "",
        "train_dir": str(model_dir),
        "training": False,
        "train": 0,
        "batch_size": int(args.batch_size),
        "return_softmax": 0,
        "background_frequency": 0.0,
        "background_volume": 0.0,
        "time_shift_ms": 0.0,
        "sp_time_shift_ms": 0.0,
        "resample": 0.0,
        "pick_deterministically": True,
        # These model-construction flags are used by kws_transformer.model()
        # but are absent from the checkpoint's saved flags.json.
        "distill_teacher_json": "",
        "prenorm": False,
        "approximate_gelu": False,
    })
    flags = SimpleNamespace(**cfg)

    # Import order matches the already-verified smoke exporter to avoid
    # kws_streaming circular-import problems.
    from kws_streaming.train import model_train_eval as _official_entry  # noqa: F401
    from kws_streaming.models import kws_transformer
    from kws_streaming.data import input_data

    tf.reset_default_graph()
    session_config = tf.ConfigProto(
        device_count={"GPU": 0},
        allow_soft_placement=True,
    )

    with tf.Session(config=session_config) as sess:
        # Build the official model and the repository's deterministic test index.
        processor = input_data.AudioProcessor(flags)
        model = kws_transformer.model(flags)

        transformer = next(
            layer for layer in model.layers if hasattr(layer, "enc_layers")
        )

        # Find the official waveform-to-MFCC feature layer by its expected output
        # shape rather than relying on a version-specific layer name.
        feature_layers = []
        for layer in model.layers:
            try:
                shape = tuple(layer.output.shape.as_list()[1:])
            except (AttributeError, TypeError, ValueError):
                continue
            if shape == (98, 40):
                feature_layers.append(layer)
        if len(feature_layers) != 1:
            details = []
            for layer in model.layers:
                try:
                    shape = tuple(layer.output.shape.as_list())
                except Exception:
                    shape = "unknown"
                details.append("{}: {}".format(layer.name, shape))
            raise RuntimeError(
                "Expected exactly one model layer producing (98, 40) MFCCs; "
                "found {}. Layer outputs:\n{}".format(
                    len(feature_layers), "\n".join(details)
                )
            )
        feature_layer = feature_layers[0]

        # Reuse the original trained Transformer and classifier layers, exposing
        # the input to the Encoder and each block's output for golden comparison.
        feature_input = tf.keras.Input(
            shape=(98, 40), dtype=tf.float32, name="golden_mfcc_input"
        )
        x = transformer.patch_proj(feature_input)
        dynamic_batch = tf.shape(x)[0]
        class_token = tf.broadcast_to(
            transformer.class_emb,
            [dynamic_batch, 1, transformer.d_model],
        )
        x = tf.concat([class_token, x], axis=1)
        x = x + transformer.pos_emb

        sequence_outputs = [x]  # encoder_input, before Transformer block 0
        for block in transformer.enc_layers:
            x, _ = block(x, training=False)
            sequence_outputs.append(x)

        classifier = model.layers[-1]
        reference_logits_tensor = classifier(x[:, 0, :])

        total = processor.set_size("testing")
        if total <= 0:
            raise RuntimeError("AudioProcessor returned an empty testing set")
        n = min(int(args.num_samples), int(total))
        if n != args.num_samples:
            print("Requested {} samples; testing set contains only {}.".format(
                args.num_samples, total
            ))

        if n > args.batch_size:
            raise ValueError(
                "This exporter currently exports at most --batch-size samples "
                "per run. Use --num-samples <= {}.".format(args.batch_size)
            )

        sess.run(tf.global_variables_initializer())
        status = model.load_weights(str(ckpt))
        status.assert_existing_objects_matched()
        status.expect_partial()
        if hasattr(status, "run_restore_ops"):
            status.run_restore_ops()

        # get_data is deterministic here because pick_deterministically=True
        # and mode='testing'. Keep its label/path order exactly as returned.
        audio, labels = processor.get_data(
            n, 0, flags,
            0.0, 0.0, 0, "testing",
            0.0, 0.0, sess,
        )
        audio = np.asarray(audio, dtype=np.float32)
        labels = np.asarray(labels, dtype=np.int64).reshape(-1)
        if audio.shape[0] != n or labels.shape[0] != n:
            raise RuntimeError(
                "Unexpected test batch shapes: audio={}, labels={}, expected n={}".format(
                    audio.shape, labels.shape, n
                )
            )

        # The official Keras model was constructed with a fixed batch size (100
        # in the standard config). Pad only for graph execution; discard padded
        # outputs so the artifact contains exactly n real test examples.
        if n < args.batch_size:
            pad_n = args.batch_size - n
            pad_audio = np.repeat(audio[-1:], pad_n, axis=0)
            audio_for_model = np.concatenate([audio, pad_audio], axis=0)
        else:
            audio_for_model = audio

        # Official input graph: waveform -> MFCC. The waveform batch is padded
        # to the model's fixed batch dimension, then trimmed back to n examples.
        features_full = sess.run(
            feature_layer.output,
            feed_dict={model.inputs[0]: audio_for_model},
        )
        features = np.asarray(features_full[:n], dtype=np.float32)
        if features.shape != (n, 98, 40):
            raise AssertionError("Unexpected MFCC shape: {}".format(features.shape))

        manual_values = sess.run(
            sequence_outputs + [reference_logits_tensor],
            feed_dict={feature_input: features},
        )
        manual_values = [np.asarray(v) for v in manual_values]
        encoder_input = manual_values[0]
        layer_outputs = manual_values[1:13]
        reference_logits = np.asarray(manual_values[13], dtype=np.float32)

        official_output_values = sess.run(
            model.outputs,
            feed_dict={model.inputs[0]: audio_for_model},
        )
        if isinstance(official_output_values, (tuple, list)):
            official_logits = np.asarray(official_output_values[0][:n], dtype=np.float32)
        else:
            official_logits = np.asarray(official_output_values[:n], dtype=np.float32)

        if len(layer_outputs) != 12:
            raise AssertionError("Expected 12 encoder outputs, got {}".format(len(layer_outputs)))
        if encoder_input.shape != (n, 99, 64):
            raise AssertionError("Unexpected Encoder input shape: {}".format(encoder_input.shape))
        for i, out in enumerate(layer_outputs):
            if out.shape != (n, 99, 64):
                raise AssertionError("Layer {} output shape: {}".format(i, out.shape))
        if reference_logits.shape != (n, 12):
            raise AssertionError("Unexpected logits shape: {}".format(reference_logits.shape))
        if not all(np.all(np.isfinite(v)) for v in [features, encoder_input] + layer_outputs + [reference_logits]):
            raise AssertionError("Non-finite values found in golden tensors")

        max_logit_diff = float(np.max(np.abs(official_logits - reference_logits)))
        if not np.allclose(official_logits, reference_logits, rtol=1e-5, atol=1e-6):
            raise AssertionError(
                "Manual Transformer path differs from official model; max abs diff={}".format(
                    max_logit_diff
                )
            )

        predicted = np.argmax(reference_logits, axis=1).astype(np.int64)
        accuracy = float(np.mean(predicted == labels))
        words = list(processor.words_list)
        label_names = np.asarray([words[int(y)] for y in labels], dtype=np.str_)
        predicted_names = np.asarray([words[int(y)] for y in predicted], dtype=np.str_)

        entries = processor.data_index["testing"][:n]
        sample_paths = np.asarray([
            str(entry.get("file", entry.get("path", ""))) for entry in entries
        ], dtype=np.str_)

        payload = {
            "sample_index": np.arange(n, dtype=np.int32),
            "sample_path": sample_paths,
            "waveform": audio,
            "mfcc_features": features,
            "encoder_input": encoder_input.astype(np.float32),
            "final_encoder_output": layer_outputs[-1].astype(np.float32),
            "final_logits": reference_logits.astype(np.float32),
            "official_logits": official_logits.astype(np.float32),
            "labels": labels,
            "label_names": label_names,
            "predicted_labels": predicted,
            "predicted_names": predicted_names,
        }
        for i, out in enumerate(layer_outputs):
            payload["layer_{:02d}_output".format(i)] = out.astype(np.float32)

        out_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(str(out_npz), **payload)

        manifest = {
            "checkpoint": str(ckpt),
            "repository_commit_expected": "237e4097afd4f6851e0b82f0a8d65c2dfe8eae30",
            "dataset_dir": str(data_dir),
            "dataset_split": "AudioProcessor / testing / pick_deterministically=True",
            "num_samples": int(n),
            "testing_set_size": int(total),
            "sample_index_range": [0, int(n - 1)],
            "model_batch_size": int(args.batch_size),
            "input_shapes": {
                "waveform": [int(n), 16000],
                "mfcc_features": [int(n), 98, 40],
                "encoder_input": [int(n), 99, 64],
                "each_encoder_layer_output": [int(n), 99, 64],
                "final_logits": [int(n), 12],
            },
            "labels_in_index_order": words,
            "accuracy_on_exported_subset": accuracy,
            "official_vs_manual_logits_max_abs_diff": max_logit_diff,
            "checkpoint_training_performed": False,
        }
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        print("Checkpoint:", ckpt)
        print("Testing set size:", total)
        print("Exported samples:", n)
        print("Waveforms:", audio.shape)
        print("MFCC features:", features.shape)
        print("Encoder input:", encoder_input.shape)
        print("Encoder layer outputs:", len(layer_outputs))
        print("Final logits:", reference_logits.shape)
        print("Subset accuracy: {:.4f}%".format(accuracy * 100.0))
        print("Max official/manual logit difference:", max_logit_diff)
        print("NPZ:", out_npz)
        print("Manifest:", out_json)
        print("Golden export: PASS")


if __name__ == "__main__":
    main()
