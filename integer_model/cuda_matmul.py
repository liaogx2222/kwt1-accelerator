"""Optional exact signed INT8 x INT8 -> INT32 dense backend.

Uses torch._int_mm, never a float matmul. CPU reference remains the default.
Padding adds zeros to the row dimension only; every original row is retained.
"""
import numpy as np
import torch


class CudaInt8Matmul:
    def __init__(self):
        if not torch.cuda.is_available() or not hasattr(torch, "_int_mm"):
            raise RuntimeError("CUDA integer matrix multiplication is unavailable")
        self.weights = {}

    def __call__(self, x, w):
        if x.dtype != np.int8 or w.dtype != np.int8 or x.shape[-1] != w.shape[0]:
            raise TypeError("Expected compatible signed int8 operands")
        flat = np.ascontiguousarray(x.reshape(-1,x.shape[-1]))
        rows = len(flat)
        padded = ((rows+15)//16)*16
        if rows != padded:
            flat = np.pad(flat, ((0,padded-rows),(0,0)))
        if id(w) not in self.weights:
            self.weights[id(w)] = torch.from_numpy(np.ascontiguousarray(w)).to("cuda")
        with torch.no_grad():
            out = torch._int_mm(torch.from_numpy(flat).to("cuda"), self.weights[id(w)])
            if out.dtype != torch.int32:
                raise TypeError("CUDA backend did not return INT32")
            return out[:rows].cpu().numpy().reshape(x.shape[:-1]+(w.shape[1],))
