"""Offline parameter/LUT export; uses frozen training calibration only."""
import argparse
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from integer_model.export import export

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raw", type=Path, default=ROOT / "testdata/integer_v1/fixture/raw_parameters.npz")
    p.add_argument("--calibration", type=Path, default=ROOT / "testdata/ptq_calibration/kwt1_ptq_activation_scale_candidates.csv")
    p.add_argument("--output", type=Path, default=ROOT / "testdata/integer_v1/params")
    a = p.parse_args()
    m = export(a.raw, a.calibration, a.output)
    print("Exported", m["encoder_weight_matrices"], "matrices; all static range proofs passed")
