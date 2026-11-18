"""Isolated S16 first input / S8 internal candidate, same frozen weights.

Extends the evidence from S8-only scale trials. Generated source derivatives
are archived; no original runtime/export/RTL or v1 parameters are changed.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from local_tools import ROOT,sha


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args();out=args.output.resolve()
    assert not out.exists(),'New S16-input candidate directory';out.mkdir(parents=True)
    base=ROOT/'scripts/run_accuracy_point1_candidates.py'
    runtime=ROOT/'integer_model/runtime.py'
    bindings={p.relative_to(ROOT).as_posix():sha(p) for p in [Path(__file__),base,runtime,ROOT/'integer_model/export.py',ROOT/'integer_model/cuda_matmul.py']}
    text=runtime.read_text()
    assert text.count('x.dtype != np.int8 or x.ndim')==1
    assert text.count('check_range(x, -127, 127, "encoder input")')==1
    text=text.replace('x.dtype != np.int8 or x.ndim','x.dtype != np.int16 or x.ndim')
    text=text.replace('check_range(x, -127, 127, "encoder input")','check_range(x, -32767, 32767, "encoder input")')
    text=text.replace('Encoder requires int8 [batch,99,64]','Candidate requires int16 first input [batch,99,64]')
    (out/'runtime_input16.py').write_text(text)
    cuda='''import numpy as np
from integer_model.cuda_matmul import CudaInt8Matmul as Narrow
class CudaInt8Matmul:
 def __init__(self):self.narrow=Narrow()
 def __call__(self,x,w):
  if x.dtype==np.int8:return self.narrow(x,w)
  if x.dtype!=np.int16:raise TypeError("Unsupported candidate input")
  low=((x.astype(np.int32)&255)-128).astype(np.int8)
  high=(x.astype(np.int32)>>8).astype(np.int8)
  value=self.narrow(low,w).astype(np.int64)+(self.narrow(high,w).astype(np.int64)<<8)+128*w.astype(np.int64).sum(axis=0)
  if np.any(value<-(1<<31)) or np.any(value>(1<<31)-1):raise OverflowError("S16xS8 accumulator")
  return value.astype(np.int32)
'''
    (out/'input16_cuda.py').write_text(cuda)
    source=base.read_text()
    source=re.sub(r'RECIPES=\{.*?\}\n',"RECIPES={'input16_only':'Training max_abs S16 first input; all internal activations retain v1 p999 S8.'}\n",source,count=1,flags=re.S)
    source=source.replace("args.recipe=='input_max'","args.recipe=='input16_only'")
    source=source.replace('from integer_model.runtime import Encoder','from runtime_input16 import Encoder')
    source=source.replace('from integer_model.cuda_matmul import CudaInt8Matmul','from input16_cuda import CudaInt8Matmul')
    anchor="        source=row['threshold_source']\n";assert source.count(anchor)==1
    source=source.replace(anchor,anchor+'''        if tensor=='encoder_input':
            value=float(row['clip_threshold'])/32767
            row.update(format='INT16',qmin='-32767',qmax='32767',scale=repr(value),step=repr(value))
''')
    anchor="    exporter=out/'export_candidate_executed.py';exporter.write_text(export_source)"
    assert source.count(anchor)==1
    changes='''    export_source=export_source.replace('r["format"] == "INT8"','r["format"] in ("INT8","INT16")')
    export_source=export_source.replace('bound = w.shape[0]*127**2 + np.abs(bq)','input_qmax = 32767 if key in ("l00_q","l00_k","l00_v") else 127\\n        bound = w.shape[0]*input_qmax*127 + np.abs(bq)')
    export_source=export_source.replace('sr = 127*(sx+sb)/32767','sr = ((32767 if key=="l00_r1" else 127)*sx+127*sb)/32767')
    export_source=export_source.replace('INTEGER_V1_FORMULAS_SCALE_CANDIDATE','INTEGER_S16_FIRST_INPUT_S8_INTERNAL_CANDIDATE')
'''
    source=source.replace(anchor,changes+anchor)
    anchor=',-127,127).astype(np.int8)';assert source.count(anchor)==1
    source=source.replace(anchor,',-32767,32767).astype(np.int16)')
    evaluator=out/'evaluate_input16.py';evaluator.write_text(source)
    recipe=dict(preregistered_before_result=True,first_input_bits=16,internal_activations_bits=8,
        first_input_scale='frozen training max_abs / 32767',other_scales='frozen training p999 / 127',
        weights_changed=False,training=False,official_test_used=False,
        motivation='S8 input-max improved 4338 -> 4341 but missed 4344 target; increase only the first input precision as isolated next factor',
        CUDA='exact signed16 decomposition into two signed8 integer matrix products and a weight-sum correction',
        production_RTL_compatible=False,first_layer_residual_scale_bound_generalized=True,
        extra_byte_MAC_work_if_first_QKV_need_two_passes=3*99*64*64)
    (out/'recipe.json').write_text(json.dumps(recipe,indent=2));(out/'source_bindings.json').write_text(json.dumps(bindings,indent=2))
    environment=dict(os.environ);environment['PYTHONPATH']=str(ROOT/'scripts')+os.pathsep+str(ROOT)
    command=[sys.executable,str(evaluator),'--recipe','input16_only','--output',str(out/'run')]
    (out/'command.json').write_text(json.dumps(command,indent=2))
    with (out/'execution.log').open('w') as log:
        p=subprocess.run(command,cwd=ROOT,env=environment,stdout=log,stderr=subprocess.STDOUT)
    assert p.returncode==0,(out/'execution.log').read_text()[-3000:]
    measured=json.loads((out/'run/metrics.json').read_text());measured.update(first_input_bits=16,internal_activations_bits=8,
        production_RTL_compatible=False,existing_v1_RTL_pass_inherited=False)
    (out/'metrics.json').write_text(json.dumps(measured,indent=2))
    for path,digest in bindings.items():assert sha(ROOT/path)==digest,path
    (out/'manifest.json').write_text(json.dumps({p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file() and p!=out/'manifest.json'},indent=2))
    print(json.dumps(measured,indent=2))


if __name__=='__main__':main()
