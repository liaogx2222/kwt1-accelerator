"""Independent CPU forward graph audit for S16 first input / S8 internals."""
import argparse
import json
import math
import sys
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
sys.path.insert(0,str(ROOT))
from integer_model.runtime import Encoder,rq


def cpu_forward(x,p):
    model=Encoder(p)
    # Explicit graph uses the unchanged integer operator implementations. It
    # bypasses only original Encoder.__call__'s S8 input validation.
    for i in range(12):
        key,name=f'l{i:02d}',f'layer_{i:02d}'
        q,k,v=[model.dense(x,key+'_'+short,name+'/'+short+'_projection') for short in ['q','k','v']]
        score=q.astype(np.int32)@np.swapaxes(k.astype(np.int32),-1,-2)
        probability=model.softmax(score,key+'_score',name+'/attention_softmax')
        context=rq(probability.astype(np.int32)@v.astype(np.int32),p[key+'_ctx_m'],p[key+'_ctx_s'])
        context=np.clip(context,-127,127).astype(np.int8)
        projected=model.dense(context,key+'_o',name+'/attention_output_projection')
        residual=model.residual(x,projected,key+'_r1',name+'/residual1_sum')
        norm=model.layernorm(residual,key+'_ln1',name+'/layernorm1_output')
        hidden=model.dense(norm,key+'_fc1',name+'/ffn_dense1_output')
        gelu=p[key+'_gelu_lut'][hidden.astype(np.int16)+128]
        second=model.dense(gelu,key+'_fc2',name+'/ffn_dense2_output')
        residual=model.residual(norm,second,key+'_r2',name+'/residual2_sum')
        x=model.layernorm(residual,key+'_ln2',name+'/layernorm2_output')
    return x


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    base,out=args.input.resolve(),args.output.resolve();assert not out.exists(),'New audit output'
    for name,digest in json.loads((base/'manifest.json').read_text()).items():assert sha(base/name)==digest,name
    for name,digest in json.loads((base/'source_bindings.json').read_text()).items():assert sha(ROOT/name)==digest,name
    folder=base/'run';metrics=json.loads((base/'metrics.json').read_text());pm=json.loads((folder/'params/manifest.json').read_text())
    p=dict(np.load(folder/'params/parameters.npz'));baseline=dict(np.load(ROOT/'testdata/integer_v1/params/parameters.npz'))
    assert sha(folder/'params/parameters.npz')==pm['parameters_sha256']==metrics['candidate_parameters_sha256']
    for key,desc in pm['array_schema'].items():
        import hashlib
        assert hashlib.sha256(p[key].tobytes()).hexdigest()==desc['sha256']
    assert all(np.array_equal(value,p[key]) for key,value in baseline.items() if key.endswith('_w'))
    fixture=ROOT/'testdata/integer_v1/fixture';labels=np.load(fixture/'labels.npy');inputs=np.load(fixture/'encoder_input.npy',mmap_mode='r')
    fp=np.load(fixture/'fp_logits.npy').argmax(axis=1);logits=np.load(folder/'logits.npy');assert np.isfinite(logits).all()
    predictions=logits.argmax(axis=1);assert np.count_nonzero(fp==labels)==4348
    correct=int(np.count_nonzero(predictions==labels));assert correct==metrics['integer_correct']
    raw=np.load(fixture/'raw_parameters.npz');outputs=np.load(folder/'encoder_output_int8.npy',mmap_mode='r')
    head=(outputs[:,0,:].astype(np.float32)*np.float32(pm['final_scale']))@raw['head_w']+raw['head_b']
    assert np.array_equal(head.argmax(axis=1),predictions)
    indices=[int(np.flatnonzero(labels==label)[0]) for label in range(12)]
    x=np.clip(np.rint(inputs[indices].astype(np.float64)/pm['decode_scales']['encoder_input']),-32767,32767).astype(np.int16)
    result=cpu_forward(x,p);assert np.array_equal(result,outputs[indices])
    sx=pm['decode_scales']['encoder_input'];sb=pm['decode_scales']['layer_00/attention_output_projection']
    assert pm['decode_scales']['layer_00/residual1_sum']==(32767*sx+127*sb)/32767
    for key in ['l00_q','l00_k','l00_v']:
        proof=pm['proofs'][key];assert proof['accumulator_abs_bound']>=64*32767*127 and proof['accumulator_abs_bound']<(1<<31)
    report=dict(audit_passed=True,recipe='S16 first input / S8 internals',samples=4445,FP_correct=4348,integer_correct=correct,
        accuracy_percent=100*correct/4445,accuracy_drop_pp=100*(4348-correct)/4445,
        target_drop_pp=0.1,required_correct=4344,accuracy_target_met=correct>=4344,
        independent_CPU_graph_output_codes=int(result.size),CPU_mismatches=0,
        all_72_weight_arrays_unchanged=True,first_input_accumulator_bounds_proved=True,
        first_residual_full_S16_input_bound_checked=True,first_input_bytes=12672,output_bytes=6336,
        requant_shift_range=metrics['requant_shift_range'],residual_shift_values=metrics['residual_shift_values'],
        candidate_parameters_sha256=pm['parameters_sha256'],LN_E01_inherited=False,
        old_v1_RTL_pass_inherited=False,new_RTL_validated=False,official_600_evaluated=False,
        scope='integer software candidate audit; requires new input/packet/residual/bank/RTL and LN quality acceptance')
    out.mkdir(parents=True);(out/'verification.json').write_text(json.dumps(report,indent=2))
    sources=[Path(__file__),ROOT/'integer_model/runtime.py',base/'manifest.json',folder/'params/manifest.json',base/'metrics.json']
    (out/'source_bindings.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p) for p in sources},indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
