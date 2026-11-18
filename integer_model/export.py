"""OFFLINE floating point conversion only. Frozen weights are never updated."""
import csv
import hashlib
import json
import math
from pathlib import Path
import numpy as np


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def q31(alpha):
    alpha = np.asarray(alpha, np.float64)
    if np.any(~np.isfinite(alpha)) or np.any(alpha <= 0):
        raise ValueError("Scales must be finite and positive")
    mantissa, exponent = np.frexp(alpha)
    m = np.rint(mantissa*(1 << 31)).astype(np.int64)
    carry = m == (1 << 31)
    m = np.where(carry, m >> 1, m)
    s = 31-exponent.astype(np.int64)-carry.astype(np.int64)
    assert np.all((m > 0) & (m < (1 << 31)))
    return m.astype(np.int32), s.astype(np.int32)


def export(raw_path, calibration_path, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if (output / "manifest.json").exists():
        raise FileExistsError("Preserve parameter evidence; choose a new directory")
    raw = np.load(raw_path)
    scales = {}
    with open(calibration_path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r["format"] == "INT8" and r["threshold_source"] == "abs_p999_est":
                if r["tensor"] in scales:
                    raise ValueError("Duplicate scale")
                scales[r["tensor"]] = float(r["scale"])
    assert scales and all(math.isfinite(s) and s > 0 for s in scales.values())
    params, proofs, decode = {}, {}, dict(scales)

    def coefficient(key, alpha):
        params[key+"_m"], params[key+"_s"] = q31(alpha)

    def dense(key, sx, sy):
        w = raw[key+"_w"].astype(np.float64)
        sw = np.maximum(np.abs(w).max(axis=0)/127, 1e-12)
        params[key+"_w"] = np.clip(np.rint(w/sw), -127, 127).astype(np.int8)
        b = raw[key+"_b"].astype(np.float64) if key+"_b" in raw else np.zeros(w.shape[1])
        bq = np.rint(b/(sx*sw))
        bound = w.shape[0]*127**2 + np.abs(bq)
        if np.any(bound > (1 << 31)-1):
            raise OverflowError(key+" bias/accumulator range proof failed")
        params[key+"_b"] = bq.astype(np.int32)
        coefficient(key, sx*sw/sy)
        assert np.all(bound*params[key+"_m"].astype(np.float64) < (1 << 63))
        proofs[key] = {"reduction_k": w.shape[0], "accumulator_abs_bound": int(bound.max()),
                       "bias_abs_max": int(np.abs(bq).max()),
                       "shift_min": int(params[key+"_s"].min()), "shift_max": int(params[key+"_s"].max())}

    def residual(key, sx, sb, trace_name):
        sr = 127*(sx+sb)/32767
        coeff = np.array([sx/sr, sb/sr], np.float64)
        shift = int(math.floor(math.log2(((1 << 31)-1)/coeff.max())))
        m = np.rint(coeff*(2.**shift)).astype(np.int64)
        if np.any(m < (1 << 24)) or np.any(m > (1 << 31)-1):
            raise OverflowError("Residual coefficients lose required relative precision")
        params[key+"_coeff"] = np.array([m[0], m[1], shift], np.int64)
        decode[trace_name] = sr
        return sr

    def ln(key, sr, sy):
        eps = max(1, int(round(4096*1e-6/sr**2*(1 << 16))))
        # Runtime uses signed64, which is stricter than the spec's uint64 H.
        assert ((4096*32767**2) << 16)+eps < (1 << 63)
        params[key+"_eps"] = np.array(eps, np.int64)
        g, b = [np.rint(raw[key+suffix].astype(np.float64)*(1 << 20)) for suffix in ["_g", "_b"]]
        assert max(np.abs(g).max(), np.abs(b).max()) < (1 << 31)
        bound = np.ceil(9*np.abs(g)+np.abs(b)+1)
        assert np.max(bound) < (1 << 31)
        params[key+"_g"], params[key+"_b"] = g.astype(np.int32), b.astype(np.int32)
        coefficient(key, 1/((1 << 20)*sy))
        assert bound.max()*int(params[key+"_m"]) < (1 << 63)
        proofs[key] = {"epsilon_q16": eps, "affine_abs_bound_n_le_9": int(bound.max()),
                       "H_worst_case": ((4096*32767**2) << 16)+eps}

    sx = scales["encoder_input"]
    for i in range(12):
        key, name = f"l{i:02d}", f"layer_{i:02d}"
        s = lambda n: scales[name+"/"+n]
        for short in ["q", "k", "v"]:
            dense(key+"_"+short, sx, s(short+"_projection"))
        coefficient(key+"_score", 256*s("q_projection")*s("k_projection")/8)
        coefficient(key+"_ctx", s("v_projection")/(65535*s("attention_context")))
        dense(key+"_o", s("attention_context"), s("attention_output_projection"))
        sr1 = residual(key+"_r1", sx, s("attention_output_projection"), name+"/residual1_sum")
        ln(key+"_ln1", sr1, s("layernorm1_output"))
        dense(key+"_fc1", s("layernorm1_output"), s("ffn_dense1_output"))
        table = []
        for q in range(-128, 128):
            x = max(-127, q)*s("ffn_dense1_output")
            value = .5*x*(1+math.erf(x/math.sqrt(2)))
            table.append(max(-127, min(127, round(value/s("gelu_output")))))
        params[key+"_gelu_lut"] = np.array(table, np.int8)
        dense(key+"_fc2", s("gelu_output"), s("ffn_dense2_output"))
        sr2 = residual(key+"_r2", s("layernorm1_output"), s("ffn_dense2_output"), name+"/residual2_sum")
        ln(key+"_ln2", sr2, s("layernorm2_output"))
        decode[name+"/attention_score_raw"] = s("q_projection")*s("k_projection")
        decode[name+"/attention_softmax"] = 1/65535
        sx = s("layernorm2_output")
    params["exp_lut"] = np.array([round((1 << 20)*math.exp(-j/256)) for j in range(4096)]+[0], np.uint32)
    path = output / "parameters.npz"
    np.savez(path, **params)
    manifest = {"numeric_spec": "INTEGER_NUMERICS_V1", "rounding": "nearest_ties_even",
                "scale_source": "training abs_p999_est, 2048 samples", "testing_used": False,
                "raw_parameters_sha256": sha(raw_path), "calibration_sha256": sha(calibration_path),
                "parameters_sha256": sha(path), "export_script_sha256": sha(__file__),
                "encoder_weight_matrices": 72, "decode_scales": decode,
                "proofs": proofs, "final_scale": sx,
                "array_schema": {k: {"dtype": str(v.dtype), "shape": list(v.shape),
                                     "sha256": hashlib.sha256(v.tobytes()).hexdigest()} for k, v in params.items()}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
