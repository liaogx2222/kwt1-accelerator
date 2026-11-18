"""Snapshot the exact checked SYSBUS_V1 RTL project, read-only parent access."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PARENT=ROOT.parent/'keyword-transformer/deliverables/sysbus_v1_20261113_v2/project'
EXPECTED='218c0212b640a1e0cac7f562aa4de39b8a3752ed9cc1db858d0d4c3d6e9a87bc'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def snapshot(out):
    assert not out.exists(),'preserve existing source snapshot'
    original=(PARENT/'manifest.json').read_bytes();assert hashlib.sha256(original).hexdigest()==EXPECTED
    m=json.loads(original);selected={}
    for n,h in m['files'].items():
        data=(PARENT/n).read_bytes();assert hashlib.sha256(data).hexdigest()==h,'parent drift '+n
        if n.startswith(('cpu/','rtl/','soc/','fixtures/')) or n in ['flow/local_sources.txt','flow/includes.txt','flow/sram_contract_ret1n.v','flow/tb_soc_metrics.sv']:
            selected[n]=data
    assert (PARENT/'manifest.json').read_bytes()==original
    out.mkdir(parents=True)
    for n,data in selected.items():
        target=out/n;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    receipt=dict(parent_commit='2cf2dfa',arithmetic_revision='595724b88858b142a407f6a5c4761945252d523b',
        origin_project_manifest_sha256=EXPECTED,files={n:hashlib.sha256(b).hexdigest() for n,b in sorted(selected.items())},
        server_files_or_parent_modified=False,scope='local RTL/project snapshot only; no commercial flow/library/cache')
    (out/'source_manifest.json').write_text(json.dumps(receipt,indent=2));return receipt

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);a=ap.parse_args()
    r=snapshot(a.output.resolve());print('SNAPSHOT',len(r['files']),'files',r['origin_project_manifest_sha256'])
