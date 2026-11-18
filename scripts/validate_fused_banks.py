"""Final-source value execution plus independent physical-bank replay."""
import argparse,hashlib,importlib.util,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from run_r1r2_low_memory import install
from validate_kwt1_r1 import boundary_oracle
from integer_model.fused_layer import FusedLayer
from validate_fused_schedule import fused_budget
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--quick',action='store_true');a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True);install()
    p=dict(np.load(ROOT/'testdata/integer_v1/params/parameters.npz'));meta=json.loads((ROOT/'testdata/integer_v1/params/manifest.json').read_text())
    x=np.load(ROOT/'testdata/integer_v1/fixture/encoder_input.npy',mmap_mode='r')[187]
    x=np.clip(np.rint(x.astype(np.float64)/meta['decode_scales']['encoder_input']),-127,127).astype(np.int8)
    expected=boundary_oracle(p,0,x);model=FusedLayer(p,a.output/'banks.gz',0,coefficient_cache=True,gelu_ports=8,pingpong=True)
    value=model.run(x,expected);np.save(a.output/'output.npy',value)
    path=ROOT.parent/'docs/architecture/review_r1r2_execution.py';spec=importlib.util.spec_from_file_location('review_banks',path);review=importlib.util.module_from_spec(spec);spec.loader.exec_module(review)
    independent=review.bank_audit(a.output/'banks.gz');core=model.b.cycle-model.local_load_cycles-model.handoff_cycles
    assert core==473871 and fused_budget(model.measured)['passed']
    result=dict(passed=True,core_cycles=core,register=fused_budget(model.measured),independent=independent,
                coefficient_read_bytes=model.coefficient_reads,source_hashes={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in
                 ['integer_model/fused_layer.py','integer_model/event_arithmetic.py','integer_model/executable_layer.py','integer_model/execution_banks.py','integer_model/pipeline_contract.py','integer_model/register_contract.py']})
    (a.output/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print('FUSED BANK REPLAY PASS',core,result['register'],flush=True)
if __name__=='__main__':main()
