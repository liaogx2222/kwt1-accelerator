"""Bind real Q/K/V results to S SRAM in the accepted Compact forward configuration."""
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


def overlay(source,simulate=False):
    anchor='    output wire forward_ready,forward_available'+(',' if simulate else '')+'\n'
    ports='''    output wire forward_ready,forward_available,
    input wire qkv_read,qkv_response_ready,qkv_release,
    input wire [1:0] qkv_matrix,
    input wire [8:0] qkv_index,
    output wire qkv_available,qkv_read_ready,qkv_response_valid,qkv_response_error,
    output wire [15:0] qkv_response_mask,
    output wire [127:0] qkv_response_data'''
    edits=[
        (anchor,ports+(',' if simulate else '')+'\n'),
        ('    assign range_ready=physical_range_ready&&!coeff_request;', '''    wire qkv_tile=tile_id==2||tile_id==4||tile_id==5;
    reg qkv_input_done;
    wire qkv_first_input=!require_forward&&lease_hold&&!qkv_input_done;
    always @(posedge nice_clk or negedge nice_rst_n) begin
        if(!nice_rst_n)qkv_input_done<=0;
        else if(dense_abort||!lease_hold)qkv_input_done<=0;
        else if(qkv_available)qkv_input_done<=1;
    end
    wire qkv_ingest_ready,dense_result_valid;
    wire result_open=!qkv_tile||qkv_ingest_ready;
    wire [3:0] qkv_s_en,qkv_s_we;
    wire [11:0] qkv_s_addr;
    wire [63:0] qkv_s_data;
    wire qkv_s_active=|qkv_s_en;
    assign dense_valid=dense_result_valid&&result_open;
    assign range_ready=physical_range_ready&&!coeff_request&&!qkv_available;'''),
        ('ffn_start_ok&&!output_available&&!drain_busy&&!forward_write&&',
         'ffn_start_ok&&!output_available&&!drain_busy&&!forward_write&&!qkv_available&&'),
        ('(drain_read&&(ln_s_active||copy_phase||write_s));',
         '(drain_read&&(ln_s_active||copy_phase||write_s))||\n                       (qkv_s_active&&(ln_s_active||copy_read||write_s||drain_read));'),
        ('!ln_phase&&!drain_busy;', '!ln_phase&&!drain_busy&&!qkv_available&&!qkv_s_active;'),
        ('    wire [3:0] s_enable=drain_read?', '''    wire [3:0] first_input_mask;
    for (genvar i=0;i<4;i=i+1) begin: input_tail
        wire [11:0] addr=scratch_addr[i*12+:12];
        assign first_input_mask[i]=!qkv_first_input||addr<1536||addr>=1792||(i<2&&!addr[0]);
    end
    wire [3:0] copy_mask=qkv_first_input&&qkv_tile&&copy_addr>=1536 ?
                         (copy_addr[0]?4'h0:4'h3):4'hf;
    wire [3:0] s_enable=qkv_s_active?qkv_s_en:drain_read?'''),
        ('copy_phase?{4{copy_read}}:write_s?ffn_s_write:(scratch_ready?scratch_en:4\'b0)',
         'copy_phase?(copy_mask&{4{copy_read}}):write_s?ffn_s_write:(scratch_ready?(scratch_en&first_input_mask):4\'b0)'),
        ('s_write=drain_read?', 's_write=qkv_s_active?qkv_s_we:drain_read?'),
        ('s_address=drain_read?', 's_address=qkv_s_active?{4{qkv_s_addr}}:drain_read?'),
        ('s_wdata=ln_s_active?', 's_wdata=qkv_s_active?qkv_s_data:ln_s_active?'),
        ('.range_valid(coeff_request||range_valid)', '.range_valid(coeff_request||(range_valid&&!qkv_available))'),
        ('!drain_busy&&!forward_write),', '!drain_busy&&!forward_write&&!qkv_available),'),
        ('.result_valid(dense_valid),\n        .result_ready(dense_result_ready)',
         '.result_valid(dense_result_valid),\n        .result_ready(dense_result_ready&&result_open),.result_flush_ready(result_open)'),
        ('    kwt_compact_dense dense (','''    kwt_compact_qkv_resident qkv (
        .clk(nice_clk),.rst_n(nice_rst_n),.clear(dense_abort||!lease_hold),
        .result_valid(qkv_tile&&dense_valid&&dense_result_ready),.result_ready(qkv_ingest_ready),
        .matrix(tile_id),.tag(dense_tag),.result(dense_data),.matrix_done(dense_done),
        .available(qkv_available),.release_result(qkv_release),
        .read_valid(qkv_read),.read_ready(qkv_read_ready),.read_matrix(qkv_matrix),.read_index(qkv_index),
        .response_valid(qkv_response_valid),.response_ready(qkv_response_ready),
        .response_data(qkv_response_data),.response_mask(qkv_response_mask),.response_error(qkv_response_error),
        .s_en(qkv_s_en),.s_we(qkv_s_we),.s_addr(qkv_s_addr),.s_wdata(qkv_s_data),.s_rdata(scratch_rdata));

    kwt_compact_dense dense ('''),
    ]
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def instrument(source,probe):
    edits=[
        ('namespace {',f'#include "{probe}"\n\nnamespace {{'),
        ('    CompactLN2DrainProbe drain;','    CompactLN2DrainProbe drain;\n    CompactQKVResidentProbe resident;'),
        ('(6167u<<4)|3u','(14407u<<4)|3u'),
        ('dense.matrices==6','dense.matrices==3'),
        ('!dut.drain_valid && !dut.probe_drain_read && !dut.drain_busy,"failed to invalidate S drain"',
         '!dut.qkv_available && !dut.qkv_response_valid,"failed to invalidate Q/K/V S ownership"'),
        ('        dense.drive(dut,frame,tile?r->matrix:-1,clocks);',
         '        dense.drive(dut,frame,tile?r->matrix:-1,clocks);\n        resident.drive(dut,clocks);'),
        ('dut.drain_valid && !(dut.drain_ready&&dut.forward_ready) && drain.words>=8',
         'dut.qkv_response_valid && !dut.qkv_response_ready && resident.words>=8'),
        ('            drain.held=false;', '            resident.held=false;'),
        ('!dut.drain_valid&&!dut.probe_drain_read&&!dut.drain_busy&&!dut.probe_forward_write&&!dut.forward_available,"stale forwarding after cancel"',
         '!dut.qkv_available&&!dut.qkv_response_valid&&!dut.qkv_read_ready&&!dut.probe_s_read,"stale Q/K/V response after cancel"'),
        ('        dense.observe(dut,frame,tile?r->matrix:-1,packets[frame<13?frame:12]);',
         '''        dense.observe(dut,frame,tile?r->matrix:-1,packets[frame<13?frame:12]);
        resident.observe(dut,dense.expected_rq);'''),
        ('            drain.report();','            drain.report();\n            resident.report();'),
        ('        drain=CompactLN2DrainProbe{};', '        drain=CompactLN2DrainProbe{};\n        resident=CompactQKVResidentProbe{};'),
        ('PASS drain_cancel words_before=%llu reads_before=%llu error_index=6167',
         'PASS resident_cancel vectors_before=%llu stalls_before=%llu error_index=14407'),
        ('(unsigned long long)session.drain.words,(unsigned long long)session.drain.reads',
         '(unsigned long long)session.resident.words,(unsigned long long)session.resident.stalls'),
        ('PASS FORWARD FAULT stalled-result cancel and same-model hard-reset recovery',
         'PASS RESIDENT FAULT stalled-result cancel and same-model hard-reset recovery'),
    ]
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def dense_flush(source):
    # A full V writeback may outlive the last RQ beat by four cycles.
    # Retain ownership until it drains before starting another S-to-A copy.
    source=replace_once(source,'    input wire result_ready,','    input wire result_ready,result_flush_ready,')
    source=replace_once(source,'.release_valid(state==RELEASE)', '.release_valid(state==RELEASE&&result_flush_ready)')
    return replace_once(source,'RELEASE: if(release_ready)', 'RELEASE: if(release_ready&&result_flush_ready)')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    out=parser.parse_args().output.resolve();out.mkdir(parents=True)
    evidence=ROOT/'testdata/input16_rtl_20261105'
    base=evidence/'p4_e203_compact_forward_v3'
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
    sim=out/'qkv_probe_top.sv'
    sim.write_text(overlay((base/'forward_probe_top.sv').read_text(),simulate=True))
    wrapper=out/'reference_top.sv'
    wrapper.write_text(cpu_overlay(out,cpu,frozen/'reference_top.sv',sim.read_text()))
    observer=out/'observer.cpp'
    probe=rtl/'compact_qkv_resident_probe.hpp'
    observer.write_text(instrument((base/observer.name).read_text(),f'{cwd}/{rel(probe)}'))
    core=rtl/'kwt_compact_qkv_resident.sv'
    dense_source=out/'kwt_compact_dense.sv'
    dense_source.write_text(dense_flush((ln2/dense_source.name).read_text()))
    platform=[wrapper,out/'e203_cpu_top.v',out/'e203_cpu.v']
    hardware=[ROOT/p for p in baseline['source_sha256'] if p.endswith(('.sv','.v')) and
              (p.startswith(('rtl/','../e203_hbirdv2/')) or (p.startswith(rel(ln2)+'/') and
                 Path(p).name not in {'kwt_e203_dense_supply.sv','reference_top.sv','e203_cpu_top.v','e203_cpu.v'}))]
    hardware=[p for p in hardware if p.name not in {'config.v','e203_defines.v','e203_cpu_top.v','e203_cpu.v',dense_source.name}]

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
read_verilog -sv -overwrite {rel(top)} {rel(core)} {rel(dense_source)}
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
        unchanged=[n for n,m in before.items() if n not in {'e203_subsys_nice_core','kwt_compact_dense'} and m.get('cells')]
        assert all(graph_digest(before[n])==graph_digest(after[n]) for n in unchanged)
        return area_report(out,lib),unchanged

    def regression():
        files=' '.join(rel(p) for p in [*hardware,*platform,sim,core,dense_source])
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
            bank,forward,resident,dense=(metrics(p) for p in ('PASS BANKS ','PASS FORWARD ','PASS RESIDENT ','PASS DENSE '))
            assert tuple(dense[k] for k in ('reads','aux','matrices','raw','rq','residual','stats','ln','ln_writes'))==(
                361796,6580,72,684288,684288,76032,1188,76032,9504)
            assert (resident['vectors'],resident['codes'],resident['rejected'])==(15504,228096,12)
            old=baseline['cases']['ready']['bank']
            expected=12*(2*3200+3168)
            assert bank=={**old,'s_reads':old['s_reads']+expected-9216,
                          's_writes':old['s_writes']+expected-2304}
            if case=='recovery':
                assert 'PASS RESIDENT FAULT stalled-result cancel and same-model hard-reset recovery' in lines
            cases[case]=dict(bank=bank,forward=forward,resident=resident,dense=dense)
        assert cases['normal']==cases['recovery']
        return cases

    with ThreadPoolExecutor(max_workers=2) as pool:
        mapped=pool.submit(mapping)
        cases=regression()
        area,unchanged=mapped.result()
    sources={**baseline['source_sha256']}
    sources.update({rel(p):sha(p) for p in [Path(__file__),probe,core,dense_source,top,sim,observer,*platform,
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
