"""Export versioned CPU, actual firmware, frozen RTL, host fixtures and evidence."""
import argparse
import json
import shutil
from pathlib import Path
from local_tools import ROOT,sha

def read(p):return json.loads(p.read_text())

def export(evidence,destination,cpu):
    result=read(evidence/'verification.json');assert result['passed'] and result['full_classes']==12
    for name,digest in read(evidence/'evidence_manifest.json')['sha256'].items():assert sha(evidence/name)==digest,name
    for name,digest in read(evidence/'source_manifest.json').items():assert sha(ROOT/name)==digest,name
    if destination.exists():raise ValueError('Export exists; choose a new destination')
    hardware={k.replace('\\','/'):v for k,v in read(ROOT/'testdata/rtl_v2/release/source_manifest.json').items()}
    files=set(hardware)|set(read(evidence/'source_manifest.json'))
    files.update(['scripts/local_tools.py','scripts/run_local_flow.py','scripts/run_yosys_v2.py','scripts/reference_package.py','scripts/export_reference_system.py','scripts/check_technology.py','scripts/test_technology_preflight.py','flow/tools.example.json','flow/REFERENCE_E203.md','flow/requirements-reference.lock','flow/targets/smic40.binding.pending.json','flow/smic40_synthesis.tcl','flow/smic40_sta.tcl'])
    files.update(p.relative_to(ROOT).as_posix() for p in (ROOT/'rtl/integration').glob('tb*.sv'))
    files.update(['rtl/integration/tech_sram_model.sv','rtl/integration/test_initial_bus_failure.cpp','rtl/integration/INTERFACE_CONTRACT.md'])
    for name in files:assert (ROOT/name).is_file(),name
    prov=read(evidence/'classes_0_3/provenance.json')
    for name,digest in prov['cpu'].items():assert sha(cpu/name)==digest,name
    destination.mkdir(parents=True)
    def copy(source,relative):
        dest=destination/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
    for name in sorted(files):copy(ROOT/name,name)
    for name in prov['cpu']:copy(cpu/name,'cpu/e203_hbirdv2/'+name)
    # Only the linked CPU image/data enter target RAM. These goldens stay host-only.
    fixture=ROOT/'testdata/integration_v1/release/candidate_system'
    for p in fixture.iterdir():
        if (p.suffix=='.hex' and p.name.startswith(('input_','expected_','common.bin','layer_'))) or p.name in ['cases.json','cases.txt']:copy(p,'fixtures/'+p.name)
    for name in ['math.txt','iter.txt']:copy(ROOT/'testdata/rtl_v1/release/unit'/name,'fixtures/unit/'+name)
    for name in ['verification.json','metrics.json','source_manifest.json','toolchain.json','evidence_manifest.json']:copy(evidence/name,'evidence/'+name)
    for group in ['classes_0_3','classes_4_7','classes_8_11','faults']:
        for p in (evidence/group).iterdir():
            if p.is_file() and (p.name.startswith(('firmware.','cpu_observed_')) or p.name in ['cpu_metrics.txt','memory_map.json','provenance.json','execution.json','live.log']):copy(p,'evidence/'+group+'/'+p.name)
    bind=destination/'bindings';bind.mkdir();(bind/'hardware_sources.json').write_text(json.dumps(hardware,indent=2))
    # The original checker needs the full project's frozen integer data; standalone
    # replay explicitly uses bound fixture comparison and includes its provenance.
    (destination/'README.md').write_text((ROOT/'flow/REFERENCE_E203.md').read_text(),encoding='utf-8')
    values={p.relative_to(destination).as_posix():sha(p) for p in sorted(destination.rglob('*')) if p.is_file()}
    (destination/'manifest.json').write_text(json.dumps(dict(sha256=values,cpu_revision=prov['cpu_revision'],scope='reference RTL system; full-project integer gate evidence plus standalone frozen-golden replay',physical_signoff=False),indent=2))
    print(json.dumps(dict(output=str(destination),files=len(values),bytes=sum(p.stat().st_size for p in destination.rglob('*') if p.is_file()),physical_signoff=False),indent=2))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--evidence',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--cpu',type=Path,default=ROOT.parent/'e203_hbirdv2');a=ap.parse_args();export(a.evidence.resolve(),a.output.resolve(),a.cpu.resolve())
