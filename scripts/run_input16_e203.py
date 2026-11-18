"""Actual E203 RTL and optimized PIO firmware for the isolated S16 candidate."""
import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from local_tools import ROOT,sha,Tools
import run_reference_e203 as original


def change(t,old,new,count=1):
    assert t.count(old)==count,(old,t.count(old));return t.replace(old,new)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True);rel=out.relative_to(ROOT).as_posix();base=ROOT/'testdata/input16_rtl_20261105';rtl=ROOT/'rtl/input16_signed';cpu=ROOT.parent/'e203_hbirdv2';tools=Tools();start=time.time()
    def run(cmd,name):
        result=subprocess.run([str(x) for x in cmd],capture_output=True,text=True);(out/(name+'.log')).write_text(result.stdout+result.stderr);assert result.returncode==0,(name,result.stdout[-2200:],result.stderr[-2200:]);return result.stdout
    def linux(cmd,name):return run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc','cd /mnt/e/project/ChipCompetition/keyword-transformer && '+cmd],name)
    previous=ROOT/'testdata/e203_software_20261104/full_classes';prevhash=json.loads((previous/'manifest.json').read_text());fixtures=base/'full_native';fhash=json.loads((fixtures/'manifest.json').read_text())
    for n in ['main.c','driver.c','word_access.h']:assert sha(previous/n)==prevhash[n]
    for f in fixtures.glob('*.hex'):
        if f.name.startswith(('common.bin','layer_','input_','expected_')):assert sha(f)==fhash[f.name];shutil.copyfile(f,out/f.name)
    shutil.copyfile(fixtures/'cases.txt',out/'cases.txt');shutil.copyfile(fixtures/'cases.json',out/'cases.json')
    h=ROOT/'rtl/integration/driver/kwt1.h';(out/'kwt1.h').write_text(change(h.read_text(),'const int8_t input[6336]','const int16_t input[6336]'))
    main=change((previous/'main.c').read_text(),'extern int8_t __input[],__output[];','extern int16_t __input[];extern int8_t __output[];').replace('0x4b575431u','0x4b575432u');(out/'main.c').write_text(main)
    driver=change((previous/'driver.c').read_text(),'const int8_t input[6336]','const int16_t input[6336]',2).replace('0x4b575431u','0x4b575432u');driver=change(driver,'input[k]==-128','input[k]==-32768')
    driver=change(driver,'for(k=0;k<6336;k+=4) {\n  if(k+4==6336','for(k=0;k<12672;k+=4) {\n  if(k+4==12672');(out/'driver.c').write_text(driver);shutil.copyfile(previous/'word_access.h',out/'word_access.h')
    exp=ROOT/'firmware/e203_experiments_20261104';link=(exp/'link_itcm.ld').read_text();link=change(link,'__output = ORIGIN(RAM)+0x22000','__output = ORIGIN(RAM)+0x24000');link=change(link,'__packet = ORIGIN(RAM)+0x24000','__packet = ORIGIN(RAM)+0x26000')
    link=change(link,' ASSERT(__packet+61728',' ASSERT(__input+12672<=__output,"S16 input/output overlap")\n ASSERT(__output+6336<=__packet,"output/packet overlap")\n ASSERT(__packet+61728');(out/'link.ld').write_text(link)
    flags=['-march=rv32imac_zicsr','-mabi=ilp32','-mcmodel=medany','-msmall-data-limit=0','-O2','-flto','-g','-ffreestanding','-fno-builtin','-fno-stack-protector','-nostdlib','-nostartfiles','-Wall','-Wextra','-Werror']
    cmd=[tools.gcc(),*flags,'-I'+str(out),'-T',out/'link.ld','-Wl,--no-relax,-Map='+str(out/'firmware.map'),exp/'start_itcm.S',out/'main.c',out/'driver.c','-o',out/'firmware.elf'];(out/'compiler_command.json').write_text(json.dumps(list(map(str,cmd)),indent=2));run(cmd,'firmware')
    run([tools.binutil('objcopy'),'-O','binary',out/'firmware.elf',out/'firmware.bin'],'objcopy');syms=run([tools.binutil('nm'),'-n',out/'firmware.elf'],'firmware_symbols');mem={s.split()[2]:int(s.split()[0],16) for s in syms.splitlines() if len(s.split())==3};assert mem['__input']+12672<=mem['__output'] and mem['__output']+6336<=mem['__packet'] and mem['__packet']+61728<=mem['__stack_bottom']
    (out/'memory_map.json').write_text(json.dumps({k:v for k,v in mem.items() if k.startswith('__')},indent=2))
    original.wrapper(out);wrapper=(out/'reference_top.sv').read_text();begin=wrapper.index(' wire av,');end=wrapper.index(' e203_cpu_top cpu(')
    wrapper=wrapper[:begin]+''' kwt_input16_icb_top path(clk,rst_n,accel_abort,drop_response,pv,pread,pa,pw,pmask,pr,prv,prr,prd,
  hv,hread,ha,hw,hm,hr,hrv,hrr,hrd,irq,bus_rc,parameter_words);
'''+wrapper[end:];(out/'reference_top.sv').write_text(wrapper)
    host=ROOT/'rtl/reference/sim_e203.cpp';sim=change(host.read_text(),'kOutputOffset=0x22000,kPacketOffset=0x24000','kOutputOffset=0x24000,kPacketOffset=0x26000');sim=change(sim,'input.size()==6336','input.size()==12672')
    sim=change(sim,'static int rc_event=999','static uint64_t end_reads=0,end_writes=0,begin_host_words=0;\nstatic int rc_event=999')
    sim=change(sim,'start_params=d.parameter_words;','start_params=d.parameter_words;begin_host_words=host_words;')
    sim=change(sim,'end_clock=clocks;end_retired=retired;','end_clock=clocks;end_retired=retired;end_reads=ram_reads;end_writes=ram_writes;')
    sim=change(sim,' metrics<<ji<<',''' {
  std::ofstream windows(root+"/windows.txt",std::ios::app);
  uint64_t rd=uint64_t(acc_counters[4])|(uint64_t(acc_counters[5])<<32),wr=uint64_t(acc_counters[6])|(uint64_t(acc_counters[7])<<32);
  windows<<ji<<" "<<begin_clock<<" "<<end_clock<<" "<<clocks<<" "<<end_reads-begin_reads<<" "<<end_writes-begin_writes<<" "<<ram_reads-end_reads<<" "<<ram_writes-end_writes<<" "<<rd<<" "<<wr<<" "<<host_words-begin_host_words<<"\\n";
 }
 metrics<<ji<<''');(out/'sim_input16_e203.cpp').write_text(sim)
    names=['kwt_sram_sp.sv','kwt_mac8x8.sv','kwt_iterative.sv','kwt_math.sv','kwt_packet_loader.sv','kwt_layer_banked.sv','kwt1_accel.sv','kwt1_mmio.sv'];project=[ROOT/'rtl/micro/mul_pipe.sv',ROOT/'rtl/micro/rne_pipe.sv',*[rtl/n for n in names],ROOT/'rtl/reference/icb_kwt_bridge.sv',ROOT/'rtl/input16_icb_top.sv',out/'reference_top.sv']
    cpu_files=[*sorted((cpu/'rtl/e203/core').glob('*.v')),*sorted((cpu/'rtl/e203/general').glob('*.v')),cpu/'rtl/e203/subsys/e203_subsys_nice_core.v'];cpu_paths=['../e203_hbirdv2/'+s.relative_to(cpu).as_posix() for s in cpu_files if s.name not in ['config.v','e203_defines.v']]
    paths=' '.join([*cpu_paths,*[s.relative_to(ROOT).as_posix() for s in project]]);hostpath=f'/mnt/e/project/ChipCompetition/keyword-transformer/{rel}/sim_input16_e203.cpp'
    linux(f'verilator --cc --exe --build -j 2 --no-timing -Wno-fatal -DFPGA_SOURCE -DKWT_SIM -I../e203_hbirdv2/rtl/e203/core -Irtl/input16_signed/generated --top-module reference_top --Mdir {rel}/model -CFLAGS -O2 {paths} {hostpath}','build')
    exe=f'{rel}/model/Vreference_top';text=linux(f'{exe} {rel} batch','execution');assert 'PASS E203 jobs=12' in text,text[-1500:]
    fault=out/'faults';fault.mkdir()
    for f in out.iterdir():
        if f.is_file() and (f.name in ['firmware.bin','cases.txt'] or f.name.startswith(('common.bin','layer_','input_','expected_'))):shutil.copyfile(f,fault/f.name)
    faults=linux(f'{exe} {rel}/faults faults','fault_execution');assert 'PASS E203 jobs=4' in faults,faults[-1500:]
    def inspect(folder,expected_jobs):
        m=[[int(v) for v in l.split()] for l in (folder/'cpu_metrics.txt').read_text().splitlines()];w=[[int(v) for v in l.split()] for l in (folder/'windows.txt').read_text().splitlines()];assert len(m)==len(w)==expected_jobs;codes=0
        for row,window in zip(m,w):
            i,label,mode,rc,cycles=row[:5];j,b,e,end,mr,mw,tr,tw,ar,aw,host_words=window;assert i==j and cycles==e-b and end>=e and row[-2:]==[mr+tr,mw+tw]
            if rc==0:
                assert row[8:12]==[189328,13,13,0] and host_words==189328+3168 and ar>0 and aw>0
                actual=(folder/f'cpu_observed_job_{i:02d}.hex').read_text();assert actual.split()==(folder/f'expected_{label:03d}.hex').read_text().split();codes+=6336
        return m,w,codes
    m,w,codes=inspect(out,12);fm,fw,fcodes=inspect(fault,4);assert [x[3] for x in fm]==[-3,0,-7,0]
    cycles=sum(r[4] for r in m);report=dict(passed=True,cpu_revision=run(['git','-C',cpu,'rev-parse','HEAD'],'cpu_revision').strip(),same_CPU_object=True,
        classes=12,codes=codes,recovery_codes=fcodes,mismatches=0,actual_CPU_RTL=True,actual_13_packets=True,task_cycles=[r[4] for r in m],total_cycles=cycles,
        throughput_at_assumed_150MHz=12*150000000/cycles,achieved_150MHz_verified=False,window='B0 input scheduled through B1 driver return after full final writeback; B2 statistics separate',
        window_columns=['job','begin','driver_return','report_finished','main_shared_reads','main_shared_writes','tail_shared_reads','tail_shared_writes','private_reads','private_writes','host_input_parameter_writes'],windows=w,
        private_SRAM_bytes=163840,input_bytes=12672,stack_high_water=max(r[13] for r in m),fault_rc=[r[3] for r in fm],fault_windows=fw,full_SoC_power_measured=False,runtime_seconds=time.time()-start)
    (out/'verification.json').write_text(json.dumps(report,indent=2));bound=[Path(__file__),Path(original.__file__),h,host,exp/'start_itcm.S',exp/'link_itcm.ld',*[previous/n for n in ['main.c','driver.c','word_access.h']],rtl/'generated/kwt_profile.svh',*project,*cpu_files]
    (out/'source_bindings.json').write_text(json.dumps({os.path.relpath(p,ROOT).replace('\\','/'):sha(p) for p in bound},indent=2));(out/'manifest.json').write_text(json.dumps({f.relative_to(out).as_posix():sha(f) for f in out.rglob('*') if f.is_file() and 'model' not in f.relative_to(out).parts},indent=2));print(json.dumps({k:v for k,v in report.items() if k not in ['windows','fault_windows']},indent=2))


if __name__=='__main__':main()
