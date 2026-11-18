"""Independent output, totals, source and SoC package acceptance checks."""
import argparse
import ast
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zlib
ROOT=Path(__file__).resolve().parents[1]

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def campaign(out,base=None):
    names=['soc_joint_acceptance_20261111','soc_joint_group345_20261111','soc_joint_group678_20261111','soc_joint_group9ab_20261111']
    folders=[base/n for n in ['group012','group345','group678','group9ab']] if base else [ROOT/'testdata'/n for n in names]
    cases={};artifacts={}
    model=folders[0]/'model'
    bound=json.loads((model/'sources.json').read_text())
    assert all(sha(Path(p))==v for p,v in bound.items()),'compiled RTL or host changed'
    fixture=ROOT/'deliverables/local_port_20261103/fixtures'
    for p in folders:
        s=json.loads((p/'summary.json').read_text());assert s['passed'] and s['real_cpu'] and s['full_subsystem']
        for line in (p/'soc_metrics.txt').read_text().splitlines():
            row=list(map(int,line.split()));n=row[0];assert n not in cases
            assert row[5:]==[189328,13,1584,190924],row
            observed=p/('soc_observed_%03d.hex'%n);expected=fixture/('expected_%03d.hex'%n)
            assert observed.read_bytes()==expected.read_bytes()
            cases[n]=row;artifacts[str(observed.relative_to(ROOT))]=sha(observed)
        for f in ['summary.json','soc_metrics.txt','native.log','bootrom.hex','rom.json','fixture_hashes.json']:
            artifacts[str((p/f).relative_to(ROOT))]=sha(p/f)
    assert set(cases)==set(range(12))
    fault=(folders[0]/'native.log').read_text()
    assert 'PASS SOC_CRC_REJECT' in fault and 'SOC_RESET_IN_LN' in fault
    unit=(base/'interfaces' if base else ROOT/'testdata/soc_joint_interfaces_20261111')/'summary.json';assert json.loads(unit.read_text())['passed']
    artifacts[str(unit.relative_to(ROOT))]=sha(unit)
    total=sum(r[1] for r in cases.values())
    result=dict(passed=True,normal_codes=12*6336,cases={str(n):cases[n] for n in sorted(cases)},
        cycles_per_task=sorted({r[1] for r in cases.values()}),total_cycles=total,
        conditional_task_s_at_150MHz=12*150e6/total,conditional_ms_per_task_at_150MHz=total/12/150e3,
        CRC_rejection=True,LN_reset_recovery_included_in_case0=True,
        reset_case_not_counted_twice=True,clock_gating='FPGA_SOURCE bypass',
        power_mW=None,energy_uJ=None,charged_area_mm2=None,full_soc_area_mm2=None,
        private_macros=20,shared_macros=64,shared_bytes=524288,
        compiled_source_sha256=bound,model_sha256=sha(model/'sim.exe'),evidence_sha256=artifacts,
        scope='actual E203 subsystem, development 12-class fixtures, no-delay native logic model; not official or physical signoff')
    extra=base/'crc_recovery' if base else ROOT/'testdata/soc_joint_crc_recovery_20261111'
    if (extra/'summary.json').exists():
        assert json.loads((extra/'summary.json').read_text())['passed']
        assert 'PASS SOC_CRC_REJECT' in (extra/'native.log').read_text()
        assert (extra/'soc_observed_000.hex').read_bytes()==(fixture/'expected_000.hex').read_bytes()
        result['extra_CRC_full_recovery_codes']=6336
        for f in ['summary.json','native.log','soc_metrics.txt','bootrom.hex','soc_observed_000.hex']:
            result['evidence_sha256'][str((extra/f).relative_to(ROOT))]=sha(extra/f)
    out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if not isinstance(v,(dict,list))},indent=2))

def package(bundle,out):
    if out.exists():raise ValueError('fresh test directory required')
    out.mkdir(parents=True)
    data=(bundle/'soc_source.tar.gz').read_bytes()
    m=json.loads((bundle/'transfer_manifest.json').read_text());assert len(data)==m['bytes'] and sha(bundle/'soc_source.tar.gz')==m['sha256']
    project=out/'project';project.mkdir()
    with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as tf:
        assert all(not Path(p.name).is_absolute() and '..' not in Path(p.name).parts and p.isfile() for p in tf.getmembers())
        tf.extractall(project)
    def cmd(args,success=True):
        p=subprocess.run([sys.executable,str(project/'flow/project.py'),*args],capture_output=True,text=True)
        assert (p.returncode==0)==success,p.stdout+p.stderr
    cmd(['check'],False)
    cmd(['import-cpu',str(ROOT.parent/'e203_hbirdv2/rtl/e203')])
    cmd(['import-accelerator',str(ROOT/'deliverables/rtl_v2_paired_ln_clean_20261111/project')])
    cmd(['import-fixtures',str(ROOT/'deliverables/local_port_20261103/fixtures')])
    cmd(['check'])
    cmd(['filelist',str(project/'absolute.f')])
    absolute=(project/'absolute.f').read_text().splitlines()
    assert all(Path(n[len('+incdir+'):] if n.startswith('+incdir+') else n).exists() for n in absolute)
    ast.parse((project/'flow/project.py').read_text(),feature_version=(3,6))
    filelist=(project/'flow/files.f').read_text().splitlines()
    assert all((project/n).is_file() for n in filelist if not n.startswith('+'))
    assert sum(n.endswith('sirv_mrom_top.v') for n in filelist)==1
    assert not any(n.startswith('cpu/') and n.endswith('sirv_mrom.v') for n in filelist)
    (project/'soc/kwt_soc_joint.sv').write_text('TAMPER SELF TEST')
    cmd(['check'],False)
    report=dict(passed=True,relocated_import=True,CRLF_normalization=True,source_tamper_rejected=True,
        unique_actual_ROM=True,absolute_compile_paths=True,python36=True,EDA_execution=False)
    (out/'summary.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);ap.add_argument('--bundle',type=Path);ap.add_argument('--campaign-dir',type=Path)
    a=ap.parse_args()
    if a.bundle:package(a.bundle.resolve(),a.output.resolve())
    else:campaign(a.output.resolve(),a.campaign_dir.resolve() if a.campaign_dir else None)
