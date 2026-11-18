"""Exercise real E203 QK, B-score storage and the compressed exp Softmax."""
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


B_PORTS='''    input wire [7:0] score_b_en,score_b_we,
    input wire [9:0] score_b_addr,
    input wire [127:0] score_b_wdata,
    output wire score_b_conflict,
'''
B_LINKS='''        .score_b_en(score_b_en),.score_b_we(score_b_we),.score_b_addr(score_b_addr),
        .score_b_wdata(score_b_wdata),.score_b_conflict(score_b_conflict),
'''


def banks_overlay(source):
    source=replace_once(source,'    input wire [11:0] compute_en,', B_PORTS.replace('output wire','output reg')+'    input wire [11:0] compute_en,')
    source=replace_once(source,'    assign bank_grant', '''    wire score_collision=(|score_b_en)&&(write_first||write_second||read_b||tile_valid);
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)score_b_conflict<=0;
        else score_b_conflict<=score_collision;
    end
    assign bank_grant''')
    return replace_once(source,'''        kwt_small_sp weight(clk,wb0||wb1||read_b,wb0||wb1,
                            wb0 ? mapped_addr : wb1 ? write_addr : tile_addr,
                            wb0 ? sink_data[15:0] : high_half,tile_data[16*bank+:16]);''','''        wire score_use=allowed&&score_b_en[bank]&&!score_collision;
        kwt_small_sp weight(clk,wb0||wb1||read_b||score_use,wb0||wb1||(score_use&&score_b_we[bank]),
                            wb0 ? mapped_addr : wb1 ? write_addr : score_use ? score_b_addr : tile_addr,
                            wb0 ? sink_data[15:0] : wb1 ? high_half : score_b_wdata[16*bank+:16],tile_data[16*bank+:16]);''')


def body_overlay(source):
    source=replace_once(source,'    input wire [11:0] compute_en,',B_PORTS+'    input wire [11:0] compute_en,')
    return replace_once(source,'        .compute_en(compute_en)',B_LINKS+'        .compute_en(compute_en)')


def overlay(source,simulate=False):
    ports='''    input wire sm_prob_ready,
    output wire qk_score_ready,sm_prob_valid,
    output wire [3:0] sm_row,
    output wire [6:0] sm_index,
    output wire [15:0] sm_prob,
'''
    if simulate:
        ports+='''    output wire probe_sm_score_fire,probe_exp_fire,
    output wire [31:0] probe_sm_score,
    output wire [12:0] probe_exp_index,
    output wire [7:0] probe_b_read,probe_b_write,
'''
    edits=[
        ('    input wire qk_score_ready,\n',ports),
        ('wire [95:0] a_addresses=', 'wire [95:0] a_addresses,a_base_addresses='),
        ('a_enable=qk_a_enable?', 'a_enable=exp_active?exp_banks_en:qk_a_enable?'),
        ('a_write=qk_a_enable?', 'a_write=exp_active?exp_banks_we:qk_a_enable?'),
        ('a_write_data=qk_a_enable?', 'a_write_data=exp_active?exp_banks_data:qk_a_enable?'),
        ('    assign aux_valid=physical_aux_valid&&!coeff_phase;',
         '    assign aux_valid=physical_aux_valid&&!coeff_phase&&(!common_lease||exp_load_ready);'),
        ('aux_ready(coeff_phase?coeff_ready:aux_ready)', 'aux_ready(coeff_phase?coeff_ready:(aux_ready&&(!common_lease||exp_load_ready)))'),
        ('        .compute_en({s_enable,a_enable})',B_LINKS+'        .compute_en({s_enable,a_enable})'),
        ('assign dense_error=qk_error||', '''assign dense_error=qk_error||sm_error||exp_load_error||score_b_conflict||
                       (qkv_available&&(!exp_cached||score_loaded!=2'b11))||
                       (exp_active&&(qk_a_enable||a_en||ln_a_read||wb_active||forward_write))||'''),
        ('''        else if(qk_tile_done)begin
            if(key_group==6)begin
                key_group<=0;
                if(query_group==6)qk_finished<=1;
                else query_group<=query_group+1'b1;
            end else key_group<=key_group+1'b1;
        end''','''        else if(sm_group_done)begin
            key_group<=0;
            if(query_group==6)qk_finished<=1;
            else query_group<=query_group+1'b1;
        end else if(qk_tile_done&&key_group!=6)key_group<=key_group+1'b1;'''),
        ('.start(qkv_available&&!qk_finished),.start_ready()',
         '.start(qkv_available&&!qk_finished&&sm_qk_open&&!(qk_tile_done&&key_group==6)),.start_ready()'),
        ('    kwt_compact_qk_feed feed (','''    wire common_lease=lease_hold&&lease_words==4144;
    reg exp_started;
    reg [1:0] score_loaded;
    reg [31:0] score_m;
    reg [5:0] score_shift;
    wire exp_start=common_lease&&!exp_started&&physical_aux_valid&&aux_index==48;
    wire exp_start_ready,exp_load_ready,exp_load_error,exp_cached;
    always @(posedge nice_clk or negedge nice_rst_n) begin
        if(!nice_rst_n)begin exp_started<=0;score_loaded<=0;score_m<=0;score_shift<=0;end
        else if(dense_abort||!lease_hold)begin exp_started<=0;score_loaded<=0;end
        else begin
            if(exp_start&&exp_start_ready)exp_started<=1;
            if(aux_valid&&aux_ready&&!common_lease)begin
                if(aux_index==14272)begin score_m<=aux_data;score_loaded[0]<=1;end
                if(aux_index==14276)begin score_shift<=aux_data[5:0];score_loaded[1]<=aux_data<64;end
            end
        end
    end
    wire exp_query,exp_ready,exp_resp_valid,exp_resp_ready,exp_error;
    wire [12:0] exp_index;
    wire [20:0] exp_value;
    wire [7:0] exp_banks_en,exp_banks_we;
    wire [79:0] exp_banks_addr;
    wire [127:0] exp_banks_data;
    wire exp_active=|exp_banks_en;
    for(genvar ea=0;ea<8;ea=ea+1)begin: exp_a_addr
        assign a_addresses[12*ea+:12]=exp_active?{2'd0,exp_banks_addr[10*ea+:10]}:a_base_addresses[12*ea+:12];
    end
    kwt_compact_exp_cache exp_cache (
        .clk(nice_clk),.rst_n(nice_rst_n),.abort(dense_abort),
        .load_start(exp_start),.load_start_ready(exp_start_ready),.load_valid(common_lease&&aux_valid&&aux_ready),
        .load_ready(exp_load_ready),.load_data(aux_data),.load_last(aux_index==4143),
        .cache_valid(exp_cached),.load_error(exp_load_error),
        .query_valid(exp_query),.query_ready(exp_ready),.query_index(exp_index),
        .response_valid(exp_resp_valid),.response_ready(exp_resp_ready),.response_data(exp_value),.response_error(exp_error),
        .bank_en(exp_banks_en),.bank_we(exp_banks_we),.bank_addr(exp_banks_addr),.bank_wdata(exp_banks_data),
        .bank_rdata(compute_rdata[127:0]));

    wire sm_qk_open,sm_group_done,sm_error,sm_score_fire;
    wire signed [31:0] sm_score_data;
    wire [7:0] score_b_en,score_b_we;
    wire [9:0] score_b_addr;
    wire [127:0] score_b_wdata;
    wire score_b_conflict;
    kwt_compact_qk_softmax softmax (
        .clk(nice_clk),.rst_n(nice_rst_n),.clear(qk_clear),
        .start(qkv_available&&!qk_finished),.tail(query_group==6),.qk_open(sm_qk_open),
        .qk_end(qk_tile_done&&key_group==6),.qk_valid(qk_score_valid),.qk_ready(qk_score_ready),
        .qk_quad(qk_row[3:2]),.qk_key({key_group,qk_col}),.qk_mask(qk_mask),.qk_scores(qk_scores),
        .score_m(score_m),.score_shift(score_shift),.exp_valid(exp_query),.exp_ready(exp_ready),.exp_index(exp_index),
        .exp_resp_valid(exp_resp_valid),.exp_resp_ready(exp_resp_ready),.exp_value(exp_value),.exp_error(exp_error),
        .b_en(score_b_en),.b_we(score_b_we),.b_addr(score_b_addr),.b_wdata(score_b_wdata),.b_rdata(tile_data),
        .score_fire(sm_score_fire),.score_data(sm_score_data),.prob_valid(sm_prob_valid),.prob_ready(sm_prob_ready),
        .prob_row(sm_row),.prob_index(sm_index),.prob(sm_prob),.done(sm_group_done),.error(sm_error));

    kwt_compact_qk_feed feed ('''),
    ]
    if simulate:
        edits.append(('    assign probe_capture=ln_a_read;', '''    assign probe_sm_score_fire=sm_score_fire;
    assign probe_sm_score=sm_score_data;
    assign probe_exp_fire=exp_query&&exp_ready;
    assign probe_exp_index=exp_index;
    assign probe_b_read=score_b_en&~score_b_we;
    assign probe_b_write=score_b_en&score_b_we;
    assign probe_capture=ln_a_read;'''))
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def instrument(source,old_qk,qk,probe):
    edits=[
        (old_qk,qk),('namespace {',f'#include "{probe}"\n\nnamespace {{'),
        ('return {{13232,1024,4}', 'return {{14272,5,-1},{13232,1024,4}'),
        ('    CompactQKIntegratedProbe resident;', '    CompactQKIntegratedProbe resident;\n    CompactSoftmaxIntegratedProbe softmax;'),
        ('dut.qk_score_ready=clocks%11>=4;', 'dut.sm_prob_ready=clocks%11>=4;'),
        ('dut.probe_qk_reuse=std::getenv("KWT_QK_RELOAD")==nullptr;', 'dut.probe_qk_reuse=1;'),
        ('!dut.qkv_available && !dut.qk_score_valid', '!dut.qkv_available && !dut.sm_prob_valid'),
        ('dut.qk_score_valid && !dut.qk_score_ready && resident.codes>=8',
         'dut.sm_prob_valid && !dut.sm_prob_ready && softmax.codes>=8'),
        ('            resident.held=false;', '            softmax.held=false;'),
        ('!dut.qkv_available&&!dut.qk_score_valid&&!dut.qk_tile_done&&!dut.probe_s_read&&!dut.probe_a_read',
         '!dut.qkv_available&&!dut.sm_prob_valid&&!dut.probe_b_read&&!dut.probe_b_write&&!dut.probe_exp_fire'),
        ('        resident.observe(dut,dense.expected_rq);',
         '        resident.observe(dut,dense.expected_rq);\n        softmax.observe(dut,packets[frame<13?frame:12],packets[0]);'),
        ('reads==361796 && writes==189328 && aux==6580','reads==361856 && writes==189328 && aux==6640'),
        ('            resident.report();','            resident.report();\n            softmax.report();'),
        ('        resident=CompactQKIntegratedProbe{};',
         '        resident=CompactQKIntegratedProbe{};\n        softmax=CompactSoftmaxIntegratedProbe{};'),
        ('PASS shared_qk_cancel codes_before=', 'PASS softmax_cancel codes_before='),
        ('session.resident.codes,(unsigned long long)session.resident.stalls',
         'session.softmax.codes,(unsigned long long)session.softmax.stalls'),
        ('PASS SHARED_QK FAULT', 'PASS E203_SOFTMAX FAULT'),
    ]
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    out=parser.parse_args().output.resolve();out.mkdir(parents=True)
    evidence=ROOT/'testdata/input16_rtl_20261105'
    base=evidence/'p4_e203_compact_shared_qk_v1'
    exp_base=evidence/'p4_compact_softmax_storage_v2'
    b_base=evidence/'p4_compact_qk_score_store_v3'
    ln2=evidence/'p3_e203_compact_ln2_v2'
    frozen=evidence/'trim2_e203'
    rtl=ROOT/'rtl/block_transfer'
    cpu=ROOT.parent/'e203_hbirdv2'
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    def rel(path):
        return os.path.relpath(path,ROOT).replace('\\','/')

    for folder in (base,exp_base,b_base):
        manifest=json.loads((folder/'manifest.json').read_text())
        for name,value in manifest.items():
            assert sha(folder/name)==value,name
    baseline=json.loads((base/'verification.json').read_text())
    for name,value in baseline['source_sha256'].items():
        assert sha(ROOT/name)==value,name
    top=out/'kwt_e203_dense_supply.sv'
    top.write_text(overlay((base/top.name).read_text()))
    sim=out/'softmax_probe_top.sv'
    sim.write_text(overlay((base/'shared_qk_probe_top.sv').read_text(),simulate=True))
    wrapper=out/'reference_top.sv'
    wrapper.write_text(cpu_overlay(out,cpu,frozen/'reference_top.sv',sim.read_text()))
    observer=out/'observer.cpp'
    old_qk=rtl/'compact_qk_integrated_probe.hpp'
    qk_probe=out/old_qk.name
    qk_probe.write_text(replace_once(old_qk.read_text(),'&&stalls>0','&&stalls==0'))
    probe=rtl/'compact_softmax_integrated_probe.hpp'
    observer.write_text(instrument((base/observer.name).read_text(),*(f'{cwd}/{rel(p)}' for p in (old_qk,qk_probe,probe))))
    body=out/'kwt_e203_dense_body.sv'
    body.write_text(body_overlay((ln2/body.name).read_text()))
    reader=ln2/'kwt_indexed_block_reader.sv'
    banks=out/'kwt_indexed_weight_banks.sv'
    banks.write_text(banks_overlay((ln2/banks.name).read_text()))
    added=[body,banks,rtl/'kwt_compact_qk_softmax.sv',rtl/'kwt_compact_qk_score_store.sv',
           rtl/'kwt_compact_exp_cache.sv',exp_base/'kwt_compact_softmax_row.sv']
    platform=[wrapper,out/'e203_cpu_top.v',out/'e203_cpu.v']
    skips={'config.v','e203_defines.v','e203_cpu_top.v','e203_cpu.v','kwt_e203_dense_supply.sv','reference_top.sv',
           'kwt_compact_dense.sv','kwt_compact_qk_feed.sv',body.name,banks.name}
    hardware=[ROOT/p for p in baseline['source_sha256'] if p.endswith(('.sv','.v')) and
              p.startswith(('rtl/','../e203_hbirdv2/',rel(ln2)+'/')) and Path(p).name not in skips]
    hardware.extend(base/n for n in ('kwt_compact_dense.sv','kwt_compact_qk_feed.sv'))

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
read_verilog -sv -overwrite -Irtl/input16_trim2/generated {' '.join(rel(p) for p in [top,reader,*added])}
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
        changed={'e203_subsys_nice_core','kwt_e203_dense_body','kwt_indexed_weight_banks'}
        unchanged=[n for n,m in before.items() if n not in changed and 'kwt_indexed_block_reader' not in n and m.get('cells')]
        assert all(graph_digest(before[n])==graph_digest(after[n]) for n in unchanged)
        return area_report(out,lib),unchanged

    def regression():
        files=' '.join(rel(p) for p in [*hardware,*platform,sim,*added])
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
            bank,forward,qk,sm,dense=(metrics(p) for p in ('PASS BANKS ','PASS FORWARD ','PASS SHARED_QK ','PASS E203_SOFTMAX ','PASS DENSE '))
            assert (sm['rows'],sm['codes'],sm['indices'],sm['b_reads'],sm['b_writes'])==(1188,117612,117612,235224,235224)
            assert (dense['cycles']>baseline['cases']['reuse']['dense']['cycles']) and dense['reads']==361856
            assert bank['a_writes']==baseline['cases']['reuse']['bank']['a_writes']+2512
            if case=='recovery':
                assert 'PASS E203_SOFTMAX FAULT stalled-result cancel and same-model hard-reset recovery' in lines
            cases[case]=dict(bank=bank,forward=forward,qk=qk,softmax=sm,dense=dense)
        assert cases['normal']==cases['recovery']
        return cases

    with ThreadPoolExecutor(max_workers=2) as pool:
        mapped=pool.submit(mapping)
        cases=regression()
        area,unchanged=mapped.result()
    sources={**baseline['source_sha256']}
    sources.update({rel(p):sha(p) for p in [Path(__file__),probe,qk_probe,top,sim,observer,*platform,*added,
                    base/'verification.json',base/'manifest.json',base/'mapped.json',exp_base/'manifest.json',b_base/'manifest.json']})
    report=dict(passed=True,actual_E203=True,full_encoder=False,supply_MBps=100,cases=cases,mismatches=0,
                baseline_cycles=baseline['cases']['reuse']['dense']['cycles'],partition_standard_cell_mm2=area,
                baseline_standard_cell_mm2=baseline['partition_standard_cell_mm2'],reused_gate_modules=unchanged,
                private_macro_count=20,private_sram_bytes=65536,throughput_tasks_per_second=None,
                mean_SoC_power_mW=None,complete_counted_area_mm2=None)
    (out/'verification.json').write_text(json.dumps({**report,'source_sha256':sources},indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
