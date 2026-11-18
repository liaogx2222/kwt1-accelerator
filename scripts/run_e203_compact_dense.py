"""Connect real E203 packet supply to compact A/B SRAM, narrow MAC and RQ."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess

from local_tools import ROOT, sha
from run_e203_compact_supply import cpu_overlay, replace_once


def observer(source, header):
    source=replace_once(source,'namespace {',f'#include "{header}"\n\nnamespace {{')
    start=source.index('    // Raw coefficient spans')
    end=source.index('\n}',start)
    source=source[:start]+'''    return {{13232,1024,4},{10584,1024,2},{14408,1024,5},
            {12080,1024,3},{2008,4096,0},{6296,4096,1}};'''+source[end:]
    source=replace_once(source,'    Vreference_top dut;', '    Vreference_top dut;\n    DenseScoreboard dense;')
    source=replace_once(source,'        dut.compute_en=0; dut.compute_we=0;',
                        '        dense.load(root);\n        dut.scratch_en=0; dut.scratch_we=0; dut.scratch_addr=0; dut.scratch_wdata=0;')
    source=replace_once(source,'for(const auto &r:ranges) count+=r.words;',
                        'for(const auto &r:ranges) count+=r.words;\n                if(frame!=0) count+=1536;')
    start=source.index('    void verify_tile(')
    end=source.index('    void tick()',start)
    source=source[:start]+source[end:]
    start=source.index('        const bool tile=')
    end=source.index('        dut.clk=0;',start)
    source=source[:start]+'''        const bool tile=r&&range_active&&r->matrix>=0;
        dense.drive(dut,frame,tile?r->matrix:-1,clocks);
'''+source[end:]
    start=source.index('        if(dut.tile_response)')
    end=source.index('        dut.clk=1;',start)
    source=source[:start]+'''        dense.observe(dut,frame,tile?r->matrix:-1,packets[frame<13?frame:12]);
        if(dut.dense_done) {++index; range_active=false;}
'''+source[end:]
    start=source.index('            check(frame==13')
    end=source.index('        } else check(frame==1',start)
    source=source[:start]+'''            check(frame==13 && reads==359312 && writes==189328 && aux==4096 &&
                  dense.matrices==72 && dense.raw_codes==110592 && dense.rq_codes==110592,"dense count");
            std::printf("PASS DENSE cycles=%llu retired=%llu staging=%llu lease=%llu reads=%llu aux=%llu matrices=%llu raw=%llu rq=%llu a_writes=%llu coeff=%llu mac=%llu rq_cycles=%llu stalls=%llu saturation=%llu\\n",
                (unsigned long long)(clocks-begin),(unsigned long long)retired,(unsigned long long)staging_cycles,
                (unsigned long long)lease_cycles,(unsigned long long)reads,(unsigned long long)aux,
                (unsigned long long)dense.matrices,(unsigned long long)dense.raw_codes,
                (unsigned long long)dense.rq_codes,(unsigned long long)dense.writes,
                (unsigned long long)dense.coeff_cycles,(unsigned long long)dense.mac_cycles,
                (unsigned long long)dense.rq_cycles,(unsigned long long)dense.stall_cycles,
                (unsigned long long)dense.saturations);
'''+source[end:]
    return source


def check_coefficients(packets):
    table=dict(fc1=(1496,1752,1240,256),fc2=(6168,6232,6104,64),k=(10456,10520,0,64),
               o=(11952,12016,11888,64),q=(13104,13168,0,64),v=(14280,14344,0,64))
    shifts=[]
    for layer,p in enumerate(packets):
        words=[int(w,16) for w in p.read_text().split()]
        raw=b''.join(w.to_bytes(4,'little') for w in words)
        entries=struct.unpack_from('<8sHBBIII32sII',raw)
        desc={}
        for j in range(entries[4]):
            entry=struct.unpack_from('<32s8sBBH3IIII32s28x',raw,64+128*j)
            name=entry[0].rstrip(b'\0').decode()
            assert name.startswith(f'l{layer:02d}_')
            desc[name[4:]]=((64+entries[5]+entry[8])//4,entry[9]//4)
        for key,(mul,shift,bias,length) in table.items():
            assert desc[key+'_m']==(mul,length) and desc[key+'_s']==(shift,length)
            assert desc.get(key+'_b')==((bias,length) if bias else None)
            shifts.extend(words[shift:shift+length])
    assert len(shifts)==6912 and (min(shifts),max(shifts))==(38,48)
    return [min(shifts),max(shifts)]


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--rq',choices=['generic','right'],default='right')
    ap.add_argument('--no-map',action='store_true')
    args=ap.parse_args()
    out=args.output.resolve()
    out.mkdir(parents=True)
    rel=out.relative_to(ROOT).as_posix()
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    base=ROOT/'testdata/input16_rtl_20261105'
    previous=base/'p2_e203_compact_indexed_v2'
    frozen=base/'trim2_e203'
    cpu=ROOT.parent/'e203_hbirdv2'
    rtl=ROOT/'rtl/block_transfer'
    trim=ROOT/'rtl/input16_trim2'
    overlay=rtl/'kwt_e203_dense_supply.sv'
    dense=rtl/'kwt_compact_dense.sv'
    body_source=rtl/'kwt_e203_compact_supply.sv'
    host_source=rtl/'sim_e203_compact_supply.cpp'
    score=rtl/'compact_dense_scoreboard.hpp'
    arith_source=ROOT/'rtl/experimental/kwt_arithmetic16_single.sv'
    narrow=rtl/'kwt_rne_dense_right.sv'
    math=[ROOT/'rtl/micro'/n for n in ('mul_pipe.sv','rne_pipe.sv')]
    if args.rq=='right':
        math.append(narrow)
    bound=json.loads((previous/'verification.json').read_text())['source_sha256']
    for p in (body_source,host_source):
        assert sha(p)==bound[p.relative_to(ROOT).as_posix()],p
    previous_inputs=[previous/n for n in ('kwt_indexed_block_reader.sv','kwt_indexed_weight_banks.sv','firmware.bin')]
    packets=[frozen/f'layer_{i:02d}.bin.hex' for i in range(12)]
    fixtures=[*packets,frozen/'common.bin.hex',frozen/'input_000.hex',frozen/'reference_top.sv']
    for folder,paths in ((previous,previous_inputs),(frozen,fixtures)):
        manifest=json.loads((folder/'manifest.json').read_text())
        for p in paths:
            assert sha(p)==manifest[p.name],p
    shifts=check_coefficients(packets)
    for p in previous_inputs:
        shutil.copyfile(p,out/p.name)
    body=replace_once(body_source.read_text(),'module e203_subsys_nice_core','module kwt_e203_dense_body')
    body=replace_once(body,'output wire [191:0] compute_rdata','output wire [191:0] compute_rdata,\n    output wire bank_abort')
    body=replace_once(body,'    assign aux_valid', '    assign bank_abort = sink_abort;\n    assign aux_valid')
    (out/'kwt_e203_dense_body.sv').write_text(body)
    (out/'reference_top.sv').write_text(cpu_overlay(out,cpu,frozen/'reference_top.sv',overlay.read_text()))
    arith=arith_source.read_text()
    if args.rq=='right':
        arith=replace_once(arith,'  rne_pipe #(.TAG_W(16))','  kwt_rne_dense_right #(.TAG_W(16))')
    (out/'arithmetic.sv').write_text(arith)
    (out/'observer.cpp').write_text(observer(host_source.read_text(),cwd+'/'+score.relative_to(ROOT).as_posix()))

    def paths(sources):
        return ' '.join(os.path.relpath(p,ROOT).replace('\\','/') for p in sources)

    def linux(command,log):
        with (out/log).open('w') as fd:
            result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {command}'],
                                  stdout=fd,stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError((out/log).read_text(errors='replace')[-5000:])

    generated=[out/n for n in ('kwt_e203_dense_body.sv','kwt_indexed_block_reader.sv','kwt_indexed_weight_banks.sv','arithmetic.sv')]
    platform=[out/n for n in ('e203_cpu_top.v','e203_cpu.v','reference_top.sv')]
    upstream=sorted((cpu/'rtl/e203/core').glob('*.v'))+sorted((cpu/'rtl/e203/general').glob('*.v'))
    skip={'config.v','e203_defines.v','e203_cpu_top.v','e203_cpu.v'}
    sram=trim/'kwt_sram_sp.sv'
    project=[overlay,dense,sram,*generated,*math]
    source=paths([*project,*platform,*(p for p in upstream if p.name not in skip)])
    linux(f'verilator --cc --exe --build -j 3 --no-timing -Wno-fatal --output-split 14000 '
          f'-DFPGA_SOURCE -DKWT_SIM -I../e203_hbirdv2/rtl/e203/core -Irtl/input16_trim2/generated '
          f'--top-module reference_top --Mdir {rel}/model {source} {cwd}/{rel}/observer.cpp','build.log')
    cases={}
    for rate in (50,100,200):
        linux(f'{rel}/model/Vreference_top {rel}/firmware.bin {paths([frozen])} {600//rate} normal',f'{rate}.log')
        keys=('cycles','retired','staging','lease','reads','aux','matrices','raw','rq','a_writes',
              'coeff','mac','rq_cycles','stalls','saturation')
        values=list(map(int,re.search(r'PASS DENSE '+r' '.join(k+r'=(\d+)' for k in keys),
                                     (out/f'{rate}.log').read_text()).groups()))
        cases[str(rate)]=dict(zip(keys,values))

    area=None
    lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    blackbox=trim/'kwt_tech_sram_blackbox.sv'
    if not args.no_map:
        (out/'mapping.ys').write_text(f'''read_liberty -lib {paths([lib])}
read_verilog -sv -DKWT_TECH_SRAM -Irtl/input16_trim2/generated {paths([*project,blackbox])}
synth -top e203_subsys_nice_core -flatten -noabc
dfflibmap -liberty {paths([lib])}
abc -liberty {paths([lib])}
clean
check -assert
stat -liberty {paths([lib])}
write_json {rel}/mapped.json
''')
        linux(f'yosys -Q -s {rel}/mapping.ys','mapping.log')
        area=float(re.search(r'Chip area for module .*?:\s+([\d.]+)',(out/'mapping.log').read_text())[1])/1e6
        cells=json.loads((out/'mapped.json').read_text())['modules']['e203_subsys_nice_core']['cells'].values()
        assert [sum(c['type']==f'kwt_tech_sram_{depth}x16' for c in cells) for depth in (1024,4096)]==[16,4]
    sources=[Path(__file__),ROOT/'scripts/run_e203_compact_supply.py',ROOT/'scripts/run_input16_e203_block.py',
             *project,*platform,*upstream,*fixtures,*previous_inputs,body_source,host_source,arith_source,score,
             trim/'generated/kwt_profile.svh',lib,blackbox]
    report=dict(passed=True,actual_E203=True,full_encoder=False,scope='13 packets and one 16-row group per real matrix',
                rq=args.rq,shift_range=shifts,private_macro_count=20,private_sram_bytes=65536,
                per_run_raw_codes=110592,per_run_rq_codes=110592,mismatches=0,cases=cases,
                supply_dense_partition_standard_cell_mm2=area,throughput_tasks_per_second=None,
                mean_SoC_power_mW=None,complete_counted_area_mm2=None,
                source_sha256={paths([p]):sha(p) for p in sources})
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='source_sha256'},indent=2))


if __name__=='__main__':
    main()
