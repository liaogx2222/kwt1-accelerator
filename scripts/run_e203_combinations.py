"""Controlled AC/ABC firmware, same CPU model and multi-task window contract."""
import argparse,json,os,shutil,subprocess,time
from pathlib import Path
from local_tools import ROOT,Tools,run,sha
BASE=ROOT/'testdata/reference_e203/parallel_20261103'
EX=ROOT/'firmware/e203_experiments_20261104'
OBS=ROOT/'rtl/e203_combinations_20261104/window_observer.hpp'

def prepare(out,kind):
    main=(ROOT/'firmware/reference/main.c').read_text().replace('static int cancelled(void *ctx){(void)ctx;return 0;}','').replace('2000000,cancelled,idle','2000000,0,idle')
    driver=(ROOT/'rtl/integration/driver/kwt1.c').read_text()
    if kind=='abc':
        driver='#include "word_access.h"\n'+driver
        anchor=' size_t k;int rc;\n if((rc=wait_status(d,1u<<9,0)))return rc;'
        assert driver.count(anchor)==1
        driver=driver.replace(anchor,' size_t k;int rc;\n if(!kwt_word_contract(p->data,p->size))return KWT1_ARGUMENT;\n if((rc=wait_status(d,1u<<9,0)))return rc;').replace('le32(p->data+k)','kwt_packet_word(p->data+k)')
    (out/'main.c').write_text(main);(out/'driver.c').write_text(driver);shutil.copyfile(EX/'word_access.h',out/'word_access.h')
    t=Tools();args=[t.gcc(),'-march=rv32imac_zicsr','-mabi=ilp32','-mcmodel=medany','-msmall-data-limit=0','-O2','-g','-ffreestanding','-fno-builtin','-fno-stack-protector','-nostdlib','-nostartfiles','-Wall','-Wextra','-Werror','-I'+str(ROOT/'rtl/integration/driver'),'-I'+str(EX),'-T',EX/'link_itcm.ld','-Wl,--no-relax,-Map='+str(out/'firmware.map'),EX/'start_itcm.S',out/'main.c',out/'driver.c','-o',out/'firmware.elf']
    run(args,out,'gcc');run([t.binutil('objcopy'),'-O','binary',out/'firmware.elf',out/'firmware.bin'],out,'objcopy')
    symbols=run([t.binutil('nm'),'-n',out/'firmware.elf'],out,'nm');(out/'firmware.nm').write_text(symbols)
    mem={s.split()[2]:int(s.split()[0],16) for s in symbols.splitlines() if len(s.split())==3};assert mem['__image_end']==0xa0002010 and mem['__itcm_end']-mem['__itcm_start']<=65536
    (out/'memory_map.json').write_text(json.dumps(mem,indent=2));(out/'compiler_command.json').write_text(json.dumps([str(x) for x in args],indent=2))
    run([t.binutil('objdump'),'-d',out/'firmware.elf'],out,'disassembly')

def build(out):
    model=BASE/'build/model';stamp=json.loads((model/'stamp.json').read_text())
    for name,digest in stamp['inputs'].items():assert sha(Path(name))==digest,name
    source=(ROOT/'rtl/reference/sim_e203.cpp').read_text()
    for old,new in [('static uint32_t word(uint32_t off)','#include "window_observer.hpp"\nstatic uint32_t word(uint32_t off)'),(' if(d.retired)retired++;',' observe_tick(mtake,hrq,ma,mread,ha,hread);\n if(d.retired)retired++;'),('static void finish_job(int rc){','static void finish_job(int rc){\n observe_finish();'),(' std::printf("JOB %u label=%d fault=%d BEGIN',' observe_begin();\n std::printf("JOB %u label=%d fault=%d BEGIN')]:
        assert source.count(old)==1;source=source.replace(old,new)
    src=out/'sim_combinations.cpp';src.write_text(source);shutil.copyfile(OBS,out/OBS.name)
    t=Tools();_,vr=t.verilator();cxx=t.cxx();os.environ['ZIG_GLOBAL_CACHE_DIR']=str(ROOT/'tools/zig-cache')
    objects=sorted((p for p in model.glob('part*.o') if p.name!='part0.o'),key=lambda p:int(p.stem[4:]));assert len(objects)==11
    bound={str(p):sha(p) for p in [*objects,*model.glob('*.h'),OBS,Path(__file__),ROOT/'rtl/reference/sim_e203.cpp',EX/'start_itcm.S',EX/'link_itcm.ld',EX/'word_access.h']}
    (out/'build_bindings.json').write_text(json.dumps(bound,indent=2))
    run([*cxx,'-std=c++17','-O3','-I'+str(vr/'include'),'-I'+str(vr/'include/vltstd'),'-I'+str(model),'-c',src,'-o',out/'observer.o'],out,'compile')
    run([*cxx,'-o',out/'combinations.exe',out/'observer.o',*objects],out,'link');return out/'combinations.exe'

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--kind',choices=['ac','abc'],required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--labels',default='0');ap.add_argument('--faults',action='store_true');ap.add_argument('--model',type=Path);a=ap.parse_args();out=a.output.resolve();assert not out.exists(),'New output required';out.mkdir(parents=True)
    prepare(out,a.kind)
    base=BASE/'classes_0_3';manifest=json.loads((BASE/'evidence_manifest.json').read_text())['sha256']
    for p in base.glob('*.hex'):
        if p.name.startswith(('common.bin','layer_','input_','expected_')):assert sha(p)==manifest['classes_0_3/'+p.name];shutil.copyfile(p,out/p.name)
    labels=list(map(int,a.labels.split(',')));(out/'cases.txt').write_text(''.join(f'{n} 0\n' for n in labels))
    if a.model:
        exe=a.model.resolve()
        for path,digest in json.loads((exe.parent/'build_bindings.json').read_text()).items():assert sha(Path(path))==digest,path
    else:exe=build(out)
    start=time.time();mode='faults' if a.faults else 'batch'
    with (out/'execution.log').open('w') as log:p=subprocess.run([str(exe),str(out),mode],stdout=log,stderr=subprocess.STDOUT)
    assert p.returncode==0,(p.returncode,(out/'execution.log').read_text()[-1500:])
    (out/'execution.json').write_text(json.dumps(dict(passed=True,kind=a.kind,labels=labels,mode=mode,elapsed_seconds=time.time()-start,model_sha256=sha(exe),firmware_sha256=sha(out/'firmware.bin')),indent=2))
    from summarize_e203_combinations import summarize
    summarize(out)

if __name__=='__main__':main()
