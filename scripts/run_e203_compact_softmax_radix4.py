"""Change only the reciprocal implementation in the validated E203 Softmax partition."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess

from local_tools import ROOT, sha
from map_compact_ffn_writeback import graph_digest
from run_e203_compact_dense99 import area_report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    out=parser.parse_args().output.resolve();out.mkdir(parents=True)
    evidence=ROOT/'testdata/input16_rtl_20261105'
    base=evidence/'p4_e203_compact_softmax_v3'
    shared=evidence/'p4_e203_compact_shared_qk_v1'
    variant=evidence/'p4_compact_softmax_recip_v1'
    ln2=evidence/'p3_e203_compact_ln2_v2'
    frozen=evidence/'trim2_e203'
    lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    def rel(path):
        return os.path.relpath(path,ROOT).replace('\\','/')

    for folder in (base,variant):
        manifest=json.loads((folder/'manifest.json').read_text())
        for name,value in manifest.items():
            assert sha(folder/name)==value,name
    baseline=json.loads((base/'verification.json').read_text())
    for name,value in baseline['source_sha256'].items():
        assert sha(ROOT/name)==value,name
    row=variant/'kwt_compact_softmax_row.sv'
    reciprocal=ROOT/'rtl/block_transfer/kwt_compact_softmax_recip.sv'
    variant_sources=json.loads((variant/'verification.json').read_text())['source_sha256']
    assert sha(reciprocal)==variant_sources[rel(reciprocal)]
    platform=[base/n for n in ('reference_top.sv','e203_cpu_top.v','e203_cpu.v','softmax_probe_top.sv')]
    local=[base/n for n in ('kwt_indexed_weight_banks.sv','kwt_e203_dense_body.sv')]
    dense_sources=[shared/n for n in ('kwt_compact_dense.sv','kwt_compact_qk_feed.sv')]
    skip={'config.v','e203_defines.v','kwt_e203_dense_supply.sv','kwt_compact_softmax_row.sv',
          *[p.name for p in platform+local+dense_sources]}
    hardware=[ROOT/p for p in baseline['source_sha256'] if p.endswith(('.sv','.v')) and
              p.startswith(('rtl/','../e203_hbirdv2/',rel(ln2)+'/')) and Path(p).name not in skip]
    observer=base/'observer.cpp'

    def linux(command,log):
        with (out/log).open('w') as fd:
            result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {command}'],
                                  stdout=fd,stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError((out/log).read_text(errors='replace')[-5000:])

    def mapping():
        script=out/'mapping.ys'
        script.write_text(f'''read_json {rel(base/'mapped.json')}
read_verilog -sv -overwrite {rel(row)} {rel(reciprocal)}
synth -top e203_subsys_nice_core -noabc -noshare
dfflibmap -liberty {rel(lib)}
abc -fast -liberty {rel(lib)}
clean
check -assert
stat -liberty {rel(lib)}
write_json {rel(out/'mapped.json')}
''')
        linux(f'yosys -Q -s {rel(script)}','mapping.log')
        before=json.loads((base/'mapped.json').read_text())['modules']
        after=json.loads((out/'mapped.json').read_text())['modules']
        unchanged=[n for n,m in before.items() if n!='kwt_compact_softmax_row' and m.get('cells')]
        assert all(graph_digest(before[n])==graph_digest(after[n]) for n in unchanged)
        return area_report(out,lib),unchanged

    def regression():
        files=' '.join(rel(p) for p in [*hardware,*platform,*local,*dense_sources,row,reciprocal])
        linux(f'verilator --cc --exe --build -j 3 --no-timing -Wno-fatal --output-split 14000 '
              f'-DFPGA_SOURCE -DKWT_SIM -I../e203_hbirdv2/rtl/e203/core -Irtl/input16_trim2/generated '
              f'--top-module reference_top --Mdir {rel(out)}/model {files} {cwd}/{rel(observer)}','build.log')
        cases={}
        for case,mode in (('normal','normal'),('recovery','faults')):
            linux(f'env KWT_DRAIN_READY=1 {rel(out)}/model/Vreference_top {rel(ln2/"firmware.bin")} {rel(frozen)} 6 {mode}',f'{case}.log')
            lines=(out/f'{case}.log').read_text().splitlines()
            def metrics(prefix):
                line=next(s for s in lines if s.startswith(prefix))
                return {k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)}
            bank,forward,qk,softmax,dense=(metrics(p) for p in (
                'PASS BANKS ','PASS FORWARD ','PASS SHARED_QK ','PASS E203_SOFTMAX ','PASS DENSE '))
            old=baseline['cases']['normal']
            assert bank==old['bank'] and forward==old['forward']
            assert {k:v for k,v in softmax.items() if k!='stalls'}=={k:v for k,v in old['softmax'].items() if k!='stalls'}
            assert dense['cycles']<old['dense']['cycles']
            if case=='recovery':
                assert 'PASS E203_SOFTMAX FAULT stalled-result cancel and same-model hard-reset recovery' in lines
            cases[case]=dict(bank=bank,forward=forward,qk=qk,softmax=softmax,dense=dense)
        assert cases['normal']==cases['recovery']
        return cases

    with ThreadPoolExecutor(max_workers=2) as pool:
        mapped=pool.submit(mapping)
        cases=regression()
        area,unchanged=mapped.result()
    sources={**baseline['source_sha256']}
    sources.update({rel(p):sha(p) for p in [Path(__file__),row,reciprocal,*platform,*local,*dense_sources,observer,
                    base/'verification.json',base/'manifest.json',base/'mapped.json',variant/'manifest.json']})
    report=dict(passed=True,actual_E203=True,full_encoder=False,supply_MBps=100,cases=cases,mismatches=0,
                baseline_cycles=baseline['cases']['normal']['dense']['cycles'],partition_standard_cell_mm2=area,
                baseline_standard_cell_mm2=baseline['partition_standard_cell_mm2'],reused_gate_modules=unchanged,
                private_macro_count=20,private_sram_bytes=65536,throughput_tasks_per_second=None,
                mean_SoC_power_mW=None,complete_counted_area_mm2=None)
    (out/'verification.json').write_text(json.dumps({**report,'source_sha256':sources},indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
