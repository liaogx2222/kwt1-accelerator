"""Only enable exact fast modes in the frozen streaming core."""
from pathlib import Path
import hashlib
import subprocess
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    p=ROOT/'rtl/iter_fast/kwt_layer_banked.sv';assert not p.exists()
    data=subprocess.check_output(['git','show','8901e14ba4028d0711f25e0cfa598c6abe13835b:rtl/softmax_stream/kwt_layer_banked.sv'],cwd=ROOT)
    assert hashlib.sha256(data).hexdigest()=='3fd343ca3bba46b28043cb6ea4338871b323a56f12908fea515b764883a3b3a4'
    old=b'.SHORT_CONST_DIV(1),.RADIX4_CONST(1)';assert data.count(old)==1
    p.write_bytes(data.replace(old,old+b',.RADIX16_CONST(1),.DOUBLE_SQRT(1)'));print('ENABLED actual iterative modes')
