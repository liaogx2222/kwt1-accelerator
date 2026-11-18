"""Final provenance/target gate, without confusing software accuracy and RTL/PPA."""
import argparse
import ast
import json
import re
import subprocess
from pathlib import Path
from local_tools import ROOT,sha


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args();out=args.output.resolve()
    assert not (out/'verification.json').exists(),'Published delivery exists';out.mkdir(parents=True,exist_ok=True)
    count={'evidence_hashes':0,'source_hashes':0};bindings={}
    def read(path):return json.loads(path.read_text())
    def verify(base,values,kind):
        for name,digest in values.items():assert sha(base/name.replace('\\','/'))==digest,name;count[kind]+=1
    def manifest(folder,name='manifest.json'):
        data=read(folder/name);verify(folder,data.get('sha256',data),'evidence_hashes');bindings[(folder/name).relative_to(ROOT).as_posix()]=sha(folder/name)
    root=ROOT/'testdata/accuracy_point1_20261104'
    for name in ['input_max','context_max','mid_all','max_all','input16_only','review_s8','review_input16']:
        folder=root/name;manifest(folder);verify(ROOT,read(folder/'source_bindings.json'),'source_hashes')
    a=read(root/'review_s8/verification.json');b=read(root/'review_input16/verification.json')
    assert a['audit_passed'] and not a['accuracy_target_met']
    assert b['audit_passed'] and b['accuracy_target_met'] and b['integer_correct']==4345
    assert b['accuracy_drop_pp']<=0.1 and not b['new_RTL_validated'] and not b['official_600_evaluated']
    for name in ['competitive_targets_20261104','competitive_targets_loader_20261104','competitive_targets_review_20261104']:
        folder=ROOT/'testdata'/name;manifest(folder);verify(ROOT,read(folder/'source_bindings.json'),'source_hashes')
    budget=read(ROOT/'testdata/competitive_targets_review_20261104/analysis.json')
    assert budget['cycles_per_task']==625000 and budget['actual_loader']['total_loader_cycles']==526906
    assert budget['shared_arithmetic_lower_bounds']['scalar_multiply_requests_excluding_standalone_M_REQ']==2025540
    assert not budget['all_targets_met'] and not budget['new_RTL_implemented']
    for name in ['e203_software_20261104/review','competition_metrics_20261104','competition_metrics_rebuild_20261104',
                 'e203_combined_20261104','integration_v1/release','rtl_v2/release']:
        folder=ROOT/'testdata'/name;file='evidence_manifest.json' if (folder/'evidence_manifest.json').exists() else 'manifest.json'
        manifest(folder,file)
        for source in ['source_bindings.json','source_manifest.json']:
            if (folder/source).exists():verify(ROOT,read(folder/source),'source_hashes')
    workspace=ROOT.parent;targets=workspace/'docs/architecture/PROJECT_TARGETS_20261104.json';t=read(targets)
    assert t['accuracy']['candidate_integer_correct']==b['integer_correct'] and t['accuracy']['validation_target_met']
    assert not t['implementation_status']['new_RTL_approved_or_implemented']
    assert t['benchmark']['tasks_per_second']==240 and t['benchmark']['SoC_power_mW']/240*1000==75
    previous=ROOT/'testdata/competition_metrics_delivery_20261104';manifest(previous)
    for name,digest in read(previous/'verification.json')['document_sha256'].items():
        filename=Path(name).name
        source=out/'previous_navigation'/filename if name.startswith('docs/') and filename in ['README.md','IMPLEMENTATION_ROADMAP.md'] else workspace/name
        assert sha(source)==digest,(name,source)
    docs=[workspace/'docs/architecture'/name for name in ['POINT1_ACCURACY_AND_240TPS_REVIEW_20261104.md','README.md','IMPLEMENTATION_ROADMAP.md']]
    document_sha={};links=0
    for path in docs:
        text=path.read_text(encoding='utf-8');assert len(re.findall(r'^```',text,re.M))%2==0,path
        for target in re.findall(r'(?<!!)\[[^\]]+\]\(([^)]+)\)',text):
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',target):continue
            target=target.split('#',1)[0].strip('<>')
            if target:assert (path.parent/target).exists(),(path,target);links+=1
        document_sha[path.relative_to(workspace).as_posix()]=sha(path)
    scripts=['run_accuracy_point1_candidates.py','check_accuracy_point1_candidates.py','run_accuracy_input16.py',
             'check_accuracy_input16.py','analyze_competitive_targets.py','measure_packet_loader_bound.py',
             'extend_competitive_bounds.py',Path(__file__).name]
    for name in scripts:
        path=ROOT/'scripts'/name;ast.parse(path.read_text(encoding='utf-8'),filename=str(path));bindings[path.relative_to(ROOT).as_posix()]=sha(path)
    for pattern in ['*/export_candidate_executed.py','input16_only/*.py','input16_only/run/export_candidate_executed.py']:
        for path in root.glob(pattern):ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
    def git(folder,*args):return subprocess.check_output(['git','-c','safe.directory='+folder.as_posix(),'-C',str(folder),*args],text=True).strip()
    cpu=workspace/'e203_hbirdv2';assert not git(cpu,'status','--porcelain')
    assert git(cpu,'rev-parse','HEAD')=='9f3e34f337f5d0a1236a285871ffa2032491617a'
    assert git(ROOT,'diff','--numstat','--','kws_streaming/data/input_data.py').split()[:2]==['3','3']
    assert not git(ROOT,'diff','--check')
    bindings['../docs/architecture/PROJECT_TARGETS_20261104.json']=sha(targets)
    for path in [root/'preregistered.json',root/'second_wave_preregistered.json']:bindings[path.relative_to(ROOT).as_posix()]=sha(path)
    report=dict(passed=True,scope='new target research delivery; software Validation accuracy passed, new hardware/PPA not implemented',
        **count,software_accuracy_drop_pp=b['accuracy_drop_pp'],software_accuracy_target_met=True,
        full_validation_samples=4445,integer_correct=4345,FP_correct=4348,
        independently_recomputed_CPU_output_codes=a['independently_CPU_recomputed_output_codes']+b['independent_CPU_graph_output_codes'],
        CPU_output_mismatches=0,actual_loader_RTL_floor_cycles=526906,
        target_cycles=625000,throughput_target_met=False,new_RTL_implemented=False,new_area_power_measured=False,
        LN_E01_inherited=False,official_600_evaluated=False,markdown_files=3,local_links_checked=links,
        Python_sources_parsed=len(scripts),CPU_repository_clean=True,user_sort_patch_insertions=3,user_sort_patch_deletions=3,
        document_sha256=document_sha)
    (out/'verification.json').write_text(json.dumps(report,indent=2));(out/'source_bindings.json').write_text(json.dumps(bindings,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file() and p!=out/'manifest.json'},indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
