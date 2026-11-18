"""Evaluate all 12 layers in integer arithmetic on a frozen Validation fixture.

Float operations here are restricted to input encoding, the frozen PC head,
and error measurements. integer_model.runtime is the complete encoder path.
"""
import argparse
import csv
import hashlib
import json
import sys
import time
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from integer_model.runtime import Encoder
from integer_model.export import sha


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


class Observer:
    def __init__(self, scales, raw):
        self.scales, self.raw = scales, raw
        self.stats, self.local, self.cache, self.trace = {}, {}, {}, {}
        self.capture = True

    def errors(self, name, actual, reference, lsb=None):
        diff = actual-reference
        r = self.local.setdefault(name, {"name": name, "count": 0, "error_square_sum": 0.,
                                        "reference_square_sum": 0., "max_abs": 0., "abs_sum": 0.,
                                        "first_batch_abs_lsb": []})
        r["count"] += diff.size
        r["error_square_sum"] += float(np.sum(diff*diff))
        r["reference_square_sum"] += float(np.sum(reference*reference))
        r["abs_sum"] += float(np.sum(np.abs(diff)))
        r["max_abs"] = max(r["max_abs"], float(np.abs(diff).max()))
        if self.capture and lsb:
            r["first_batch_abs_lsb"] = (np.abs(diff)/lsb).reshape(-1).tolist()
        return r

    def __call__(self, name, q, clipped):
        lo, hi = int(q.min()), int(q.max())
        r = self.stats.setdefault(name, {"tensor": name, "dtype": str(q.dtype), "elements": 0,
                                         "min": lo, "max": hi, "clipped": 0, "boundary_hits": 0})
        r["elements"] += q.size
        r["min"], r["max"] = min(r["min"], lo), max(r["max"], hi)
        r["clipped"] += clipped
        if q.dtype == np.int8:
            r["boundary_hits"] += int(np.count_nonzero(np.abs(q.astype(np.int16)) == 127))
        elif q.dtype == np.int16:
            r["boundary_hits"] += int(np.count_nonzero(np.abs(q.astype(np.int32)) == 32767))
        if self.capture:
            self.trace[name] = q.copy()
        if name.endswith("/attention_score_raw"):
            self.cache["score"] = q
        if name.endswith("/attention_softmax"):
            score_name = name.rsplit("/", 1)[0]+"/attention_score_raw"
            scores = self.cache.pop("score").astype(np.float64)*self.scales[score_name]/8
            scores -= scores.max(axis=-1, keepdims=True)
            ex = np.exp(scores)
            ref = ex/ex.sum(axis=-1, keepdims=True)
            decoded = q.astype(np.float64)/65535
            rr = self.errors(name+"/same_integer_score", decoded, ref)
            rr["max_row_l1"] = max(rr.get("max_row_l1", 0.), float(np.abs(decoded-ref).sum(axis=-1).max()))
        if name.endswith("/residual1_sum") or name.endswith("/residual2_sum"):
            self.cache["residual"] = q.astype(np.float64)*self.scales[name]
        if name.endswith("/layernorm1_output") or name.endswith("/layernorm2_output"):
            i = int(name[6:8])
            j = 1 if name.endswith("1_output") else 2
            x = self.cache.pop("residual")
            centered = x-x.mean(axis=-1, keepdims=True)
            normalized = centered/np.sqrt(np.mean(centered*centered, axis=-1, keepdims=True)+1e-6)
            ref = normalized*self.raw[f"l{i:02d}_ln{j}_g"]+self.raw[f"l{i:02d}_ln{j}_b"]
            sy = self.scales[name]
            decoded = q.astype(np.float64)*sy
            self.errors(name+"/same_integer_residual", decoded, ref, sy)
            clipped_ref = np.clip(ref, -127*sy, 127*sy)
            self.errors(name+"/same_integer_residual_clip_excluded", decoded, clipped_ref, sy)

    def reports(self):
        rows = []
        for r in self.local.values():
            copy = {k: v for k, v in r.items() if k != "first_batch_abs_lsb"}
            copy["rmse"] = (r["error_square_sum"]/r["count"])**.5
            copy["nrmse"] = (r["error_square_sum"]/max(r["reference_square_sum"], 1e-30))**.5
            copy["mae"] = r["abs_sum"]/r["count"]
            if r["first_batch_abs_lsb"]:
                copy["first_batch_p99_abs_output_lsb"] = float(np.percentile(r["first_batch_abs_lsb"], 99))
            rows.append(copy)
        return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fixture", type=Path, default=ROOT / "testdata/integer_v1/fixture")
    p.add_argument("--params", type=Path, default=ROOT / "testdata/integer_v1/params")
    p.add_argument("--output", type=Path, default=ROOT / "testdata/integer_v1/validation")
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--max-samples", type=int, default=0)
    p.add_argument("--dense-backend", choices=["numpy", "cuda-int8"], default="numpy")
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    if (a.output / "metrics.json").exists():
        raise FileExistsError("Preserve previous evaluation; use a new output directory")
    fm = json.loads((a.fixture / "manifest.json").read_text(encoding="utf-8"))
    pm = json.loads((a.params / "manifest.json").read_text(encoding="utf-8"))
    assert fm["partition"] == "validation" and fm["testing_batches_requested"] == 0
    assert sha(a.params / "parameters.npz") == pm["parameters_sha256"]
    # Verify the exact frozen files, including identity/order and software head.
    for name, digest in fm["files_sha256"].items():
        if sha(a.fixture / name) != digest:
            raise ValueError("Fixture hash mismatch: "+name)
    params = dict(np.load(a.params / "parameters.npz"))
    raw = np.load(a.fixture / "raw_parameters.npz")
    assert sha(a.fixture / "raw_parameters.npz") == pm["raw_parameters_sha256"]
    inputs = np.load(a.fixture / "encoder_input.npy", mmap_mode="r")
    reference = np.load(a.fixture / "fp_encoder_output.npy", mmap_mode="r")
    labels = np.load(a.fixture / "labels.npy")
    fp_logits = np.load(a.fixture / "fp_logits.npy")
    n = min(len(labels), a.max_samples) if a.max_samples else len(labels)
    outputs = np.lib.format.open_memmap(str(a.output / "encoder_output_int8.npy"), mode="w+", dtype=np.int8, shape=(n,99,64))
    logits = np.empty((n, 12), np.float32)
    obs = Observer(pm["decode_scales"], raw)
    matmul = None
    if a.dense_backend == "cuda-int8":
        from integer_model.cuda_matmul import CudaInt8Matmul
        matmul = CudaInt8Matmul()
    encoder = Encoder(params, obs, dense_matmul=matmul)
    error_ss = ref_ss = abs_sum = 0.
    max_error = 0.
    input_clipped = 0
    start = time.perf_counter()
    for offset in range(0, n, a.batch_size):
        count = min(a.batch_size, n-offset)
        fq = np.rint(inputs[offset:offset+count].astype(np.float64)/pm["decode_scales"]["encoder_input"])
        input_clipped += int(np.count_nonzero(np.abs(fq) > 127))
        q = np.clip(fq, -127, 127).astype(np.int8)
        out = encoder(q)
        outputs[offset:offset+count] = out
        # Frozen software classifier, same float32 dtype as original model.
        decoded = out.astype(np.float32)*np.float32(pm["final_scale"])
        logits[offset:offset+count] = decoded[:, 0, :]@raw["head_w"]+raw["head_b"]
        diff = decoded.astype(np.float64)-reference[offset:offset+count]
        error_ss += float(np.sum(diff*diff))
        ref_ss += float(np.sum(reference[offset:offset+count].astype(np.float64)**2))
        abs_sum += float(np.sum(np.abs(diff)))
        max_error = max(max_error, float(np.abs(diff).max()))
        if offset == 0:
            np.savez(a.output / "integer_trace_first_batch.npz", **obs.trace)
            np.save(a.output / "input_int8_first_batch.npy", q)
            # Batch grouping must not change any output codes.
            repeat = Encoder(params)(q[:1])
            assert np.array_equal(repeat[0], out[0])
            obs.capture = False
            obs.trace = {}
        if offset % (a.batch_size*10) == 0 or offset+count == n:
            print("integer {}/{} elapsed {:.1f}s".format(offset+count, n, time.perf_counter()-start), flush=True)
    outputs.flush()
    np.save(a.output / "logits.npy", logits)
    pred, fp_pred = logits.argmax(axis=-1), fp_logits[:n].argmax(axis=-1)
    correct = int(np.sum(pred == labels[:n]))
    fp_correct = int(np.sum(fp_pred == labels[:n]))
    drop = (fp_correct-correct)*100/n
    confusion = np.zeros((12, 12), np.int64)
    np.add.at(confusion, (labels[:n], pred), 1)
    local = obs.reports()
    write_csv(a.output / "stage_ranges.csv", list(obs.stats.values()))
    write_csv(a.output / "local_nonlinear_errors.csv", local)
    write_csv(a.output / "predictions.csv", [{"offset": i, "label": int(labels[i]), "fp_pred": int(fp_pred[i]),
                 "integer_pred": int(pred[i]), "fp_correct": int(fp_pred[i] == labels[i]),
                 "integer_correct": int(pred[i] == labels[i])} for i in range(n)])
    write_csv(a.output / "per_class.csv", [{"label": i, "name": fm["label_names"][i],
                 "samples": int(np.sum(labels[:n] == i)), "fp_correct": int(np.sum((labels[:n] == i) & (fp_pred == i))),
                 "integer_correct": int(confusion[i, i])} for i in range(12)])
    # Compare captured stages with FP32 on the same first min(batch sizes) samples.
    int_trace = np.load(a.output / "integer_trace_first_batch.npz")
    fp_trace = np.load(a.fixture / "fp_trace_first_batch.npz")
    errors = []
    for name in int_trace.files:
        if name in fp_trace.files and name in pm["decode_scales"]:
            m = min(len(int_trace[name]), len(fp_trace[name]))
            val = int_trace[name][:m].astype(np.float64)*pm["decode_scales"][name]
            ref = fp_trace[name][:m].astype(np.float64)
            d = val-ref
            errors.append({"tensor": name, "samples": m, "rmse": float(np.mean(d*d)**.5),
                           "nrmse": float(np.sum(d*d)/max(np.sum(ref*ref),1e-30))**.5,
                           "mae": float(np.abs(d).mean()), "max_abs": float(np.abs(d).max()),
                           "p99_abs": float(np.percentile(np.abs(d),99))})
    write_csv(a.output / "stage_errors_first_batch.csv", errors)
    metrics = {"scheme": "INTEGER_NUMERICS_V1_W8_A8_Pu16_Rs16", "partition": "validation", "samples": n,
               "fp_correct": fp_correct, "integer_correct": correct, "fp_accuracy": fp_correct/n,
               "integer_accuracy": correct/n, "accuracy_drop_pp": drop,
               "prediction_agreement": float(np.mean(pred == fp_pred)),
               "fp_correct_integer_wrong": int(np.sum((fp_pred == labels[:n]) & (pred != labels[:n]))),
               "fp_wrong_integer_correct": int(np.sum((fp_pred != labels[:n]) & (pred == labels[:n]))),
               "encoder_output_rmse": (error_ss/(n*99*64))**.5,
               "encoder_output_nrmse": (error_ss/ref_ss)**.5,
               "encoder_output_mae": abs_sum/(n*99*64), "encoder_output_max_abs": max_error,
               "input_clipped_count": input_clipped, "confusion_matrix": confusion.tolist(),
               "development_drop_le_0_5pp": drop <= .5, "freeze_gate_drop_le_1pp": drop <= 1.,
               "official_2pp_diagnostic_only": drop <= 2.,
               "softmax_max_row_l1": max(r.get("max_row_l1",0.) for r in local),
               "same_input_ln_nrmse_max_with_clipping": max(r["nrmse"] for r in local if r["name"].endswith("/same_integer_residual")),
               "same_input_ln_nrmse_max_clip_excluded": max(r["nrmse"] for r in local if r["name"].endswith("clip_excluded")),
               "batch1_repeat_bit_exact": True, "testing_batches_requested": 0,
               "runtime_seconds": time.perf_counter()-start, "numpy_version": np.__version__,
               "dense_backend": a.dense_backend,
               "dense_backend_source_sha256": sha(ROOT / "integer_model/cuda_matmul.py") if matmul else None,
               "fixture_manifest_sha256": sha(a.fixture / "manifest.json"),
               "params_manifest_sha256": sha(a.params / "manifest.json"),
               "runtime_source_sha256": sha(ROOT / "integer_model/runtime.py"),
               "evaluator_source_sha256": sha(__file__),
               "outputs_sha256": {x.name: sha(x) for x in a.output.iterdir() if x.is_file()}}
    (a.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps({k: metrics[k] for k in ["samples", "fp_correct", "integer_correct", "accuracy_drop_pp", "runtime_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
