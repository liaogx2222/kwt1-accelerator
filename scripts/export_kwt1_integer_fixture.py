"""Freeze Validation inputs, FP32 outputs and original parameters; never train.

Run with kwt_ref Python. The integer evaluator has no TensorFlow dependency.
Only the PC frontend and frozen software classifier are outside the encoder.
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
os.environ.setdefault("TF_FORCE_GPU_ALLOW_GROWTH", "true")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import numpy as np
import tensorflow as tensorflow

tensorflow.compat.v1.disable_eager_execution()
tensorflow.config.experimental.enable_tensor_float_32_execution(False)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from validate_kwt1_ptq_activations import build_flags, labels_to_ids
from calibrate_kwt1_ptq import build_internal_graph
from kws_streaming.layers.compat import tf
from kws_streaming.models import kws_transformer
from kws_streaming.data import input_data


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=ROOT / "testdata/integer_v1/fixture")
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--max-samples", type=int, default=0)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    if (a.output / "manifest.json").exists():
        raise FileExistsError("Use a new output directory to preserve frozen evidence")
    model_dir = ROOT / "models_data_v2_12_labels/kwt1"
    flags = build_flags(model_dir, ROOT / "data2", a.batch_size)
    flags.use_spec_augment = 0
    flags.use_spec_cutout = 0
    flags.sp_resample = 0.0
    flags.volume_resample = 0.0
    assert (flags.num_layers, flags.d_model, flags.heads, flags.mlp_dim) == (12, 64, 1, 256)
    sources = [model_dir / "best_weights.index", model_dir / "best_weights.data-00000-of-00001",
               model_dir / "flags.json", ROOT / "kws_streaming/data/input_data.py",
               ROOT / "kws_streaming/models/transformer_utils.py", Path(__file__).resolve()]
    before = {str(x.relative_to(ROOT)): sha(x) for x in sources}
    config = tensorflow.compat.v1.ConfigProto(allow_soft_placement=True)
    config.gpu_options.allow_growth = True
    with tensorflow.compat.v1.Session(config=config) as sess:
        tensorflow.compat.v1.keras.backend.set_session(sess)
        processor = input_data.AudioProcessor(flags)
        original_get_data = processor.get_data

        def validation_only(*args, **kwargs):
            mode = kwargs.get("mode", args[6] if len(args) > 6 else None)
            if mode != "validation":
                raise RuntimeError("This exporter only permits Validation batches")
            return original_get_data(*args, **kwargs)

        processor.get_data = validation_only
        model = kws_transformer.model(flags)
        transformer = next(x for x in model.layers if hasattr(x, "enc_layers"))
        feature = next(x for x in model.layers if x.__class__.__name__ == "SpeechFeatures")
        capture, names = build_internal_graph(model, feature, transformer)
        taps = tf.keras.Model(model.input, [capture.outputs[0], capture.outputs[-2], capture.outputs[-1]])
        sess.run(tensorflow.compat.v1.global_variables_initializer())
        status = model.load_weights(str(model_dir / "best_weights"))
        status.assert_existing_objects_matched()
        status.expect_partial()
        status.run_restore_ops()
        raw = {}
        for i, block in enumerate(transformer.enc_layers):
            for name, dense in [("q", block.att.query_dense), ("k", block.att.key_dense),
                                ("v", block.att.value_dense), ("o", block.att.combine_heads),
                                ("fc1", block.ffn.layers[0]), ("fc2", block.ffn.layers[2])]:
                w = dense.get_weights()
                raw[f"l{i:02d}_{name}_w"] = w[0]
                if len(w) == 2:
                    raw[f"l{i:02d}_{name}_b"] = w[1]
            for j, ln in enumerate([block.layernorm1, block.layernorm2], 1):
                assert ln.epsilon == 1e-6
                g, b = ln.get_weights()
                raw[f"l{i:02d}_ln{j}_g"] = g
                raw[f"l{i:02d}_ln{j}_b"] = b
        raw["head_w"], raw["head_b"] = model.layers[-1].get_weights()
        np.savez(a.output / "raw_parameters.npz", **raw)
        total = processor.set_size("validation")
        n = min(total, a.max_samples) if a.max_samples else total
        arrays = {name: np.lib.format.open_memmap(str(a.output / (name + ".npy")), mode="w+",
                  dtype=np.float32, shape=shape) for name, shape in {
                      "encoder_input": (n, 99, 64), "fp_encoder_output": (n, 99, 64),
                      "fp_logits": (n, 12)}.items()}
        labels = np.empty(n, np.int64)
        first_repeat = None
        official_difference = None
        for offset in range(0, n, a.batch_size):
            count = min(a.batch_size, n - offset)
            audio, by = processor.get_data(count, offset, flags, 0., 0., 0, "validation", 0., 0., sess)
            if count < a.batch_size:
                audio = np.concatenate([audio, np.repeat(audio[-1:], a.batch_size-count, axis=0)])
            outputs = taps.predict(audio, batch_size=a.batch_size, verbose=0)
            if offset == 0:
                repeat = taps.predict(audio, batch_size=a.batch_size, verbose=0)
                first_repeat = [bool(np.array_equal(x, y)) for x, y in zip(outputs, repeat)]
                official = model.predict(audio, batch_size=a.batch_size, verbose=0)
                official_difference = float(np.max(np.abs(official - outputs[-1])))
                assert all(first_repeat) and official_difference <= 1e-4
                trace = capture.predict(audio, batch_size=a.batch_size, verbose=0)
                np.savez(a.output / "fp_trace_first_batch.npz", **dict(zip(names, trace)))
            for key, value in zip(arrays, outputs):
                arrays[key][offset:offset+count] = value[:count]
            labels[offset:offset+count] = labels_to_ids(by)
            if offset % (a.batch_size*10) == 0 or offset+count == n:
                print("fixture {}/{}".format(offset+count, n), flush=True)
        for arr in arrays.values():
            arr.flush()
        np.save(a.output / "labels.npy", labels)
        correct = int(np.sum(np.argmax(arrays["fp_logits"], axis=-1) == labels))
        identities = []
        for i, item in enumerate(processor.data_index["validation"][:n]):
            silence = item["label"] == input_data.SILENCE_LABEL
            path = Path(item["file"])
            identities.append({"offset": i, "label_id": int(labels[i]), "source_label": item["label"],
                               "waveform": "zeros:16000" if silence else path.relative_to(ROOT / "data2").as_posix(),
                               "sha256": None if silence else sha(path)})
        (a.output / "samples.json").write_text(json.dumps(identities, indent=2), encoding="utf-8")
        assert before == {str(x.relative_to(ROOT)): sha(x) for x in sources}
        manifest = {"partition": "validation", "samples": n, "partition_size": total,
                    "fp_correct": correct, "fp_accuracy": correct/n, "tf_version": tensorflow.__version__,
                    "numpy_version": np.__version__, "tf32": False, "batch_size": a.batch_size,
                    "repeat_first_batch_bit_identical": first_repeat,
                    "official_vs_manual_first_batch_logit_max_abs": official_difference,
                    "testing_batches_requested": 0, "training_performed": False,
                    "augmentation_disabled": True, "source_sha256": before,
                    "label_names": list(processor.words_list),
                    "files_sha256": {x.name: sha(x) for x in a.output.iterdir() if x.is_file()}}
        (a.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print("FP32 {}/{} = {:.8%}".format(correct, n, correct/n), flush=True)


if __name__ == "__main__":
    main()
