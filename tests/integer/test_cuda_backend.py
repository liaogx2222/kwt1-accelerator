"""Prove optional CUDA dense backend matches CPU integer accumulators/encoder."""
import json
import sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from integer_model.runtime import Encoder
from integer_model.cuda_matmul import CudaInt8Matmul


def main():
    root = ROOT / "testdata/integer_v1"
    p = dict(np.load(root / "params/parameters.npz"))
    backend = CudaInt8Matmul()
    rng = np.random.default_rng(20261020)
    checked = 0
    # Every actual matrix including 99-row tails and K=256.
    for i in range(12):
        for kind in ["q","k","v","o","fc1","fc2"]:
            w = p[f"l{i:02d}_{kind}_w"]
            x = rng.integers(-127,128,size=(1,99,w.shape[0]),dtype=np.int16).astype(np.int8)
            out = backend(x,w)
            expected = x.astype(np.int32)@w.astype(np.int32)
            assert np.array_equal(out,expected)
            checked += out.size
    q = np.load(root / "smoke32/input_int8_first_batch.npy")
    reference = np.load(root / "smoke32/encoder_output_int8.npy")
    cuda = Encoder(p,dense_matmul=backend)(q)
    assert np.array_equal(cuda,reference[:len(q)])
    # Also compare every emitted stage, for a representative sample.
    traces = [{},{}]
    for target, mm in zip(traces,[None,backend]):
        Encoder(p,lambda name,x,clip: target.update({name: x.copy()}),dense_matmul=mm)(q[:1])
    assert traces[0].keys() == traces[1].keys()
    for key in traces[0]:
        assert np.array_equal(traces[0][key],traces[1][key]), key
    result = {"passed": True,"all_72_dense_accumulator_codes": checked,
              "full_encoder_codes": int(cuda.size), "all_stage_tensors":len(traces[0]),
              "all_stage_codes":sum(x.size for x in traces[0].values()), "mismatches":0}
    (root / "cuda_backend_tests.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
