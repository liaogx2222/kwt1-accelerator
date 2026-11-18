"""Exercise the direct stream overlay on real E203 and the unchanged trim2 core."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from local_tools import ROOT, Tools, sha
from run_input16_e203_block import firmware_sources, phase_report, replace_once


def overlays(out, frozen, cpu, rtl):
    ports = '''    output wire stream_valid,
    input wire stream_ready, stream_error, stream_cancel,
    output wire [31:0] stream_data,
'''
    connections = '''    .stream_valid(stream_valid), .stream_ready(stream_ready),
    .stream_error(stream_error), .stream_cancel(stream_cancel), .stream_data(stream_data),
'''
    for name, opening, instance in [
        ('e203_cpu_top.v', 'module e203_cpu_top(\n', '  e203_cpu #(.MASTER(1)) u_e203_cpu(\n'),
        ('e203_cpu.v', '    parameter MASTER = 1\n)(\n', 'e203_subsys_nice_core u_e203_nice_core  (\n'),
    ]:
        source = (cpu/'rtl/e203/core'/name).read_text()
        source = replace_once(source, opening, opening+ports)
        source = replace_once(source, instance, instance+connections)
        (out/name).write_text(source)

    top = (frozen/'reference_top.sv').read_text()
    top = replace_once(top, 'input clk,rst_n,accel_abort,drop_response,',
                       '''input clk,rst_n,accel_abort,drop_response,stream_cancel,
 output stream_accepted, output [31:0] stream_payload,''')
    top = replace_once(top, ' kwt_input16_icb_top path(', ''' wire stream_valid,stream_ready,stream_error;
 wire [31:0] stream_data;
 assign stream_payload=stream_data;
 kwt_input16_icb_top path(''')
    top = replace_once(top, 'irq,bus_rc,parameter_words);',
                       'irq,bus_rc,parameter_words,stream_valid,stream_ready,stream_error,stream_data,stream_accepted);')
    top = replace_once(top, ' e203_cpu_top cpu(\n', ' e203_cpu_top cpu(\n'+connections)
    (out/'reference_top.sv').write_text(top)

    bridge = (ROOT/'rtl/input16_icb_top.sv').read_text()
    bridge = replace_once(bridge, 'output wire [31:0] parameter_words);',
                          '''output wire [31:0] parameter_words,
 input wire stream_valid, output wire stream_ready,stream_error,
 input wire [31:0] stream_data, output wire stream_accepted);
 wire [31:0] scalar_words;''')
    bridge = replace_once(bridge, 'ae,bus_rc,parameter_words);', 'ae,bus_rc,scalar_words);')
    bridge = replace_once(bridge, 'ard,ae,irq);',
                          '''ard,ae,irq,
  stream_valid,stream_ready,stream_error,stream_data,drop_response,stream_accepted,scalar_words,parameter_words);''')
    (out/'kwt_input16_icb_top.sv').write_text(bridge)

    mmio = (rtl/'kwt1_mmio.sv').read_text()
    mmio = replace_once(mmio, ' output wire irq);', ''' output wire irq,
 input wire stream_valid, output wire stream_ready,stream_error,
 input wire [31:0] stream_data, input wire stream_blocked, output wire stream_accepted,
 input wire [31:0] scalar_words, output wire [31:0] total_words);''')
    mmio = replace_once(mmio, ' wire valid_cfg=issue', ' wire scalar_cfg=issue')
    mmio = replace_once(mmio, ' kwt1_accel accel(', ''' wire valid_cfg,scalar_cfg_ready;
 wire [31:0] cfg_data;
 kwt_stream_ingress ingress(clk,rst_n,stream_blocked,task_abort,error,
  stream_valid,stream_ready,stream_error,stream_data,scalar_cfg,scalar_cfg_ready,req_wdata,
  cfg_ready,valid_cfg,cfg_data,stream_accepted,scalar_words,total_words);
 kwt1_accel accel(''')
    mmio = replace_once(mmio, 'valid_cfg,cfg_ready,req_wdata,last_flag', 'valid_cfg,cfg_ready,cfg_data,last_flag')
    mmio = replace_once(mmio, 'req_ready=req_ready&&cfg_ready;', 'req_ready=req_ready&&scalar_cfg_ready;')
    mmio = replace_once(mmio, '   sw_abort<=0;\n', '   sw_abort<=0;\n   if(stream_accepted)last_flag<=0;\n')
    (out/'kwt1_mmio.sv').write_text(mmio)


def firmware(out, frozen):
    firmware_sources(out, frozen)
    driver = (out/'driver.c').read_text()
    driver = replace_once(driver, 'int kwt_block_copy(', 'uint32_t kwt_stream_first_address,kwt_stream_first_status;\nint kwt_block_copy(')
    driver = replace_once(driver, ' return rc;\n}\nstatic int packet(', ''' if(rc==0||rc==-3)return rc;
 uint32_t status=(uint32_t)rc;
 kwt_stream_first_status=status;
 kwt_stream_first_address=(uint32_t)(uintptr_t)source+4*((status>>8)&127);
 switch(status&7){case 2:return KWT1_TIMEOUT;case 3:return KWT1_CANCELLED;default:return KWT1_IO;}
}
static int packet(''')
    (out/'driver.c').write_text(driver)
    main = (out/'main.c').read_text()
    main = replace_once(main, 'void kwt_block_release_after_recovery',
                        'extern uint32_t kwt_stream_first_address,kwt_stream_first_status;\nvoid kwt_block_release_after_recovery')
    main = replace_once(main, '  uint64_t c0=cycle()', '  kwt_stream_first_address=kwt_stream_first_status=0;\n  uint64_t c0=cycle()')
    main = replace_once(main, '  hwrite(40,(uint32_t)d.last_error);',
                        '''  if(kwt_stream_first_status){hwrite(104,kwt_stream_first_address);hwrite(108,kwt_stream_first_status);}
  hwrite(40,(uint32_t)d.last_error);''')
    (out/'main.c').write_text(main)


def observer(out, a):
    source = (a/'observer.cpp').read_text()
    source = replace_once(source, 'static int rc_event=999', 'static uint32_t fault_address=0,fault_status=0;\nstatic int rc_event=999')
    source = replace_once(source, ' acquires=releases=cancels=peak=0;', ' fault_address=fault_status=0;\n acquires=releases=cancels=peak=0;')
    source = replace_once(source, 'jobs[ji].fault==2?-7:0', 'jobs[ji].fault==2?-7:jobs[ji].fault==3?-5:0')
    source = replace_once(source, ' }else if(rc==-7)require(last_error==-2&&abort_error==-2,"lost timeout/cleanup errors");',
                          ''' }else if(rc==-7){
  require(last_error==-2&&abort_error==-2,"lost timeout/cleanup errors");
  require(fault_address==kRamBase+kPacketOffset+4*64&&fault_status==0x80000002u,"timeout fault cursor");
 }else if(rc==-5){
  require(last_error==-5&&abort_error==0,"in-block cancellation was not confirmed");
  require(fault_address==kRamBase+kPacketOffset+4*17&&fault_status==0x80001103u,"cancel fault cursor");
 }''')
    source = replace_once(source, '  case 100:', '''  case 104:fault_address=value;break;
  case 108:fault_status=value;break;
  case 100:''')
    source = replace_once(source, ' d.drop_response=active', ''' d.stream_cancel=active&&fault_active&&jobs[ji].fault==3&&d.parameter_words-start_params>=17;
 d.drop_response=active''')
    source = replace_once(source, 'jobs.push_back({0,2});jobs.push_back({0,0});}',
                          'jobs.push_back({0,2});jobs.push_back({0,0});jobs.push_back({0,3});jobs.push_back({0,0});}')
    (out/'observer.cpp').write_text(source)
    header = (a/'window_observer.hpp').read_text()
    scalar = 'r->reference_top__DOT__path__DOT__bridge__DOT__state==1&&r->reference_top__DOT__path__DOT__ar'
    header = replace_once(header, ' if('+scalar, ' if(d.stream_accepted || ('+scalar)
    header = replace_once(header, '__bridge__DOT__addr&65535)==16){\n  require(leased', '__bridge__DOT__addr&65535)==16)){\n  require(leased')
    header = replace_once(header, 'require(value==r->reference_top__DOT__path__DOT__bridge__DOT__data,',
                          'require(value==(d.stream_accepted?d.stream_payload:r->reference_top__DOT__path__DOT__bridge__DOT__data),')
    header = replace_once(header, '(jobs[ji].fault==2 && lease_bytes<packet.size() && reset_requests==1 && last_error==-2 && abort_error==-2),',
                          '''(jobs[ji].fault==2 && lease_bytes==256 && reset_requests==1 && last_error==-2 && abort_error==-2) ||
  (jobs[ji].fault==3 && lease_bytes==68 && d.bus_rc==0 &&
   r->reference_top__DOT__path__DOT__accelerator__DOT__accel__DOT__state==0),''')
    header = replace_once(header, 'phases[p]++;phase_retired[p]+=d.retired;',
                          'phases[p]++;phase_retired[p]+=d.retired;\n   if(d.stream_accepted)data_ready_cycles++;')
    (out/'window_observer.hpp').write_text(header)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True)
    base = ROOT/'testdata/input16_rtl_20261105'
    frozen, a = base/'trim2_e203', base/'p2_e203_block_verified'
    cpu = ROOT.parent/'e203_hbirdv2'
    rtl = ROOT/'rtl/input16_trim2'
    rel = out.relative_to(ROOT).as_posix()
    cwd = '/mnt/e/project/ChipCompetition/keyword-transformer'
    tools = Tools()

    def run(command, log):
        with (out/log).open('w') as handle:
            result = subprocess.run([str(v) for v in command], stdout=handle, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f'{log}\n{(out/log).read_text(errors="replace")[-4000:]}')

    def linux(command, log):
        run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {command}'],log)

    fixtures = sorted(frozen.glob('*.bin.hex')) + [frozen/f'{n}_000.hex' for n in ('input','expected')]
    frozen_sources = [frozen/n for n in ('kwt1.h','word_access.h','link.ld','driver.c','main.c','reference_top.sv','firmware.bin')]
    a_sources = [a/n for n in ('observer.cpp','window_observer.hpp','verification.json')]
    for folder, files in ((frozen, fixtures+frozen_sources), (a,a_sources)):
        manifest = json.loads((folder/'manifest.json').read_text())
        for path in files:
            assert sha(path)==manifest[path.name], path
    for path in frozen_sources[:3]:
        shutil.copyfile(path, out/path.name)
    overlays(out, frozen, cpu, rtl)
    firmware(out, frozen)
    observer(out, a)
    start = ROOT/'firmware/e203_experiments_20261104/start_itcm.S'
    flags = ['-march=rv32imac_zicsr','-mabi=ilp32','-mcmodel=medany','-msmall-data-limit=0','-O2','-flto','-g',
             '-ffreestanding','-fno-builtin','-fno-stack-protector','-nostdlib','-nostartfiles','-Wall','-Wextra','-Werror']
    cmd = [tools.gcc(),*flags,'-I'+str(out),'-T',out/'link.ld','-Wl,--no-relax,-Map='+str(out/'firmware.map'),
           start,out/'main.c',out/'driver.c','-o',out/'firmware.elf']
    (out/'compiler_command.json').write_text(json.dumps(list(map(str,cmd)),indent=2))
    run(cmd,'firmware.log')
    run([tools.binutil('objcopy'),'-O','binary',out/'firmware.elf',out/'firmware.bin'],'objcopy.log')
    run(['git','-C',cpu,'rev-parse','HEAD'],'cpu_revision.txt')
    cpu_files = sorted((cpu/'rtl/e203/core').glob('*.v')) + sorted((cpu/'rtl/e203/general').glob('*.v'))
    generated = [out/n for n in ('e203_cpu_top.v','e203_cpu.v','kwt_input16_icb_top.sv','kwt1_mmio.sv','reference_top.sv')]
    skip = {p.name for p in generated} | {'config.v','e203_defines.v','kwt_tech_sram_blackbox.sv'}
    inputs = [ROOT/'rtl/block_transfer'/n for n in ('kwt_e203_stream_write.sv','kwt_stream_ingress.sv')]
    inputs += [ROOT/'rtl/micro/mul_pipe.sv',ROOT/'rtl/micro/rne_pipe.sv',ROOT/'rtl/reference/icb_kwt_bridge.sv']
    inputs += sorted(p for p in rtl.glob('*.sv') if p.name not in skip)
    bound = [Path(__file__),ROOT/'scripts/run_input16_e203_block.py',start,*fixtures,*frozen_sources,*a_sources,
             *cpu_files,*inputs,*generated,ROOT/'rtl/input16_icb_top.sv',rtl/'kwt1_mmio.sv',rtl/'generated/kwt_profile.svh']
    (out/'source_bindings.json').write_text(json.dumps({os.path.relpath(p,ROOT).replace('\\','/'):sha(p) for p in bound},indent=2))
    sources = ' '.join(os.path.relpath(p,ROOT).replace('\\','/') for p in [*cpu_files,*inputs,*generated]
                       if p in generated or p.name not in skip)
    linux(f'verilator --cc --exe --no-timing -Wno-fatal --output-split 16000 --output-split-cfuncs 500 '
          f'-DFPGA_SOURCE -DKWT_SIM -I../e203_hbirdv2/rtl/e203/core -Irtl/input16_trim2/generated '
          f'--top-module reference_top --Mdir {rel}/model {sources} {cwd}/{rel}/observer.cpp','generate.log')
    linux(f'make -C {rel}/model -f Vreference_top.mk -j 3 OPT_FAST=-O2 OPT_SLOW=-O0','build.log')
    results = {}
    for name, image, mode, expected_jobs in [
        ('pio',frozen/'firmware.bin','batch',[0]),('block',out/'firmware.bin','batch',[0]),
        ('faults',out/'firmware.bin','faults',[1,3,5]),
    ]:
        folder = out/name
        folder.mkdir()
        for path in fixtures:
            shutil.copyfile(path,folder/path.name)
        shutil.copyfile(image,folder/'firmware.bin')
        (folder/'cases.txt').write_text('0 0\n')
        linux(f'{rel}/model/Vreference_top {rel}/{name} {mode}',name+'.log')
        cases = phase_report(folder)
        for job in expected_jobs:
            assert (folder/f'cpu_observed_job_{job:02d}.hex').read_text().split()==(folder/'expected_000.hex').read_text().split()
            assert cases[job]['words']==cases[job]['staging_reads']==cases[job]['data_ready_cycles']==189328
        if name=='faults':
            assert cases[2]['words']==64 and cases[2]['staging_reads']==65
            assert cases[4]['words']==17 and cases[4]['staging_reads']==18
            assert len(cases)==6
        results[name]=cases
    baseline = json.loads((a/'verification.json').read_text())
    assert results['pio'][0]==baseline['cases']['pio'][0]
    block=results['block'][0]
    report=dict(passed=True,actual_E203=True,added_RAM_port=False,architecture='trim2 direct loader',
                cases=results,phase_order=baseline['phase_order'],output_codes=5*6336,mismatches=0,
                tasks_per_second_at_assumed_150MHz=150000000/block['cycles'],mean_SoC_power_mW=None,
                complete_counted_area_mm2=None)
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.relative_to(out).as_posix():sha(p) for p in out.rglob('*')
                                                if p.is_file() and 'model' not in p.relative_to(out).parts},indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
