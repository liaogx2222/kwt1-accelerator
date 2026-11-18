import os
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import tensorflow.compat.v1 as tf

# 保持与该仓库的 TF1-style 推理代码兼容
tf.disable_eager_execution()

def main():
    repo = Path(__file__).resolve().parents[1]
    model_dir = repo / "models_data_v2_12_labels" / "kwt1"
    weight_prefix = model_dir / "best_weights"
    report_path = repo / "manifest" / "kwt1_model_inspection.txt"

    if not Path(str(weight_prefix) + ".index").is_file():
        raise FileNotFoundError(
            "Missing checkpoint index: " +
            str(weight_prefix) + ".index"
        )

    # 从赛题指定目录读取模型训练时保存的参数。
    with open(model_dir / "flags.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # 显式指定本地目录与检查模式；不启动训练或评估流程。
    cfg["train_dir"] = str(model_dir)
    cfg["batch_size"] = 1
    cfg["training"] = False
    cfg["return_softmax"] = 0

    # 兼容 flags.json 中未保存、但模型构建代码会访问的参数。
    cfg.setdefault("distill_teacher_json", "")
    cfg.setdefault("prenorm", False)
    cfg.setdefault("approximate_gelu", False)

    flags = SimpleNamespace(**cfg)

    tf.reset_default_graph()
    session_config = tf.ConfigProto(device_count={"GPU": 0})
    sess = tf.Session(config=session_config)
    tf.keras.backend.set_session(sess)
    tf.keras.backend.set_learning_phase(0)

    try:
        # 先导入官方入口，按其初始化顺序加载模型注册表，
        # 避免直接导入 kws_transformer 时触发循环导入。
        import sys
        sys.path.insert(0, str(repo))
        from kws_streaming.train import model_train_eval as _official_entry
        from kws_streaming.models import kws_transformer

        # 使用官方模型构建函数，不修改网络结构。
        model = kws_transformer.model(flags)

        # 按官方训练代码的图模式流程初始化并恢复权重。
        sess.run(tf.global_variables_initializer())
        status = model.load_weights(str(weight_prefix))

        # 检查当前推理模型的对象是否已匹配 checkpoint
        status.assert_existing_objects_matched()

        # 训练 checkpoint 中还包含 optimizer 状态，推理模型不需要恢复它们
        status.expect_partial()

        # 在图模式下，显式执行待恢复的 restore ops（若接口可用）
        if hasattr(status, "run_restore_ops"):
            status.run_restore_ops()

        lines = []
        lines.append("KWT-1 model inspection")
        lines.append("checkpoint_prefix=" + str(weight_prefix))
        lines.append("model_name=" + str(cfg.get("model_name")))
        lines.append("num_layers=" + str(cfg.get("num_layers")))
        lines.append("d_model=" + str(cfg.get("d_model")))
        lines.append("heads=" + str(cfg.get("heads")))
        lines.append("mlp_dim=" + str(cfg.get("mlp_dim")))
        lines.append("prenorm=" + str(cfg["prenorm"]))
        lines.append("approximate_gelu=" +
                     str(cfg["approximate_gelu"]))
        lines.append("input_shape=" + str(model.input_shape))
        lines.append("output_shape=" + str(model.output_shape))
        lines.append("parameter_count=" + str(model.count_params()))
        lines.append("")
        lines.append("=== Keras model summary ===")

        model_summary = []
        model.summary(print_fn=model_summary.append)
        lines.extend(model_summary)

        lines.append("")
        lines.append("=== Model variable names and shapes ===")
        for i, var in enumerate(model.weights):
            lines.append(
                "{:03d} {} shape={}".format(
                    i, var.name, var.shape
                )
            )

        lines.append("")
        lines.append("=== Checkpoint variable names and shapes ===")
        for name, shape in tf.train.list_variables(
            str(weight_prefix)
        ):
            lines.append("{} shape={}".format(name, shape))

        lines.append("")
        lines.append("=== SHA-256 ===")
        for filename in [
            "best_weights.index",
            "best_weights.data-00000-of-00001",
            "flags.json",
            "labels.txt",
        ]:
            path = model_dir / filename
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append("{}  {}".format(digest, filename))

        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

        print("Weight loading: PASS")
        print("Model input shape:", model.input_shape)
        print("Model output shape:", model.output_shape)
        print("Parameter count:", model.count_params())
        print("Model weights:", len(model.weights))
        print("Inspection report:", report_path)

    finally:
        sess.close()

if __name__ == "__main__":
    main()
