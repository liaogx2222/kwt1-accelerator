"""Small VNC delta: new isolated input16 partition, original jobs stay untouched."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zlib
from export_clean_project import archive

ROOT=Path(__file__).resolve().parents[1]
REV='595724b88858b142a407f6a5c4761945252d523b'


def sha(data):return hashlib.sha256(data).hexdigest()
def dump(data):return (json.dumps(data,indent=2,sort_keys=True)+'\n').encode()


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();out=a.output.resolve();assert not out.exists()
    producer=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    assert not subprocess.check_output(['git','status','--porcelain','--',
        'scripts/export_input16_fast_server.py','scripts/install_parallel_batch.py'],cwd=ROOT), 'commit producer before release'
    base=ROOT/'deliverables/reset_anchor_20261111/project'
    template=ROOT/'deliverables/parallel_max_20261112_v2/batch/writeback'
    source=ROOT.parent/'arch60-input16'
    original=json.loads((base/'manifest.json').read_bytes())
    pool={row['sha256']:(base/n).read_bytes() for n,row in original['files'].items()}
    assert all(sha(data)==h for h,data in pool.items())
    old=json.loads((template/'manifest.json').read_bytes())
    files={n:(template/n).read_bytes() for n in old['files'] if not n.startswith('fixtures/')}
    assert all(sha(data)==old['files'][n]['sha256'] for n,data in files.items())
    for n in list(files):
        if n.startswith(('rtl/v2/','rtl/micro/','rtl/integration/')):
            files[n]=subprocess.check_output(['git','show',REV+':'+n],cwd=source)
    evidence=json.loads((source/'testdata/input16_fast/fixtures_final/binding.json').read_bytes())
    validation=json.loads(subprocess.check_output(['git','show',
        'b9b7650662eb782cfa22f99cbfdee75eb3191943:manifest/input16_fast_20261112.json'],cwd=source))
    assert validation['passed'] and validation['RTL_revision']==REV and validation['full_network_codes']==76032
    assert validation['accuracy_binding_sha256']==sha((source/'testdata/input16_fast/fixtures_final/binding.json').read_bytes())
    assert evidence['accuracy_drop_pp']<=.1 and evidence['profile_sha256']=='9b90642ca9237d108fba7269306afa7fec6283e88733831b9e06106f23d86c2d'
    files['input16_accuracy_binding.json']=dump(evidence)
    files['input16_validation.json']=dump(validation)
    # These extra source files bind the CPU firmware/NICE ABI even though this
    # partition mapping does not map CPU, interconnect, shared SRAM, ROM or TCM.
    for n in ['rtl/arch60_block/kwt_nice_block.sv','rtl/arch60_block/kwt_cpu_nice_arbiter.sv']+[
        'rtl/arch60_block/generated/'+p for p in ['task.S','sirv_mrom_top.v','fixed_bootrom.hex','kwt_soc_joint.sv']]:
        files[n]=subprocess.check_output(['git','show',REV+':'+n],cwd=source)
    manifest=dict(old,git_revision=REV,RTL_revision=REV,numerical_contract='S16_FIRST_INPUT_S8_INTERNAL_W8_INPUT16_ONLY',
        parent_RTL_revision=old['RTL_revision'],input_bytes=12672,output_bytes=6336,
        ID='0x4b575433',shared_input_address='0xa0040000',fixtures_status='not deployed: source-specific full-SoC validation is archived in input16 worktree',
        functional_reference_full_SoC_cycles=2407590,reference_scope='all twelve full SoC classes plus zero-init recovery; two-state native RTL',
        flow_producer_revision=producer,flow_template_revision='7b22f70bb6d6b0effbbc0df8cf8e280c25091ae0',
        declared_state_bits=33004,declared_state_bytes_ceiling=4126,legacy_4KiB_declared_state_pass=False,
        files={n:dict(bytes=len(d),sha256=sha(d)) for n,d in sorted(files.items())})
    label='input16_fast';project_manifest=dump(manifest)
    batch={label+'/'+n:d for n,d in files.items()}
    batch[label+'/manifest.json']=project_manifest
    batch['batch_run.py']=(ROOT/'deliverables/parallel_max_20261112_v2/batch/batch_run.py').read_bytes()
    spec=dict(schema=1,producer_revision=producer,development_dirty=False,
        scope='input16 accelerator partition only; not full SoC PPA',
        batch_tools={'batch_run.py':sha(batch['batch_run.py'])},
        projects={label:dict(manifest_sha256=sha(project_manifest),RTL_revision=REV,BLOCK_STREAM=1,
            hold_optimization=False,scope=manifest['scope'],reference_cycles=2407590)},
        requested_jobs=1,cores_per_job=4,hold_optimization=False,no_shared_work_or_alib_cache=True,
        default_clock_period_ns=6.666667,complete_SoC_PPA=False,power_mW=None,energy_uJ=None)
    batch['batch_manifest.json']=dump(spec)
    batch['INSTALL_RECEIPT.json']=dump(dict(batch_manifest_sha256=sha(batch['batch_manifest.json']),producer_revision=producer,RTL_revision=REV))
    assets={sha(d):d for d in batch.values() if sha(d) not in pool}
    directory='kwt_parallel_max_20261112_input16_'+REV[:7]
    meta=dict(directory=directory,base_manifest_sha256=sha((base/'manifest.json').read_bytes()),
        assets={h:len(d) for h,d in assets.items()},files={n:dict(bytes=len(d),sha256=sha(d)) for n,d in batch.items()})
    capsule={'parallel_fix/install.py':(ROOT/'scripts/install_parallel_batch.py').read_bytes().replace(b'\r\n',b'\n'),
        'parallel_fix/install.json':dump(meta)}
    capsule.update({'parallel_fix/assets/'+h:d for h,d in assets.items()})
    payload=archive(capsule);enc=base64.b64encode(zlib.compress(payload,9)).decode()
    script='''import base64,zlib,hashlib,io,tarfile,subprocess,sys
from pathlib import Path,PurePosixPath
assert hashlib.sha256(Path("manifest.json").read_bytes()).hexdigest()=="%s","WRONG_BASE_PROJECT"
encoded="""
%s
"""
data=zlib.decompress(base64.b64decode(encoded))
assert len(data)==%d and hashlib.sha256(data).hexdigest()=="%s","TRANSFER_HASH_MISMATCH"
stage=Path("vnc_input16_%s");stage.mkdir()
with tarfile.open(fileobj=io.BytesIO(data),mode="r:gz") as stream:
    for member in stream.getmembers():
        path=PurePosixPath(member.name)
        assert member.isfile() and not path.is_absolute() and ".." not in path.parts
    stream.extractall(str(stage))
subprocess.check_call([sys.executable,str(stage/"parallel_fix/install.py")])
target=Path("..").resolve()/"%s"
subprocess.check_call([sys.executable,str(target/"batch_run.py"),"check"])
print("INPUT16_SERVER_READY "+str(target))
'''%(meta['base_manifest_sha256'],'\n'.join(enc[i:i+800] for i in range(0,len(enc),800)),len(payload),sha(payload),REV[:7],directory)
    out.mkdir(parents=True)
    for name,data in batch.items():
        p=out/'batch'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    for name,data in capsule.items():
        p=out/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    (out/'fix.tar.gz').write_bytes(payload);(out/'PASTE_INSTALL.py').write_text(script,encoding='ascii')
    chunks=[];chunk=''
    for line in script.splitlines(True):
        if len(chunk)+len(line)>28000:chunks.append(chunk);chunk=''
        chunk+=line
    if chunk:chunks.append(chunk)
    for i,chunk in enumerate(chunks):(out/('PASTE_PART_%02d.txt'%(i+1))).write_text(chunk,encoding='ascii')
    report=dict(RTL_revision=REV,producer_revision=producer,directory=directory,projects=1,bytes=len(payload),sha256=sha(payload),
        clipboard_parts=len(chunks),no_existing_job_or_worktree_mutated=True,actual_server_run=False,
        accuracy_drop_pp=evidence['accuracy_drop_pp'],accuracy_scope=evidence['accuracy_scope'],
        reference_cycles=2407590,whole_SoC_area_mm2=None,power_mW=None,energy_uJ=None)
    (out/'transfer_manifest.json').write_bytes(dump(report));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
