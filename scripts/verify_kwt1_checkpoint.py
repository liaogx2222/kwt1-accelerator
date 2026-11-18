import os
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

import sys
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import tensorflow.compat.v1 as tf

tf.disable_eager_execution()

REPO = Path(__file__).resolve().parents[1]

# 确保可以导入仓库内的 kws_streaming 包
sys.path.insert(0, str(REPO))

MODEL_DIR = REPO / "models_data_v2_12_labels" / "kwt1"
CKPT = str(MODEL_DIR / "best_weights")
SUFFIX = "/.ATTRIBUTES/VARIABLE_VALUE"


def main():
    if not Path(CKPT + ".index").is_file():
        raise FileNotFoundError(CKPT + ".index")

    with open(MODEL_DIR / "flags.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)

    cfg.update({
        "train_dir": str(MODEL_DIR),
        "batch_size": 1,
        "training": False,
        "return_softmax": 0,
    })
    cfg.setdefault("distill_teacher_json", "")
    cfg.setdefault("prenorm", False)
    cfg.setdefault("approximate_gelu", False)

    flags = SimpleNamespace(**cfg)
    tf.reset_default_graph()
    sess = tf.Session(config=tf.ConfigProto(device_count={"GPU": 0}))
    tf.keras.backend.set_session(sess)
    tf.keras.backend.set_learning_phase(0)

    try:
        # 保持官方入口的模块初始化顺序，避免循环导入
        from kws_streaming.train import model_train_eval as _official_entry
        from kws_streaming.models import kws_transformer

        model = kws_transformer.model(flags)
        sess.run(tf.global_variables_initializer())

        status = model.load_weights(CKPT)
        status.assert_existing_objects_matched()
        status.expect_partial()
        if hasattr(status, "run_restore_ops"):
            status.run_restore_ops()

        reader = tf.train.load_checkpoint(CKPT)
        transformer = next(
            layer for layer in model.layers if hasattr(layer, "enc_layers")
        )
        classifier = model.layers[-1]
        head_dense = next(
            layer for layer in classifier.layers
            if hasattr(layer, "kernel") and hasattr(layer, "bias")
        )

        checks = []

        def add(name, variable, key):
            expected = reader.get_tensor(key + SUFFIX)
            actual = sess.run(variable)

            if expected.shape != actual.shape:
                checks.append((
                    name, False,
                    "shape mismatch model={} checkpoint={}".format(
                        actual.shape, expected.shape
                    )
                ))
                return

            exact = np.array_equal(actual, expected)
            max_abs = float(np.max(np.abs(actual - expected))) if actual.size else 0.0
            checks.append((
                name, exact,
                "shape={} max_abs_diff={:.9g}".format(actual.shape, max_abs)
            ))

        root = "layer_with_weights-0/"

        add("class_emb", transformer.class_emb, root + "class_emb")
        add("pos_emb", transformer.pos_emb, root + "pos_emb")
        add("patch_proj.kernel", transformer.patch_proj.kernel,
            root + "patch_proj/kernel")
        add("patch_proj.bias", transformer.patch_proj.bias,
            root + "patch_proj/bias")

        for i, block in enumerate(transformer.enc_layers):
            base = root + "enc_layers/{}/".format(i)

            for attr in ("query_dense", "key_dense", "value_dense"):
                layer = getattr(block.att, attr)
                add("layer{}.att.{}.kernel".format(i, attr), layer.kernel,
                    base + "att/{}/kernel".format(attr))

            add("layer{}.att.combine.kernel".format(i),
                block.att.combine_heads.kernel,
                base + "att/combine_heads/kernel")
            add("layer{}.att.combine.bias".format(i),
                block.att.combine_heads.bias,
                base + "att/combine_heads/bias")

            # FFN 顺序为 Dense -> GELU -> Dense；GELU 没有权重
            for seq_idx, weighted_idx in ((0, 0), (2, 1)):
                dense = block.ffn.layers[seq_idx]
                path = base + "ffn/layer_with_weights-{}/".format(weighted_idx)
                add("layer{}.ffn{}.kernel".format(i, weighted_idx),
                    dense.kernel, path + "kernel")
                add("layer{}.ffn{}.bias".format(i, weighted_idx),
                    dense.bias, path + "bias")

            for ln_name in ("layernorm1", "layernorm2"):
                ln = getattr(block, ln_name)
                path = base + ln_name + "/"
                add("layer{}.{}.gamma".format(i, ln_name), ln.gamma,
                    path + "gamma")
                add("layer{}.{}.beta".format(i, ln_name), ln.beta,
                    path + "beta")

        # 外层 12 类分类头；它不属于硬件编码器，但也应与权重匹配
        head_base = "layer_with_weights-1/layer_with_weights-0/"
        add("classifier.kernel", head_dense.kernel, head_base + "kernel")
        add("classifier.bias", head_dense.bias, head_base + "bias")

        failures = [x for x in checks if not x[1]]
        print("Checkpoint:", CKPT)
        print("Model parameters:", model.count_params())
        print("Model weights:", len(model.weights))
        print("Compared tensors:", len(checks))
        print("Exact matches:", len(checks) - len(failures))
        print("Mismatches:", len(failures))

        for name, ok, detail in checks:
            if not ok:
                print("FAIL:", name, detail)

        if len(checks) != 162:
            raise RuntimeError(
                "Expected 162 model tensors, compared {}".format(len(checks))
            )
        if failures:
            raise RuntimeError(
                "Checkpoint verification failed; do not freeze the reference model."
            )

        print("CHECKPOINT_NUMERICAL_MATCH: PASS")

    finally:
        sess.close()


if __name__ == "__main__":
    main()
