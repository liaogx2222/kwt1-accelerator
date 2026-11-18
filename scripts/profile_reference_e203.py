"""Non-intrusive host observer; reuse source-bound generated model objects.

One frozen class-0 task, original firmware and transaction timing unchanged.
"""
import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from local_tools import ROOT, Tools, sha


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    out=a.output.resolve();assert not out.exists(),'Use new output';out.mkdir(parents=True)
    shutil.copyfile(Path(__file__),out/'runner_executed.py')
    release=ROOT/'testdata/reference_e203/parallel_20261103';model=release/'build/model'
    base=release/'classes_0_3';stamp=json.loads((model/'stamp.json').read_text())
    for name,digest in stamp['inputs'].items():assert sha(Path(name))==digest,name
    manifest=json.loads((release/'evidence_manifest.json').read_text())['sha256']
    for name in ['classes_0_3/firmware.bin','classes_0_3/firmware.elf','classes_0_3/firmware.nm']:
        assert sha(release/name)==manifest[name]
    for path in base.glob('*.hex'):
        if not path.name.startswith(('common.bin','layer_','input_','expected_')):continue
        assert sha(path)==manifest['classes_0_3/'+path.name],path.name
        shutil.copyfile(path,out/path.name)
    for name in ['firmware.bin','firmware.elf','firmware.nm']:shutil.copyfile(base/name,out/name)
    (out/'cases.txt').write_text('0 0\n')
    observer=ROOT/'scripts/profile_e203_observer.hpp'
    source=(ROOT/'rtl/reference/sim_e203.cpp').read_text()
    replacements={
        'static uint32_t word(uint32_t off)': '#include "profile_e203_observer.hpp"\nstatic uint32_t word(uint32_t off)',
        ' if(d.retired)retired++;': ' profile_tick(mtake,hrq,ma,mread,ha,hread);\n if(d.retired)retired++;',
        'static void finish_job(int rc){': 'static void finish_job(int rc){\n profile_finish();',
    }
    for old,new in replacements.items():assert source.count(old)==1;source=source.replace(old,new)
    src=out/'sim_profile.cpp';src.write_text(source)
    shutil.copyfile(observer,out/observer.name)
    tools=Tools();_,runtime=tools.verilator();cxx=tools.cxx()
    os.environ['ZIG_GLOBAL_CACHE_DIR']=str(ROOT/'tools/zig-cache')
    commands=[]
    def run(args,name):
        args=[str(x) for x in args];commands.append(args)
        with (out/(name+'.log')).open('w',encoding='utf-8') as log:
            result=subprocess.run(args,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        assert result.returncode==0,(name,result.returncode)
    objects=sorted((p for p in model.glob('part*.o') if p.name!='part0.o'),key=lambda p:int(p.stem[4:]))
    assert len(objects)==11
    bindings={str(p):sha(p) for p in [*objects,*model.glob('*.h'),observer,Path(__file__),ROOT/'rtl/reference/sim_e203.cpp']}
    (out/'build_bindings.json').write_text(json.dumps(bindings,indent=2))
    run([*cxx,'-std=c++17','-O3','-I'+str(runtime/'include'),'-I'+str(runtime/'include/vltstd'),'-I'+str(model),'-c',src,'-o',out/'observer.o'],'compile')
    run([*cxx,'-o',out/'profile.exe',out/'observer.o',*objects],'link')
    run([out/'profile.exe',out,'batch'],'execution')
    from summarize_reference_profile import summarize
    summarize(out,commands,bindings)


if __name__=='__main__':main()
