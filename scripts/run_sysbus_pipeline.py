"""Python 3.6 server pipeline. One reused model, 12 cases + reset in parallel."""
import concurrent.futures
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'flow'))
import project
PT='/eda/synopsys/prime/prime_2022.03-SP5-1/bin/pt_shell'
DC='/eda/synopsys/dc/dc_2022.03-SP5-5/bin/dc_shell'
VCS='/eda/synopsys/vcs/vcs_2020.03-SP2-6/bin/vcs'


def state(stage,**kwargs):
    value=dict(stage=stage,UTC=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),**kwargs)
    p=ROOT/'build/progress.tmp.json';p.write_text(json.dumps(value,indent=2)+'\n')
    os.replace(str(p),str(ROOT/'build/progress.json'));print(stage,flush=True)


def execute(args,log,env,cwd=None):
    with log.open('x') as output:
        p=subprocess.run(list(map(str,args)),cwd=str(cwd or ROOT),env=env,
                         stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT)
    assert p.returncode==0,'TOOL_FAILED '+str(log)
    text=log.read_text(errors='replace')
    assert not re.search(r'^\s*(?:Error(?::|-\[)|SOC_FATAL|Fatal:|%Fatal)',text,re.M),'TOOL_LOG_ERROR '+str(log)
    return text


def check_reports(folder):
    for p in folder.rglob('*.rpt'):
        assert not re.search(r'^\s*Error(?::|-\[)',p.read_text(errors='replace'),re.M),'REPORT_ERROR '+str(p)


def gate(case,recovery,env):
    name='recovery' if recovery else 'cold' if case==0 else 'case_%02d'%case
    out=ROOT/'build/gate'/name;out.mkdir()
    proof=dict(manifest_sha256=project.sha(ROOT/'manifest.json'),
        netlist_sha256=project.sha(ROOT/'build/dc/mapped.v'),simv_sha256=project.sha(ROOT/'build/gate/model/simv'))
    (out/'inputs.json').write_text(json.dumps(proof,indent=2)+'\n')
    text=execute([ROOT/'build/gate/model/simv','+CASE='+str(case),'+RECOVERY='+str(int(recovery)),
        '+FIXTURES='+str(ROOT/'fixtures'),'+OUT='+str(out),'+notimingcheck','+no_notifier'],out/'run.log',env)
    assert 'PASS SOC_INPUT16_GATE recovery='+str(int(recovery)) in text,'GATE_NOT_PASSED '+name
    assert not re.search(r'SOC_.*(?:MISMATCH|ERROR|WATCHDOG)|SAIF_REPORT_ARG_CHECK',text),'GATE_OR_SAIF_ERROR '+name
    if recovery:assert 'SOC_GATE_RESET_IN_FLIGHT' in text
    (out/'result.json').write_text(json.dumps(dict(passed=True,case=case,recovery=recovery,
        saif_sha256=project.sha(out/'task.saif'),netlist_sha256=proof['netlist_sha256']),indent=2)+'\n')
    return name


def power_case(case,env):
    power_env=dict(env,SOC_POWER_CASE=str(case))
    log=ROOT/('build/pt_case_%02d.console.log'%case)
    text=execute([PT,'-f','flow/pt.tcl'],log,power_env)
    assert 'SOC_FULL_PT_DONE' in text,'PT_NOT_COMPLETE'
    check_reports(ROOT/('build/pt_case_%02d'%case))
    sys.path.insert(0,str(ROOT/'flow'))
    import collect
    # Each call writes a separate result; neither the source nor raw evidence changes.
    old_env=os.environ.get('SOC_POWER_CASE');os.environ['SOC_POWER_CASE']=str(case)
    try:return collect.collect()
    finally:
        if old_env is None:os.environ.pop('SOC_POWER_CASE',None)
        else:os.environ['SOC_POWER_CASE']=old_env


def main():
    project.check();(ROOT/'build').mkdir(exist_ok=True)
    with (ROOT/'build/launch.lock').open('x') as f:f.write(str(os.getpid()))
    env=dict(os.environ);env.pop('SOC_PT_PREFLIGHT',None);env.pop('SOC_POWER_CASE',None)
    lc=shutil.which('lc_shell')
    if lc and lc.endswith('/bin/lc_shell'):env['SYNOPSYS_LC_ROOT']=str(Path(lc).parent.parent)
    assert os.access(os.path.join(env.get('SYNOPSYS_LC_ROOT',''),'bin/lc_shell'),os.X_OK),'LC_ROOT_MISSING'
    state('incremental_System_Bus_mapping_reusing_CPU_core_and_accelerator')
    assert 'SOC_FULL_DC_DONE' in execute([DC,'-f','flow/dc.tcl','-output_log_file','build/dc.log'],ROOT/'build/dc.console.log',env)
    check_reports(ROOT/'build/dc/reports')
    project.netlist()
    state('TT_preflight_with_declared_clock_slew')
    assert 'SOC_FULL_PT_DONE' in execute([PT,'-f','flow/pt.tcl'],ROOT/'build/pt_preflight.console.log',dict(env,SOC_PT_PREFLIGHT='1'))
    check_reports(ROOT/'build/pt_preflight')
    state('compile_reused_full_gate_model')
    model=ROOT/'build/gate/model';model.mkdir(parents=True)
    cells=[str(Path(env['KWT_PDK_ROOT'])/('SCC40NLL_VHSC40_'+vt+'_V0.1')/('SCC40NLL_VHSC40_'+vt+'_V0p1')/'verilog'/('scc40nll_vhsc40_'+vt.lower()+'.v')) for vt in ['HVT','LVT','RVT']]
    execute([VCS,'-full64','-sverilog','-lca','-timescale=1ns/1ps','+define+SOC_SAIF','-top','tb_soc_metrics',
        *cells,ROOT/'flow/sram_contract_ret1n.v',ROOT/'build/dc/mapped.v',ROOT/'flow/tb_soc_metrics.sv',
        '-o',model/'simv'],model/'compile.log',env,model)
    cases=json.loads((ROOT/'manifest.json').read_text()).get('performance_cases',[0])
    assert cases and cases[0]==0 and len(set(cases))==len(cases) and all(0<=x<12 for x in cases)
    state('gate_cold_cases_and_reset_recovery_parallel',parallel_simulations=len(cases)+1,cases=cases)
    # Cold case0 powers immediately when complete; never wait for all 13 first.
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(cases)+1) as pool:
        cold=pool.submit(gate,0,False,env)
        rest=[pool.submit(gate,i,False,env) for i in cases[1:]]
        recovery=pool.submit(gate,0,True,env)
        cold.result();state('cold0_passed_collecting_first_real_power')
        first=power_case(0,env)
        state('first_metrics_ready_other_cases_running',first_metrics='build/metrics_case_00.json')
        for task in concurrent.futures.as_completed(rest):print('GATE_FINISHED '+task.result(),flush=True)
        recovery.result()
    rows=[first]
    for case in cases[1:]:state('same_window_power_case',case=case);rows.append(power_case(case,env))
    total_cycles=sum(x['cycles'] for x in rows)
    seconds=sum(x['same_window_SAIF_duration_seconds'] for x in rows)
    energies=[x['SoC_energy_uJ_per_task'] for x in rows]
    good=all(x is not None for x in energies)
    total_energy=sum(energies) if good else None
    result=dict(tasks=len(cases),cases=rows,total_cycles=total_cycles,
        throughput_at_assumed_150MHz=len(cases)*150e6/total_cycles,
        mean_energy_uJ=total_energy/len(cases) if good else None,
        time_weighted_mean_power_mW=total_energy/seconds/1000 if good else None,
        recovery_passed=True,timing_signoff=False,power_coverage_review_required=True)
    with (ROOT/'build/metrics_campaign.json').open('x') as f:json.dump(result,f,indent=2)
    state('all_metrics_ready_for_timing_activity_and_compliance_review',qualification_complete=False)


if __name__=='__main__':
    try:main()
    except Exception as error:
        if (ROOT/'build').exists():state('failed_preserve_evidence',error=str(error))
        raise
