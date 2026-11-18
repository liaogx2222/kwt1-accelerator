import os
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import tensorflow.compat.v1 as tf

tf.disable_eager_execution()


def main():
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))

    model_dir = repo / "models_data_v2_12_labels" / "kwt1"
    data_dir = repo / "data2"
    weight_prefix = model_dir / "best_weights"
    report_dir = repo / "reports" / "kwt1_reference"
    report_dir.mkdir(parents=True, exist_ok=True)

    with open(model_dir / "flags.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)

    cfg.update({
        "data_dir": str(data_dir),
        "data_url": "",
        "train_dir": str(model_dir),
        "training": False,
        "batch_size": 100,
        "return_softmax": 0,
        "background_frequency": 0.0,
        "background_volume": 0.0,
        "time_shift_ms": 0.0,
        "sp_time_shift_ms": 0.0,
        "resample": 0.0,
        "pick_deterministically": True,
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
        # Keep the official import order used by the inspection script.
        from kws_streaming.train import model_train_eval as _official_entry
        from kws_streaming.models import kws_transformer
        from kws_streaming.data import input_data

        processor = input_data.AudioProcessor(flags)
        model = kws_transformer.model(flags)

        sess.run(tf.global_variables_initializer())
        status = model.load_weights(str(weight_prefix))
        status.assert_existing_objects_matched()
        status.expect_partial()
        if hasattr(status, "run_restore_ops"):
            status.run_restore_ops()

        total = processor.set_size("testing")
        y_true_parts = []
        y_pred_parts = []

        for offset in range(0, total, flags.batch_size):
            real_n = min(flags.batch_size, total - offset)

            batch_x, batch_y = processor.get_data(
                real_n, offset, flags,
                0.0, 0.0, 0, "testing",
                0.0, 0.0, sess,
            )

            if real_n < flags.batch_size:
                pad_n = flags.batch_size - real_n
                pad_x = np.repeat(batch_x[-1:], pad_n, axis=0)
                batch_x = np.concatenate([batch_x, pad_x], axis=0)

            pred = model.predict(batch_x, verbose=0)
            if isinstance(pred, (list, tuple)):
                pred = pred[-1]

            y_true_parts.append(np.asarray(batch_y, dtype=np.int64))
            y_pred_parts.append(np.argmax(pred[:real_n], axis=1).astype(np.int64))

        y_true = np.concatenate(y_true_parts)
        y_pred = np.concatenate(y_pred_parts)
        labels = list(processor.words_list)
        nclass = len(labels)

        cm = np.zeros((nclass, nclass), dtype=np.int64)
        np.add.at(cm, (y_true, y_pred), 1)

        accuracy = float(np.mean(y_true == y_pred))
        per_class = []
        for i, label in enumerate(labels):
            n = int(cm[i].sum())
            correct = int(cm[i, i])
            per_class.append({
                "label": label,
                "samples": n,
                "correct": correct,
                "accuracy": correct / n if n else None,
            })

        result = {
            "checkpoint": str(weight_prefix),
            "data_dir": str(data_dir),
            "parameter_count": int(model.count_params()),
            "labels": labels,
            "testing_samples": int(len(y_true)),
            "correct": int(np.sum(y_true == y_pred)),
            "accuracy": accuracy,
            "accuracy_percent": accuracy * 100.0,
            "confusion_matrix_rows_true_cols_pred": cm.tolist(),
            "per_class": per_class,
            "evaluation": {
                "batch_size": int(flags.batch_size),
                "background_frequency": 0.0,
                "background_volume": 0.0,
                "time_shift_samples": 0,
                "resample_offset": 0.0,
                "volume_augmentation_offset": 0.0,
                "silence_percentage": cfg["silence_percentage"],
                "unknown_percentage": cfg["unknown_percentage"],
                "split_rule": "repository AudioProcessor / which_set",
            },
        }

        json_path = report_dir / "metrics.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        with open(report_dir / "report.txt", "w", encoding="utf-8") as f:
            f.write("KWT-1 floating-point reference evaluation\n")
            f.write("Checkpoint: {}\n".format(weight_prefix))
            f.write("Parameters: {}\n".format(model.count_params()))
            f.write("Samples: {}\n".format(len(y_true)))
            f.write("Correct: {}\n".format(np.sum(y_true == y_pred)))
            f.write("Accuracy: {:.4f}%\n\n".format(accuracy * 100))
            f.write("Per-class accuracy:\n")
            for row in per_class:
                pct = (
                    "{:.4f}%".format(row["accuracy"] * 100)
                    if row["accuracy"] is not None else "N/A"
                )
                f.write(
                    "{}: {}/{} ({})\n".format(
                        row["label"], row["correct"], row["samples"], pct
                    )
                )
            f.write("\nConfusion matrix (rows=true, columns=predicted):\n")
            f.write("labels=" + json.dumps(labels, ensure_ascii=False) + "\n")
            for row in cm:
                f.write(" ".join(str(int(v)) for v in row) + "\n")

        print("Checkpoint:", weight_prefix)
        print("Labels:", labels)
        print("Testing samples:", len(y_true))
        print("Accuracy: {:.4f}%".format(accuracy * 100))
        print("\nPer-class accuracy:")
        for row in per_class:
            pct = (
                "{:.2f}%".format(row["accuracy"] * 100)
                if row["accuracy"] is not None else "N/A"
            )
            print("  {:12s} {:5d}/{:<5d} {}".format(
                row["label"], row["correct"], row["samples"], pct
            ))
        print("\nReports:", report_dir)

    finally:
        sess.close()


if __name__ == "__main__":
    main()
