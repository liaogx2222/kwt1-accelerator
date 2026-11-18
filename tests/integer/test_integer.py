"""Independent arbitrary-precision checks for the hardware numerical contract."""
import argparse
import json
import math
import sys
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from integer_model.runtime import Encoder, rne, shift_rne, rq


def oracle(n, d):
    a = abs(int(n))
    q, r = divmod(a, int(d))
    return (-1 if n < 0 else 1)*(q+int(2*r > d or (2*r == d and q & 1)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--params", type=Path, default=ROOT / "testdata/integer_v1/params")
    p.add_argument("--output", type=Path, default=ROOT / "testdata/integer_v1/unit_tests.json")
    a = p.parse_args()
    rng = np.random.default_rng(20261020)
    checks = {}
    n = rng.integers(-(1 << 62), 1 << 62, size=20000, dtype=np.int64)
    d = rng.integers(1, 1 << 62, size=20000, dtype=np.int64)
    assert np.array_equal(rne(n, d), [oracle(x, y) for x, y in zip(n, d)])
    checks["rne_random_arbitrary_precision"] = len(n)
    ties = np.array([-9,-7,-5,-3,-1,0,1,3,5,7,9], np.int64)
    assert np.array_equal(rne(ties,2), [oracle(x,2) for x in ties])
    edge = np.array([-(1 << 63)+1, -(1 << 62), -3,-1,0,1,3,1 << 62,(1 << 63)-1], np.int64)
    for s in [0,1,2,14,18,31,37,38,62,63,64,100]:
        assert np.array_equal(shift_rne(edge,s), [oracle(x,1 << s) for x in edge])
    assert np.array_equal(shift_rne(ties,-10), ties*1024)
    for x, s in [(edge, -1), (np.array([1],np.int64),-63), (np.array([-(1 << 63)],np.int64),1)]:
        try:
            shift_rne(x,s)
        except OverflowError:
            pass
        else:
            raise AssertionError("Expected overflow refusal")
    assert shift_rne(np.array([0],np.int64),-100).item() == 0
    try:
        rq(np.array([(1 << 63)-1],np.int64), 2, 1)
    except OverflowError:
        pass
    else:
        raise AssertionError("RQ failed to detect product overflow")
    checks["shift_edges_and_overflow_refusal"] = True
    ns = rng.integers(-2000000,2000000,10000,dtype=np.int64)
    ms = rng.integers(1 << 30,(1 << 31)-1,10000,dtype=np.int64)
    ss = rng.integers(0,64,10000,dtype=np.int64)
    assert np.array_equal(rq(ns,ms,ss), [oracle(int(x)*int(m),1 << int(s)) for x,m,s in zip(ns,ms,ss)])
    checks["rq_random_arbitrary_precision"] = len(ns)
    params = dict(np.load(a.params / "parameters.npz"))
    model = Encoder(params)
    dense_checked = 0
    for i in range(12):
        for kind in ["q","k","v","o","fc1","fc2"]:
            key = f"l{i:02d}_{kind}"
            w = params[key+"_w"]
            x = rng.integers(-127,128,size=(1,3,w.shape[0]),dtype=np.int16).astype(np.int8)
            actual = model.dense(x,key,"check")
            for row in range(3):
                for o in [0,w.shape[1]//2,w.shape[1]-1]:
                    acc = sum(int(x[0,row,k])*int(w[k,o]) for k in range(w.shape[0]))+int(params[key+"_b"][o])
                    s,m = int(params[key+"_s"][o]),int(params[key+"_m"][o])
                    expect = oracle(acc*m,1 << s) if s >= 0 else acc*m*(1 << -s)
                    assert actual[0,row,o] == max(-127,min(127,expect))
                    dense_checked += 1
    checks["all_72_dense_scalar_outputs"] = dense_checked
    e = params["exp_lut"].astype(np.int64)
    assert e[0] == 1 << 20 and e[-1] == 0 and np.all(e[:-1] >= e[1:])
    # Decimal independent of the libm double exp used by offline export.
    with localcontext() as ctx:
        ctx.prec = 60
        for j in range(4096):
            v = (Decimal(2)**20*(-Decimal(j)/256).exp()).to_integral_value(rounding=ROUND_HALF_EVEN)
            assert e[j] == int(v)
    checks["exp_lut_decimal60_all_entries"] = 4096
    soft_checked = 0
    for i in range(12):
        scores = rng.integers(-1032256,1032257,size=(2,99,99),dtype=np.int32)
        scores[0,0,:] = 42
        scores[0,1,:] = -1032256
        scores[0,1,0] = 1032256
        key = f"l{i:02d}_score"
        actual = model.softmax(scores,key,"check")
        # Scalar index/requant and division oracle on every probability.
        m,s = int(params[key+"_m"]),int(params[key+"_s"])
        for batch in range(2):
            for row in range(99):
                maximum = int(scores[batch,row].max())
                indices = [min(4096,max(0,-oracle((int(v)-maximum)*m,1 << s))) for v in scores[batch,row]]
                ex = [int(e[j]) for j in indices]
                den = sum(ex)
                expect = [oracle(65535*v,den) for v in ex]
                assert np.array_equal(actual[batch,row],expect)
                soft_checked += 99
    checks["softmax_scalar_probability_codes"] = soft_checked
    ln_checked = 0
    cases = np.array([[0]*64,[37]*64,[-32767,32767]*32,[1]*63+[2],[-32767]*63+[32767]],np.int16)
    for i in range(12):
        for j in [1,2]:
            key = f"l{i:02d}_ln{j}"
            actual = model.layernorm(cases,key,"check")
            for row, x in enumerate(cases):
                sx = sum(map(int,x)); t = sum(int(v)**2 for v in x)
                h = ((64*t-sx*sx) << 16)+int(params[key+"_eps"])
                inv = oracle(1 << 40,math.isqrt(h))
                for ch in range(64):
                    norm = oracle((64*int(x[ch])-sx)*inv,1 << 18)
                    affine = oracle(norm*int(params[key+"_g"][ch]),1 << 14)+int(params[key+"_b"][ch])
                    expect = oracle(affine*int(params[key+"_m"]),1 << int(params[key+"_s"]))
                    assert actual[row,ch] == max(-127,min(127,expect))
                    ln_checked += 1
    checks["ln_scalar_boundary_codes_24_stages"] = ln_checked
    pm = json.loads((a.params / "manifest.json").read_text(encoding="utf-8"))
    # Independent scipy special function checks every legal GELU input.
    from scipy.special import erf
    gelu_checked = 0
    for i in range(12):
        sx = pm["decode_scales"][f"layer_{i:02d}/ffn_dense1_output"]
        sy = pm["decode_scales"][f"layer_{i:02d}/gelu_output"]
        x = np.arange(-127,128,dtype=np.float64)*sx
        expected = np.clip(np.rint(.5*x*(1+erf(x/np.sqrt(2)))/sy),-127,127).astype(np.int8)
        assert np.array_equal(expected,params[f"l{i:02d}_gelu_lut"][1:])
        gelu_checked += 255
    checks["gelu_scipy_all_legal_codes"] = gelu_checked
    residual_checked = 0
    for i in range(12):
        for j in [1,2]:
            key = f"l{i:02d}_r{j}"
            aa = rng.integers(-127,128,size=(3,99,64),dtype=np.int16).astype(np.int8)
            bb = rng.integers(-127,128,size=aa.shape,dtype=np.int16).astype(np.int8)
            aa[0,0,:] = 127
            bb[0,0,:] = 127
            aa[0,1,:] = -127
            bb[0,1,:] = -127
            actual = model.residual(aa,bb,key,"check")
            ma,mb,s = map(int,params[key+"_coeff"])
            expected = np.array([max(-32767,min(32767,oracle(int(x)*ma+int(y)*mb,1 << s)))
                                 for x,y in zip(aa.flat,bb.flat)],np.int16).reshape(aa.shape)
            assert np.array_equal(actual,expected)
            residual_checked += aa.size
    checks["residual_scalar_codes_24_stages"] = residual_checked
    # U16 probabilities must not be interpreted as signed16 or signed8.
    pv_checked = 0
    for i in range(10):
        pp = rng.integers(0,65536,size=(2,99,99),dtype=np.int32)
        vv = rng.integers(-127,128,size=(2,99,64),dtype=np.int32)
        pp[0,0,0] = 65535
        expected = np.matmul(pp.astype(np.int64),vv.astype(np.int64))
        actual = np.matmul(pp,vv)
        split = np.matmul(pp & 255,vv)+(np.matmul(pp >> 8,vv) << 8)
        assert np.array_equal(actual,expected) and np.array_equal(split,expected)
        for batch,row,ch in [(0,0,0),(0,98,63),(1,1,31)]:
            assert actual[batch,row,ch] == sum(int(pp[batch,row,k])*int(vv[batch,k,ch]) for k in range(99))
        pv_checked += actual.size
    checks["u16_s8_pv_and_two_pass_codes"] = pv_checked
    # Regress existing Q smoke using saved integer operands, not FP-output QDQ.
    path = ROOT / "testdata/ptq_integer_q_512/kwt1_q_projection_integer_smoke.npz"
    if path.exists():
        z = np.load(path)
        acc = np.matmul(z["q_input_int8"].astype(np.int32), z["q_kernel_int8"].astype(np.int32))
        assert np.array_equal(acc,z["accumulator_without_bias_int32"])
        acc = acc.astype(np.int64)+z["bias_int32"]
        assert np.array_equal(acc,z["accumulator_with_bias_int32"])
        out = np.clip(rq(acc,z["multiplier_q31"],z["right_shift"]),-127,127).astype(np.int8)
        assert np.array_equal(out,z["q_projection_int8"])
        checks["historical_q512_codes_zero_mismatch"] = out.size
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps({"passed": True,"checks":checks},indent=2),encoding="utf-8")
    print(json.dumps(checks,indent=2))


if __name__ == "__main__":
    main()
