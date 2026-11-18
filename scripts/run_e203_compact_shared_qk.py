"""Run resident QK on the same E203 accelerator's Dense MAC instance."""
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


REQUESTS={
    'init':1,'valid':1,'last':1,'a':128,'b':128,'read':1,'row':4,'col':4,'tag':16,
    'raw_ready':1,'release':1,
}
RESPONSES={'init_ready':1,'ready':1,'read_ready':1,'raw':1,'raw_data':128,'raw_tag':16,'release_ready':1}


def declaration(prefix,ports):
    return ''.join(f'    {prefix} wire '+(f'[{width-1}:0] ' if width>1 else '')+f'qk_mac_{key},\n'
                   for key,width in ports.items())


def dense_overlay(source):
    source=replace_once(source,'    input wire clk,rst_n,abort,','    input wire clk,rst_n,abort,qk_owner,\n'+
                        declaration('input',REQUESTS)+declaration('output',RESPONSES).rstrip())
    response_wires=dict(init_ready='init_ready',ready='mac_ready',read_ready='read_ready',raw='raw_valid',
                        raw_data='raw_data',raw_tag='full_raw_tag',release_ready='release_ready')
    assignment=''.join(f'    assign qk_mac_{key}='+('qk_owner&&' if RESPONSES[key]==1 else '')+wire+';\n'
                       for key,wire in response_wires.items())
    edits=[
        ('    assign raw_accept = raw_valid&&raw_ready;', '''    wire dense_raw_ready;
    assign raw_ready=qk_owner?qk_mac_raw_ready:dense_raw_ready;
    assign raw_accept=!qk_owner&&raw_valid&&raw_ready;
'''+assignment.rstrip()),
        ('.init_valid(state==INIT)', '.init_valid(qk_owner?qk_mac_init:state==INIT)'),
        ('.init_bias(has_bias?biases:512\'b0)', '.init_bias(!qk_owner&&has_bias?biases:512\'b0)'),
        ('.mac_valid(state==MAC&&tile_response)', '.mac_valid(qk_owner?qk_mac_valid:(state==MAC&&tile_response))'),
        ('.mac_unsigned_a(wide&&!response_plane),.mac_shift8(response_plane),.mac_last(response_last)',
         '.mac_unsigned_a(!qk_owner&&wide&&!response_plane),.mac_shift8(!qk_owner&&response_plane),.mac_last(qk_owner?qk_mac_last:response_last)'),
        ('.mac_a(a_rdata),.mac_b(tile_data)', '.mac_a(qk_owner?qk_mac_a:a_rdata),.mac_b(qk_owner?qk_mac_b:tile_data)'),
        ('.read_valid(state==RAW)', '.read_valid(qk_owner?qk_mac_read:state==RAW)'),
        (".read_row({output_group[5:4],2'b0}),.read_col(output_group[3:0]),.read_tag({3'b0,row_group,col_tile,output_group})",
         ".read_row(qk_owner?qk_mac_row:{output_group[5:4],2'b0}),.read_col(qk_owner?qk_mac_col:output_group[3:0]),\n"
         "        .read_tag(qk_owner?qk_mac_tag:{3'b0,row_group,col_tile,output_group})"),
        ('.release_valid(state==RELEASE&&result_flush_ready)',
         '.release_valid(qk_owner?qk_mac_release:(state==RELEASE&&result_flush_ready))'),
        ('.rq_valid(raw_valid),.rq_ready(raw_ready)', '.rq_valid(!qk_owner&&raw_valid),.rq_ready(dense_raw_ready)'),
    ]
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def feed_overlay(source):
    edits=[
        ('input wire clk,rst_n,clear,','input wire clk,rst_n,clear,reuse_q,'),
        ('    reg [2:0] q_group,k_group;',
         '    reg [2:0] q_group,k_group;\n    reg cache_valid;'),
        ('quad<=0;col<=0;end\n        else if(clear)state<=IDLE;',
         'quad<=0;col<=0;cache_valid<=0;end\n        else if(clear)begin state<=IDLE;cache_valid<=0;end'),
        ('state<=query_group<7&&key_group<7?LOAD_Q:FAILED;', '''if(query_group>=7||key_group>=7)state<=FAILED;
                else if(reuse_q&&cache_valid&&query_group==q_group)state<=INIT;
                else begin state<=LOAD_Q;cache_valid<=0;end'''),
        ('state<=q_phase?INIT:READ;', 'state<=q_phase?INIT:READ;\n                        if(q_phase)cache_valid<=1;'),
    ]
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def top_overlay(source,simulate=False):
    start=source.index('    input wire qkv_read,qkv_response_ready,qkv_release,')
    end=source.index('\n',source.index('    output wire [127:0] qkv_response_data',start))
    source=source[:start]+'''    input wire qk_score_ready,
    output wire qkv_available,qk_score_valid,qk_tile_done,
    output wire [2:0] qk_query,qk_key,
    output wire [3:0] qk_row,qk_col,qk_mask,
    output wire [127:0] qk_scores'''+(',\n    input wire probe_qk_reuse,' if simulate else '')+source[end:]
    signals=declaration('',{**REQUESTS,**RESPONSES}).replace('     wire','    wire').replace(',\n',';\n')
    mac_links=''.join(f'        .qk_mac_{key}(qk_mac_{key}),\n' for key in (*REQUESTS,*RESPONSES))
    qk=f'''    reg [2:0] query_group,key_group;
    reg qk_finished;
    wire qk_clear=dense_abort||!lease_hold||!qkv_available;
    wire qk_reuse={"probe_qk_reuse" if simulate else "1'b1"};
    wire qkv_read,qkv_read_ready,qkv_response_valid,qkv_response_ready,qkv_response_error;
    wire [1:0] qkv_matrix;
    wire [8:0] qkv_index;
    wire [15:0] qkv_response_mask;
    wire [127:0] qkv_response_data;
    wire qkv_release=qkv_available&&qk_finished;
    assign qk_query=query_group;
    assign qk_key=key_group;
    always @(posedge nice_clk or negedge nice_rst_n) begin
        if(!nice_rst_n)begin query_group<=0;key_group<=0;qk_finished<=0;end
        else if(qk_clear)begin query_group<=0;key_group<=0;qk_finished<=0;end
        else if(qk_tile_done)begin
            if(key_group==6)begin
                key_group<=0;
                if(query_group==6)qk_finished<=1;
                else query_group<=query_group+1'b1;
            end else key_group<=key_group+1'b1;
        end
    end
{signals}    kwt_compact_qk_feed feed (
        .clk(nice_clk),.rst_n(nice_rst_n),.clear(qk_clear),.reuse_q(qk_reuse),
        .start(qkv_available&&!qk_finished),.start_ready(),.query_group(query_group),.key_group(key_group),
        .qkv_read(qkv_read),.qkv_ready(qkv_read_ready),.qkv_matrix(qkv_matrix),.qkv_index(qkv_index),
        .qkv_valid(qkv_response_valid),.qkv_response_ready(qkv_response_ready),.qkv_data(qkv_response_data),
        .qkv_mask(qkv_response_mask),.qkv_error(qkv_response_error),
        .a_enable(qk_a_enable),.a_write(qk_a_write),.a_addr(qk_a_addr),.a_wdata(qk_a_wdata),.a_rdata(compute_rdata[127:0]),
{mac_links}        .score_valid(qk_score_valid),.score_ready(qk_score_ready),.scores(qk_scores),
        .score_row(qk_row),.score_col(qk_col),.score_mask(qk_mask),.done(qk_tile_done),.error(qk_error));

    kwt_compact_dense dense (
        .qk_owner(qkv_available),
{mac_links.rstrip()}'''
    # Feed and Dense use different port prefixes for the same MAC wires.
    qk=qk.replace(mac_links,mac_links.replace('.qk_mac_', '.mac_'),1)
    edits=[
        ('    wire [95:0] a_addresses=', '''    wire qk_a_enable,qk_a_write,qk_error;
    wire [9:0] qk_a_addr;
    wire [127:0] qk_a_wdata;
    wire [95:0] a_addresses='''),
        ('forward_write?forward_a_index:', 'qk_a_enable?qk_a_addr:forward_write?forward_a_index:'),
        ('a_enable=forward_write?', "a_enable=qk_a_enable?8'hff:forward_write?"),
        ('a_write=forward_write?', 'a_write=qk_a_enable?{8{qk_a_write}}:forward_write?'),
        ('a_write_data=forward_write?', 'a_write_data=qk_a_enable?qk_a_wdata:forward_write?'),
        ('!capture_phase&&!drain_busy&&!forward_write&&!use_forward;',
         '!capture_phase&&!drain_busy&&!forward_write&&!use_forward&&!qkv_available;'),
        ('assign dense_error=arithmetic_error||',
         'assign dense_error=qk_error||(qk_a_enable&&(a_en||ln_a_read||wb_active||forward_write))||arithmetic_error||'),
        ('    kwt_compact_dense dense (',qk),
    ]
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def instrument(source,old_probe,probe):
    edits=[
        (old_probe,probe),('CompactQKVResidentProbe resident','CompactQKIntegratedProbe resident'),
        ('resident.drive(dut,clocks);','dut.qk_score_ready=clocks%11>=4;\n        dut.probe_qk_reuse=std::getenv("KWT_QK_RELOAD")==nullptr;'),
        ('!dut.qkv_available && !dut.qkv_response_valid','!dut.qkv_available && !dut.qk_score_valid'),
        ('dut.qkv_response_valid && !dut.qkv_response_ready && resident.words>=8',
         'dut.qk_score_valid && !dut.qk_score_ready && resident.codes>=8'),
        ('!dut.qkv_available&&!dut.qkv_response_valid&&!dut.qkv_read_ready&&!dut.probe_s_read',
         '!dut.qkv_available&&!dut.qk_score_valid&&!dut.qk_tile_done&&!dut.probe_s_read&&!dut.probe_a_read'),
        ('resident=CompactQKVResidentProbe{};', 'resident=CompactQKIntegratedProbe{};'),
        ('PASS resident_cancel vectors_before=', 'PASS shared_qk_cancel codes_before='),
        ('session.resident.words','session.resident.codes'),
        ('PASS RESIDENT FAULT','PASS SHARED_QK FAULT'),
    ]
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    out=parser.parse_args().output.resolve();out.mkdir(parents=True)
    evidence=ROOT/'testdata/input16_rtl_20261105'
    base=evidence/'p4_e203_compact_qkv_resident_v4'
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
    top.write_text(top_overlay((base/top.name).read_text()))
    sim=out/'shared_qk_probe_top.sv'
    sim.write_text(top_overlay((base/'qkv_probe_top.sv').read_text(),simulate=True))
    wrapper=out/'reference_top.sv'
    wrapper.write_text(cpu_overlay(out,cpu,frozen/'reference_top.sv',sim.read_text()))
    observer=out/'observer.cpp'
    probe=rtl/'compact_qk_integrated_probe.hpp'
    observer.write_text(instrument((base/observer.name).read_text(),
        f'{cwd}/{rel(rtl/"compact_qkv_resident_probe.hpp")}',f'{cwd}/{rel(probe)}'))
    dense_source=out/'kwt_compact_dense.sv'
    dense_source.write_text(dense_overlay((base/dense_source.name).read_text()))
    core=out/'kwt_compact_qk_feed.sv'
    original_feed=rtl/core.name
    core.write_text(feed_overlay(original_feed.read_text()))
    platform=[wrapper,out/'e203_cpu_top.v',out/'e203_cpu.v']
    hardware=[ROOT/p for p in baseline['source_sha256'] if p.endswith(('.sv','.v')) and
              (p.startswith(('rtl/','../e203_hbirdv2/')) or (p.startswith(rel(ln2)+'/') and
                 Path(p).name not in {'kwt_e203_dense_supply.sv','reference_top.sv','e203_cpu_top.v','e203_cpu.v'}))]
    hardware=[p for p in hardware if p.name not in {'config.v','e203_defines.v','e203_cpu_top.v','e203_cpu.v',dense_source.name,core.name}]

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
        for case,mode,flag in (('reuse','normal','env -u KWT_QK_RELOAD'),('reload','normal','env KWT_QK_RELOAD=1'),
                               ('recovery','faults','env -u KWT_QK_RELOAD')):
            linux(f'{flag} KWT_DRAIN_READY=1 {rel(out)}/model/Vreference_top {rel(ln2/"firmware.bin")} {rel(frozen)} 6 {mode}',f'{case}.log')
            lines=(out/f'{case}.log').read_text().splitlines()
            def metrics(prefix):
                line=next(s for s in lines if s.startswith(prefix))
                return {k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)}
            bank,forward,qk,dense=(metrics(p) for p in ('PASS BANKS ','PASS FORWARD ','PASS SHARED_QK ','PASS DENSE '))
            assert tuple(dense[k] for k in ('reads','aux','matrices','raw','rq','residual','stats','ln','ln_writes'))==(
                361796,6580,72,684288,684288,76032,1188,76032,9504)
            assert (qk['tiles'],qk['codes'],qk['beats'])==(588,117612,29700)
            old=baseline['cases']['normal']['bank']
            q_copies=7 if case=='reload' else 1
            assert bank=={**old,'s_reads':old['s_reads']-12*9568+12*3200*(7+q_copies),
                          'a_reads':old['a_reads']+12*7*448*8,'a_writes':old['a_writes']+12*q_copies*448*8}
            if case=='recovery':
                assert 'PASS SHARED_QK FAULT stalled-result cancel and same-model hard-reset recovery' in lines
            cases[case]=dict(bank=bank,forward=forward,qk=qk,dense=dense)
        assert cases['reuse']==cases['recovery']
        return cases

    with ThreadPoolExecutor(max_workers=2) as pool:
        mapped=pool.submit(mapping)
        cases=regression()
        area,unchanged=mapped.result()
    sources={**baseline['source_sha256']}
    sources.update({rel(p):sha(p) for p in [Path(__file__),probe,core,original_feed,dense_source,top,sim,observer,*platform,
                    base/'verification.json',base/'manifest.json',base/'mapped.json']})
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
