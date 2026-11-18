"""Read-only final gate: reference PIO metrics, immutable history and documents."""
import argparse
import ast
import json
import re
import subprocess
from pathlib import Path
from local_tools import ROOT, sha


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    out=args.output.resolve();assert not out.exists(),'New delivery output'
    count=dict(evidence_hashes=0,source_hashes=0)
    bindings={}
    def read(path):return json.loads(path.read_text())
    def verify(base,values,key):
        for name,digest in values.items():
            assert sha(base/name.replace('\\','/'))==digest,name
            count[key]+=1
    def manifest(folder,name='manifest.json'):
        values=read(folder/name);verify(folder,values.get('sha256',values),'evidence_hashes')
        bindings[(folder/name).relative_to(ROOT).as_posix()]=sha(folder/name)
    campaign=ROOT/'testdata/e203_software_20261104'
    selection=read(campaign/'selection.json')
    for group in selection['comparison_groups']+['observer_control_v2','full_classes','faults','opaque_contract']:
        folder=campaign/group;manifest(folder)
        verify(ROOT,read(folder/'source_bindings.json'),'source_hashes')
        if (folder/'actual_model_command.json').exists():
            cmd=read(folder/'actual_model_command.json')
            assert sha(Path(cmd[0]))==read(folder/'execution.json')['model_sha256']
    model=campaign/'transaction_model_v2'
    verify(ROOT,read(model/'build_bindings.json'),'source_hashes')
    assert sha(model/'combinations.exe')==read(model/'summary.json')['model_sha256']
    review=campaign/'review';manifest(review)
    verify(ROOT,read(review/'source_bindings.json'),'source_hashes')
    verified=read(review/'verification.json');assert verified['passed'] and verified['all_independent_codes']==177408
    metrics=ROOT/'testdata/competition_metrics_20261104';manifest(metrics)
    verify(ROOT,read(metrics/'source_bindings.json'),'source_hashes')
    rebuild=ROOT/'testdata/competition_metrics_rebuild_20261104';manifest(rebuild)
    assert read(rebuild/'verification.json')['binary_identical']
    assert sha(rebuild/'firmware.bin')==sha(metrics/'reference_firmware/firmware.bin')
    result=read(metrics/'metrics.json');reference=result['software_reference']
    assert not result['official_submission_complete']
    assert result['official_metrics']['total_counted_area_mm2'] is None
    assert result['official_metrics']['mean_power_mW'] is None and result['official_metrics']['energy_J_per_task'] is None
    assert result['official_metrics']['accuracy_percent'] is None
    assert reference['twelve_task_cycles']==sum(reference['measured_task_cycles'])==115270956
    assert abs(reference['throughput_at_assumed_150MHz']-12*150000000/115270956)<1e-12
    assert sum(reference['SRAM_reads_per_task'])==130348846
    assert sum(reference['SRAM_writes_per_task'])==15750432
    assert not reference['internal_9M_target_met'] and not reference['DMA']
    rules=read(metrics/'competition_source.json')
    assert sha(ROOT.parent/rules['extracted_text'])==rules['extracted_text_sha256']
    assert sha(ROOT.parent/rules['original_pdf'])==rules['original_pdf_sha256']
    for name in ['e203_combined_20261104','e203_factors_20261104','reference_e203/parallel_20261103',
                 'integration_v1/release','rtl_v2/release','rtl_v1/release','next_stage_v1']:
        folder=ROOT/'testdata'/name;manifest(folder,'evidence_manifest.json')
        verify(ROOT,read(folder/'source_manifest.json'),'source_hashes')
    previous=ROOT/'testdata/system_analysis_20261104/delivery_review'
    manifest(previous)
    previous_docs=read(previous/'verification.json')['document_sha256']
    navigation=['README.md','IMPLEMENTATION_ROADMAP.md','PLATFORM_HANDOFF.md']
    for name,digest in previous_docs.items():
        filename=Path(name).name
        path=campaign/'previous_navigation'/filename if filename in navigation else ROOT.parent/name
        assert sha(path)==digest,(name,path)
        bindings[path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else '../'+name]=digest
    docs=[ROOT.parent/'docs/architecture'/name for name in [
        'E203_PIO_AND_COMPETITION_METRICS_20261104.md',*navigation]]
    docs.append(metrics/'reference_firmware/README.md')
    links=0;document_sha={}
    for path in docs:
        text=path.read_text(encoding='utf-8');assert len(re.findall(r'^```',text,re.M))%2==0,path
        for target in re.findall(r'(?<!!)\[[^\]]+\]\(([^)]+)\)',text):
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',target):continue
            target=target.split('#',1)[0].strip('<>')
            if target:assert (path.parent/target).exists(),(path,target);links+=1
        document_sha[path.relative_to(ROOT.parent).as_posix()]=sha(path)
    scripts=['run_e203_software_experiments.py','run_e203_direct_backend.py','run_e203_inline_backend.py',
        'run_e203_platform_pio.py','run_e203_pio_loop.py','build_e203_transaction_observer.py',
        'run_e203_pio_metrics.py','check_e203_software_campaign.py','build_competition_metrics.py',
        'rebuild_e203_pio_package.py','probe_open_reference_srams.py','validate_e203_platform_pio.py',Path(__file__).name]
    for name in scripts:
        path=ROOT/'scripts'/name;ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
        bindings[path.relative_to(ROOT).as_posix()]=sha(path)
    def git(folder,*args):
        return subprocess.check_output(['git','-c','safe.directory='+folder.as_posix(),'-C',str(folder),*args],text=True).strip()
    cpu=ROOT.parent/'e203_hbirdv2'
    assert git(cpu,'rev-parse','HEAD')=='9f3e34f337f5d0a1236a285871ffa2032491617a'
    assert not git(cpu,'status','--porcelain')
    assert git(ROOT,'diff','--numstat','--','kws_streaming/data/input_data.py').split()[:2]==['3','3']
    assert not git(ROOT,'diff','--check')
    report=dict(passed=True,scope='reference implementation and delivery consistency, not official score/SMIC40 signoff',
        **count,independently_recomputed_codes=177408,mismatches=0,
        twelve_class_tasks_in_one_CPU=True,recovery_tasks=2,
        immediate_error_checked_ACC_transactions=verified['immediate_error_checked_ACC_transactions'],
        exported_firmware_rebuild_identical=True,markdown_files=len(docs),local_links=links,
        Python_sources_parsed=len(scripts),historical_navigation_snapshots=3,
        CPU_repository_clean=True,user_sort_patch_insertions=3,user_sort_patch_deletions=3,
        official_submission_complete=False,only_open_sources_available_user_confirmed=True,
        complete_STA=False,area_including_SRAM=None,power_mW=None,energy_J=None,
        internal_9M_target_met=False,document_sha256=document_sha)
    out.mkdir(parents=True)
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'source_bindings.json').write_text(json.dumps(bindings,indent=2))
    (out/'manifest.json').write_text(json.dumps({path.name:sha(path) for path in out.iterdir() if path.is_file()},indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
