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
sys.path.insert(0, str(REPO))

MODEL_DIR = REPO / "models_data_v2_12_labels" / "kwt1"
CKPT = str(MODEL_DIR / "best_weights")
OUT_DIR = REPO / "testdata"
OUT_FILE = OUT_DIR / "smoke_kwt1_reference.npz"


def main():
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
        # 按官方入口的模块初始化顺序导入，避免循环导入
        from kws_streaming.train import model_train_eval as _official_entry
        from kws_streaming.models import kws_transformer

        # 构建官方 KWT-1 分类模型
        model = kws_transformer.model(flags)

        transformer = next(
            layer for layer in model.layers
            if hasattr(layer, "enc_layers")
        )
        feature_layer = next(
            layer for layer in model.layers
            if layer.name == "speech_features"
        )

        # 将原模型的音频预处理输出暴露出来
        feature_model = tf.keras.Model(
            inputs=model.inputs,
            outputs=feature_layer.output
        )

        # 复用原模型中的同一组权重，构建仅用于观察中间结果的模型
        feature_shape = (
            int(cfg["spectrogram_length"]),
            int(cfg["dct_num_features"]),
        )
        feature_input = tf.keras.Input(
            batch_size=1,
            shape=feature_shape,
            name="reference_mfcc"
        )

        x = transformer.patch_proj(feature_input)

        batch_size = tf.shape(x)[0]
        class_token = tf.broadcast_to(
            transformer.class_emb,
            [batch_size, 1, transformer.d_model]
        )

        # 分类 Token + 98 个时间 Token + 位置编码
        x = tf.concat([class_token, x], axis=1)
        x = x + transformer.pos_emb

        encoder_input = x
        sequence_outputs = [encoder_input]

        # 逐层运行原始 TransformerBlock，不改模型结构
        for block in transformer.enc_layers:
            x, _ = block(x, training=False)
            sequence_outputs.append(x)

        # 原模型分类头只作用于最后一层的分类 Token
        classifier = model.layers[-1]
        logits = classifier(x[:, 0, :])

        reference_model = tf.keras.Model(
            inputs=feature_input,
            outputs=sequence_outputs + [logits],
            name="kwt1_sequence_reference"
        )

        # 初始化并显式加载赛题指定的 best_weights
        sess.run(tf.global_variables_initializer())
        status = model.load_weights(CKPT)
        status.assert_existing_objects_matched()
        status.expect_partial()

        if hasattr(status, "run_restore_ops"):
            status.run_restore_ops()

        # 全零波形仅用于验证数据流
        audio = np.zeros(
            (1, int(cfg["desired_samples"])),
            dtype=np.float32
        )

        features = sess.run(
            feature_model.outputs,
            feed_dict={model.inputs[0]: audio}
        )
        if isinstance(features, (list, tuple)):
            features = features[0]

        outputs = sess.run(
            reference_model.outputs,
            feed_dict={feature_input: features}
        )

        official_outputs = sess.run(
            model.outputs,
            feed_dict={model.inputs[0]: audio}
        )
        if isinstance(official_outputs, (list, tuple)):
            official_logits = official_outputs[0]
        else:
            official_logits = official_outputs

        reference_logits = outputs[-1]
        max_logit_diff = float(
            np.max(np.abs(official_logits - reference_logits))
        )

        assert features.shape == (1, 98, 40), features.shape
        assert outputs[0].shape == (1, 99, 64), outputs[0].shape

        for i in range(12):
            assert outputs[i + 1].shape == (1, 99, 64)

        assert reference_logits.shape == (1, 12)
        assert np.all(np.isfinite(outputs[0]))
        assert all(np.all(np.isfinite(y)) for y in outputs)
        assert np.allclose(
            official_logits, reference_logits,
            rtol=1e-5, atol=1e-6
        ), "分类头对照失败"

        payload = {
            "smoke_audio": audio[0],
            "mfcc_features": features[0],
            "encoder_input": outputs[0][0],
            "final_encoder_output": outputs[12][0],
            "final_logits": reference_logits[0],
            "official_logits": official_logits[0],
        }

        for i in range(12):
            payload["layer_{:02d}_output".format(i)] = outputs[i + 1][0]

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(str(OUT_FILE), **payload)

        print("Checkpoint:", CKPT)
        print("Input waveform:", audio.shape)
        print("MFCC features:", features.shape)
        print("Encoder input:", outputs[0].shape)
        print("Encoder layers:", len(transformer.enc_layers))
        print("Final encoder output:", outputs[12].shape)
        print("Classification logits:", reference_logits.shape)
        print("Max logit difference:", max_logit_diff)
        print("Smoke test: PASS")
        print("Output file:", OUT_FILE)

    finally:
        sess.close()


if __name__ == "__main__":
    main()
