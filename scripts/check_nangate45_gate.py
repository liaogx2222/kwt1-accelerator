"""Independent full mapped-netlist cold/reset-recovery output audit."""
import argparse,json,re,sys
from pathlib import Path
from local_tools import ROOT,sha
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
def read(p):return json.loads(p.read_text())
def stored(p):return b''.join(int(x,16).to_bytes(4,'little') for x in p.read_text().split())
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--gate',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();gate=a.gate.resolve();out=a.output.resolve();assert not out.exists(),'New audit output';assert (gate/'verification.json').exists(),'Mapped gate is still running/not passed';out.mkdir(parents=True)
    for name,digest in read(gate/'evidence_manifest.json')['sha256'].items():assert sha(gate/name)==digest,name
    for name,digest in read(gate/'source_bindings.json').items():assert sha(ROOT/name)==digest,name
    result=read(gate/'verification.json');assert result['passed'] and result['output_codes']==12672 and not result['formal_equivalence']
    import numpy as np
    from integer_model.runtime import Encoder
    from validate_kwt1_r2 import artifacts
    packets,params=artifacts();features=np.load(ROOT/'testdata/integer_v1/fixture/encoder_input.npy',mmap_mode='r');labels=np.load(ROOT/'testdata/integer_v1/fixture/labels.npy');meta=read(ROOT/'testdata/integer_v1/params/manifest.json');codes=0
    for c in result['cases']:
        sample=c['sample'];assert labels[sample]==c['label'];x=np.clip(np.rint(features[sample].astype(np.float64)/meta['decode_scales']['encoder_input']),-127,127).astype(np.int8);y=Encoder(params)(x[None])[0].tobytes();idx=c['case']
        assert stored(gate/'run'/f'input_{idx:03d}.hex')==x.tobytes();assert stored(gate/'run'/f'provider_observed_{idx:03d}.hex')==stored(gate/'run'/f'expected_{idx:03d}.hex')==y;codes+=6336
    for name,data in packets.items():assert stored(gate/'run'/(name+'.hex'))==data
    rows=[list(map(int,line.split())) for line in (gate/'run/provider_metrics.txt').read_text().splitlines()];assert len(rows)==2 and all(row[2]==5058532 and row[8:10]==[13,61728] for row in rows)
    log=(gate/'run/live.log').read_text();assert 'GATE RESET PASS LN arithmetic in-flight' in log and 'PASS PROVIDER cases=2 codes=12672' in log
    match=re.search(r'PASS GATE BUS accepted=(\d+) retired=(\d+) reset_discarded=(\d+)',log);assert match;accepted,retired,discarded=map(int,match.groups());assert accepted==retired+discarded
    mapped=ROOT/'testdata/nangate45_reference/native_compat_20261104/mapped.v';assert len(re.findall(r'^\s+kwt_tech_sram_4096x16\s+',mapped.read_text(),re.M))==20
    report=dict(passed=True,output_codes_independently_recomputed=codes,mismatches=0,complete_cold_tasks=2,inflight_reset='LN N_PASS and full cold recovery',SRAM_macros=20,bus_accepted=accepted,bus_retired=retired,bus_reset_discarded=discarded,formal_equivalence=False,SDF=False,CPU_instruction_execution=False,scope='actual original Nangate45 mapped top functional regression, same-library functional cell models, 20 external SRAM contracts; not buffered diagnostic variant or timing signoff',physical_signoff=False,gate_verification_sha256=sha(gate/'verification.json'),script_sha256=sha(Path(__file__)))
    (out/'verification.json').write_text(json.dumps(report,indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':main()
