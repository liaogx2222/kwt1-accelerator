"""Export standalone SoC project; reuse hash-checked CPU/accel/fixtures over VNC."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from export_clean_project import archive
sys.path.insert(0,str(ROOT/'firmware/soc_joint'))
from assemble import assemble

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--allow-dirty',action='store_true')
    a=ap.parse_args();out=a.output.resolve()
    if out.exists():raise ValueError('choose a fresh export directory')
    tracked=['rtl/soc_joint','firmware/soc_joint','flow/soc_joint','scripts/export_soc_joint.py','scripts/run_soc_joint.py','rtl/v2','rtl/micro']
    dirty=bool(subprocess.check_output(['git','status','--porcelain','--',*tracked],cwd=ROOT))
    if dirty and not a.allow_dirty:raise ValueError('commit SoC and accelerator sources before release')
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    cpu=ROOT.parent/'e203_hbirdv2'
    cpu_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=cpu,text=True).strip()
    files={};filelist=[]
    def put(name,path):files[name]=path.read_bytes().replace(b'\r\n',b'\n')
    for p in sorted((cpu/'rtl/e203').rglob('*.v')):
        if p.name in ['sirv_mrom.v','sirv_mrom_top.v']:continue
        name='cpu/e203/'+p.relative_to(cpu/'rtl/e203').as_posix();put(name,p);filelist.append(name)
    inc=sorted({str(Path(name).parent).replace('\\','/') for name in filelist})
    for name in ['rtl/micro/mul_pipe.sv','rtl/micro/rne_pipe.sv']+['rtl/v2/'+n for n in ['kwt_sram_sp.sv','kwt_mac8x8.sv','kwt_iterative.sv','kwt_math.sv','kwt_packet_loader.sv','kwt_layer_banked.sv','kwt1_accel.sv','kwt1_mmio.sv']]:
        put(name,ROOT/name);filelist.append(name)
    put('rtl/v2/generated/kwt_profile.svh',ROOT/'rtl/v2/generated/kwt_profile.svh')
    for p in sorted((ROOT/'rtl/soc_joint').iterdir()):
        if p.is_file():put('soc/'+p.name,p)
    filelist += ['soc/'+n for n in ['sirv_mrom_top.v','kwt_soc_icb_bridge.sv','kwt_soc_shared_sram.sv','kwt_soc_joint.sv','tb_soc_joint.sv']]
    for p in sorted((ROOT/'flow/soc_joint').iterdir()):
        if p.is_file():put('flow/'+p.name,p)
    for p in sorted((ROOT/'firmware/soc_joint').iterdir()):
        if p.is_file():put('firmware/'+p.name,p)
    for p in sorted((ROOT/'deliverables/local_port_20261103/fixtures').glob('*.hex')):put('fixtures/'+p.name,p)
    files['flow/files.f']=('\n'.join(['+incdir+'+v for v in inc]+['+incdir+rtl/v2/generated']+filelist)+'\n').encode()
    out.mkdir(parents=True)
    info=assemble(ROOT/'firmware/soc_joint/task.S',out/'bootrom.hex')
    files['firmware/bootrom.hex']=(out/'bootrom.hex').read_bytes().replace(b'\r\n',b'\n')
    manifest=dict(schema=1,revision=revision,development_dirty=dirty,cpu_revision=cpu_revision,
        top='kwt_soc_joint',private_macros=20,shared_macros=64,shared_bytes=524288,
        cpu_tcm_rom_technology_binding=False,clock_gating='FPGA_SOURCE bypass: functional mode',
        ROM_bytes=info['bytes'],files={n:dict(bytes=len(d),sha256=hashlib.sha256(d).hexdigest()) for n,d in sorted(files.items())})
    files['manifest.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    for name,data in files.items():
        p=out/'project'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    full=archive(files);small=archive({n:d for n,d in files.items() if not n.startswith(('cpu/','rtl/','fixtures/'))})
    (out/'full.tar.gz').write_bytes(full);(out/'soc_source.tar.gz').write_bytes(small)
    encoded=base64.b64encode(zlib.compress(small,9)).decode();parts=[encoded[n:n+800] for n in range(0,len(encoded),800)]
    commands=[]
    for i,part in enumerate(parts):commands.append('python3 -c "open(\'soc_joint.part%04d\',\'w\').write(\'%s\')"'%(i,part))
    digest=hashlib.sha256(small).hexdigest()
    commands.append('python3 -c "import base64,zlib,hashlib;b=zlib.decompress(base64.b64decode(\'\'.join(open(\'soc_joint.part%%04d\'%%i).read() for i in range(%d))));assert len(b)==%d and hashlib.sha256(b).hexdigest()==\'%s\';open(\'soc_source.tar.gz\',\'wb\').write(b);print(\'SOC_TRANSFER_OK\')"'%(len(parts),len(small),digest))
    commands+=['wc -c soc_source.tar.gz','sha256sum soc_source.tar.gz']
    (out/'commands.csh.txt').write_text('\n'.join(commands)+'\n',encoding='ascii')
    report=dict(revision=revision,development_dirty=dirty,files=len(manifest['files']),cpu_files=len([n for n in files if n.startswith('cpu/')]),
        bytes=len(small),sha256=digest,parts=len(parts),full_bytes=len(full),full_sha256=hashlib.sha256(full).hexdigest(),ROM_bytes=info['bytes'])
    (out/'transfer_manifest.json').write_text(json.dumps(report,indent=2))
    subprocess.run([sys.executable,str(out/'project/flow/project.py'),'check'],check=True)
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
