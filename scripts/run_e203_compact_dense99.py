"""Replay all 99 rows per matrix on real E203 and the compact A/B/S bank RTL."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from local_tools import ROOT, sha
from run_e203_compact_dense import check_coefficients
from run_e203_compact_supply import cpu_overlay, replace_once


def controller(source):
    edits=[
        ('// One group of 16 rows against the full resident B matrix. A holds low-byte\n'
         '// planes at [0,K) and, for first-layer S16, high-byte planes at [K,2K).\n'
         '// The owner of the A port supplies a complete group before starting.',
         '// Seven row groups reuse one coefficient tile and a resident B matrix.'),
        ('output wire [9:0] raw_tag,','output wire [12:0] raw_tag,\n    output wire [3:0] raw_mask,'),
        ('output wire [9:0] result_tag,','output wire [12:0] result_tag,\n    output wire [3:0] result_mask,'),
        ('output wire coeff_phase,mac_phase,rq_phase\n',
         '''output wire coeff_phase,mac_phase,rq_phase,
    output wire copy_phase,copy_read,copy_write,
    output wire [11:0] copy_addr,
    input wire [63:0] copy_data
'''),
        ('DRAIN=6, RELEASE=7, FINISH=8, FAILED=9;', 'DRAIN=6, RELEASE=7, FINISH=8, FAILED=9, COPY_REQ=10, COPY_WAIT=11;'),
        ('    reg [7:0] red;', '    reg [7:0] red;\n    reg [2:0] row_group;'),
        ('    wire local_rst_n = rst_n&&!abort;',
         '''    wire local_rst_n = rst_n&&!abort;
    wire spill = wide || matrix==1;
    wire [5:0] last_output = row_group==6 ? 6'd15 : 6'd63;
    wire [8:0] copied_addr;
    wire [127:0] copied_data;
    wire copy_idle,copy_done;
    assign copy_phase=state==COPY_REQ || state==COPY_WAIT;
    kwt_dense_s_to_a copier (
        .clk(clk),.rst_n(local_rst_n),.start(state==COPY_REQ),.idle(copy_idle),.done(copy_done),
        .start_addr(matrix==1 ? {row_group,9'b0} : {1'b0,row_group,8'b0}),
        .vectors(wide?9'd128:9'd256),.s_read(copy_read),.s_addr(copy_addr),.s_data(copy_data),
        .a_write(copy_write),.a_addr(copied_addr),.a_data(copied_data));
'''),
        ('''    assign a_we = act_write&&act_ready;
    assign a_en = a_we||read_fire;
    assign a_addr = a_we ? {1'b0,act_addr} :
                    matrix==1 ? {1'b0,plane,red} : {3'b0,plane,red[5:0]};
    assign a_wdata = act_data;''',
         '''    assign a_we = copy_write || (act_write&&act_ready);
    assign a_en = a_we||read_fire;
    assign a_addr = copy_write ? {1'b0,copied_addr} : a_we ? {1'b0,act_addr} :
                    !spill ? {1'b0,row_group,red[5:0]} :
                    matrix==1 ? {1'b0,plane,red} : {3'b0,plane,red[5:0]};
    assign a_wdata = copy_write ? copied_data : act_data;'''),
        ('    assign raw_tag = full_raw_tag[9:0];\n    assign result_tag = full_result_tag[9:0];',
         '''    assign raw_tag = full_raw_tag[12:0];
    assign result_tag = full_result_tag[12:0];
    assign raw_mask = raw_tag[12:10]==6 ? 4'b0111 : 4'b1111;
    assign result_mask = result_tag[12:10]==6 ? 4'b0111 : 4'b1111;'''),
        ('{6\'b0,col_tile,output_group}', "{3'b0,row_group,col_tile,output_group}"),
        ('state<=IDLE; matrix<=0; wide<=0; col_tile<=0; coeff_kind<=0; element<=0;',
         'state<=IDLE; matrix<=0; wide<=0; col_tile<=0; coeff_kind<=0; element<=0; row_group<=0;'),
        ('matrix<=tile_id; wide<=wide_a; col_tile<=0; coeff_kind<=0;\n                state<=tile_id<6 ? COEFF_REQ : FAILED;',
         '''matrix<=tile_id; wide<=wide_a; col_tile<=0; coeff_kind<=0; row_group<=0;
                state<=tile_id<6 && (!wide_a||tile_id==2||tile_id==4||tile_id==5) ? COEFF_REQ : FAILED;'''),
        ('if(coeff_kind==2 || (coeff_kind==1&&!has_bias)) state<=INIT;',
         'if(coeff_kind==2 || (coeff_kind==1&&!has_bias)) state<=spill?COPY_REQ:INIT;'),
        ('            INIT: if(init_ready)', '''            COPY_REQ: if(copy_idle) state<=COPY_WAIT;
            COPY_WAIT: if(copy_done) state<=INIT;
            INIT: if(init_ready)'''),
        ('if(output_group==63)', 'if(output_group==last_output)'),
        ('result_tag[5:0]==63', 'result_tag[5:0]==last_output'),
        ('''                if(last_col) state<=FINISH;
                else begin col_tile<=col_tile+1'b1; coeff_kind<=0; state<=COEFF_REQ; end''',
         '''                if(row_group!=6) begin
                    row_group<=row_group+1'b1; state<=spill?COPY_REQ:INIT;
                end else if(last_col) state<=FINISH;
                else begin col_tile<=col_tile+1'b1; row_group<=0; coeff_kind<=0; state<=COEFF_REQ; end'''),
    ]
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def top_overlay(source):
    edits=[
        ('output wire [9:0] raw_tag,','output wire [12:0] raw_tag,\n    output wire [3:0] raw_mask,'),
        ('output wire [9:0] dense_tag,','output wire [12:0] dense_tag,\n    output wire [3:0] dense_mask,'),
        ('    output wire [63:0] scratch_rdata\n','''    output wire [63:0] scratch_rdata,
    output wire scratch_ready,copy_phase,copy_read,copy_write
'''),
        ('    assign scratch_rdata=compute_rdata[191:128];','''    assign scratch_rdata=compute_rdata[191:128];
    wire [11:0] copy_addr;
    assign scratch_ready=nice_rst_n&&!dense_abort&&!copy_phase;
    wire [3:0] s_enable=copy_phase?{4{copy_read}}:(scratch_ready?scratch_en:4'b0);
    wire [3:0] s_write=copy_phase?4'b0:scratch_we;
    wire [47:0] s_address=copy_phase?{4{copy_addr}}:scratch_addr;'''),
        ('.compute_en({scratch_en,{8{a_en}}}),.compute_we({scratch_we,{8{a_we}}}),',
         '.compute_en({s_enable,{8{a_en}}}),.compute_we({s_write,{8{a_we}}}),'),
        ('.compute_addr({scratch_addr,a_addresses})','.compute_addr({s_address,a_addresses})'),
        ('.raw_accept(raw_accept),.raw_tag(raw_tag),.raw_data(raw_data)',
         '.raw_accept(raw_accept),.raw_tag(raw_tag),.raw_mask(raw_mask),.raw_data(raw_data)'),
        ('.result_ready(dense_result_ready),.result_tag(dense_tag),.result_data(dense_data)',
         '.result_ready(dense_result_ready),.result_tag(dense_tag),.result_mask(dense_mask),.result_data(dense_data)'),
        ('.coeff_phase(coeff_phase),.mac_phase(mac_phase),.rq_phase(rq_phase));',
         '''.coeff_phase(coeff_phase),.mac_phase(mac_phase),.rq_phase(rq_phase),
        .copy_phase(copy_phase),.copy_read(copy_read),.copy_write(copy_write),
        .copy_addr(copy_addr),.copy_data(scratch_rdata));'''),
    ]
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def observer(source, header):
    source=re.sub(r'#include "[^"]*/compact_dense_scoreboard.hpp"',f'#include "{header}"',source,count=1)
    source=replace_once(source,'    DenseScoreboard dense;', '    Dense99Scoreboard dense;')
    source=replace_once(source,'dense.raw_codes==110592 && dense.rq_codes==110592',
                        '''dense.raw_codes==684288 && dense.rq_codes==684288 && dense.masked==6912 &&
                  dense.writes==25536 && dense.scratch_writes==48384 && dense.copy_reads==193536 &&
                  dense.copy_writes==96768''')
    source=replace_once(source,'stalls=%llu saturation=%llu','stalls=%llu saturation=%llu scratch=%llu copy_reads=%llu copy_writes=%llu copy=%llu masked=%llu')
    source=replace_once(source,'(unsigned long long)dense.saturations);',
                        '''(unsigned long long)dense.saturations,(unsigned long long)dense.scratch_writes,
                (unsigned long long)dense.copy_reads,(unsigned long long)dense.copy_writes,
                (unsigned long long)dense.copy_cycles,(unsigned long long)dense.masked);''')
    return source


def area_report(out,lib):
    design=json.loads((out/'mapped.json').read_text())['modules']
    areas={name:float(a) for name,a in re.findall(r'cell\s*\(\s*(\w+)\s*\)\s*\{.*?area\s*:\s*([\d.]+)',lib.read_text(),re.S)}
    counts={}
    def expand(name):
        if name in counts:
            return counts[name]
        result=Counter()
        for cell in design[name]['cells'].values():
            t=cell['type']
            if t in areas or t.startswith('kwt_tech_sram_'):
                result[t]+=1
            else:
                result.update(expand(t))
        counts[name]=result
        return result
    cells=expand('e203_subsys_nice_core')
    assert [cells[f'kwt_tech_sram_{d}x16'] for d in (1024,4096)]==[16,4]
    return sum(areas[k]*n for k,n in cells.items() if k in areas)/1e6


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--no-map',action='store_true')
    args=parser.parse_args()
    out=args.output.resolve()
    out.mkdir(parents=True)
    rel=out.relative_to(ROOT).as_posix()
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    base=ROOT/'testdata/input16_rtl_20261105'
    previous=base/'p3_e203_compact_dense_right'
    frozen=base/'trim2_e203'
    cpu=ROOT.parent/'e203_hbirdv2'
    rtl=ROOT/'rtl/block_transfer'
    trim=ROOT/'rtl/input16_trim2'
    old_top=rtl/'kwt_e203_dense_supply.sv'
    old_dense=rtl/'kwt_compact_dense.sv'
    copier=rtl/'kwt_dense_s_to_a.sv'
    score=rtl/'compact_dense99_scoreboard.hpp'
    sram=trim/'kwt_sram_sp.sv'
    math=[ROOT/'rtl/micro/mul_pipe.sv',rtl/'kwt_rne_dense_right.sv']
    previous_inputs=[previous/n for n in ('kwt_e203_dense_body.sv','kwt_indexed_block_reader.sv',
                                          'kwt_indexed_weight_banks.sv','arithmetic.sv','firmware.bin','observer.cpp')]
    packets=[frozen/f'layer_{i:02d}.bin.hex' for i in range(12)]
    fixtures=[*packets,frozen/'common.bin.hex',frozen/'input_000.hex',frozen/'reference_top.sv']
    for folder,inputs in ((previous,previous_inputs),(frozen,fixtures)):
        manifest=json.loads((folder/'manifest.json').read_text())
        for p in inputs:
            assert sha(p)==manifest[p.name],p
    prior=json.loads((previous/'verification.json').read_text())['source_sha256']
    for p in (old_top,old_dense,rtl/'compact_dense_scoreboard.hpp',*math):
        assert sha(p)==prior[p.relative_to(ROOT).as_posix()],p
    shifts=check_coefficients(packets)
    for p in previous_inputs[:-1]:
        shutil.copyfile(p,out/p.name)
    (out/'kwt_compact_dense.sv').write_text(controller(old_dense.read_text()))
    overlay=top_overlay(old_top.read_text())
    (out/'kwt_e203_dense_supply.sv').write_text(overlay)
    (out/'reference_top.sv').write_text(cpu_overlay(out,cpu,frozen/'reference_top.sv',overlay))
    (out/'observer.cpp').write_text(observer(previous_inputs[-1].read_text(),cwd+'/'+score.relative_to(ROOT).as_posix()))

    def paths(sources):
        return ' '.join(os.path.relpath(p,ROOT).replace('\\','/') for p in sources)

    def linux(cmd,log):
        with (out/log).open('w') as fd:
            result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {cmd}'],
                                  stdout=fd,stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError((out/log).read_text(errors='replace')[-5000:])

    generated=[out/p.name for p in previous_inputs[:4]]+[out/p.name for p in (old_top,old_dense)]
    platform=[out/n for n in ('e203_cpu_top.v','e203_cpu.v','reference_top.sv')]
    upstream=sorted((cpu/'rtl/e203/core').glob('*.v'))+sorted((cpu/'rtl/e203/general').glob('*.v'))
    skip={'config.v','e203_defines.v','e203_cpu_top.v','e203_cpu.v'}
    project=[copier,sram,*generated,*math]
    source=paths([*project,*platform,*(p for p in upstream if p.name not in skip)])
    linux(f'verilator --cc --exe --build -j 3 --no-timing -Wno-fatal --output-split 14000 '
          f'-DFPGA_SOURCE -DKWT_SIM -I../e203_hbirdv2/rtl/e203/core -Irtl/input16_trim2/generated '
          f'--top-module reference_top --Mdir {rel}/model {source} {cwd}/{rel}/observer.cpp','build.log')
    cases={}
    for rate in (50,100,200):
        linux(f'{rel}/model/Vreference_top {rel}/firmware.bin {paths([frozen])} {600//rate} normal',f'{rate}.log')
        keys=('cycles','retired','staging','lease','reads','aux','matrices','raw','rq','a_writes',
              'coeff','mac','rq_cycles','stalls','saturation','scratch','copy_reads','copy_writes','copy','masked')
        values=list(map(int,re.search(r'PASS DENSE '+r' '.join(k+r'=(\d+)' for k in keys),
                                     (out/f'{rate}.log').read_text()).groups()))
        cases[str(rate)]=dict(zip(keys,values))
    area=None
    lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    blackbox=trim/'kwt_tech_sram_blackbox.sv'
    if not args.no_map:
        (out/'mapping.ys').write_text(f'''read_liberty -lib {paths([lib])}
read_verilog -sv -DKWT_TECH_SRAM -Irtl/input16_trim2/generated {paths([*project,blackbox])}
synth -top e203_subsys_nice_core -noabc -noshare
dfflibmap -liberty {paths([lib])}
abc -liberty {paths([lib])}
clean
check -assert
stat -liberty {paths([lib])}
write_json {rel}/mapped.json
''')
        linux(f'yosys -Q -s {rel}/mapping.ys','mapping.log')
        area=area_report(out,lib)
    sources=[Path(__file__),ROOT/'scripts/run_e203_compact_dense.py',ROOT/'scripts/run_e203_compact_supply.py',
             ROOT/'scripts/run_input16_e203_block.py',*project,*platform,*upstream,*fixtures,*previous_inputs,
             old_top,old_dense,score,rtl/'compact_dense_scoreboard.hpp',trim/'generated/kwt_profile.svh',lib,blackbox]
    result=dict(passed=True,actual_E203=True,full_encoder=False,scope='independent 99-row Dense matrices with actual A/B/S banks',
                rq='right',shift_range=shifts,private_macro_count=20,private_sram_bytes=65536,
                per_run_raw_codes=684288,per_run_rq_codes=684288,per_run_masked_lanes=6912,mismatches=0,
                actual_dense_coeff_words=18432,counterfactual_per_group_coeff_words=129024,cases=cases,
                supply_dense_partition_standard_cell_mm2=area,mapping_mode='hierarchical',
                throughput_tasks_per_second=None,mean_SoC_power_mW=None,complete_counted_area_mm2=None,
                source_sha256={paths([p]):sha(p) for p in sources})
    (out/'verification.json').write_text(json.dumps(result,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='source_sha256'},indent=2))


if __name__=='__main__':
    main()
