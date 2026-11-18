"""Read-only diagnoses: separate integer LN approximation from INT8 coding."""
import csv
import json
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "testdata/integer_v1"


def main():
    p = json.loads((BASE / "params/manifest.json").read_text())
    z = np.load(BASE / "smoke32/integer_trace_first_batch.npz")
    raw = np.load(BASE / "fixture/raw_parameters.npz")
    rows = []
    for i in range(12):
        prefix = f"layer_{i:02d}"
        for j in [1,2]:
            rname = prefix+f"/residual{j}_sum"
            lname = prefix+f"/layernorm{j}_output"
            x = z[rname].astype(np.float64)*p["decode_scales"][rname]
            xc = x-x.mean(axis=-1,keepdims=True)
            n = xc/np.sqrt(np.mean(xc*xc,axis=-1,keepdims=True)+1e-6)
            nq = z[lname+"/normalized_q14"].astype(np.float64)/(1 << 14)
            norm_diff = nq-n
            ideal = n*raw[f"l{i:02d}_ln{j}_g"]+raw[f"l{i:02d}_ln{j}_b"]
            sy = p["decode_scales"][lname]
            ideal_code = np.clip(np.rint(ideal/sy),-127,127).astype(np.int8)
            actual = z[lname]
            code_diff = actual.astype(np.int16)-ideal_code.astype(np.int16)
            rows.append({"stage":lname,"samples":len(x),
                         "normalized_q14_nrmse":float(np.sum(norm_diff**2)/np.sum(n**2))**.5,
                         "normalized_q14_max_abs":float(np.abs(norm_diff).max()),
                         "integer_vs_ideal_quantized_ln_code_mismatches":int(np.count_nonzero(code_diff)),
                         "code_count":int(code_diff.size),"code_error_max":int(np.abs(code_diff).max()),
                         "code_error_gt_1":int(np.count_nonzero(np.abs(code_diff)>1))})
    with open(BASE / "ln_integer_approximation_first16.csv","w",encoding="utf-8-sig",newline="") as f:
        writer = csv.DictWriter(f,fieldnames=list(rows[0])); writer.writeheader();writer.writerows(rows)
    fp = np.load(BASE / "fixture/fp_logits.npy")
    labels = np.load(BASE / "fixture/labels.npy")
    old_path = ROOT / "testdata/ptq_activation_validation/joint_all_full_20261018_v2/kwt1_ptq_activation_validation_predictions.csv"
    with old_path.open(encoding="utf-8-sig",newline="") as f:
        old = list(csv.DictReader(f))
    old_pred = np.array([int(r["fp32_predicted_id"]) for r in old])
    old_labels = np.array([int(r["true_label_id"]) for r in old])
    ids = np.flatnonzero(old_pred != fp.argmax(-1))
    result = {"ln_first16_max_normalized_q14_nrmse":max(r["normalized_q14_nrmse"] for r in rows),
              "ln_first16_max_normalized_q14_abs_error":max(r["normalized_q14_max_abs"] for r in rows),
              "ln_first16_code_count":sum(r["code_count"] for r in rows),
              "ln_first16_code_mismatches_vs_ideal_same_input_quantized_ln":sum(r["integer_vs_ideal_quantized_ln_code_mismatches"] for r in rows),
              "ln_first16_code_error_gt_1":sum(r["code_error_gt_1"] for r in rows),
              "historical_fp_label_order_mismatches":int(np.count_nonzero(old_labels!=labels)),
              "historical_fp_changed_offsets":ids.tolist(),
              "historical_fp_differences":[{"offset":int(i),"label":int(labels[i]),"old":int(old_pred[i]),
                                             "new":int(fp[i].argmax())} for i in ids],
              "parameter_array_payload_bytes":int(sum(np.prod(r["shape"],dtype=np.int64)*np.dtype(r["dtype"]).itemsize for r in p["array_schema"].values())),
              "dense_static_accumulator_abs_bound_max":max(r["accumulator_abs_bound"] for r in p["proofs"].values() if "accumulator_abs_bound" in r)}
    (BASE / "evidence_analysis.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
