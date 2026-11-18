"""Pinned CACTI SRAM estimates; never substitute them for characterized macros."""
import argparse
import csv
import io
import json
import subprocess
from pathlib import Path
from local_tools import ROOT,sha


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    bsg=ROOT/'third_party/bsg_fakeram_reference';cacti=ROOT/'third_party/cacti_reference'
    def commit(path):return subprocess.check_output(['git','rev-parse','HEAD'],cwd=path,text=True).strip()
    assert commit(bsg)=='a2c856eacdeda5a97e23891378ba34792a3acd3c';assert commit(cacti)=='1ffd8dfb10303d306ecd8d215320aea07651e878'
    namespace={};template=bsg/'scripts/utils/cacti_config.py';exec(compile(template.read_text(),str(template),'exec'),namespace);results={}
    for depth in [128,1024,4096]:
        folder=out/f'{depth}x16';folder.mkdir();config=namespace['cacti_config'].format(depth*2,2,1,0,0,.045,16,1,'ram')
        assert '-Add ECC - "true"' in config;config=config.replace('-Add ECC - "true"','-Add ECC - "false"')
        config_path=folder/'cacti.cfg';config_path.write_text(config);linux='/mnt/e/project/ChipCompetition/keyword-transformer/'+config_path.relative_to(ROOT).as_posix()
        p=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd /mnt/e/project/ChipCompetition/keyword-transformer/third_party/cacti_reference && ./cacti -infile {linux}'],capture_output=True,text=True)
        (folder/'execution.log').write_text(p.stdout+p.stderr);assert p.returncode==0,(depth,p.stdout[-1500:],p.stderr)
        raw=(folder/'cacti.cfg.out').read_text();rows=list(csv.reader(io.StringIO(raw)));header=[s.strip() for s in rows[0]];values=[s.strip() for s in rows[-1]]
        record=dict(zip(header,values));assert int(float(values[0]))==45 and int(values[1])==depth*2 and int(values[3])==16
        results[f'{depth}x16']=dict(depth=depth,width=16,banks=1,ports='1RW',ECC=False,cache_tags=False,raw_columns=record,
            area_mm2=float(values[10]),width_um=float(values[12]),height_um=float(values[13]),read_energy_nJ=float(values[7]),write_energy_nJ=float(values[8]),
            leakage_mW=float(values[9]),access_time_ns=float(values[4]),cycle_time_ns=float(values[5]))
        assert abs(results[f'{depth}x16']['width_um']*results[f'{depth}x16']['height_um']/1e6-results[f'{depth}x16']['area_mm2'])<1e-6
    total=16*results['1024x16']['area_mm2']+4*results['4096x16']['area_mm2'];leak=16*results['1024x16']['leakage_mW']+4*results['4096x16']['leakage_mW']
    patch=subprocess.check_output(['git','diff','--','io.cc'],cwd=cacti,text=True);(out/'actual_cacti_io.patch').write_text(patch)
    report=dict(passed=True,technology='CACTI analytical 45nm, 300K, ITRS-LOP bitcell/ITRS-HP periphery, conservative interconnect',
        nominal_voltage='CACTI 45nm technology tables; not a characterized Nangate SRAM PVT corner',
        CACTI_commit=commit(cacti),BSG_commit=commit(bsg),models=results,
        resident_core_private_SRAM=dict(geometry_counts={'1024x16':16,'4096x16':4},capacity_bytes=65536,analytical_area_mm2=total,analytical_standby_leakage_mW=leak),
        complete_accelerator_area_mm2=None,SoC_average_power_mW=None,task_energy_uJ=None,
        scope='analytical SRAM component estimates only, no SPICE/characterized macro/RTL binding/whole-SoC power signoff',
        generator_default_overrides=['pure RAM without cache tags','ECC disabled to match actual 16-bit banks'],
        BSG_Liberty_power_used=False,reason='use direct CACTI read/write event energy; generated pin power tables are not a same-window SoC activity measurement')
    (out/'verification.json').write_text(json.dumps(report,indent=2));sources=[Path(__file__),template,bsg/'LICENSE',bsg/'patches/cacti.patch',cacti/'io.cc',cacti/'tech_params/45nm.dat',cacti/'cacti']
    sources += list(cacti.glob('*.cc'))+list(cacti.glob('*.h'))
    (out/'source_bindings.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p) for p in set(sources)},indent=2));(out/'manifest.json').write_text(json.dumps({p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file()},indent=2));print(json.dumps(dict(passed=True,SRAM_area_mm2=total,SRAM_standby_leakage_mW=leak,model_kind='analytical component only'),indent=2))


if __name__=='__main__':main()
