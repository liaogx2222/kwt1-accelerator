"""Integer input -> integer output. No floating point operators in this module.

NumPy int32 MAC is exact under the exported range proofs. Int64 is used for
requantization, residual alignment and LN. math.isqrt is integer arithmetic.
The optional observer receives integer tensors only; decoding is external.
"""
import math
import numpy as np

I64 = (1 << 63) - 1
I32 = (1 << 31) - 1


def integer_array(x):
    x = np.asarray(x)
    if x.dtype.kind not in "iu" or (x.dtype.kind == "u" and np.any(x > I64)):
        raise TypeError("Expected integers representable as signed64")
    return x.astype(np.int64, copy=False)


def rne(n, d):
    """Signed integer division, nearest with ties to even; no overflowing 2*r."""
    n, d = integer_array(n), integer_array(d)
    if np.any(d <= 0) or np.any(n == -(1 << 63)):
        raise OverflowError("RNE denominator/input outside supported signed64 domain")
    mag = np.abs(n)
    q, r = mag // d, mag % d
    inc = (r > d-r) | ((r == d-r) & ((q & 1) != 0))
    out = q + inc.astype(np.int64)
    return np.where(n < 0, -out, out)


def shift_rne(n, shift):
    n = integer_array(n)
    shift = int(shift)
    if np.any(n == -(1 << 63)):
        raise OverflowError("INT64_MIN is outside magnitude RNE domain")
    if shift < 0:
        if -shift >= 63:
            if np.any(n):
                raise OverflowError("left shift outside signed64")
            return n.copy()
        if np.any(np.abs(n) > (I64 >> -shift)):
            raise OverflowError("left shift would overflow signed64")
        return n << -shift
    if shift == 0:
        return n.copy()
    if shift >= 64:
        return np.zeros_like(n)
    if shift == 63:
        return np.where(n < 0, -1, 1) * (np.abs(n) > (1 << 62))
    return rne(n, 1 << shift)


def rq(n, multiplier, shifts):
    n, m = integer_array(n), integer_array(multiplier)
    if np.any(m <= 0) or np.any(m > I32):
        raise ValueError("Multiplier must be positive signed32")
    if np.any(n == -(1 << 63)) or np.any(np.abs(n) > I64 // m):
        raise OverflowError("RQ product exceeds signed64")
    product = n * m
    shifts = integer_array(shifts)
    if shifts.ndim == 0 or shifts.size == 1:
        return shift_rne(product, shifts.item())
    if product.shape[-1] != shifts.size:
        raise ValueError("Per-channel shift shape mismatch")
    out = np.empty_like(product)
    for s in np.unique(shifts):
        mask = shifts == s
        out[..., mask] = shift_rne(product[..., mask], s)
    return out


def check_range(x, low, high, name):
    if np.any(x < low) or np.any(x > high):
        raise OverflowError(name + " outside declared range")


def sat(x, bits):
    qmax = (1 << (bits-1))-1
    return np.clip(x, -qmax, qmax).astype(np.int8 if bits == 8 else np.int16)


class Encoder:
    def __init__(self, params, observer=None, dense_matmul=None):
        self.p = params
        self.observer = observer
        self.dense_matmul = dense_matmul

    def emit(self, name, x, bits=None):
        if bits is None:
            if self.observer:
                self.observer(name, x, 0)
            return x
        qmax = (1 << (bits-1))-1
        clipped = int(np.count_nonzero((x < -qmax) | (x > qmax)))
        out = sat(x, bits)
        if self.observer:
            self.observer(name, out, clipped)
        return out

    def dense(self, x, key, trace_name):
        w, b = self.p[key+"_w"], self.p[key+"_b"]
        # The exporter proves K*127**2+abs(b) < 2**31 for every channel.
        acc = (np.matmul(x.astype(np.int32), w.astype(np.int32)) if self.dense_matmul is None
               else self.dense_matmul(x, w))
        if acc.dtype != np.int32:
            raise TypeError("Dense backend must return int32 accumulators")
        acc = acc.astype(np.int64) + b
        check_range(acc, -I32-1, I32, key+" accumulator")
        self.emit(trace_name+"/accumulator", acc)
        return self.emit(trace_name, rq(acc, self.p[key+"_m"], self.p[key+"_s"]), 8)

    def residual(self, a, b, key, trace_name):
        coeff = self.p[key+"_coeff"]
        tmp = a.astype(np.int64)*coeff[0] + b.astype(np.int64)*coeff[1]
        return self.emit(trace_name, shift_rne(tmp, coeff[2]), 16)

    def layernorm(self, x, key, trace_name):
        x64 = x.astype(np.int64)
        check_range(x64, -32767, 32767, "LN input")
        sums = x64.sum(axis=-1, keepdims=True, dtype=np.int64)
        t = (x64*x64).sum(axis=-1, keepdims=True, dtype=np.int64)
        variance = 64*t - sums*sums
        check_range(variance, 0, 4096*32767**2, "LN variance")
        # All frozen E_eps values and worst-case H have signed64 proofs.
        h = (variance << 16) + self.p[key+"_eps"].item()
        d = np.fromiter((math.isqrt(int(v)) for v in h.flat), np.int64, count=h.size).reshape(h.shape)
        reciprocal = rne(1 << 40, d)
        centered = 64*x64 - sums
        normalized = shift_rne(centered*reciprocal, 18)
        affine = shift_rne(normalized*self.p[key+"_g"], 14) + self.p[key+"_b"]
        check_range(affine, -I32-1, I32, "LN affine")
        self.emit(trace_name+"/variance", variance)
        self.emit(trace_name+"/normalized_q14", normalized)
        return self.emit(trace_name, rq(affine, self.p[key+"_m"], self.p[key+"_s"]), 8)

    def softmax(self, scores, key, name):
        diff = scores.astype(np.int64)-scores.max(axis=-1, keepdims=True)
        u = np.clip(rq(diff, self.p[key+"_m"], self.p[key+"_s"]), -4096, 0)
        e = self.p["exp_lut"][(-u).astype(np.int32)].astype(np.int64)
        denominator = e.sum(axis=-1, keepdims=True, dtype=np.int64)
        check_range(denominator, 1 << 20, 99*(1 << 20), "Softmax denominator")
        reciprocal = ((1 << 47)+denominator-1)//denominator
        numerator = 65535*e
        quotient = (numerator*reciprocal) >> 47
        quotient -= (quotient*denominator > numerator).astype(np.int64)
        rem = numerator - quotient*denominator
        quotient += ((rem > denominator-rem) | ((rem == denominator-rem) & ((quotient & 1) != 0)))
        check_range(quotient, 0, 65535, "Softmax probability")
        check_range(quotient.sum(axis=-1), 65486, 65584, "Softmax row sum")
        self.emit(name+"/index_q8", -u)
        return self.emit(name, quotient.astype(np.uint16))

    def __call__(self, x):
        if x.dtype != np.int8 or x.ndim != 3 or x.shape[1:] != (99, 64):
            raise ValueError("Encoder requires int8 [batch,99,64]")
        check_range(x, -127, 127, "encoder input")
        self.emit("encoder_input", x)
        for i in range(12):
            key, name = f"l{i:02d}", f"layer_{i:02d}"
            q, k, v = [self.dense(x, key+"_"+short, name+"/"+long+"_projection")
                       for short, long in [("q", "q"), ("k", "k"), ("v", "v")]]
            score = np.matmul(q.astype(np.int32), np.swapaxes(k.astype(np.int32), -1, -2))
            self.emit(name+"/attention_score_raw", score)
            p = self.softmax(score, key+"_score", name+"/attention_softmax")
            context_acc = np.matmul(p.astype(np.int32), v.astype(np.int32))
            self.emit(name+"/context_accumulator", context_acc)
            context = self.emit(name+"/attention_context", rq(context_acc, self.p[key+"_ctx_m"], self.p[key+"_ctx_s"]), 8)
            o = self.dense(context, key+"_o", name+"/attention_output_projection")
            r1 = self.residual(x, o, key+"_r1", name+"/residual1_sum")
            norm = self.layernorm(r1, key+"_ln1", name+"/layernorm1_output")
            fc1 = self.dense(norm, key+"_fc1", name+"/ffn_dense1_output")
            gelu = self.emit(name+"/gelu_output", self.p[key+"_gelu_lut"][fc1.astype(np.int16)+128])
            fc2 = self.dense(gelu, key+"_fc2", name+"/ffn_dense2_output")
            r2 = self.residual(norm, fc2, key+"_r2", name+"/residual2_sum")
            x = self.layernorm(r2, key+"_ln2", name+"/layernorm2_output")
        return x
