"""Run indexed compact packet supply on E203 RTL and the existing shared bus."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from local_tools import ROOT, Tools, sha
from run_input16_e203_block import replace_once


def indexed_reader(source):
    source = replace_once(source, 'module kwt_verified_block_reader', 'module kwt_indexed_block_reader')
    source = replace_once(source, "profile_header(common,layer,int'(index))",
                          "profile_header(common,layer,{17'b0,index})")
    source = replace_once(source, '    output wire reset_required\n', '''    output wire reset_required,
    input wire range_valid, range_weight, finish_frame,
    output wire range_ready, bank_close,
    input wire [14:0] range_start, range_words,
    output wire [14:0] sink_index,
    output reg sink_weight,
    output wire sink_range_last
''')
    source = replace_once(source, 'QUARANTINE=8;', 'QUARANTINE=8, SELECT=9;')
    source = replace_once(source, 'TIMED_OUT=8;', 'TIMED_OUT=8, RANGE=9;')
    source = replace_once(source, '    wire tag_matches', '''    reg [14:0] range_end;
    wire [15:0] requested_end = {1'b0,range_start} + {1'b0,range_words};
    wire matrix_span = (range_start==2008 && requested_end==6104) ||
                       (range_start==6296 && requested_end==10392) ||
                       (range_start==10584 && requested_end==11608) ||
                       (range_start==12080 && requested_end==13104) ||
                       (range_start==13232 && requested_end==14256) ||
                       (range_start==14408 && requested_end==15432);
    wire aux_span = common ? range_start>=48 :
        (range_start>=1232 && requested_end<=2008) ||
        (range_start>=6104 && requested_end<=6296) ||
        (range_start>=10392 && requested_end<=10584) ||
        (range_start>=11608 && requested_end<=12080) ||
        (range_start>=13104 && requested_end<=13232) ||
        (range_start>=14256 && requested_end<=14408);
    wire legal_range = range_words!=0 && requested_end<={1'b0,words} &&
                       (range_weight ? !common&&matrix_span : aux_span);
    assign range_ready = state==SELECT && !stop && !finish_frame;
    assign bank_close = state==SELECT && !stop && finish_frame;
    assign sink_index = index;
    assign sink_range_last = index==range_end;
    wire tag_matches''')
    source = replace_once(source, 'bank_owned<=0; sink_data<=0;', 'bank_owned<=0; sink_data<=0; sink_weight<=0; range_end<=0;')
    source = replace_once(source, '''                       else if(bank_grant)begin bank_owned<=1; state<=ISSUE; end
                HOLD:''', '''                       else if(bank_grant)begin bank_owned<=1; state<=SELECT; end
                SELECT: if(stop)fail(CANCELLED,1'b0);
                        else if(finish_frame)state<=CONSUME;
                        else if(range_valid)begin
                            if(!legal_range)begin
                                error_code<=RANGE; error_index<=range_start; state<=ABORT_SINK;
                            end else begin
                                index<=range_start; range_end<=15'(requested_end-1'b1);
                                sink_weight<=range_weight; state<=ISSUE;
                            end
                        end
                HOLD:''')
    return replace_once(source, 'if(last_word)state<=CONSUME;', 'if(sink_range_last)state<=SELECT;')


def indexed_banks(source):
    source = replace_once(source, 'module kwt_compact_weight_banks', 'module kwt_indexed_weight_banks')
    source = replace_once(source, '    output wire [191:0] compute_rdata\n',
                          '    output wire [191:0] compute_rdata,\n    input wire [14:0] sink_word_index,\n    input wire close_frame\n')
    source = replace_once(source, '    reg [14:0] packet_word;', '    wire [14:0] packet_word = sink_word_index;')
    for item in (' packet_word<=0;', ' packet_word<=packet_word+1\'b1;', ' last_in_packet<=sink_last;'):
        source = replace_once(source, item, '') if source.count(item)==1 else source.replace(item, '')
    return replace_once(source, '                if (take) begin', "                if (close_frame) last_in_packet<=1;\n                if (take) begin")


def cpu_overlay(out, cpu, wrapper, overlay):
    ports = overlay.split('\n\n    input wire lease_valid',1)[1].split('\n);',1)[0]
    ports = '    input wire lease_valid'+ports
    names = []
    for line in ports.splitlines():
        fields = re.sub(r'^\s*(input|output) wire\s+(\[[^\]]+\]\s+)?','',line)
        names.extend(n.strip() for n in fields.rstrip(',').split(','))
    connections = ''.join(f'    .{n}({n}),\n' for n in names)
    for name, opening, instance in (
        ('e203_cpu_top.v','module e203_cpu_top(\n','  e203_cpu #(.MASTER(1)) u_e203_cpu(\n'),
        ('e203_cpu.v','    parameter MASTER = 1\n)(\n','e203_subsys_nice_core u_e203_nice_core  (\n'),
    ):
        source = (cpu/'rtl/e203/core'/name).read_text()
        source = replace_once(source,opening,opening+ports+',\n')
        (out/name).write_text(replace_once(source,instance,instance+connections))
    original = wrapper.read_text()
    end = original.index(' wire pv,')
    header = original[:end]
    header = replace_once(header, 'input clk,rst_n,accel_abort,drop_response,', 'input clk,rst_n,mem_rsp_err,\n'+ports+',')
    header = replace_once(header,'output retired,output irq,output signed [31:0] bus_rc,output [31:0] parameter_words);','output retired);')
    source = header + original[original.index(' e203_cpu_top cpu('):]
    source = replace_once(source,' e203_cpu_top cpu(\n',' e203_cpu_top cpu(\n'+connections)
    for old, new in (('pv','hv'),('pr','hr'),('pa','ha'),('pw','hw'),('pread','hread'),('pmask','hm'),
                     ('prv','hrv'),('prr','hrr'),('prd','hrd'),('irq',"1'b0")):
        source = replace_once(source,'('+old+')','('+new+')')
    return replace_once(source,".mem_icb_rsp_err(1'b0)",".mem_icb_rsp_err(mem_rsp_err)")


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    out=args.output.resolve()
    out.mkdir(parents=True)
    rel=out.relative_to(ROOT).as_posix()
    base=ROOT/'testdata/input16_rtl_20261105'
    frozen=base/'trim2_e203'
    cpu=ROOT.parent/'e203_hbirdv2'
    rtl=ROOT/'rtl/block_transfer'
    trim=ROOT/'rtl/input16_trim2'
    overlay=rtl/'kwt_e203_compact_supply.sv'
    firmware=ROOT/'firmware/compact_supply_reference.c'
    startup=ROOT/'firmware/e203_experiments_20261104/start_itcm.S'
    host=rtl/'sim_e203_compact_supply.cpp'
    packets=sorted(frozen.glob('*.bin.hex'))
    manifest=json.loads((frozen/'manifest.json').read_text())
    for path in [*packets, frozen/'link.ld', frozen/'reference_top.sv']:
        assert sha(path)==manifest[path.name], path
    assert len(packets)==13
    (out/'kwt_indexed_block_reader.sv').write_text(indexed_reader((rtl/'kwt_verified_block_reader.sv').read_text()))
    (out/'kwt_indexed_weight_banks.sv').write_text(indexed_banks((rtl/'kwt_compact_weight_banks.sv').read_text()))
    (out/'reference_top.sv').write_text(cpu_overlay(out,cpu,frozen/'reference_top.sv',overlay.read_text()))

    def run(cmd, log):
        with (out/log).open('w') as fd:
            p=subprocess.run([str(v) for v in cmd],stdout=fd,stderr=subprocess.STDOUT)
        if p.returncode:
            raise RuntimeError((out/log).read_text(errors='replace')[-3500:])

    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    def linux(cmd,log):
        run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {cmd}'],log)

    tools=Tools()
    compiler=[tools.gcc(),'-march=rv32imac_zicsr','-mabi=ilp32','-mcmodel=medany','-msmall-data-limit=0',
              '-O2','-g','-ffreestanding','-fno-builtin','-nostdlib','-nostartfiles','-Wall','-Wextra','-Werror',
              '-T',frozen/'link.ld','-Wl,--no-relax,-Map='+str(out/'firmware.map'),
              startup,firmware,'-o',out/'firmware.elf']
    (out/'compiler_command.json').write_text(json.dumps(list(map(str,compiler)),indent=2))
    run(compiler,'firmware.log')
    run([tools.binutil('objcopy'),'-O','binary',out/'firmware.elf',out/'firmware.bin'],'objcopy.log')
    run(['git','-C',cpu,'rev-parse','HEAD'],'cpu_revision.txt')
    upstream=sorted((cpu/'rtl/e203/core').glob('*.v'))+sorted((cpu/'rtl/e203/general').glob('*.v'))
    generated=[out/n for n in ('e203_cpu_top.v','e203_cpu.v','reference_top.sv','kwt_indexed_block_reader.sv','kwt_indexed_weight_banks.sv')]
    skip={'config.v','e203_defines.v','e203_cpu_top.v','e203_cpu.v'}
    def paths(sources):
        return ' '.join(os.path.relpath(p,ROOT).replace('\\','/') for p in sources)
    board=[overlay,trim/'kwt_sram_sp.sv',*generated]
    compile_sources=paths([*board,*(p for p in upstream if p.name not in skip)])
    linux(f'verilator --cc --exe --build -j 3 --no-timing -Wno-fatal --output-split 16000 '
          f'-DFPGA_SOURCE -DKWT_SIM -I../e203_hbirdv2/rtl/e203/core -Irtl/input16_trim2/generated '
          f'--top-module reference_top --Mdir {rel}/model {compile_sources} {cwd}/{paths([host])}','build.log')
    cases={}
    for rate in (50,100,200):
        linux(f'{rel}/model/Vreference_top {rel}/firmware.bin {paths([frozen])} {600//rate} normal',f'{rate}.log')
        keys=('cycles','retired','staging_cycles','lease_cycles','lease_retired','reads','aux','weights','writes','frames')
        values=list(map(int,re.search(r'PASS NORMAL '+r' '.join(k+r'=(\d+)' for k in keys),
                                     (out/f'{rate}.log').read_text()).groups()))
        case=dict(zip(keys,values))
        assert case['reads']==363824 and case['weights']==294912 and case['aux']==27040
        case['other_cycles']=case['cycles']-case['staging_cycles']-case['lease_cycles']
        assert case['other_cycles']>0
        cases[str(rate)]=case
    linux(f'{rel}/model/Vreference_top {rel}/firmware.bin {paths([frozen])} 6 faults','faults.log')
    assert 'PASS FAULTS' in (out/'faults.log').read_text()

    lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    map_sources=[overlay,*generated[3:],trim/'kwt_sram_sp.sv',trim/'kwt_tech_sram_blackbox.sv']
    (out/'mapping.ys').write_text(f'''read_liberty -lib {paths([lib])}
read_verilog -sv -DKWT_TECH_SRAM -Irtl/input16_trim2/generated {paths(map_sources)}
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
    sources=[Path(__file__),ROOT/'scripts/run_input16_e203_block.py',*upstream,*packets,host,firmware,startup,
             frozen/'link.ld',frozen/'reference_top.sv',rtl/'kwt_verified_block_reader.sv',
             rtl/'kwt_compact_weight_banks.sv',trim/'generated/kwt_profile.svh',*board,*map_sources,lib]
    report=dict(passed=True,actual_E203=True,full_encoder=False,shared_sram_extra_ports=0,
                scope='frame staging, CRC, indexed replay, weight SRAM and raw common/coefficient consumers',
                cases=cases,private_macro_count=20,private_sram_bytes=65536,supply_partition_standard_cell_mm2=area,
                throughput_tasks_per_second=None,mean_SoC_power_mW=None,complete_counted_area_mm2=None,
                source_sha256={paths([p]):sha(p) for p in sources})
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='source_sha256'},indent=2))


if __name__=='__main__':
    main()
