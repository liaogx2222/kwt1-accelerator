"""Fail closed: all four deliveries plus independent oracle/audit are mandatory."""
import argparse,hashlib,json,shutil,sys,re
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from validate_kwt1_r1 import boundary_oracle,edge_input
from integer_model.runtime import Encoder

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def read(path):return json.loads(path.read_text())
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--quick',action='store_true');a=ap.parse_args();out=a.output.resolve()
    required=['reset.json','io_final/system_io.json','pipeline_final/summary.json','control_final/summary.json','layer_final/summary.json','fused/summary.json','fused_audit.json','banks_final/summary.json','cold_fixed/cold_tasks.json','cold_fused/cold_tasks.json']
    result={'passed':False,'required':required}
    try:
        docs={name:read(out/name) for name in required};assert all(d['passed'] for d in docs.values())
        schedule=docs['fused/summary.json'];assert not schedule['quick'] and len(schedule['layers'])==24
        assert {(r['layer'],r['mode']) for r in schedule['layers']}=={(i,m) for i in range(12) for m in ['normal','boundary']}
        from assess_next_registers import assess
        registers=assess(out);assert registers['fused_passed']
        from normalize_next_io import normalize
        direction=normalize(out);assert direction['passed']
        p=dict(np.load(ROOT/'testdata/integer_v1/params/parameters.npz'));meta=read(ROOT/'testdata/integer_v1/params/manifest.json')
        fixture=np.load(ROOT/'testdata/integer_v1/fixture/encoder_input.npy',mmap_mode='r');saved=np.load(ROOT/'testdata/integer_v1/validation/encoder_output_int8.npy',mmap_mode='r')
        x=np.clip(np.rint(fixture[187].astype(np.float64)/meta['decode_scales']['encoder_input']),-127,127).astype(np.int8)
        codes=0
        for i in range(12):
            for mode in ['normal','boundary']:
                inp=x if mode=='normal' else edge_input();golden=boundary_oracle(p,i,inp)['layernorm2_output'];value=np.load(out/'fused'/f'{mode}_{i:02d}'/'output.npy')
                assert np.array_equal(golden,value);codes+=value.size
                if mode=='normal':x=value
        assert np.array_equal(x,saved[187])
        banks=docs['banks_final/summary.json'];assert banks['independent']['passed'] and banks['core_cycles']==473871
        assert np.array_equal(np.load(out/'banks_final/output.npy'),np.load(out/'fused/normal_00/output.npy'))
        for name,sha in banks['source_hashes'].items():assert digest(ROOT/name)==sha
        cold=[]
        for variant in ['cold_fixed','cold_fused']:
            document=docs[variant+'/cold_tasks.json'];assert document['same_objects'] and len(document['tasks'])==2
            streams={t['same_stream_object'] for t in document['tasks']};banks={t['same_banks_object'] for t in document['tasks']};assert len(streams)==len(banks)==1
            for t in document['tasks']:
                assert t['cold_packets']==13 and len(t['layers'])==12 and t['io']['final_ack_included']
                assert t['total_cycles']==sum(r['cycles'] for r in t['layers'])+t['io']['io_cycles']
                ledger=t['io']['ledger'];assert len(ledger)==61
                assert [r['kind'] for r in ledger if r['segment']=='device_stream']==['common.bin','input']+[f'layer_{i:02d}.bin' for i in range(12)]+['output']
                for segment in ['device_stream','host_cpu_link','cpu_device_link','CPU_copy']:
                    assert sum(r['bytes'] for r in ledger if r['segment']==segment)==757312+2*6336
                value=np.load(out/variant/f'task_{t["task"]}_output.npy');assert np.array_equal(value,saved[t['sample']]);assert digest_bytes(value.tobytes())==t['output_sha256'];codes+=value.size
            cold.append(dict(variant=variant,total_cycles=[t['total_cycles'] for t in document['tasks']]))
        rtl=docs['layer_final/summary.json'];assert not rtl['quick'] and rtl['cases']==12 and rtl['profiles']==rtl['labels']==list(range(12))
        metrics=np.loadtxt(out/'layer_final/metrics.txt',dtype=np.int64);assert metrics.shape==(12,5) and np.all(metrics[:,3]==6336) and np.all(metrics[:,4]==0)
        # Recreate each RTL scoreboard oracle from the frozen runtime.
        for c in read(out/'layer_final/cases.json'):
            inp=np.clip(np.rint(fixture[c['sample']].astype(np.float64)/meta['decode_scales']['encoder_input']),-127,127).astype(np.int8)
            taps={};Encoder(p,lambda n,v,k:taps.update({n:v[0].copy()}) if n.endswith('/layernorm2_output') else None)(inp[None])
            value=taps[f'layer_{c["profile"]:02d}/layernorm2_output'].tobytes()
            words=[int(s,16) for s in (out/'layer_final'/f'expected_{c["case"]:03d}.hex').read_text().split()]
            observed=[int(s,16) for s in (out/'layer_final'/f'observed_{c["case"]:03d}.hex').read_text().split()]
            assert words==observed and value==b''.join(w.to_bytes(4,'little') for w in observed)
        for name,sha in read(out/'layer_final/rtl_source_hashes.json').items():assert digest(ROOT/name)==sha,'RTL changed after compilation'
        pipe=docs['pipeline_final/summary.json'];assert pipe['legacy_1818_retested'] and pipe['iterative_vectors']==582
        assert all(p['consecutive_accepts']>=256 for p in pipe['pipelines'].values());assert pipe['pipelines']['rq']['fixed_profile_RQ_vectors']==864
        assert [r['MBps'] for r in docs['io_final/system_io.json']['scenarios']]==[25,50,100,200,600]
        historical=read(ROOT/'testdata/integer_v1/evidence_bundle_manifest.json')['sha256']
        assert all(digest(ROOT.parent/name)==expected for name,expected in historical.items())
        assert digest(ROOT/'testdata/integer_v1/params/parameters.npz')=='4699ba38d9df1a635ff25eb379cc27521cf8b04205f2eba3f9c8d94a5d120a7a'
        frozen=read(ROOT/'testdata/r1r2/release/provenance.json')
        for name,sha in frozen['inputs'].items():assert digest(ROOT/name)==sha
        for name in ['integer_model/runtime.py','integer_model/export.py','integer_model/hw_abi.py','requirements-r1r2.lock']:
            assert digest(ROOT/name)==frozen['sources'][name]
        for name,sha in read(ROOT/'testdata/integer_v1/fixture/manifest.json')['files_sha256'].items():
            assert digest(ROOT/'testdata/integer_v1/fixture'/name)==sha
        # Freeze reproducible final sources and tools, without replacing old release.
        sources=list((ROOT/'integer_model').glob('*.py'))+list((ROOT/'rtl').rglob('*.sv'))
        sources += [Path(__file__),*[ROOT/'scripts'/name for name in ['validate_next_stage.py','validate_fused_schedule.py','validate_fused_audit.py','validate_fused_banks.py','validate_pipeline_rtl.py','validate_layer_rtl.py','validate_layer_control.py','validate_system_io.py','validate_kwt1_r1.py','validate_kwt1_r2.py','validate_arithmetic_rtl.py','run_r1r2_low_memory.py','audit_r1_events.py','assess_next_registers.py','normalize_next_io.py','write_next_report.py']],ROOT/'requirements-r1r2.lock',ROOT/'integer_model/NEXT_STAGE_README.md']
        hashes={}
        for source in sources:
            rel=source.relative_to(ROOT);target=out/'source'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target);hashes[str(rel).replace('\\','/')]=digest(source)
        (out/'source_manifest.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
        external=ROOT.parent/'docs/architecture/review_r1r2_execution.py';target=out/'source_workspace/docs/architecture/review_r1r2_execution.py'
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(external,target)
        (out/'external_source_manifest.json').write_text(json.dumps({'docs/architecture/review_r1r2_execution.py':digest(external)},indent=2),encoding='utf-8')
        tools=read(ROOT/'testdata/r1r2/release/toolchain_components.json')
        for name,sha in tools['Icarus_files'].items():assert digest(Path(name))==sha
        assert digest(Path(tools['numpy_core']['path']))==tools['numpy_core']['sha256']
        assert sys.version_info[:3]==(3,10,9) and np.__version__=='1.26.2'
        (out/'toolchain_components.json').write_text(json.dumps(tools,indent=2),encoding='utf-8')
        result.update(passed=True,saved_output_codes_recomputed=codes,RTL_scoreboard_codes=rtl['output_codes'],cold=cold,
                      max_register_bytes=max(r['total'] for r in registers['rows'] if not r['case'].startswith('cold_fixed')),
                      cache_control_conservative_register_bytes=max(r['total'] for r in registers['rows'] if r['case'].startswith('cold_fixed')),
                      legacy_frozen_files=len(historical),source_files=len(hashes),scope='software task/I/O + elastic micro RTL + behavioral-memory single-layer RTL; no full-layer cycle or PPA signoff')
    except Exception as error:
        result['error']=repr(error);(out/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8');raise
    (out/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    try:
        # Default report output follows the evidence root, allowing clean replays.
        import write_next_report
        write_next_report.OUT=out;write_next_report.main()
        documents=[ROOT.parent/'docs/architecture'/name for name in ['README.md','KWT1_ARCHITECTURE_V1.md','INTEGER_NUMERICS_V1.md','IMPLEMENTATION_ROADMAP.md','TASK_PIPELINE_LAYER_REPORT.md']]
        documents += [out/'REPORT.md',ROOT/'integer_model/NEXT_STAGE_README.md']
        links=0
        for document in documents:
            body=document.read_text(encoding='utf-8');assert body.count('```')%2==0
            for link in re.findall(r'\[[^\]]+\]\(([^)]+)\)',body):
                target=link.strip('<>').split('#')[0]
                if not target or '://' in target:continue
                assert (document.parent/target).exists(),f'broken link {document}: {target}';links+=1
        (out/'documentation_check.json').write_text(json.dumps(dict(passed=True,documents=len(documents),local_links=links),indent=2),encoding='utf-8')
        files={str(p.relative_to(out)).replace('\\','/'):digest(p) for p in out.rglob('*') if p.is_file() and p.name!='evidence_manifest.json' and not any(part.endswith('debug') for part in p.parts)}
        (out/'evidence_manifest.json').write_text(json.dumps(dict(sha256=files),indent=2),encoding='utf-8')
    except Exception as error:
        result.update(passed=False,error=repr(error));(out/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8');raise
    print(json.dumps(result,indent=2))
def digest_bytes(data):return hashlib.sha256(data).hexdigest()
if __name__=='__main__':main()
