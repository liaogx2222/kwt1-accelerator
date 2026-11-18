"""Wait for the running input16 DC, map platform, gate cold/reset in parallel, PT."""
import concurrent.futures
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'flow'))
import project
DC='/eda/synopsys/dc/dc_2022.03-SP5-5/bin/dc_shell'
PT='/eda/synopsys/prime/prime_2022.03-SP5-1/bin/pt_shell'
VCS='/eda/synopsys/vcs/vcs_2020.03-SP2-6/bin/vcs'


def state(stage,**values):
    p=ROOT/'build/progress.tmp.json'
    p.write_text(json.dumps(dict(stage=stage,UTC=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),**values),indent=2)+'\n')
    os.replace(str(p),str(ROOT/'build/progress.json'))
    print(stage,flush=True)


def execute(command,log,env=None,cwd=None):
    with log.open('x') as f:
        p=subprocess.run(command,cwd=str(cwd or ROOT),env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT)
    assert p.returncode==0, 'COMMAND_FAILED '+str(log)


def gate(mode,env):
    out=ROOT/'build/gate'/mode;out.mkdir()
    inputs=dict(manifest_sha256=project.sha(ROOT/'manifest.json'),netlist_sha256=project.sha(ROOT/'build/dc/mapped.v'),
        simv_sha256=project.sha(ROOT/'build/gate/model/simv'))
    (out/'inputs.json').write_text(json.dumps(inputs,indent=2)+'\n')
    execute([str(ROOT/'build/gate/model/simv'),'+CASE=0','+RECOVERY='+('1' if mode=='recovery' else '0'),
        '+FIXTURES='+str(ROOT/'fixtures'),'+OUT='+str(out),'+notimingcheck','+no_notifier'],out/'run.log',env)
    text=(out/'run.log').read_text(errors='replace')
    assert 'PASS SOC_INPUT16_GATE recovery='+('1' if mode=='recovery' else '0') in text, 'GATE_NOT_PASSED '+mode
    assert not re.search(r'SOC_.*(?:MISMATCH|ERROR|WATCHDOG)|Fatal:|%Fatal',text), 'GATE_ERRORS '+mode
    if mode=='recovery':assert 'SOC_GATE_RESET_IN_FLIGHT' in text
    (out/'result.json').write_text(json.dumps(dict(passed=True,saif_sha256=project.sha(out/'task.saif'),
        netlist_sha256=inputs['netlist_sha256'],scope='full digital SoC; zero delay gate functional, not SDF timing verification'),indent=2)+'\n')


def main():
    project.check();(ROOT/'build').mkdir(exist_ok=True)
    with (ROOT/'build/launch.lock').open('x') as f:f.write(str(os.getpid()))
    spec=json.loads((ROOT/'manifest.json').read_text());assert not spec.get('work_in_progress'), 'DEVELOPMENT_PROJECT_CANNOT_LAUNCH_CAD'
    source=(ROOT.parent/spec['accelerator_directory']/'input16_fast').resolve()
    assert source.is_dir(),'RUNNING_INPUT16_PROJECT_NOT_FOUND '+str(source)
    state('waiting_for_running_input16_DC',source=str(source))
    while not (source/'build/dc/netlist_manifest.json').exists():
        log=source/'build/dc.console.log'
        if log.exists():
            with log.open('rb') as f:f.seek(max(0,log.stat().st_size-32768));tail=f.read().decode(errors='replace')
            assert not re.search(r'^(?:Error:|KWT_FATAL)',tail,re.M), 'ACCELERATOR_DC_FAILED_PRESERVE_LOGS'
        time.sleep(15)
    execute([sys.executable,str(source/'flow/project.py'),'check-dc'],ROOT/'build/source_dc_check.log')
    sm=json.loads((source/'manifest.json').read_text());assert sm['RTL_revision']==spec['RTL_revision'] and sm['BLOCK_STREAM']==1, 'WRONG_INPUT16_REVISION_OR_PARAMETER'
    frozen=ROOT/'frozen_accel';frozen.mkdir()
    for n in ['mapped.ddc','mapped.v']:shutil.copyfile(str(source/'build/dc'/n),str(frozen/n))
    (frozen/'input.json').write_text(json.dumps(dict(source=str(source),source_manifest_sha256=project.sha(source/'manifest.json'),
        original_netlist_receipt=json.loads((source/'build/dc/netlist_manifest.json').read_text()),
        ddc_sha256=project.sha(frozen/'mapped.ddc'),verilog_sha256=project.sha(frozen/'mapped.v')),indent=2)+'\n')
    env=dict(os.environ);lc=shutil.which('lc_shell')
    if lc and lc.endswith('/bin/lc_shell'):env['SYNOPSYS_LC_ROOT']=str(Path(lc).parent.parent)
    assert os.access(os.path.join(env.get('SYNOPSYS_LC_ROOT',''),'bin/lc_shell'),os.X_OK), 'LC_ROOT_MISSING'
    state('mapping_platform_with_frozen_accelerator')
    execute([DC,'-f','flow/dc.tcl','-output_log_file','build/dc.log'],ROOT/'build/dc.console.log',env)
    dc_text=(ROOT/'build/dc.console.log').read_text(errors='replace')
    assert 'SOC_FULL_DC_DONE' in dc_text and not re.search(r'^(?:Error:|SOC_FATAL)',dc_text,re.M),'SOC_DC_ERROR_GATE'
    project.netlist();state('TT_link_timing_power_capability_preflight')
    pre_env=dict(env,SOC_PT_PREFLIGHT='1')
    execute([PT,'-f','flow/pt.tcl'],ROOT/'build/pt_preflight.console.log',pre_env)
    assert (ROOT/'build/pt_preflight/complete').exists(),'PT_PREFLIGHT_COMPLETION_MISSING'
    assert not re.search(r'^(?:Error:|SOC_FATAL)',(ROOT/'build/pt_preflight.console.log').read_text(errors='replace'),re.M),'PT_PREFLIGHT_ERROR_GATE'
    env.pop('SOC_PT_PREFLIGHT',None)
    state('compiling_full_SoC_gate_model')
    model=ROOT/'build/gate/model';model.mkdir(parents=True)
    cells=[]
    for vt in ['HVT','LVT','RVT']:
        cells.append(str(Path(env['KWT_PDK_ROOT'])/('SCC40NLL_VHSC40_'+vt+'_V0.1')/
            ('SCC40NLL_VHSC40_'+vt+'_V0p1')/'verilog'/('scc40nll_vhsc40_'+vt.lower()+'.v')))
    execute([VCS,'-full64','-sverilog','-lca','-timescale=1ns/1ps','+define+SOC_SAIF','-top','tb_soc_metrics',
        *cells,str(ROOT/'flow/sram_contract_ret1n.v'),str(ROOT/'build/dc/mapped.v'),
        str(ROOT/'flow/tb_soc_metrics.sv'),'-o',str(model/'simv')],model/'compile.log',env,model)
    state('gate_cold_and_recovery_running_in_parallel')
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(gate,n,env) for n in ['cold','recovery']]
        for f in futures:f.result()
    project.activity();state('PT_and_full_SoC_power')
    env.pop('KWT_GATE_SAIF',None)
    execute([PT,'-f','flow/pt.tcl'],ROOT/'build/pt.console.log',env)
    assert (ROOT/'build/pt/complete').exists(), 'PT_COMPLETION_MISSING'
    assert not re.search(r'^(?:Error:|SOC_FATAL)',(ROOT/'build/pt.console.log').read_text(errors='replace'),re.M),'SOC_PT_ERROR_GATE'
    import collect
    collect.collect()
    state('reports_ready_for_review',timing_signoff=False,power_coverage_review_required=True)


if __name__=='__main__':
    try:main()
    except Exception as error:
        if (ROOT/'build').exists():state('failed_preserve_evidence',error=str(error))
        raise
