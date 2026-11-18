#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Analyze activation ranges from export_kwt1_golden.py output.

Example:
  python scripts/analyze_kwt1_golden.py --input testdata/kwt1_golden_32.npz

Writes a summary CSV, per-channel CSV, and JSON report next to the NPZ by default.
The result is exploratory calibration data, not a final fixed-point specification.
"""
import argparse
import csv
import json
import re
from pathlib import Path

import numpy as np


def quantile(values, q):
    # NumPy 1.19 supports percentile() but not the newer method= API.
    return float(np.percentile(values, q))


def collect_layer_keys(npz):
    keys = []
    if "encoder_input" in npz.files:
        keys.append("encoder_input")
    layer_keys = [k for k in npz.files if re.fullmatch(r"layer_\d{2}_output", k)]
    layer_keys.sort(key=lambda k: int(re.search(r"layer_(\d+)_", k).group(1)))
    keys.extend(layer_keys)
    if "final_logits" in npz.files:
        keys.append("final_logits")
    return keys


def summarize(name, array):
    x = np.asarray(array, dtype=np.float64)
    finite_mask = np.isfinite(x)
    finite = x[finite_mask]
    if finite.size == 0:
        raise ValueError("Tensor has no finite values: " + name)
    abs_finite = np.abs(finite)
    return {
        "tensor": name,
        "shape": list(x.shape),
        "dtype_in_npz": str(np.asarray(array).dtype),
        "count": int(x.size),
        "finite_count": int(finite.size),
        "nonfinite_count": int(x.size - finite.size),
        "min": float(np.min(finite)),
        "max": float(np.max(finite)),
        "mean": float(np.mean(finite)),
        "std": float(np.std(finite)),
        "rms": float(np.sqrt(np.mean(finite * finite))),
        "max_abs": float(np.max(abs_finite)),
        "abs_p99": quantile(abs_finite, 99.0),
        "abs_p999": quantile(abs_finite, 99.9),
        "abs_p9999": quantile(abs_finite, 99.99),
        "abs_median": quantile(abs_finite, 50.0),
        "zero_fraction": float(np.mean(finite == 0.0)),
    }


def per_channel_rows(name, array):
    """For [N,T,C] activations, summarize each feature channel across N,T."""
    x = np.asarray(array, dtype=np.float64)
    if x.ndim != 3:
        return []
    rows = []
    for c in range(x.shape[-1]):
        v = x[:, :, c].reshape(-1)
        v = v[np.isfinite(v)]
        if not v.size:
            continue
        a = np.abs(v)
        rows.append({
            "tensor": name,
            "channel": c,
            "min": float(np.min(v)),
            "max": float(np.max(v)),
            "mean": float(np.mean(v)),
            "std": float(np.std(v)),
            "max_abs": float(np.max(a)),
            "abs_p99": quantile(a, 99.0),
            "abs_p999": quantile(a, 99.9),
        })
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="testdata/kwt1_golden_32.npz",
                        help="Golden NPZ exported by export_kwt1_golden.py")
    parser.add_argument("--out-dir", default=None,
                        help="Output directory (default: NPZ parent directory)")
    args = parser.parse_args()

    npz_path = Path(args.input).resolve()
    if not npz_path.is_file():
        raise FileNotFoundError("Golden NPZ not found: {}".format(npz_path))
    out_dir = Path(args.out_dir).resolve() if args.out_dir else npz_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    with np.load(str(npz_path), allow_pickle=False) as npz:
        keys = collect_layer_keys(npz)
        if not keys:
            raise ValueError(
                "No recognized tensors found. NPZ keys: {}".format(npz.files)
            )
        summaries = [summarize(k, npz[k]) for k in keys]
        channel_rows = []
        for key in keys:
            channel_rows.extend(per_channel_rows(key, npz[key]))
        available_keys = list(npz.files)

    summary_csv = out_dir / (npz_path.stem + "_activation_stats.csv")
    channel_csv = out_dir / (npz_path.stem + "_channel_stats.csv")
    report_json = out_dir / (npz_path.stem + "_activation_stats.json")

    summary_fields = [
        "tensor", "shape", "dtype_in_npz", "count", "finite_count",
        "nonfinite_count", "min", "max", "mean", "std", "rms", "max_abs",
        "abs_p99", "abs_p999", "abs_p9999", "abs_median", "zero_fraction",
    ]
    with summary_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=summary_fields)
        writer.writeheader()
        for row in summaries:
            out = dict(row)
            out["shape"] = "x".join(str(v) for v in out["shape"])
            writer.writerow(out)

    channel_fields = [
        "tensor", "channel", "min", "max", "mean", "std", "max_abs",
        "abs_p99", "abs_p999",
    ]
    with channel_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=channel_fields)
        writer.writeheader()
        writer.writerows(channel_rows)

    report = {
        "input_npz": str(npz_path),
        "npz_keys": available_keys,
        "analyzed_tensors": summaries,
        "channel_stats_csv": str(channel_csv),
        "summary_csv": str(summary_csv),
        "note": (
            "Exploratory stats only. Thirty-two test samples are insufficient to freeze "
            "fixed-point formats. Use a representative calibration set, preferably the "
            "validation split, before selecting scales/bit widths; reserve contest test "
            "samples for final evaluation."
        ),
    }
    with report_json.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("Input NPZ:", npz_path)
    print("Analyzed tensors:", len(summaries))
    print()
    print("{:<22s} {:>12s} {:>12s} {:>12s} {:>12s}".format(
        "Tensor", "min", "max", "abs_p99", "max_abs"))
    for row in summaries:
        print("{:<22s} {:>12.5g} {:>12.5g} {:>12.5g} {:>12.5g}".format(
            row["tensor"], row["min"], row["max"], row["abs_p99"], row["max_abs"]))
    bad = sum(row["nonfinite_count"] for row in summaries)
    print("\nNon-finite values in analyzed tensors:", bad)
    print("Summary CSV:", summary_csv)
    print("Per-channel CSV:", channel_csv)
    print("JSON report:", report_json)
    if bad:
        raise SystemExit("FAIL: non-finite tensor values detected")
    print("Activation analysis: PASS")


if __name__ == "__main__":
    main()
