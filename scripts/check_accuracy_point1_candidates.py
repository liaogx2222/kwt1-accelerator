"""Independent full-logit/parameter/CPU audit of preregistered S8 candidates."""
import argparse
import csv
import json
import math
import sys
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
sys.path.insert(0,str(ROOT))
from integer_model.runtime import Encoder


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    base,out=args.input.resolve(),args.output.resolve();assert not out.exists(),'New audit output'
    prereg=json.loads((base/'preregistered.json').read_text());recipes=prereg['recipes_before_evaluation']
    fixture=ROOT/'testdata/integer_v1/fixture';v1=ROOT/'testdata/integer_v1/params';old=ROOT/'testdata/integer_v1/validation'
    labels=np.load(fixture/'labels.npy');fp=np.load(fixture/'fp_logits.npy').argmax(axis=1);assert np.count_nonzero(fp==labels)==4348
    old_pred=np.load(old/'logits.npy').argmax(axis=1);assert np.count_nonzero(old_pred==labels)==4338
    raw=np.load(fixture/'raw_parameters.npz');baseline=dict(np.load(v1/'parameters.npz'));oldmeta=json.loads((v1/'manifest.json').read_text())
    oldout=np.load(old/'encoder_output_int8.npy',mmap_mode='r');replayed=[]
    for i in range(0,4445,32):
        h=(oldout[i:i+32,0,:].astype(np.float32)*np.float32(oldmeta['final_scale']))@raw['head_w']+raw['head_b']
        replayed.extend(h.argmax(axis=1).tolist())
    assert np.array_equal(replayed,old_pred),'Head batching changed baseline predictions'
    inputs=np.load(fixture/'encoder_input.npy',mmap_mode='r')
    samples=[int(np.flatnonzero(labels==c)[0]) for c in range(12)]
    comparisons={};hashes=cpu_codes=0;bindings={}
    with (ROOT/'testdata/ptq_calibration/kwt1_ptq_activation_scale_candidates.csv').open(encoding='utf-8-sig',newline='') as f:
        training={}
        for row in csv.DictReader(f):
            if row['format']=='INT8':training.setdefault(row['tensor'],{})[row['threshold_source']]=float(row['scale'])
    for name in recipes:
        folder=base/name
        for path,digest in json.loads((folder/'manifest.json').read_text()).items():
            assert sha(folder/path)==digest,(name,path);hashes+=1
        for path,digest in json.loads((folder/'source_bindings.json').read_text()).items():
            assert sha(ROOT/path)==digest,path;bindings[path]=digest
        measured=json.loads((folder/'metrics.json').read_text());assert measured['completed'] and measured['samples']==4445
        pm=json.loads((folder/'params/manifest.json').read_text());p=dict(np.load(folder/'params/parameters.npz'))
        assert sha(folder/'params/parameters.npz')==pm['parameters_sha256']==measured['candidate_parameters_sha256']
        for key,desc in pm['array_schema'].items():
            assert sha_bytes(p[key].tobytes())==desc['sha256'] and p[key].shape==tuple(desc['shape']) and str(p[key].dtype)==desc['dtype']
        selected=json.loads((folder/'recipe.json').read_text())['selected_scales']
        for tensor,row in selected.items():
            options=training[tensor]
            maximum=name=='max_all' or (name=='input_max' and tensor=='encoder_input') or (name=='context_max' and tensor.endswith('/attention_context'))
            expected=math.sqrt(options['abs_p999_est']*options['max_abs']) if name=='mid_all' else options['max_abs' if maximum else 'abs_p999_est']
            assert row['scale']==expected,(name,tensor)
            # These diagnostic tensors are intentionally re-derived by the
            # exporter, not assigned the unused generic calibration row.
            suffix=tensor.rsplit('/',1)[-1]
            if suffix in ['residual1_sum','residual2_sum','attention_score_raw','attention_softmax']:
                layer=int(tensor[6:8]);prefix=f'layer_{layer:02d}/';s=lambda key:selected[prefix+key]['scale']
                if suffix=='residual1_sum':
                    sx=selected['encoder_input']['scale'] if layer==0 else selected[f'layer_{layer-1:02d}/layernorm2_output']['scale']
                    effective=127*(sx+s('attention_output_projection'))/32767
                elif suffix=='residual2_sum':effective=127*(s('layernorm1_output')+s('ffn_dense2_output'))/32767
                elif suffix=='attention_score_raw':effective=s('q_projection')*s('k_projection')
                else:effective=1/65535
                assert pm['decode_scales'][tensor]==effective,(name,tensor)
            else:assert pm['decode_scales'][tensor]==expected,(name,tensor)
        assert all(np.array_equal(p[key],value) for key,value in baseline.items() if key.endswith('_w'))
        logits=np.load(folder/'logits.npy');assert logits.shape==(4445,12) and np.isfinite(logits).all()
        pred=logits.argmax(axis=1);assert np.array_equal(pred,np.load(folder/'predictions.npy'))
        correct=int(np.count_nonzero(pred==labels));assert measured['integer_correct']==correct
        outputs=np.load(folder/'encoder_output_int8.npy',mmap_mode='r')
        x=np.clip(np.rint(inputs[samples].astype(np.float64)/pm['decode_scales']['encoder_input']),-127,127).astype(np.int8)
        reference=Encoder(p)(x);assert np.array_equal(reference,outputs[samples]),name;cpu_codes+=reference.size
        reconstructed=(outputs[:,0,:].astype(np.float32)*np.float32(pm['final_scale']))@raw['head_w']+raw['head_b']
        assert np.array_equal(reconstructed.argmax(axis=1),pred),'Saved output/head mismatch'
        comparisons[name]=dict(correct=correct,accuracy_drop_pp=(4348-correct)*100/4445,target_met=correct>=4344,
            recovered_vs_v1=int(np.count_nonzero((old_pred!=labels)&(pred==labels))),
            lost_vs_v1=int(np.count_nonzero((old_pred==labels)&(pred!=labels))),
            FP_correct_candidate_wrong=int(np.count_nonzero((fp==labels)&(pred!=labels))),
            FP_wrong_candidate_correct=int(np.count_nonzero((fp!=labels)&(pred==labels))),
            candidate_parameters_sha256=pm['parameters_sha256'],requant_shift_range=measured['requant_shift_range'],
            residual_shift_values=measured['residual_shift_values'])
        bindings[(folder/'params/manifest.json').relative_to(ROOT).as_posix()]=sha(folder/'params/manifest.json')
        bindings[(folder/'manifest.json').relative_to(ROOT).as_posix()]=sha(folder/'manifest.json')
    eligible=[name for name in recipes if comparisons[name]['target_met']]
    report=dict(audit_passed=True,accuracy_target_met=bool(eligible),candidates=comparisons,
        preferred_candidate=eligible[0] if eligible else None,preference='preregistered order, smallest scale-change footprint first',
        required_correct=4344,baseline_correct=4338,FP_correct=4348,samples=4445,
        independently_CPU_recomputed_output_codes=cpu_codes,CPU_output_mismatches=0,
        baseline_head_batch32_predictions_unchanged=True,artifact_hashes_checked=hashes,
        weights_changed=False,training_performed=False,test_set_used=False,official_600_evaluated=False,
        LN_E01_automatically_inherited=False,new_profile_RTL_validated=False,
        scope='development Validation candidate assessment, not a new production numeric freeze or official accuracy result')
    out.mkdir(parents=True);(out/'verification.json').write_text(json.dumps(report,indent=2))
    bindings[Path(__file__).relative_to(ROOT).as_posix()]=sha(Path(__file__));bindings[(base/'preregistered.json').relative_to(ROOT).as_posix()]=sha(base/'preregistered.json')
    (out/'source_bindings.json').write_text(json.dumps(bindings,indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2));print(json.dumps(report,indent=2))


def sha_bytes(value):
    import hashlib
    return hashlib.sha256(value).hexdigest()


if __name__=='__main__':main()
