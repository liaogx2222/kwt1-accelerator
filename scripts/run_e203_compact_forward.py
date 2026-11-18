"""Run the Compact LN2 SRAM output through physical A into later Q/K/V."""
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
from run_e203_compact_supply import cpu_overlay, replace_once


def overlay(source, simulate=False):
    anchor='    output wire [63:0] drain_data'+(',' if simulate else '')+'\n'
    ports='''    output wire [63:0] drain_data,
    input wire require_forward,
    output wire forward_ready,forward_available'''
    if simulate:
        ports+=''',
    output wire probe_forward_write,
    output wire [9:0] probe_forward_index,
    output wire [127:0] probe_forward_data'''
    edits=[
        (anchor,ports+(',' if simulate else '')+'\n'),
        ('    wire [9:0] drain_read_index;', '''    wire [9:0] drain_read_index,forward_s_index,forward_a_index;
    wire forward_write;
    wire [127:0] forward_a_data;
    wire use_forward=require_forward&&(tile_id==2||tile_id==4||tile_id==5);'''),
        ('ln_a_read?ln_a_addr:wb_active?wb_addr:a_addr','forward_write?forward_a_index:ln_a_read?ln_a_addr:wb_active?wb_addr:a_addr'),
        ('a_enable=ln_a_read?', "a_enable=forward_write?8'hff:ln_a_read?"),
        ('a_write=ln_a_read?', "a_write=forward_write?8'hff:ln_a_read?"),
        ('a_write_data=wb_active?', 'a_write_data=forward_write?forward_a_data:wb_active?'),
        ('assign dense_ready=internal_dense_ready&&ffn_start_ok&&!output_available&&!drain_busy;',
         '''wire start_allowed=ffn_start_ok&&!output_available&&!drain_busy&&!forward_write&&
                       (!use_forward||forward_available);
    assign dense_ready=internal_dense_ready&&start_allowed;'''),
        ('assign act_ready=internal_act_ready&&!output_available&&!capture_phase;',
         'assign act_ready=internal_act_ready&&!output_available&&!capture_phase&&!drain_busy&&!forward_write&&!use_forward;'),
        ('(a_en&&(wb_active||ln_a_read))||(wb_active&&ln_a_read)||',
         '(a_en&&(wb_active||ln_a_read||forward_write))||(wb_active&&ln_a_read)||\n                       (forward_write&&(ln_a_read||wb_active))||'),
        ("{4{{2'b0,drain_read_index}}}","{4{{2'b0,forward_s_index}}}"),
        ('finish_frame&&!coeff_phase&&!output_available&&!drain_busy)',
         'finish_frame&&!coeff_phase&&!output_available&&!drain_busy&&!forward_write)'),
        ('.out_valid(drain_valid),.out_ready(drain_ready)', '.out_valid(drain_valid),.out_ready(drain_ready&&forward_ready)'),
        ('.start_valid(dense_start&&ffn_start_ok&&!output_available&&!drain_busy)', '.start_valid(dense_start&&start_allowed)'),
        ('.act_write(act_write&&!output_available&&!capture_phase)', '.act_write(act_write&&act_ready)'),
        ('    kwt_compact_dense dense (','''    kwt_compact_ln2_forward forwarding (
        .clk(nice_clk),.rst_n(nice_rst_n),.abort(dense_abort),.epoch(lease_epoch),
        .read_index(drain_read_index),.s_index(forward_s_index),
        .valid(drain_valid&&drain_ready),.ready(forward_ready),.data(drain_data),
        .write_a(forward_write),.a_index(forward_a_index),.a_data(forward_a_data),.available(forward_available));

    kwt_compact_dense dense ('''),
    ]
    if simulate:
        edits.append(('    assign probe_drain_read=drain_read;', '''    assign probe_drain_read=drain_read;
    assign probe_forward_write=forward_write;
    assign probe_forward_index=forward_a_index;
    assign probe_forward_data=forward_a_data;'''))
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def instrument(source,old_score,score,old_probe,probe):
    edits=[
        (old_score,score),(old_probe,probe),
        ('        dut.drain_ready=','        dut.require_forward=frame>1;\n        dut.drain_ready='),
        ('dense.writes==25536', 'dense.writes==10752'),
        ('dut.drain_valid && !dut.drain_ready && drain.words>=8',
         'dut.drain_valid && !(dut.drain_ready&&dut.forward_ready) && drain.words>=8'),
        ('!dut.drain_valid&&!dut.probe_drain_read&&!dut.drain_busy,"stale S drain after cancel"',
         '!dut.drain_valid&&!dut.probe_drain_read&&!dut.drain_busy&&!dut.probe_forward_write&&!dut.forward_available,"stale forwarding after cancel"'),
        ('PASS DRAIN FAULT stalled-result cancel and same-model hard-reset recovery',
         'PASS FORWARD FAULT stalled-result cancel and same-model hard-reset recovery'),
    ]
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def scoreboard(source):
    return replace_once(source,'    static bool spilled', '''    static bool forwarded(unsigned frame,int matrix) {
        return frame>1&&(matrix==2||matrix==4||matrix==5);
    }
    int value(unsigned frame,int matrix,unsigned row,unsigned k) const {
        if(forwarded(frame,matrix)) {
            require(ln.output.size()==6336,"missing previous LN2 reference");
            return ln.output[row*64+k];
        }
        return DenseScoreboard::value(frame,matrix,row,k);
    }

    static bool spilled''').replace('if(matrix==1||loaded==7*count*(spill?2:1))',
        'if(matrix==1||forwarded(frame,matrix)||loaded==7*count*(spill?2:1))').replace(
        '            running=true; expected99(frame,matrix,packet);',
        '''            if(forwarded(frame,matrix))require(dut.forward_available&&loaded==0,"missing forwarded A lease");
            running=true; expected99(frame,matrix,packet);''')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    out=parser.parse_args().output.resolve(); out.mkdir(parents=True)
    evidence=ROOT/'testdata/input16_rtl_20261105'
    base=evidence/'p3_e203_compact_ln2_drain'
    ln2=evidence/'p3_e203_compact_ln2_v2'
    frozen=evidence/'trim2_e203'
    rtl=ROOT/'rtl/block_transfer'
    cpu=ROOT.parent/'e203_hbirdv2'
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    def rel(path):
        return os.path.relpath(path,ROOT).replace('\\','/')

    manifest=json.loads((base/'manifest.json').read_text())
    baseline=json.loads((base/'verification.json').read_text())
    for name,value in manifest.items():
        assert sha(base/name)==value,name
    for name,value in baseline['source_sha256'].items():
        assert sha(ROOT/name)==value,name
    top=out/'kwt_e203_dense_supply.sv'
    top.write_text(overlay((base/top.name).read_text()))
    sim=out/'forward_probe_top.sv'
    sim.write_text(overlay((base/'drain_probe_top.sv').read_text(),simulate=True))
    wrapper=out/'reference_top.sv'
    wrapper.write_text(cpu_overlay(out,cpu,frozen/'reference_top.sv',sim.read_text()))
    observer=out/'observer.cpp'
    score=out/'forward_scoreboard.hpp'
    old_score=ln2/'ln2_scoreboard.hpp'
    score.write_text(scoreboard(old_score.read_text()))
    old_probe=rtl/'compact_ln2_drain_probe.hpp'
    probe=rtl/'compact_ln2_forward_probe.hpp'
    observer.write_text(instrument((base/observer.name).read_text(),*(f'{cwd}/{rel(p)}' for p in (old_score,score,old_probe,probe))))
    core=rtl/'kwt_compact_ln2_forward.sv'
    platform=[wrapper,out/'e203_cpu_top.v',out/'e203_cpu.v']
    hardware=[ROOT/p for p in baseline['source_sha256'] if p.endswith(('.sv','.v')) and
              (p.startswith(('rtl/','../e203_hbirdv2/')) or (p.startswith(rel(ln2)+'/') and
                 Path(p).name not in {'kwt_e203_dense_supply.sv','reference_top.sv','e203_cpu_top.v','e203_cpu.v'}))]
    hardware=[p for p in hardware if p.name not in {'config.v','e203_defines.v','e203_cpu_top.v','e203_cpu.v'}]

    def linux(command,log):
        with (out/log).open('w') as fd:
            result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {command}'],
                                  stdout=fd,stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError((out/log).read_text(errors='replace')[-5000:])

    def mapping():
        lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
        script=out/'mapping.ys'
        script.write_text(f'''read_json {rel(base/'mapped.json')}
read_verilog -sv -overwrite {rel(top)} {rel(core)}
synth -top e203_subsys_nice_core -noabc -noshare
dfflibmap -liberty {rel(lib)}
abc -liberty {rel(lib)}
clean
check -assert
stat -liberty {rel(lib)}
write_json {rel(out/'mapped.json')}
''')
        linux(f'yosys -Q -s {rel(script)}','mapping.log')
        before=json.loads((base/'mapped.json').read_text())['modules']
        after=json.loads((out/'mapped.json').read_text())['modules']
        unchanged=[n for n,m in before.items() if n!='e203_subsys_nice_core' and m.get('cells')]
        assert all(graph_digest(before[n])==graph_digest(after[n]) for n in unchanged)
        return area_report(out,lib),unchanged

    def regression():
        files=' '.join(rel(p) for p in [*hardware,*platform,sim,core])
        linux(f'verilator --cc --exe --build -j 3 --no-timing -Wno-fatal --output-split 14000 '
              f'-DFPGA_SOURCE -DKWT_SIM -I../e203_hbirdv2/rtl/e203/core -Irtl/input16_trim2/generated '
              f'--top-module reference_top --Mdir {rel(out)}/model {files} {cwd}/{rel(observer)}','build.log')
        cases={}
        for case,mode in (('ready','normal'),('recovery','faults')):
            linux(f'env KWT_DRAIN_READY=1 {rel(out)}/model/Vreference_top {rel(ln2/"firmware.bin")} {rel(frozen)} 6 {mode}',f'{case}.log')
            lines=(out/f'{case}.log').read_text().splitlines()
            def metrics(prefix):
                line=next(s for s in lines if s.startswith(prefix))
                return {k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)}
            bank,forward,dense=(metrics(p) for p in ('PASS BANKS ','PASS FORWARD ','PASS DENSE '))
            assert tuple(dense[k] for k in ('reads','aux','matrices','raw','rq','residual','stats','ln','ln_writes'))==(
                361796,6580,72,684288,684288,76032,1188,76032,9504)
            assert forward['words']==9504 and forward['a_vectors']==5376 and forward['linked_qkv']==33
            old=baseline['cases']['ready']['bank']
            assert bank=={**old,'a_writes':old['a_writes']+(5376-33*448)*8}
            if case=='recovery':
                assert 'PASS FORWARD FAULT stalled-result cancel and same-model hard-reset recovery' in lines
            cases[case]=dict(bank=bank,forward=forward,dense=dense)
        assert cases['ready']==cases['recovery']
        return cases

    with ThreadPoolExecutor(max_workers=2) as pool:
        mapped=pool.submit(mapping)
        cases=regression()
        area,unchanged=mapped.result()
    sources={**baseline['source_sha256']}
    sources.update({rel(p):sha(p) for p in [Path(__file__),probe,core,top,sim,observer,score,*platform,
                    base/'verification.json',base/'manifest.json',base/'mapped.json']})
    report=dict(passed=True,actual_E203=True,full_encoder=False,supply_MBps=100,cases=cases,mismatches=0,
                baseline_cycles=baseline['cases']['ready']['dense']['cycles'],partition_standard_cell_mm2=area,
                baseline_standard_cell_mm2=baseline['partition_standard_cell_mm2'],reused_gate_modules=unchanged,
                private_macro_count=20,private_sram_bytes=65536,throughput_tasks_per_second=None,
                mean_SoC_power_mW=None,complete_counted_area_mm2=None)
    (out/'verification.json').write_text(json.dumps({**report,'source_sha256':sources},indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
