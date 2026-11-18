"""Release the exact virtual-constant accounting retry and progress-only bench delta."""
import argparse
import ast
import base64
import hashlib
import json
from pathlib import Path
import zlib
from export_soc_link_recovery import build,ROOT
from patch_soc_saif_string import updated_tb
from retry_soc_virtual_constants import progress_tb


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    old_tb=updated_tb((ROOT/'deliverables/input16_soc_metrics_TT_release_20261112_v3/project/flow/tb_soc_metrics.sv').read_bytes())
    new_tb=progress_tb(old_tb)
    assets=build();assets.pop('clock_preflight.tcl')
    assets['map.tcl']=assets['map.tcl'].replace(b'/soc_recovery_v1/constraints_clean.sdc',b'/soc_recovery_v2/constraints_clean.sdc')
    assets['retry.py']=(ROOT/'scripts/retry_soc_virtual_constants.py').read_text().encode()
    spec=dict(assets={n:hashlib.sha256(data).hexdigest() for n,data in assets.items()},expected_TB_sha256=hashlib.sha256(old_tb).hexdigest(),new_TB_sha256=hashlib.sha256(new_tb).hexdigest())
    for n,data in assets.items():
        if n.endswith('.py'):ast.parse(data,feature_version=(3,6))
        (out/n).write_bytes(data)
    assets['spec.json']=(json.dumps(spec,indent=2)+'\n').encode();(out/'spec.json').write_bytes(assets['spec.json'])
    (out/'tb_with_progress.sv').write_bytes(new_tb)
    raw=json.dumps({n:data.decode() for n,data in assets.items()},sort_keys=True).encode();encoded=base64.b64encode(zlib.compress(raw,9)).decode()
    loader='''import base64,zlib,hashlib,json,subprocess,sys
from pathlib import Path
b=zlib.decompress(base64.b64decode("""
%s
"""))
assert hashlib.sha256(b).hexdigest()=="%s","RETRY_TRANSFER_CHANGED"
root=Path("/home/2026contest/server6/s6_43usr/Desktop/project/kwt_soc_input16_metrics_595724b_tt_20261112")
work=root/"review_tools/soc_virtual_constant_loader_v2"
assert not work.exists(),"PRESERVE_RETRY_LOADER"
work.mkdir(parents=True)
for name,source in json.loads(b.decode()).items():
    assert name in ["recover.py","map.tcl","constraints_clean.sdc","retry.py","spec.json"]
    with (work/name).open("xb") as stream:stream.write(source.encode())
subprocess.check_call([sys.executable,str(work/"retry.py")])
'''%('\n'.join(encoded[i:i+800] for i in range(0,len(encoded),800)),hashlib.sha256(raw).hexdigest())
    ast.parse(loader,feature_version=(3,6));assert max(map(len,loader.splitlines()))<=800
    (out/'PASTE_INSTALL.py').write_text(loader,encoding='ascii')
    (out/'release.json').write_text(json.dumps(dict(payload_sha256=hashlib.sha256(raw).hexdigest(),max_line_bytes=800,
        actual_server_retry_started=False,CPU_or_accelerator_recompiled=False,heartbeat_interval_cycles=10000,
        watchdog_or_DUT_timing_changed=False),indent=2)+'\n')
    print('VIRTUAL_CONSTANT_RETRY_READY',len(loader))


if __name__=='__main__':main()
