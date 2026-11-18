"""Reconstruct deterministic calibration and fixture with a new source closure.

Never claims a newly captured identity list was saved by the historical run.
Original scripts/artifacts remain unchanged; comparisons decide the status.
"""
import csv
import hashlib
import importlib.metadata
import json
import os
import runpy
import sys
from pathlib import Path
os.environ.setdefault('CUDA_VISIBLE_DEVICES','0')
os.environ.setdefault('TF_FORCE_GPU_ALLOW_GROWTH','true')
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL','2')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(ROOT/'scripts')]
OUT = ROOT/'testdata/p3b/provenance'


def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1 << 20),b''):h.update(b)
    return h.hexdigest()


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'summary.json').exists():raise FileExistsError('Preserve provenance evidence')
    before={p.relative_to(ROOT).as_posix():sha(p) for folder in ['scripts','kws_streaming','integer_model'] for p in (ROOT/folder).rglob('*.py')}
    import numpy as np
    import tensorflow as tf
    tf.compat.v1.disable_eager_execution()
    from kws_streaming.train import model_train_eval
    from kws_streaming.data import input_data
    original=input_data.AudioProcessor.get_data
    identities={'training':[],'validation':[]}
    requested=[]
    def captured(self,*args,**kwargs):
        mode=kwargs.get('mode',args[6] if len(args)>6 else None)
        if mode not in identities:raise RuntimeError('No testing batches permitted')
        result=original(self,*args,**kwargs)
        how_many,offset,flags=args[:3]
        assert flags.pick_deterministically
        audio,labels=result
        requested.append({'partition':mode,'offset':offset,'count':len(audio)})
        for j,(wave,label) in enumerate(zip(audio,labels)):
            item=self.data_index[mode][(offset+j)%len(self.data_index[mode])]
            path=Path(item['file']);silence=item['label']==input_data.SILENCE_LABEL
            identities[mode].append({'offset':offset+j,'label_id':int(label),'source_label':item['label'],
                'waveform':'zeros:16000' if silence else path.relative_to(ROOT/'data2').as_posix(),
                'wav_sha256':None if silence else sha(path),
                'loader_output_dtype':str(wave.dtype),'loader_output_sha256':hashlib.sha256(wave.tobytes()).hexdigest()})
        return result
    input_data.AudioProcessor.get_data=captured
    # Historical calibration did not disable TF32; explicitly record current default.
    calibration_tf32=tf.config.experimental.tensor_float_32_execution_enabled()
    sys.argv=[str(ROOT/'scripts/calibrate_kwt1_ptq.py'),'--batch-size','16','--max-samples','2048','--output-dir',str(OUT/'calibration_replay')]
    runpy.run_path(sys.argv[0],run_name='__main__')
    (OUT/'training_identities_reconstructed.json').write_text(json.dumps(identities['training'],indent=2),encoding='utf-8')
    comparison={}
    for filename in ['kwt1_ptq_activation_scale_candidates.csv','kwt1_ptq_training_activation_stats.csv','kwt1_ptq_training_channel_stats.csv','kwt1_ptq_training_predictions.csv','kwt1_ptq_weight_stats.csv']:
        old=ROOT/'testdata/ptq_calibration'/filename;new=OUT/'calibration_replay'/filename
        aa=list(csv.DictReader(old.open(encoding='utf-8-sig',newline='')))
        bb=list(csv.DictReader(new.open(encoding='utf-8-sig',newline='')))
        unequal=[]
        if len(aa)==len(bb):
            for i,(a,b) in enumerate(zip(aa,bb)):
                for key in a:
                    if a[key]!=b.get(key):
                        if len(unequal)<30:unequal.append({'row':i,'field':key,'old':a[key],'replay':b.get(key)})
        else:unequal=[{'old_rows':len(aa),'replay_rows':len(bb)}]
        comparison[filename]={'old_sha256':sha(old),'replay_sha256':sha(new),'byte_identical':sha(old)==sha(new),'table_equal':aa==bb,'first_mismatches':unequal}
    (OUT/'calibration_comparison.json').write_text(json.dumps(comparison,indent=2),encoding='utf-8')
    tf.keras.backend.clear_session()
    sys.argv=[str(ROOT/'scripts/export_kwt1_integer_fixture.py'),'--output',str(OUT/'fixture_replay')]
    runpy.run_path(sys.argv[0],run_name='__main__')
    fixture_compare={}
    for name in ['encoder_input.npy','fp_encoder_output.npy','fp_logits.npy','labels.npy','raw_parameters.npz']:
        old=ROOT/'testdata/integer_v1/fixture'/name;new=OUT/'fixture_replay'/name
        row={'old_sha256':sha(old),'replay_sha256':sha(new),'byte_identical':sha(old)==sha(new)}
        if name.endswith('.npy'):
            a,b=np.load(old,mmap_mode='r'),np.load(new,mmap_mode='r')
            row.update({'elements_different':int(np.count_nonzero(a!=b)),'max_abs_difference':float(np.max(np.abs(a.astype(np.float64)-b.astype(np.float64))))})
        else:
            a,b=np.load(old),np.load(new)
            row['all_arrays_equal']=a.files==b.files and all(np.array_equal(a[k],b[k]) for k in a.files)
        fixture_compare[name]=row
    (OUT/'validation_loader_identities_reconstructed.json').write_text(json.dumps(identities['validation'],indent=2),encoding='utf-8')
    changed={k for k,v in before.items() if sha(ROOT/k)!=v}
    assert not changed,changed
    modules={}
    for name,module in list(sys.modules.items()):
        path=getattr(module,'__file__',None)
        if path:
            p=Path(path).resolve()
            try:rel=p.relative_to(ROOT)
            except ValueError:continue
            if p.is_file():modules[name]={'path':rel.as_posix(),'sha256':sha(p)}
    packages={}
    for dist in importlib.metadata.distributions():
        packages[dist.metadata['Name']]=dist.version
    result={'scope':'New deterministic reconstruction, not a historical identity attestation',
        'old_artifacts_modified':False,'python':sys.version,'executable_sha256':sha(sys.executable),
        'tensorflow':tf.__version__,'calibration_tf32':calibration_tf32,'training_identities_captured':len(identities['training']),
        'training_identity_reconstruction_matches_all_saved_tables':all(v['table_equal'] for v in comparison.values()),
        'validation_fixture_comparison':fixture_compare,'testing_batches_requested':0,
        'requests':requested,'local_python_source_superset_sha256':before,'imported_project_modules':modules,
        'installed_distributions':packages,
        'build_info':tf.sysconfig.get_build_info(),
        'wrapper_sha256':sha(__file__)}
    (OUT/'summary.json').write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
    print('Provenance complete, calibration tables exact:',result['training_identity_reconstruction_matches_all_saved_tables'],flush=True)


if __name__=='__main__':main()
