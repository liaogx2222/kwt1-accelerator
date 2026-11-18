"""Copy compact raw PV16 evidence verbatim, without models/ASTs or caches."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--input',required=True,type=Path);ap.add_argument('--output',required=True,type=Path);a=ap.parse_args()
    src=a.input.resolve();out=a.output.resolve();assert not out.exists()
    summary=json.loads((src/'release_summary.json').read_text());assert summary['passed']
    selected={}
    def add(p,name=None):
        assert p.is_file(),str(p)
        assert p.stat().st_size<2000000,'unexpected large artifact'
        selected[name or p.relative_to(src).as_posix()]=p
    add(src/'release_summary.json');add(src/'tool_versions.json')
    projects=set()
    for group in summary['evidence']:
        folder=src/group;add(folder/'summary.json')
        for case in sorted(folder.glob('case_*')):
            for name in ['run.log','command.json','result.json']:add(case/name)
            for p in case.glob('matrix_task_*.hex'):add(p)
            command=json.loads((case/'command.json').read_text())
            project=Path(next(s.split('=',1)[1] for s in command if s.startswith('+FIXTURES='))).parent
            projects.add(project)
            model=Path(command[0]).parent
            add(model/'sources.json', 'model_receipts/'+model.relative_to(src).as_posix()+'/sources.json')
        for name in ['verilate.log','link.log']:
            if (folder/name).exists():add(folder/name)
    for p in projects:add(p/'source_manifest.json')
    for name in ['mac_four_state_v2','consumer_boundaries_v2','baseline_inventory','candidate_inventory']:
        for p in (src/name).iterdir():
            if p.name in ['summary.json','command.json','run.log','compile.log','tool.log','math.txt','iter.txt','tb_consumers.sv']:add(p)
    proof=src/'software_proof/proof.json'
    if not proof.exists():proof=ROOT/'testdata/sysbus_contract_20261113/pv16_feasibility/proof.json'
    add(proof,'software_proof/proof.json')
    for name in ['pv_stall/case_00/run.log','mac_four_state/tool_discovery_failure.log','consumer_boundaries/compile.log']:
        if (src/name).exists():add(src/name,'failed_attempts/'+name)
    # Keep the already-passing immediate-restoration diagnostic too. The
    # final observed-restoration run is the mandatory release stall gate.
    diagnostic=src/'stall_fixed/run'
    if (diagnostic/'summary.json').exists():
        for p in [diagnostic/'summary.json',diagnostic/'case_00/run.log']:add(p)
    package=ROOT/'deliverables/pv16_opt_20261114'
    for name in ['manifest.json','SHA256SUMS','rtl.diff']:add(package/name,'RTL_archive/'+name)
    out.mkdir(parents=True)
    (out/'.gitattributes').write_text('* -text\n')
    index={}
    for name,p in sorted(selected.items()):
        data=p.read_bytes();target=out/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        digest=hashlib.sha256(data).hexdigest();assert hashlib.sha256(target.read_bytes()).hexdigest()==digest
        index[name]=dict(source=str(p),bytes=len(data),sha256=digest)
    (out/'index.json').write_text(json.dumps(dict(passed=True,verbatim_raw_copies=True,files=index),indent=2)+'\n')
    print('FROZEN',len(index),'files',sum(v['bytes'] for v in index.values()),'bytes')
