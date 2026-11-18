"""P0/P1 isolated experiments. Never modify prior sources/releases."""
import argparse,json,os,shutil,subprocess,time
from pathlib import Path
from local_tools import ROOT,Tools,sha,run

BASE=ROOT/'testdata/reference_e203/parallel_20261103'
EX=ROOT/'firmware/e203_experiments_20261104'
OBSERVER=ROOT/'rtl/e203_experiments_20261104/window_observer.hpp'

def prepare(out,factor):
    base=BASE/'classes_0_3';manifest=json.loads((BASE/'evidence_manifest.json').read_text())['sha256']
    for p in base.glob('*.hex'):
        if p.name.startswith(('common.bin','layer_','input_','expected_')):
            assert sha(p)==manifest['classes_0_3/'+p.name];shutil.copyfile(p,out/p.name)
    (out/'cases.txt').write_text('0 0\n')
    if factor=='baseline':
        for name in ['firmware.bin','firmware.elf','firmware.nm','firmware.map','memory_map.json']:shutil.copyfile(base/name,out/name)
        return
    main=(ROOT/'firmware/reference/main.c').read_text();driver=(ROOT/'rtl/integration/driver/kwt1.c').read_text()
    if factor=='null_cancel':
        main=main.replace('static int cancelled(void *ctx){(void)ctx;return 0;}','')
        assert '2000000,cancelled,idle' in main;main=main.replace('2000000,cancelled,idle','2000000,0,idle')
    if factor in ['aligned','misaligned']:
        driver='#include "word_access.h"\n'+driver
        anchor=' size_t k;int rc;\n if((rc=wait_status(d,1u<<9,0)))return rc;'
        assert driver.count(anchor)==1
        driver=driver.replace(anchor,' size_t k;int rc;\n if(!kwt_word_contract(p->data,p->size))return KWT1_ARGUMENT;\n if((rc=wait_status(d,1u<<9,0)))return rc;')
        assert driver.count('le32(p->data+k)')==1;driver=driver.replace('le32(p->data+k)','kwt_packet_word(p->data+k)')
        shutil.copyfile(EX/'word_access.h',out/'word_access.h')
        if factor=='misaligned':main=main.replace('p->data=__packet;','p->data=__packet+1;')
    (out/'main.c').write_text(main);(out/'driver.c').write_text(driver)
    tools=Tools();start=ROOT/'firmware/reference/start.S';link=ROOT/'firmware/reference/link.ld'
    if factor=='itcm':start=EX/'start_itcm.S';link=EX/'link_itcm.ld'
    cmd=[tools.gcc(),'-march=rv32imac_zicsr','-mabi=ilp32','-mcmodel=medany','-msmall-data-limit=0','-O2','-g','-ffreestanding','-fno-builtin','-fno-stack-protector','-nostdlib','-nostartfiles','-Wall','-Wextra','-Werror','-I'+str(ROOT/'rtl/integration/driver'),'-I'+str(EX),'-T',link,'-Wl,--no-relax,-Map='+str(out/'firmware.map'),start,out/'main.c',out/'driver.c','-o',out/'firmware.elf']
    run(cmd,out,'gcc');run([tools.binutil('objcopy'),'-O','binary',out/'firmware.elf',out/'firmware.bin'],out,'objcopy')
    symbols=run([tools.binutil('nm'),'-n',out/'firmware.elf'],out,'nm');(out/'firmware.nm').write_text(symbols)
    addresses={s.split()[2]:int(s.split()[0],16) for s in symbols.splitlines() if len(s.split())==3}
    assert addresses['__image_end']<=addresses['__input'] and addresses['__packet']+61728<=addresses['__stack_bottom']
    (out/'memory_map.json').write_text(json.dumps(addresses,indent=2))
    dis=run([tools.binutil('objdump'),'-d',out/'firmware.elf'],out,'disassembly');(out/'firmware_disassembly.txt').write_text(dis)
    (out/'compiler_command.json').write_text(json.dumps([str(x) for x in cmd],indent=2))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--factor',choices=['baseline','null_cancel','aligned','misaligned','itcm'],required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve()
    assert not out.exists(),'Use a new output';out.mkdir(parents=True)
    stamp=json.loads((BASE/'build/model/stamp.json').read_text())
    for name,digest in stamp['inputs'].items():assert sha(Path(name))==digest,name
    prepare(out,a.factor)
    source=(ROOT/'rtl/reference/sim_e203.cpp').read_text()
    edits={'static uint32_t word(uint32_t off)':'#include "window_observer.hpp"\nstatic uint32_t word(uint32_t off)',
           ' if(d.retired)retired++;':' observe_tick(mtake,hrq,ma,mread,ha,hread);\n if(d.retired)retired++;',
           'static void finish_job(int rc){':'static void finish_job(int rc){\n observe_finish();'}
    for old,new in edits.items():assert source.count(old)==1;source=source.replace(old,new)
    if a.factor=='misaligned':
        source=source.replace('int expected_rc=jobs[ji].fault==1?-3:jobs[ji].fault==2?-7:0;','int expected_rc=-4;')
        source=source.replace('else require(last_error==-3&&abort_error==0,"CRC cleanup");','else require(last_error==-4&&abort_error==0,"alignment rejection cleanup");')
    src=out/'sim_factor.cpp';src.write_text(source);shutil.copyfile(OBSERVER,out/OBSERVER.name)
    tools=Tools();_,vr=tools.verilator();cxx=tools.cxx();os.environ['ZIG_GLOBAL_CACHE_DIR']=str(ROOT/'tools/zig-cache')
    model=BASE/'build/model';objects=sorted((p for p in model.glob('part*.o') if p.name!='part0.o'),key=lambda p:int(p.stem[4:]));assert len(objects)==11
    inputs=[*objects,*model.glob('*.h'),OBSERVER,Path(__file__),ROOT/'rtl/reference/sim_e203.cpp',ROOT/'rtl/integration/driver/kwt1.c',ROOT/'firmware/reference/main.c',ROOT/'firmware/reference/start.S',ROOT/'firmware/reference/link.ld']
    if a.factor in ['aligned','misaligned']:inputs += [EX/'word_access.h']
    if a.factor=='itcm':inputs += [EX/'start_itcm.S',EX/'link_itcm.ld']
    bound={str(p):sha(p) for p in inputs};(out/'build_bindings.json').write_text(json.dumps(bound,indent=2))
    run([*cxx,'-std=c++17','-O3',*(['-DFACTOR_REJECT'] if a.factor=='misaligned' else []),'-I'+str(vr/'include'),'-I'+str(vr/'include/vltstd'),'-I'+str(model),'-c',src,'-o',out/'observer.o'],out,'compile')
    run([*cxx,'-o',out/'factor.exe',out/'observer.o',*objects],out,'link')
    start=time.time()
    with (out/'execution.log').open('w') as log:p=subprocess.run([str(out/'factor.exe'),str(out),'batch'],stdout=log,stderr=subprocess.STDOUT)
    assert p.returncode==0,(p.returncode,(out/'execution.log').read_text()[-1000:])
    for name,digest in bound.items():assert sha(Path(name))==digest,name
    (out/'execution.json').write_text(json.dumps(dict(passed=True,factor=a.factor,elapsed_seconds=time.time()-start,firmware_sha256=sha(out/'firmware.bin')),indent=2))
    from summarize_e203_factors import summarize
    summarize(out)

if __name__=='__main__':main()
