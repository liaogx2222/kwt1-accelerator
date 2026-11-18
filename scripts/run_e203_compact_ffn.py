"""Run the 99-row FC1/GELU/FC2 chain through the same compact S banks."""
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
        ('output wire scratch_ready,copy_phase,copy_read,copy_write\n',
         '''output wire scratch_ready,copy_phase,copy_read,copy_write,
    output wire [3:0] ffn_s_write,
    output wire [11:0] ffn_s_addr,
    output wire [63:0] ffn_s_data
'''),
        ('''    assign scratch_ready=nice_rst_n&&!dense_abort&&!copy_phase;
    wire [3:0] s_enable=copy_phase?{4{copy_read}}:(scratch_ready?scratch_en:4'b0);
    wire [3:0] s_write=copy_phase?4'b0:scratch_we;
    wire [47:0] s_address=copy_phase?{4{copy_addr}}:scratch_addr;''',
         '''    wire owns_s,lut_ready,fc2_ready,link_error,internal_dense_ready,arithmetic_error;
    wire ffn_start_ok=tile_id==0?lut_ready:tile_id==1?fc2_ready:1'b1;
    wire write_s=|ffn_s_write;
    wire start_fire=dense_start&&dense_ready;
    assign dense_ready=internal_dense_ready&&ffn_start_ok;
    assign dense_error=arithmetic_error||link_error;
    assign scratch_ready=nice_rst_n&&!dense_abort&&!copy_phase&&!owns_s;
    wire [3:0] s_enable=copy_phase?{4{copy_read}}:write_s?ffn_s_write:(scratch_ready?scratch_en:4'b0);
    wire [3:0] s_write=copy_phase?4'b0:write_s?ffn_s_write:scratch_we;
    wire [47:0] s_address=copy_phase?{4{copy_addr}}:write_s?{4{ffn_s_addr}}:scratch_addr;
    wire [63:0] s_wdata=write_s?ffn_s_data:scratch_wdata;
    wire [14:0] lut_offset=aux_index-15'd10392;
    kwt_compact_ffn_link ffn (
        .clk(nice_clk),.rst_n(nice_rst_n),.clear(dense_abort||!lease_hold),
        .lut_accept(aux_valid&&aux_ready&&aux_index>=10392&&aux_index<10456),
        .lut_index(lut_offset[5:0]),.lut_word(aux_data),
        .fc1_start(start_fire&&tile_id==0),.fc1_done(dense_done&&tile_id==0),.fc2_done(dense_done&&tile_id==1),
        .result_accept(dense_valid&&dense_result_ready),.result_tag(dense_tag),
        .result_mask(dense_mask),.result_data(dense_data),
        .lut_ready(lut_ready),.fc2_ready(fc2_ready),.owns_s(owns_s),.error(link_error),
        .s_write(ffn_s_write),.s_addr(ffn_s_addr),.s_data(ffn_s_data));'''),
        ('.compute_wdata({scratch_wdata,a_wdata})','.compute_wdata({s_wdata,a_wdata})'),
        ('.start_valid(dense_start),.wide_a(dense_wide),.start_ready(dense_ready),',
         '.start_valid(dense_start&&ffn_start_ok),.wide_a(dense_wide),.start_ready(internal_dense_ready),'),
        ('.result_data(dense_data),.error(dense_error),','.result_data(dense_data),.error(arithmetic_error),'),
    ]
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def scoreboard(source):
    source=replace_once(source,'    std::vector<int8_t> expected_rq;',
                        '''    std::vector<int8_t> expected_rq,gelu;
    uint64_t gelu_codes=0,gelu_beats=0;
    unsigned gelu_frame=0;''')
    source=replace_once(source,'                acc+=value(frame,matrix,row,k)*weight(packet,matrix,k,col);',
                        '''                acc+=(matrix==1 ? int(gelu[row*256+k]) : value(frame,matrix,row,k))*
                     weight(packet,matrix,k,col);''')
    source=replace_once(source,'        unsigned cols=columns(matrix);',
                        '''        if(matrix==1)require(gelu.size()==99*256&&gelu_frame==frame,"missing FC1/GELU golden");
        unsigned cols=columns(matrix);''')
    source=replace_once(source,'        }\n    }\n\n    template<class Model> void drive',
                        '''        }
        if(matrix==0) {
            gelu.resize(99*256); gelu_frame=frame;
            for(unsigned i=0;i<gelu.size();++i) {
                unsigned index=unsigned(int(expected_rq[i])+128);
                gelu[i]=int8_t(signed8(packet[10392+index/4]>>(8*(index%4))));
            }
        }
    }

    template<class Model> void drive''')
    source=replace_once(source,'        if(loaded==7*count*(spill?2:1)) {','        if(matrix==1||loaded==7*count*(spill?2:1)) {')
    source=replace_once(source,'        if(dut.dense_done) {',
                        '''        bool gelu_fire=matrix==0&&dut.dense_valid&&dut.dense_result_ready;
        require(gelu_fire==(dut.ffn_s_write!=0),"GELU/S write handshake");
        if(gelu_fire) {
            unsigned tag=dut.dense_tag, group=tag>>10, quad=(tag>>4)&3;
            unsigned col=(tag>>6&15)*16+(tag&15);
            unsigned expected_addr=group*512+2*col+quad/2;
            require(dut.ffn_s_addr==expected_addr,"GELU/S address");
            unsigned pair=2*(quad%2);
            require(dut.ffn_s_write==(3u<<pair),"GELU/S banks");
            for(unsigned bank=pair;bank<pair+2;++bank) {
                for(unsigned lane=0;lane<2;++lane) {
                    unsigned row=group*16+(quad/2)*8+bank*2+lane;
                    uint8_t expected=row<99?uint8_t(gelu[row*256+col]):0;
                    require(uint8_t(dut.ffn_s_data>>(16*bank+8*lane))==expected,"GELU/S code");
                    if(row<99)++gelu_codes;
                }
            }
            ++gelu_beats;
        }
        if(dut.dense_done) {''')
    return source


def observer(source, header):
    source=re.sub(r'#include "[^"]*/compact_dense99_scoreboard.hpp"',f'#include "{header}"',source,count=1)
    for old,new in [
        ('{12080,1024,3},{2008,4096,0},{6296,4096,1}', '{12080,1024,3},{10392,64,-1},{2008,4096,0},{6296,4096,1}'),
        ('reads==359312 && writes==189328 && aux==4096','reads==360080 && writes==189328 && aux==4864'),
        ('dense.scratch_writes==48384','dense.scratch_writes==5376'),
        ('dense.copy_writes==96768','dense.copy_writes==96768 && dense.gelu_codes==304128 && dense.gelu_beats==76800'),
        ('copy=%llu masked=%llu','copy=%llu masked=%llu gelu=%llu gelu_beats=%llu'),
        ('(unsigned long long)dense.copy_cycles,(unsigned long long)dense.masked);',
         '(unsigned long long)dense.copy_cycles,(unsigned long long)dense.masked,\n'
         '                (unsigned long long)dense.gelu_codes,(unsigned long long)dense.gelu_beats);'),
    ]:
        source=replace_once(source,old,new)
    return source


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dense99',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    previous=args.dense99.resolve()
    out=args.output.resolve()
    assert 'PASS DENSE' in (previous/'100.log').read_text()
    out.mkdir(parents=True)
    rel=out.relative_to(ROOT).as_posix()
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    base=ROOT/'testdata/input16_rtl_20261105'
    frozen=base/'trim2_e203'
    cpu=ROOT.parent/'e203_hbirdv2'
    rtl=ROOT/'rtl/block_transfer'
    trim=ROOT/'rtl/input16_trim2'
    link=rtl/'kwt_compact_ffn_link.sv'
    previous_inputs=[previous/n for n in ('kwt_e203_dense_body.sv','kwt_indexed_block_reader.sv','kwt_indexed_weight_banks.sv',
                                         'arithmetic.sv','kwt_compact_dense.sv','firmware.bin')]
    if (previous/'manifest.json').is_file():
        manifest=json.loads((previous/'manifest.json').read_text())
        for p in [*previous_inputs,previous/'kwt_e203_dense_supply.sv',previous/'observer.cpp',previous/'100.log']:
            assert sha(p)==manifest[p.name]
    for p in previous_inputs:
        shutil.copyfile(p,out/p.name)
    fixtures=[*sorted(frozen.glob('*.bin.hex')),frozen/'input_000.hex',frozen/'reference_top.sv']
    manifest=json.loads((frozen/'manifest.json').read_text())
    for p in fixtures:
        assert sha(p)==manifest[p.name]
    overlay_src=overlay((previous/'kwt_e203_dense_supply.sv').read_text())
    (out/'kwt_e203_dense_supply.sv').write_text(overlay_src)
    (out/'reference_top.sv').write_text(cpu_overlay(out,cpu,frozen/'reference_top.sv',overlay_src))
    score=(rtl/'compact_dense99_scoreboard.hpp').read_text()
    score=replace_once(score,'#include "compact_dense_scoreboard.hpp"',f'#include "{cwd}/rtl/block_transfer/compact_dense_scoreboard.hpp"')
    (out/'compact_ffn_scoreboard.hpp').write_text(scoreboard(score))
    (out/'observer.cpp').write_text(observer((previous/'observer.cpp').read_text(),f'{cwd}/{rel}/compact_ffn_scoreboard.hpp'))

    def paths(sources):
        return ' '.join(os.path.relpath(p,ROOT).replace('\\','/') for p in sources)

    def linux(cmd,log):
        with (out/log).open('w') as fd:
            p=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {cmd}'],
                             stdout=fd,stderr=subprocess.STDOUT)
        if p.returncode:
            raise RuntimeError((out/log).read_text(errors='replace')[-4500:])

    project=[link,rtl/'kwt_dense_s_to_a.sv',rtl/'kwt_rne_dense_right.sv',ROOT/'rtl/micro/mul_pipe.sv',trim/'kwt_sram_sp.sv',
             *[out/p.name for p in previous_inputs[:-1]],out/'kwt_e203_dense_supply.sv']
    platform=[out/n for n in ('e203_cpu_top.v','e203_cpu.v','reference_top.sv')]
    upstream=sorted((cpu/'rtl/e203/core').glob('*.v'))+sorted((cpu/'rtl/e203/general').glob('*.v'))
    skip={'config.v','e203_defines.v','e203_cpu_top.v','e203_cpu.v'}
    source=paths([*project,*platform,*(p for p in upstream if p.name not in skip)])
    linux(f'verilator --cc --exe --build -j 3 --no-timing -Wno-fatal --output-split 14000 '
          f'-DFPGA_SOURCE -DKWT_SIM -I../e203_hbirdv2/rtl/e203/core -Irtl/input16_trim2/generated '
          f'--top-module reference_top --Mdir {rel}/model {source} {cwd}/{rel}/observer.cpp','build.log')
    linux(f'{rel}/model/Vreference_top {rel}/firmware.bin {paths([frozen])} 6 normal','100.log')
    keys=('cycles','retired','staging','lease','reads','aux','matrices','raw','rq','a_writes','coeff','mac',
          'rq_cycles','stalls','saturation','scratch','copy_reads','copy_writes','copy','masked','gelu','gelu_beats')
    result=dict(zip(keys,map(int,re.search(r'PASS DENSE '+r' '.join(k+r'=(\d+)' for k in keys),
                                           (out/'100.log').read_text()).groups())))
    lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    (out/'mapping.ys').write_text(f'''read_liberty -lib {paths([lib])}
read_verilog -sv {paths([link])}
synth -top kwt_compact_ffn_link -noabc -noshare
dfflibmap -liberty {paths([lib])}
abc -liberty {paths([lib])}
clean
check -assert
stat -liberty {paths([lib])}
''')
    linux(f'yosys -Q -s {rel}/mapping.ys','mapping.log')
    area=float(re.search(r'Chip area for module .*?:\s+([\d.]+)',(out/'mapping.log').read_text())[1])/1e6
    sources=[Path(__file__),ROOT/'scripts/run_e203_compact_supply.py',ROOT/'scripts/run_input16_e203_block.py',
             *project,*platform,*upstream,*previous_inputs,*fixtures,previous/'kwt_e203_dense_supply.sv',previous/'observer.cpp',
             rtl/'compact_dense99_scoreboard.hpp',rtl/'compact_dense_scoreboard.hpp',out/'compact_ffn_scoreboard.hpp',
             trim/'generated/kwt_profile.svh',lib]
    report=dict(passed=True,actual_E203=True,full_encoder=False,scope='99-row Dense and chained FC1/GELU/FC2',
                chained_layers=12,case_100MBps=result,mismatches=0,ffn_link_standard_cell_area_mm2=area,
                private_macros_added=0,throughput_tasks_per_second=None,mean_SoC_power_mW=None,complete_counted_area_mm2=None,
                source_sha256={paths([p]):sha(p) for p in sources})
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='source_sha256'},indent=2))


if __name__=='__main__':
    main()
