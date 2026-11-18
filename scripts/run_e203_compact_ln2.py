"""Use actual FC1 skip data and A-bank FC2 results in exact compact LN2."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from local_tools import ROOT, sha
from map_compact_ffn_writeback import graph_digest
from run_e203_compact_dense99 import area_report
from run_e203_compact_supply import cpu_overlay, replace_once


def overlay(source):
    edits=[
        ('''    output wire output_available,output_read_ready,output_resp_valid,
    input wire output_read,output_resp_ready,output_release,
    input wire [8:0] output_addr,
    output wire [127:0] output_data,
    output wire [15:0] output_mask
''','''    output wire capture_phase,ln_phase,ln_valid,ln_res_valid,ln_stats_valid,ln_write,
    input wire ln_ready,
    output wire [6:0] ln_row,
    output wire [5:0] ln_index,ln_res_index,
    output wire [7:0] ln_data,
    output wire [15:0] ln_res_data,
    output wire [21:0] ln_sum,
    output wire [35:0] ln_squares,
    output wire [63:0] ln_root,
    output wire [31:0] ln_inverse,
    output wire [11:0] ln_s_addr,
    output wire [63:0] ln_s_wdata
'''),
        ('    wire wb_active=|wb_en;', '''    wire wb_active=|wb_en;
    wire output_available,output_read_ready,output_resp_valid,output_read,output_resp_ready,output_release;
    wire [8:0] output_addr;
    wire [127:0] output_data;
    wire [15:0] output_mask;
    wire ln_a_read,ln_error,skip_saved;
    wire [9:0] ln_a_addr;
    wire [3:0] ln_s_en,ln_s_we;
    wire ln_s_active=|ln_s_en;'''),
        ("wb_active?wb_addr:a_addr", "ln_a_read?ln_a_addr:wb_active?wb_addr:a_addr"),
        ("wire [7:0] a_enable=wb_active?wb_en:{8{a_en}};", "wire [7:0] a_enable=ln_a_read?8'hff:wb_active?wb_en:{8{a_en}};"),
        ("wire [7:0] a_write=wb_active?wb_we:{8{a_we}};", "wire [7:0] a_write=ln_a_read?8'b0:wb_active?wb_we:{8{a_we}};"),
        ('tile_id==1?fc2_ready:1\'b1','tile_id==1?(fc2_ready&&skip_saved):1\'b1'),
        ('assign act_ready=internal_act_ready&&!output_available;',
         'assign act_ready=internal_act_ready&&!output_available&&!capture_phase;'),
        ('assign dense_error=arithmetic_error||link_error||wb_error||(a_en&&wb_active);',
         '''assign dense_error=arithmetic_error||link_error||wb_error||ln_error||
                       (a_en&&(wb_active||ln_a_read))||(wb_active&&ln_a_read)||
                       (ln_s_active&&(copy_phase||write_s));'''),
        ('!dense_abort&&!copy_phase&&!owns_s;', '!dense_abort&&!copy_phase&&!owns_s&&!capture_phase&&!ln_phase;'),
        ('s_enable=copy_phase?', 's_enable=ln_s_active?ln_s_en:copy_phase?'),
        ('s_write=copy_phase?', 's_write=ln_s_active?ln_s_we:copy_phase?'),
        ('s_address=copy_phase?', 's_address=ln_s_active?{4{ln_s_addr}}:copy_phase?'),
        ('s_wdata=write_s?', 's_wdata=ln_s_active?ln_s_wdata:write_s?'),
        ('.act_write(act_write&&!output_available)', '.act_write(act_write&&!output_available&&!capture_phase)'),
        ('    kwt_compact_dense dense (','''    kwt_compact_ln2 ln2 (
        .clk(nice_clk),.rst_n(nice_rst_n),.clear(dense_abort||!lease_hold),
        .aux_accept(aux_valid&&aux_ready),.aux_index(aux_index),.aux_data(aux_data),
        .fc1_done(dense_done&&tile_id==0),.fc2_available(output_available),
        .skip_saved(skip_saved),.error(ln_error),.capture_phase(capture_phase),.ln_phase(ln_phase),
        .a_read(ln_a_read),.a_addr(ln_a_addr),.a_data(compute_rdata[127:0]),
        .s_en(ln_s_en),.s_we(ln_s_we),.s_addr(ln_s_addr),.s_wdata(ln_s_wdata),.s_rdata(scratch_rdata),
        .fc2_read(output_read),.fc2_addr(output_addr),.fc2_read_ready(output_read_ready),
        .fc2_valid(output_resp_valid),.fc2_ready(output_resp_ready),.fc2_release(output_release),
        .fc2_data(output_data),.fc2_mask(output_mask),.row_index(ln_row),
        .residual_valid(ln_res_valid),.residual_index(ln_res_index),.residual_data(ln_res_data),
        .stats_valid(ln_stats_valid),.stats_sum(ln_sum),.stats_squares(ln_squares),
        .stats_root(ln_root),.stats_inverse(ln_inverse),
        .out_valid(ln_valid),.out_ready(ln_ready),.out_index(ln_index),.out_data(ln_data),.out_write(ln_write));

    kwt_compact_dense dense ('''),
    ]
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def scoreboard(source,header):
    source=replace_once(source,'struct Dense99Scoreboard',f'#include "{header}"\n\nstruct Dense99Scoreboard')
    start=source.index('    unsigned gelu_frame=0,output_issued')
    end=source.index('    uint64_t scratch_writes=',start)
    source=source[:start]+'    unsigned gelu_frame=0;\n    CompactLN2Golden ln;\n'+source[end:]
    start=source.index('        dut.output_read=')
    end=source.index('        if(matrix<0',start)
    source=source[:start]+'        dut.ln_ready=clocks%8>=3;\n'+source[end:]
    source=replace_once(source,'            running=true; expected99(frame,matrix,packet);',
                        '''            running=true; expected99(frame,matrix,packet);
            if(matrix==1)ln.prepare(frame,packet,expected_rq,*this);''')
    start=source.index('        if(dut.output_available)')
    end=source.index('        if(dut.dense_done)',start)
    return source[:start]+'        ln.observe(dut);\n'+source[end:]


def observer(source,header):
    source=re.sub(r'#include "[^"]*/ffn_writeback_scoreboard.hpp"',f'#include "{header}"',source,count=1)
    edits=[
        ('{12080,1024,3},{10392,64,-1},{2008,4096,0}', '{12080,1024,3},{10392,64,-1},{11748,137,-1},{14264,6,-1},{2008,4096,0}'),
        ('reads==360080 && writes==189328 && aux==4864','reads==361796 && writes==189328 && aux==6580'),
        ('dense.written_back_codes==76032 && dense.output_vectors==5376',
         'dense.ln.residual_count==76032 && dense.ln.stats_count==1188 && dense.ln.output_count==76032 && dense.ln.writes==9504'),
        ('writeback=%llu output_vectors=%llu output_stalls=%llu output_window=%llu',
         'residual=%llu stats=%llu ln=%llu ln_writes=%llu capture=%llu ln_cycles=%llu ln_stalls=%llu'),
        ('''(unsigned long long)dense.gelu_beats,(unsigned long long)dense.written_back_codes,
                (unsigned long long)dense.output_vectors,(unsigned long long)dense.output_stalls,
                (unsigned long long)dense.output_window);''',
         '''(unsigned long long)dense.gelu_beats,(unsigned long long)dense.ln.residual_count,
                (unsigned long long)dense.ln.stats_count,(unsigned long long)dense.ln.output_count,
                (unsigned long long)dense.ln.writes,(unsigned long long)dense.ln.capture_cycles,
                (unsigned long long)dense.ln.ln_cycles,(unsigned long long)dense.ln.stalls);'''),
    ]
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


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
    prev=base/'p3_e203_compact_ffn99_writeback'
    original=base/'p3_e203_compact_ffn99_map_v2'
    frozen=base/'trim2_e203'
    cpu=ROOT.parent/'e203_hbirdv2'
    rtl=ROOT/'rtl/block_transfer'
    trim=ROOT/'rtl/input16_trim2'
    new=[rtl/'kwt_compact_ln2.sv',rtl/'kwt_compact_ln_row.sv',trim/'kwt_iterative.sv']
    golden=rtl/'compact_ln2_golden.hpp'
    names=('kwt_e203_dense_body.sv','kwt_indexed_block_reader.sv','kwt_indexed_weight_banks.sv',
           'arithmetic.sv','kwt_compact_dense.sv','firmware.bin')
    prev_files=[prev/n for n in (*names,'kwt_e203_dense_supply.sv','ffn_writeback_scoreboard.hpp','observer.cpp')]
    fixtures=[*sorted(frozen.glob('*.bin.hex')),frozen/'input_000.hex',frozen/'reference_top.sv']
    for folder,files in ((prev,prev_files),(frozen,fixtures)):
        manifest=json.loads((folder/'manifest.json').read_text())
        for path in files:
            assert sha(path)==manifest[path.name],path
    for name in names:
        shutil.copyfile(prev/name,out/name)
    supply=out/'kwt_e203_dense_supply.sv'
    top=overlay((prev/supply.name).read_text())
    supply.write_text(top)
    (out/'reference_top.sv').write_text(cpu_overlay(out,cpu,frozen/'reference_top.sv',top))
    header=out/'ln2_scoreboard.hpp'
    header.write_text(scoreboard((prev/'ffn_writeback_scoreboard.hpp').read_text(),cwd+'/'+golden.relative_to(ROOT).as_posix()))
    (out/'observer.cpp').write_text(observer((prev/'observer.cpp').read_text(),f'{cwd}/{rel}/{header.name}'))
    project=[*new,rtl/'kwt_compact_ffn_writeback.sv',rtl/'kwt_compact_ffn_link.sv',
             rtl/'kwt_dense_s_to_a.sv',rtl/'kwt_rne_dense_right.sv',ROOT/'rtl/micro/mul_pipe.sv',trim/'kwt_sram_sp.sv',
             *[out/n for n in names[:-1]],supply]
    platform=[out/n for n in ('e203_cpu_top.v','e203_cpu.v','reference_top.sv')]
    upstream=sorted((cpu/'rtl/e203/core').glob('*.v'))+sorted((cpu/'rtl/e203/general').glob('*.v'))
    skip={'config.v','e203_defines.v','e203_cpu_top.v','e203_cpu.v'}
    def paths(items):
        return ' '.join(os.path.relpath(p,ROOT).replace('\\','/') for p in items)
    def linux(cmd,log):
        with (out/log).open('w') as fd:
            p=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {cmd}'],
                             stdout=fd,stderr=subprocess.STDOUT)
        if p.returncode:
            raise RuntimeError((out/log).read_text(errors='replace')[-5000:])
    files=paths([*project,*platform,*(p for p in upstream if p.name not in skip)])
    linux(f'verilator --cc --exe --build -j 3 --no-timing -Wno-fatal --output-split 14000 '
          f'-DFPGA_SOURCE -DKWT_SIM -I../e203_hbirdv2/rtl/e203/core -Irtl/input16_trim2/generated '
          f'--top-module reference_top --Mdir {rel}/model {files} {cwd}/{rel}/observer.cpp','build.log')
    cases={}
    for rate in (50,100,200):
        linux(f'{rel}/model/Vreference_top {rel}/firmware.bin {paths([frozen])} {600//rate} normal',f'{rate}.log')
        log=(out/f'{rate}.log').read_text()
        assert log.startswith('PASS DENSE ')
        case=dict((k,int(v)) for k,v in re.findall(r'(\w+)=(\d+)',log))
        assert [case[k] for k in ('residual','stats','ln','ln_writes')]==[76032,1188,76032,9504]
        cases[str(rate)]=case
    lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    area=None; unchanged=[]
    if not args.no_map:
        old=original/'mapped.json'
        assert sha(old)==json.loads((original/'manifest.json').read_text())[old.name]
        (out/'mapping.ys').write_text(f'''read_json {paths([old])}
read_verilog -sv -overwrite {paths([supply,*new])}
synth -top e203_subsys_nice_core -noabc -noshare
dfflibmap -liberty {paths([lib])}
abc -liberty {paths([lib])}
clean
check -assert
stat -liberty {paths([lib])}
write_json {rel}/mapped.json
''')
        linux(f'yosys -Q -s {rel}/mapping.ys','mapping.log')
        before=json.loads(old.read_text())['modules']
        after=json.loads((out/'mapped.json').read_text())['modules']
        unchanged=[n for n,m in before.items() if n!='e203_subsys_nice_core' and m.get('cells')]
        assert all(graph_digest(before[n])==graph_digest(after[n]) for n in unchanged)
        area=area_report(out,lib)
    sources=[Path(__file__),ROOT/'scripts/run_e203_compact_supply.py',ROOT/'scripts/run_input16_e203_block.py',
             ROOT/'scripts/map_compact_ffn_writeback.py',ROOT/'scripts/run_e203_compact_dense99.py',
             *project,*platform,*upstream,*prev_files,*fixtures,header,golden,rtl/'compact_dense_scoreboard.hpp',
             out/'firmware.bin',trim/'generated/kwt_profile.svh',lib]
    if area is not None:
        sources.extend((original/'mapped.json',original/'verification.json'))
    report=dict(passed=True,actual_E203=True,full_encoder=False,scope='99-row FFN plus exact residual/LN2 from real A and S SRAM',
                cases=cases,private_macro_count=20,private_sram_bytes=65536,reused_gate_modules=unchanged,
                partition_standard_cell_mm2=area,mismatches=0,throughput_tasks_per_second=None,
                mean_SoC_power_mW=None,complete_counted_area_mm2=None,source_sha256={paths([p]):sha(p) for p in sources})
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='source_sha256'},indent=2))


if __name__=='__main__':
    main()
