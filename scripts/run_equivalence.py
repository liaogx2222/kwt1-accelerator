"""Run pinned YoWASP with an explicitly larger host/WASM recursion budget.

No package or circuit modification. ezSAT recursion exceeded the default 2 MiB
WASM stack on the large equivalence graph; the worker owns 128 MiB OS stack.
"""
import os,sys,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/rtl_v2_python'))
os.environ['YOWASP_CACHE_DIR']=str(ROOT/'tools/yowasp-cache')
import wasmtime
from wasmtime import _bindings as ffi
original_config=wasmtime.Config
class EquivalenceConfig(original_config):
    def __init__(self):
        super().__init__()
        ffi.wasmtime_config_async_stack_size_set(self.ptr(),128*1024*1024)
        self.max_wasm_stack=64*1024*1024
wasmtime.Config=EquivalenceConfig
threading.stack_size(128*1024*1024)
from yowasp_yosys import run_yosys
sys.exit(run_yosys(sys.argv[1:]))
