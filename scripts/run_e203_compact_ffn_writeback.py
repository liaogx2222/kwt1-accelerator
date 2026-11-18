"""Close the physical FC2 result handoff on the compact A-bank port."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from local_tools import ROOT, sha
from run_e203_compact_supply import cpu_overlay, replace_once


def overlay(source):
    edits=[
        ('    output wire [63:0] ffn_s_data\n','''    output wire [63:0] ffn_s_data,
    output wire output_available,output_read_ready,output_resp_valid,
    input wire output_read,output_resp_ready,output_release,
    input wire [8:0] output_addr,
    output wire [127:0] output_data,
    output wire [15:0] output_mask
'''),
        ('    wire [95:0] a_addresses={8{{2\'b0,a_addr}}};','''    wire [7:0] wb_en,wb_we;
    wire [9:0] wb_addr;
    wire [127:0] wb_wdata;
    wire wb_error,internal_act_ready;
    wire wb_active=|wb_en;
    wire [95:0] a_addresses={8{{2'b0,wb_active?wb_addr:a_addr}}};
    wire [7:0] a_enable=wb_active?wb_en:{8{a_en}};
    wire [7:0] a_write=wb_active?wb_we:{8{a_we}};
    wire [127:0] a_write_data=wb_active?wb_wdata:a_wdata;'''),
        ('assign dense_ready=internal_dense_ready&&ffn_start_ok;',
         '''assign dense_ready=internal_dense_ready&&ffn_start_ok&&!output_available;
    assign act_ready=internal_act_ready&&!output_available;'''),
        ('assign dense_error=arithmetic_error||link_error;',
         'assign dense_error=arithmetic_error||link_error||wb_error||(a_en&&wb_active);'),
        ('.finish_frame(finish_frame&&!coeff_phase)', '.finish_frame(finish_frame&&!coeff_phase&&!output_available)'),
        ('.compute_en({s_enable,{8{a_en}}}),.compute_we({s_write,{8{a_we}}})',
         '.compute_en({s_enable,a_enable}),.compute_we({s_write,a_write})'),
        ('.compute_wdata({s_wdata,a_wdata})','.compute_wdata({s_wdata,a_write_data})'),
        ('.start_valid(dense_start&&ffn_start_ok)', '.start_valid(dense_start&&ffn_start_ok&&!output_available)'),
        ('.act_write(act_write),.act_addr(act_addr),.act_data(act_data),.act_ready(act_ready)',
         '.act_write(act_write&&!output_available),.act_addr(act_addr),.act_data(act_data),.act_ready(internal_act_ready)'),
        ('    kwt_compact_dense dense (','''    kwt_compact_ffn_writeback writeback (
        .clk(nice_clk),.rst_n(nice_rst_n),.clear(dense_abort||!lease_hold),
        .fc2_start(start_fire&&tile_id==1),.fc2_done(dense_done&&tile_id==1),
        .result_accept(dense_valid&&dense_result_ready),.result_tag(dense_tag),
        .result_mask(dense_mask),.result_data(dense_data),.bank_en(wb_en),.bank_we(wb_we),
        .bank_addr(wb_addr),.bank_wdata(wb_wdata),.bank_rdata(compute_rdata[127:0]),
        .available(output_available),.error(wb_error),.release_result(output_release),
        .read_valid(output_read),.read_ready(output_read_ready),.read_addr(output_addr),
        .response_valid(output_resp_valid),.response_ready(output_resp_ready),
        .response_data(output_data),.response_mask(output_mask));

    kwt_compact_dense dense ('''),
    ]
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def scoreboard(source):
    source=replace_once(source,'    unsigned gelu_frame=0;','''    unsigned gelu_frame=0,output_issued=0,output_received=0;
    uint64_t written_back_codes=0,output_vectors=0,output_stalls=0,output_window=0;
    bool output_held=false;
    uint16_t held_mask=0;
    std::array<uint32_t,4> held_data{};''')
    source=replace_once(source,'        dut.dense_result_ready=clocks%9>=3;',
                        '''        dut.dense_result_ready=clocks%9>=3;
        dut.output_read=dut.output_available&&output_issued<448;
        dut.output_addr=output_issued;
        dut.output_resp_ready=clocks%8>=3;
        dut.output_release=dut.output_available&&output_received==448;''')
    source=replace_once(source,'        if(dut.dense_done) {','''        if(dut.output_available) {
            require(matrix<0&&dut.lease_hold,"FC2 writeback outside completed matrix");
            ++output_window;
        }
        if(dut.output_read&&dut.output_read_ready) ++output_issued;
        if(output_held) {
            require(dut.output_resp_valid&&dut.output_mask==held_mask,"FC2 writeback response changed under stall");
            for(unsigned word=0;word<4;++word)
                require(dut.output_data[word]==held_data[word],"FC2 writeback payload changed under stall");
        }
        output_held=dut.output_resp_valid&&!dut.output_resp_ready;
        if(output_held) {
            ++output_stalls;
            held_mask=dut.output_mask;
            for(unsigned word=0;word<4;++word) held_data[word]=dut.output_data[word];
        }
        if(dut.output_resp_valid&&dut.output_resp_ready) {
            require(dut.output_available&&output_received<output_issued,"unmatched A read response");
            unsigned row=(output_received/64)*16, col=output_received%64;
            unsigned mask=row==96?7u:65535u;
            require(dut.output_mask==mask,"A read tail mask");
            for(unsigned lane=0;lane<16;++lane) if(mask>>lane&1) {
                uint8_t code=dut.output_data[lane/4]>>(8*(lane%4));
                require(code==uint8_t(expected_rq[(row+lane)*64+col]),"physical FC2 writeback code");
                ++written_back_codes;
            }
            ++output_received; ++output_vectors;
        }
        if(dut.output_release) {
            require(output_received==448&&output_issued==448&&!dut.output_resp_valid,"premature A result release");
            output_issued=0; output_received=0;
        }
        if(dut.dense_done) {''')
    return source


def observer(source,header):
    source=re.sub(r'#include "[^"]*/compact_ffn_scoreboard.hpp"',f'#include "{header}"',source,count=1)
    source=replace_once(source,'dense.gelu_beats==76800','dense.gelu_beats==76800 && dense.written_back_codes==76032 && dense.output_vectors==5376')
    source=replace_once(source,'gelu_beats=%llu','gelu_beats=%llu writeback=%llu output_vectors=%llu output_stalls=%llu output_window=%llu')
    return replace_once(source,'(unsigned long long)dense.gelu_beats);',
                        '''(unsigned long long)dense.gelu_beats,(unsigned long long)dense.written_back_codes,
                (unsigned long long)dense.output_vectors,(unsigned long long)dense.output_stalls,
                (unsigned long long)dense.output_window);''')


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--ffn',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    prev=args.ffn.resolve()
    out=args.output.resolve()
    out.mkdir(parents=True)
    rel=out.relative_to(ROOT).as_posix()
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    frozen=ROOT/'testdata/input16_rtl_20261105/trim2_e203'
    cpu=ROOT.parent/'e203_hbirdv2'
    rtl=ROOT/'rtl/block_transfer'
    trim=ROOT/'rtl/input16_trim2'
    writer=rtl/'kwt_compact_ffn_writeback.sv'
    names=('kwt_e203_dense_body.sv','kwt_indexed_block_reader.sv','kwt_indexed_weight_banks.sv',
           'arithmetic.sv','kwt_compact_dense.sv','firmware.bin')
    manifest=json.loads((prev/'manifest.json').read_text())
    for name in (*names,'kwt_e203_dense_supply.sv','compact_ffn_scoreboard.hpp','observer.cpp'):
        assert sha(prev/name)==manifest[name],name
    for name in names:
        shutil.copyfile(prev/name,out/name)
    overlay_source=overlay((prev/'kwt_e203_dense_supply.sv').read_text())
    (out/'kwt_e203_dense_supply.sv').write_text(overlay_source)
    (out/'reference_top.sv').write_text(cpu_overlay(out,cpu,frozen/'reference_top.sv',overlay_source))
    (out/'ffn_writeback_scoreboard.hpp').write_text(scoreboard((prev/'compact_ffn_scoreboard.hpp').read_text()))
    (out/'observer.cpp').write_text(observer((prev/'observer.cpp').read_text(),f'{cwd}/{rel}/ffn_writeback_scoreboard.hpp'))
    project=[writer,rtl/'kwt_compact_ffn_link.sv',rtl/'kwt_dense_s_to_a.sv',rtl/'kwt_rne_dense_right.sv',
             ROOT/'rtl/micro/mul_pipe.sv',trim/'kwt_sram_sp.sv',*[out/n for n in names[:-1]],out/'kwt_e203_dense_supply.sv']
    platform=[out/n for n in ('e203_cpu_top.v','e203_cpu.v','reference_top.sv')]
    upstream=sorted((cpu/'rtl/e203/core').glob('*.v'))+sorted((cpu/'rtl/e203/general').glob('*.v'))
    skip={'config.v','e203_defines.v','e203_cpu_top.v','e203_cpu.v'}
    def paths(sources):
        return ' '.join(os.path.relpath(p,ROOT).replace('\\','/') for p in sources)
    def linux(cmd,log):
        with (out/log).open('w') as fd:
            p=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {cmd}'],
                             stdout=fd,stderr=subprocess.STDOUT)
        if p.returncode:
            raise RuntimeError((out/log).read_text(errors='replace')[-4500:])
    files=paths([*project,*platform,*(p for p in upstream if p.name not in skip)])
    linux(f'verilator --cc --exe --build -j 3 --no-timing -Wno-fatal --output-split 14000 '
          f'-DFPGA_SOURCE -DKWT_SIM -I../e203_hbirdv2/rtl/e203/core -Irtl/input16_trim2/generated '
          f'--top-module reference_top --Mdir {rel}/model {files} {cwd}/{rel}/observer.cpp','build.log')
    linux(f'{rel}/model/Vreference_top {rel}/firmware.bin {paths([frozen])} 6 normal','100.log')
    result=dict((k,int(v)) for k,v in re.findall(r'(\w+)=(\d+)',(out/'100.log').read_text()))
    assert result['writeback']==76032 and result['output_vectors']==5376
    lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    (out/'mapping.ys').write_text(f'''read_liberty -lib {paths([lib])}
read_verilog -sv {paths([writer])}
synth -top kwt_compact_ffn_writeback -noabc -noshare
dfflibmap -liberty {paths([lib])}
abc -liberty {paths([lib])}
clean
check -assert
stat -liberty {paths([lib])}
''')
    linux(f'yosys -Q -s {rel}/mapping.ys','mapping.log')
    area=float(re.search(r'Chip area for module .*?:\s+([\d.]+)',(out/'mapping.log').read_text())[1])/1e6
    sources=[Path(__file__),ROOT/'scripts/run_e203_compact_supply.py',ROOT/'scripts/run_input16_e203_block.py',
             *project,*platform,*upstream,prev/'verification.json',prev/'compact_ffn_scoreboard.hpp',prev/'observer.cpp',
             rtl/'compact_dense_scoreboard.hpp',out/'firmware.bin',trim/'generated/kwt_profile.svh',lib,
             *sorted(frozen.glob('*.bin.hex')),frozen/'input_000.hex',frozen/'reference_top.sv']
    report=dict(passed=True,actual_E203=True,full_encoder=False,scope='99-row Dense, FFN chain and physical FC2 handoff in A',
                case_100MBps=result,ffn_output_bank_addresses=[256,703],private_macros_added=0,
                writeback_controller_standard_cell_mm2=area,mismatches=0,
                throughput_tasks_per_second=None,mean_SoC_power_mW=None,complete_counted_area_mm2=None,
                source_sha256={paths([p]):sha(p) for p in sources})
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='source_sha256'},indent=2))


if __name__=='__main__':
    main()
