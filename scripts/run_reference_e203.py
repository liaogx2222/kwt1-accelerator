"""Actual supplied E203 RTL + frozen encoder; RV32 linked firmware, no host driver."""
import argparse,concurrent.futures,hashlib,json,os,re,subprocess,sys,time,shutil,platform
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];CPU=Path(os.environ.get('KWT_E203_REPO',ROOT.parent/'e203_hbirdv2')).resolve()
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from local_tools import Tools,SUFFIX,run
TOOLS=Tools()
SOURCES=[ROOT/line for line in (ROOT/'rtl/v2/files.f').read_text().splitlines() if line.strip() and not line.startswith('+') and not line.endswith('kwt1_mmio.sv')]
R=ROOT/'rtl/reference';F=ROOT/'firmware/reference'
def write(p,v):p.write_text(json.dumps(v,indent=2),encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def wrapper(out):
    header=(CPU/'rtl/e203/core/e203_cpu_top.v').read_text().split('  );',1)[0]
    pins=re.findall(r'^\s*(input|output)\s+(?:\[[^\]]+\]\s*)?(\w+)\s*[,\n]',header,re.M)
    mapping={'clk':'clk','rst_n':'rst_n','pc_rtvec':"32'ha0000000",'ext_irq_a':'irq','inspect_pc':'pc'}
    for prefix,local in [('mem','m'),('ppi','p')]:
        for old,new in [('cmd_valid','v'),('cmd_ready','r'),('cmd_addr','a'),('cmd_read','read'),('cmd_wdata','w'),('cmd_wmask','mask'),('rsp_valid','rv'),('rsp_ready','rr'),('rsp_rdata','rd')]:mapping[f'{prefix}_icb_{old}']=local+new
    text='''module reference_top(input clk,rst_n,accel_abort,drop_response,
 output mv,input mr,output [31:0] ma,mw,output mread,output [3:0] mmask,input mrv,output mrr,input [31:0] mrd,
 output hv,input hr,output [31:0] ha,hw,output hread,output [3:0] hm,input hrv,output hrr,input [31:0] hrd,
 output [31:0] pc,sp,output retired,output irq,output signed [31:0] bus_rc,output [31:0] parameter_words);
 wire pv,pr,pread,prv,prr;wire [31:0] pa,pw,prd;wire [3:0] pmask;
 wire av,ar,awrite,arv,arr,ae;wire [31:0] aa,ad,ard;wire [3:0] am;
 icb_kwt_bridge bridge(clk,rst_n,accel_abort,16'd64,drop_response,pv,pr,pa,pw,pread,pmask,prv,prr,prd,
 hv,hr,ha,hw,hread,hm,hrv,hrr,hrd,av,ar,awrite,aa,ad,am,arv,arr,ard,ae,bus_rc,parameter_words);
 kwt1_mmio accel(clk,rst_n,accel_abort,1'b1,1'b1,av,ar,awrite,aa,ad,am,arv,arr,ard,ae,irq);
 e203_cpu_top cpu(
'''
    connections=[]
    for direction,name in pins:
        signal=mapping.get(name,"1'b0" if direction=='input' else '')
        connections.append(f' .{name}({signal})')
    text+=',\n'.join(connections)
    text+='''
 );
 assign sp=cpu.u_e203_cpu.u_e203_core.u_e203_exu.u_e203_exu_regfile.rf_r[2];
 assign retired=cpu.u_e203_cpu.u_e203_core.u_e203_exu.cmt_instret_ena;
endmodule
''';(out/'reference_top.sv').write_text(text);assert len(pins)>65,len(pins)

def firmware(out,smoke=False):
    GCC=TOOLS.gcc()
    run([GCC,'-march=rv32imac_zicsr','-mabi=ilp32','-mcmodel=medany','-msmall-data-limit=0','-O2','-g','-ffreestanding','-fno-builtin','-fno-stack-protector','-nostdlib','-nostartfiles','-Wall','-Wextra','-Werror',*(['-DBOOT_SMOKE'] if smoke else []),'-I'+str(ROOT/'rtl/integration/driver'),'-T',F/'link.ld','-Wl,--no-relax,-Map='+str(out/'firmware.map'),F/'start.S',F/'main.c',ROOT/'rtl/integration/driver/kwt1.c','-o',out/'firmware.elf'],out)
    objcopy=TOOLS.binutil('objcopy');nm=TOOLS.binutil('nm')
    run([objcopy,'-O','binary',out/'firmware.elf',out/'firmware.bin'],out)
    symbols=run([nm,'-n',out/'firmware.elf'],out);(out/'firmware.nm').write_text(symbols)
    address={s.split()[2]:int(s.split()[0],16) for s in symbols.splitlines() if len(s.split())==3}
    assert address['__image_end']<=address['__input'] and address['__packet']+61728<address['__stack_bottom']
    write(out/'memory_map.json',{k:v for k,v in address.items() if k.startswith('__')})

def build(out):
    verilator,VR=TOOLS.verilator();cxx=TOOLS.cxx()
    model=out/'model';model.mkdir(parents=True,exist_ok=True);wrapper(out)
    sources=[*sorted((CPU/'rtl/e203/core').glob('*.v')),*sorted((CPU/'rtl/e203/general').glob('*.v')),CPU/'rtl/e203/subsys/e203_subsys_nice_core.v',*SOURCES,ROOT/'rtl/v2/kwt1_mmio.sv',R/'icb_kwt_bridge.sv',out/'reference_top.sv']
    sources=[p for p in sources if p.name not in ['config.v','e203_defines.v']]
    inputs=[*sources,CPU/'rtl/e203/core/config.v',CPU/'rtl/e203/core/e203_defines.v',R/'sim_e203.cpp']
    stamp=dict(inputs={str(p):sha(p) for p in inputs},verilator=sha(verilator),cxx=cxx,optimization='-O3')
    exe=model/('sim'+SUFFIX)
    if (model/'stamp.json').exists() and json.loads((model/'stamp.json').read_text())==stamp and exe.exists():return exe
    os.environ['VERILATOR_ROOT']=str(VR);os.environ['ZIG_GLOBAL_CACHE_DIR']=str(ROOT/'tools/zig-cache')
    run([verilator,'--cc','--no-timing','--Wno-fatal','-Wno-WIDTHEXPAND','-Wno-WIDTHTRUNC','-DFPGA_SOURCE','-I'+str(CPU/'rtl/e203/core'),'-I'+str(ROOT/'rtl/v2/generated'),'--top-module','reference_top','--Mdir',model,*sources],out,'verilate')
    cpp=[R/'sim_e203.cpp',*model.glob('*.cpp'),VR/'include/verilated.cpp',VR/'include/verilated_threads.cpp']
    def compile_one(item):
        n,p=item;obj=model/f'part{n}.o';r=subprocess.run([str(x) for x in [*cxx,'-std=c++17','-O3','-I'+str(VR/'include'),'-I'+str(VR/'include/vltstd'),'-I'+str(model),'-c',p,'-o',obj]],capture_output=True,text=True)
        (model/f'compile{n}.log').write_text(r.stdout+r.stderr)
        if r.returncode:raise RuntimeError(r.stderr)
        print(f'COMPILE {n+1}/{len(cpp)}',flush=True);return obj
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:objects=list(pool.map(compile_one,enumerate(cpp)))
    run([*cxx,'-o',exe,*objects],out,'link_model');write(model/'stamp.json',stamp);return exe

def fixtures(out,quick,labels=None):
    # Consume immutable host fixtures without importing training/NumPy packages.
    base=ROOT/'testdata/integration_v1/release/candidate_system'
    if not base.exists():base=ROOT/'fixtures'  # standalone system package
    for path in base.glob('*.hex'):
        if path.name.startswith(('common.bin','layer_','input_','expected_')):shutil.copyfile(path,out/path.name)
    cases=json.loads((base/'cases.json').read_text());cases=[c for c in cases if c['label'] in labels] if labels is not None else cases[:1] if quick else cases
    write(out/'cases.json',cases);(out/'cases.txt').write_text(''.join(f'{c["case"]} 0\n' for c in cases))

def provenance(out,exe):
    inputs=[*F.glob('*'),*R.glob('*'),ROOT/'scripts/run_reference_e203.py',ROOT/'scripts/local_tools.py',ROOT/'rtl/integration/driver/kwt1.c',ROOT/'rtl/integration/driver/kwt1.h',ROOT/'rtl/v2/generated/kwt_profile.svh',ROOT/'rtl/v2/files.f',*SOURCES,ROOT/'rtl/v2/kwt1_mmio.sv']
    project={p.relative_to(ROOT).as_posix():sha(p) for p in inputs if p.is_file()}
    cpu={p.relative_to(CPU).as_posix():sha(p) for p in sorted((CPU/'rtl/e203').rglob('*')) if p.is_file()}
    for name in ['LICENSE','README.md','e203_core.core']:cpu[name]=sha(CPU/name)
    git=subprocess.run(['git','-c',f'safe.directory={CPU.as_posix()}','-C',str(CPU),'rev-parse','HEAD'],capture_output=True,text=True)
    versions={}
    for name,args in [('gcc',[TOOLS.gcc(),'--version']),('verilator',[TOOLS.verilator()[0],'--version']),('cxx',[*TOOLS.cxx(),'--version'])]:
        result=subprocess.run([str(x) for x in args],capture_output=True,text=True);versions[name]=(result.stdout+result.stderr).splitlines()[:3]
    write(out/'provenance.json',dict(cpu_revision=git.stdout.strip() if git.returncode==0 else 'see bound source files',cpu_license='Apache-2.0',cpu_remote='https://github.com/riscv-mcu/e203_hbirdv2.git',cpu=cpu,project=project,host=platform.platform(),python=sys.version,tools=versions,firmware_sha256=sha(out/'firmware.elf'),model_sha256=sha(exe),defines=['FPGA_SOURCE'],ISA='rv32imac_zicsr',ABI='ilp32',cpu_boot='external shared RAM, ITCM/DTCM not used',physical_signoff=False))

def main():
    global TOOLS
    ap=argparse.ArgumentParser();ap.add_argument('--stage',choices=['smoke','run','build'],default='run');ap.add_argument('--output',type=Path,default=ROOT/'testdata/reference_e203/development');ap.add_argument('--quick',action='store_true');ap.add_argument('--tools',type=Path);ap.add_argument('--labels',help='Comma-separated labels for independent consecutive-task groups');ap.add_argument('--faults-only',action='store_true');ap.add_argument('--model',type=Path,help='Reuse a source-validated compiled reference model');a=ap.parse_args();out=a.output.resolve();TOOLS=Tools(a.tools)
    if (out/'verification.json').exists():raise ValueError('Verified result exists; choose a fresh output directory')
    out.mkdir(parents=True,exist_ok=True)
    firmware(out,a.stage=='smoke')
    if a.stage!='smoke':fixtures(out,a.quick,list(map(int,a.labels.split(','))) if a.labels else None)
    if a.model:
        exe=a.model.resolve();stamp=json.loads((exe.parent/'stamp.json').read_text())
        for name,digest in stamp['inputs'].items():assert sha(Path(name))==digest,('stale model',name)
    else:exe=build(out)
    provenance(out,exe);start=time.time()
    if a.stage=='build':return
    mode='smoke' if a.stage=='smoke' else 'faults' if a.faults_only else 'batch' if a.labels else 'quick' if a.quick else 'full'
    with (out/'live.log').open('w') as log:r=subprocess.run([str(exe),str(out),mode],stdout=log,stderr=subprocess.STDOUT)
    print((out/'live.log').read_text(),flush=True)
    if r.returncode:raise RuntimeError('reference simulation failed')
    write(out/'execution.json',dict(passed=True,stage=a.stage,quick=a.quick,mode=mode,elapsed_seconds=time.time()-start,command=[exe.name,out.name,mode],scope='actual E203 RTL executing RV32 firmware + frozen accelerator RTL; not final SoC or physical signoff'))
if __name__=='__main__':main()
