"""Release the queued SoC map/gate/power job without transferring old CPU/weights."""
import argparse
import ast
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import zlib
from export_clean_project import archive
from prepare_input16_soc_metrics import ROOT,build,REV,dump,sha
from patch_soc_saif_string import updated_tb


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    out=a.output.resolve();assert not out.exists()
    tracked=['flow/soc_metrics','scripts/prepare_input16_soc_metrics.py','scripts/install_soc_metrics.py','scripts/export_soc_metrics_queue.py']
    assert not subprocess.check_output(['git','status','--porcelain','--',*tracked],cwd=ROOT),'commit producer before release'
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    checked=ROOT/'deliverables/input16_soc_metrics_dev_20261112_v3'
    proof=json.loads((ROOT/'testdata/input16_soc_metrics_rtl_20261112_v2/summary.json').read_bytes())
    tcm=json.loads((ROOT/'testdata/soc_tcm_contract_20261112_v3/summary.json').read_bytes())
    mocked=json.loads((ROOT/'testdata/soc_metrics_TT_flow_20261112_preflight_v2/summary.json').read_bytes())
    assert proof['passed'] and tcm['passed'] and mocked['passed']
    files=build();manifest=json.loads(files['manifest.json'])
    # The tested model's HDL must match every released local elaboration source.
    local=files['flow/local_sources.txt'].decode().splitlines()+['flow/tb_soc_metrics.sv','flow/sram_contract_ret1n.v','rtl/v2/generated/kwt_profile.svh']
    for n in local:
        old='soc/kwt_soc_joint.sv' if n=='soc/local_kwt_soc_joint.sv' else n
        tested=(checked/old).read_bytes()
        if n=='flow/tb_soc_metrics.sv':tested=updated_tb(tested)
        assert files[n]==tested,'UNTESTED_RTL_DRIFT '+n
    manifest.update(work_in_progress=False,producer_revision=revision,
        local_RTL_qualification=proof,TCM_contract_qualification=tcm,commercial_EDA_not_run=True,
        SAIF_filename_contract='string variable; native VCS server probe 20261112 accepted string/literal and rejected packed/concat; fopen and nonempty checks added')
    files['manifest.json']=dump(manifest)
    for n in ['flow/project.py','flow/run.py','flow/collect.py']:ast.parse(files[n].decode(),feature_version=(3,6))
    roots=[ROOT/'deliverables/reset_anchor_20261111/project',ROOT/'deliverables/soc_joint_resetguard_20261111/project']
    names=['kwt_ret1n_reset_2b2dc17_20261111','kwt_soc_joint_0e308fd_20261111']
    pool={};source_roots={}
    for n,root in zip(names,roots):
        raw=(root/'manifest.json').read_bytes();source_roots[n]=[sha(raw)]
        for path,row in json.loads(raw)['files'].items():
            data=(root/path).read_bytes();assert sha(data)==row['sha256'];pool[sha(data)]=data
    patch=json.loads((ROOT/'deliverables/soc_tb_declfix_20261111/tb_declfix/patch.json').read_bytes())
    source_roots[names[1]].append(patch['new_manifest_sha256'])
    # The changed TB is not otherwise needed, but validates the server source pool.
    pool[patch['new_tb_sha256']]=(ROOT/'deliverables/soc_tb_declfix_20261111/tb_declfix/tb_soc_joint.sv').read_bytes()
    patches={}
    for n,data in files.items():
        old=roots[0]/n
        if n.startswith('fixtures/') and old.is_file() and sha(data) not in pool:
            a_words=old.read_bytes().decode().splitlines();b_words=data.decode().splitlines()
            if len(a_words)==len(b_words):
                patches[sha(data)]=dict(base_sha256=sha(old.read_bytes()),newline='\r\n' if b'\r\n' in data else '\n',
                    trailing_newline=data.endswith(b'\n'),changes=[[i,b] for i,(a,b) in enumerate(zip(a_words,b_words)) if a!=b])
    assets={sha(d):d for d in files.values() if sha(d) not in pool and sha(d) not in patches}
    directory='kwt_soc_input16_metrics_595724b_tt_20261112'
    meta=dict(directory=directory,source_roots=source_roots,assets={h:len(d) for h,d in assets.items()},hex_patches=patches,
        files={n:dict(bytes=len(d),sha256=sha(d)) for n,d in files.items()})
    capsule={'soc_metrics/install.py':(ROOT/'scripts/install_soc_metrics.py').read_bytes().replace(b'\r\n',b'\n'),
        'soc_metrics/install.json':dump(meta)}
    capsule.update({'soc_metrics/assets/'+h:d for h,d in assets.items()})
    payload=archive(capsule);enc=base64.b64encode(zlib.compress(payload,9)).decode()
    loader='''import base64,zlib,hashlib,tarfile,io,subprocess,sys
from pathlib import Path,PurePosixPath
assert hashlib.sha256(Path("manifest.json").read_bytes()).hexdigest()=="%s","WRONG_BASE_PROJECT"
encoded="""
%s
"""
data=zlib.decompress(base64.b64decode(encoded))
assert len(data)==%d and hashlib.sha256(data).hexdigest()=="%s","TRANSFER_HASH_MISMATCH"
stage=Path("vnc_soc_metrics_%s");stage.mkdir()
with tarfile.open(fileobj=io.BytesIO(data),mode="r:gz") as stream:
    for m in stream.getmembers():
        p=PurePosixPath(m.name);assert m.isfile() and not p.is_absolute() and ".." not in p.parts
    stream.extractall(str(stage))
subprocess.check_call([sys.executable,str(stage/"soc_metrics/install.py")])
target=Path("..").resolve()/"%s"
subprocess.check_call([sys.executable,str(target/"flow/project.py"),"check"])
print("SOC_METRICS_QUEUE_READY "+str(target))
'''%(source_roots[names[0]][0],'\n'.join(enc[i:i+800] for i in range(0,len(enc),800)),len(payload),sha(payload),revision[:7],directory)
    ast.parse(loader,feature_version=(3,6));out.mkdir(parents=True)
    for group,items in [('project',files),('capsule',capsule)]:
        for n,data in items.items():
            p=out/group/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    (out/'fix.tar.gz').write_bytes(payload);(out/'PASTE_INSTALL.py').write_text(loader,encoding='ascii')
    chunks=[];part=''
    for line in loader.splitlines(True):
        if len(part)+len(line)>28000:chunks.append(part);part=''
        part+=line
    if part:chunks.append(part)
    for i,s in enumerate(chunks):(out/('PASTE_PART_%02d.txt'%(i+1))).write_text(s,encoding='ascii')
    report=dict(producer_revision=revision,RTL_revision=REV,directory=directory,bytes=len(payload),sha256=sha(payload),
        clipboard_parts=len(chunks),hex_packets_patched=len(patches),scope='queued full digital reference SoC map/cold+reset gates/TT power',
        actual_server_run=False,local_RTL_and_TCM_passed=True,actual_power_mW=None,actual_area_mm2=None,
        declared_operating_PVT=dict(corner='TT',voltage_V=1.1,temperature_C=25,frequency_Hz=150000000))
    (out/'transfer_manifest.json').write_bytes(dump(report));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
