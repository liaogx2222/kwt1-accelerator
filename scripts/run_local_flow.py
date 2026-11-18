"""Explicit portable local stages. Missing tools fail only the requested stage."""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from local_tools import ROOT, SUFFIX, Tools, run, sha


def execute(stage, out, tools, quick=False, config=None):
    out.mkdir(parents=True, exist_ok=True)
    paths = [ROOT/x for x in (ROOT/'rtl/v2/files.f').read_text().splitlines() if x and not x.startswith('+')]
    commands = []
    tool_hashes = {}
    executed_scripts = {str(p):sha(p) for p in [Path(__file__),ROOT/'scripts/local_tools.py']}
    def call(args, name):
        commands.append([str(x) for x in args])
        binary=Path(args[0]);binary=binary if binary.is_file() else Path(shutil.which(str(binary)) or str(binary))
        if binary.is_file():tool_hashes[str(binary.resolve())]=sha(binary)
        return run(args, out, name)
    if stage == 'lint':
        call([tools.iverilog(), '-g2012', '-s', 'kwt1_mmio', '-o', out/'lint.vvp', '-f', ROOT/'rtl/v2/files.f'], 'lint')
    elif stage == 'unit':
        paths += [ROOT/'rtl/v2/tb_units.sv']
        fixture = ROOT/'testdata/rtl_v1/release/unit'
        if not fixture.exists():fixture=ROOT/'fixtures/unit'
        for name in ['math.txt', 'iter.txt']:shutil.copyfile(fixture/name, out/name)
        paths += [fixture/'math.txt', fixture/'iter.txt']
        sources = [ROOT/'rtl/micro/mul_pipe.sv', ROOT/'rtl/micro/rne_pipe.sv'] + [ROOT/'rtl/v2'/name for name in ['kwt_math.sv','kwt_sram_sp.sv','kwt_mac8x8.sv','kwt_iterative.sv','tb_units.sv']]
        call([tools.iverilog(), '-g2012', '-DKWT_SIM', '-s', 'tb_units', '-o', out/'unit.vvp', *sources], 'compile')
        result=call([tools.vvp(), out/'unit.vvp', '+root='+out.as_posix()], 'unit')
        assert 'PASS math=2592 iterative=640' in result
    elif stage == 'protocol':
        tests = [('mmio',['rtl/v2/kwt1_mmio.sv','rtl/integration/tb_mmio.sv'],[], 'tb_mmio'),
                 ('sram_behavior',['rtl/v2/kwt_sram_sp.sv','rtl/integration/tb_sram.sv'],[], 'tb_sram'),
                 ('sram_macro_wrapper',['rtl/v2/kwt_sram_sp.sv','rtl/integration/tech_sram_model.sv','rtl/integration/tb_sram.sv'],['-DKWT_TECH_SRAM'], 'tb_sram'),
                 ('reference_icb',['rtl/reference/icb_kwt_bridge.sv','rtl/reference/tb_icb_kwt_bridge.sv'],[], 'tb_icb_kwt_bridge')]
        for name, names, defines, top in tests:
            sources=[ROOT/p for p in names];paths+=sources
            call([tools.iverilog(), '-g2012', *defines, '-s', top, '-o', out/(name+'.vvp'), *sources], name+'_compile')
            result=call([tools.vvp(), out/(name+'.vvp')], name)
            assert 'PASS ' in result
        driver=[ROOT/p for p in ['rtl/integration/test_initial_bus_failure.cpp','rtl/integration/driver/kwt1.c']];paths+=driver+[ROOT/'rtl/integration/driver/kwt1.h']
        exe=out/('driver_failure'+SUFFIX)
        call([*tools.cxx(), '-x', 'c++', '-std=c++17', '-O1', *driver, '-o', exe], 'driver_compile')
        assert 'PASS INITIAL BUS' in call([exe], 'driver_failure')
    elif stage == 'encoder':
        args=[sys.executable,ROOT/'scripts/run_reference_e203.py','--output',out]
        if quick:args+=['--quick']
        if config:args+=['--tools',config]
        call(args,'encoder')
        return  # Independent checker owns the encoder's publication.
    elif stage == 'synth':
        logical_out=out.as_posix()
        try:yosys=[tools.find('yosys')]
        except FileNotFoundError:
            if not (ROOT/'tools/rtl_v2_python/yowasp_yosys').is_dir():raise
            yosys=[sys.executable,ROOT/'scripts/run_yosys_v2.py']
            try:logical_out=out.relative_to(ROOT).as_posix()
            except ValueError:raise ValueError('YoWASP requires an output beneath the project; native Yosys accepts external output')
        sources=(ROOT/'rtl/v2/synth_generic.ys').read_text().replace('testdata/rtl_v2/synth',logical_out)
        (out/'generic.ys').write_text(sources)
        call([*yosys,'-Q','-q','-l',logical_out+'/generic.log','-s',logical_out+'/generic.ys'],'synth')
        net=json.loads((out/'generic.json').read_text())['modules']['kwt1_mmio']
        cells=list(net['cells'].values());macros=sum(c['type']=='kwt_tech_sram_4096x16' for c in cells)
        assert macros==20, f'Expected 20 external SRAM macros, found {macros}'
        assert not any(c['type'].startswith('$mem') for c in cells),'Behavioral SRAM escaped macro boundary'
        paths += [ROOT/'rtl/v2/kwt_tech_sram_blackbox.sv',ROOT/'rtl/v2/synth_generic.ys',ROOT/'scripts/run_yosys_v2.py']
    else:raise ValueError(stage)
    paths += [ROOT/'scripts/local_tools.py',ROOT/'scripts/run_local_flow.py',ROOT/'rtl/v2/generated/kwt_profile.svh',ROOT/'rtl/v2/files.f']
    bound={p.relative_to(ROOT).as_posix():sha(p) for p in set(paths)}
    evidence={p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file() and p.name!='result.json'}
    for p,digest in executed_scripts.items():assert sha(Path(p))==digest,'Flow source changed during execution: '+p
    result=dict(passed=True,stage=stage,host=platform.platform(),python=sys.version,source_sha256=bound,evidence_sha256=evidence,commands=commands,tool_sha256=tool_hashes,physical_signoff=False,linux_execution='pending' if os.name=='nt' else 'this host')
    (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=True,stage=stage,output=str(out)),indent=2),flush=True)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stage',required=True,choices=['lint','unit','protocol','encoder','synth','check']);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--tools',type=Path);ap.add_argument('--quick',action='store_true');ap.add_argument('--encoder',type=Path,help='Completed independent E203 system evidence for aggregate check');a=ap.parse_args();out=a.output.resolve()
    if a.stage=='check':
        results={}
        for stage in ['lint','unit','protocol','synth']:
            f=out/stage/'result.json'
            if not f.exists():results[stage]='pending';continue
            r=json.loads(f.read_text());assert r['passed'] and r['stage']==stage
            for name,digest in r['source_sha256'].items():assert sha(ROOT/name)==digest,name
            for name,digest in r['evidence_sha256'].items():assert sha(f.parent/name)==digest,name
            for name,digest in r.get('tool_sha256',{}).items():assert sha(Path(name))==digest,name
            results[stage]='passed'
        results['encoder']='pending'
        if a.encoder and (a.encoder/'verification.json').exists():
            r=json.loads((a.encoder/'verification.json').read_text());assert r['passed'] and r['full_classes']==12
            for name,digest in json.loads((a.encoder/'source_manifest.json').read_text()).items():assert sha(ROOT/name)==digest,name
            for name,digest in json.loads((a.encoder/'evidence_manifest.json').read_text())['sha256'].items():assert sha(a.encoder/name)==digest,name
            results['encoder']='passed'
        complete=all(v=='passed' for v in results.values())
        report=dict(stages=results,all_required_stages_passed=complete,linux_execution='pending' if os.name=='nt' else 'this host',physical_signoff=False)
        (out/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));return 0 if complete else 2
    if (out/'result.json').exists():raise ValueError('Verified stage exists; choose a fresh output')
    execute(a.stage,out,Tools(a.tools),a.quick,a.tools)

if __name__=='__main__':raise SystemExit(main())
