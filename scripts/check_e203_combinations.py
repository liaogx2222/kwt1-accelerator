"""Independent combination/P2 gate: fresh integer oracle and protected history."""
import argparse,json,re,struct,sys
from pathlib import Path
from local_tools import ROOT,sha
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
GROUPS=['classes_0_3','classes_4_7','classes_8_11','faults']
def read(p):return json.loads(p.read_text())
def stored(p):return b''.join(int(x,16).to_bytes(4,'little') for x in p.read_text().split())
def verify(base,values):
    for name,digest in values.items():assert sha(base/name.replace('\\','/'))==digest,name

def check(out):
    if (out/'verification.json').exists():verify(out,read(out/'evidence_manifest.json')['sha256']);verify(ROOT,read(out/'source_manifest.json'));return read(out/'verification.json')
    import numpy as np
    from integer_model.runtime import Encoder
    from validate_kwt1_r2 import artifacts
    prior=ROOT/'testdata/reference_e203/parallel_20261103';verify(prior,read(prior/'evidence_manifest.json')['sha256']);verify(ROOT,read(prior/'source_manifest.json'))
    old=ROOT/'testdata/e203_factors_20261104';verify(old,read(old/'evidence_manifest.json')['sha256']);verify(ROOT,read(old/'source_manifest.json'))
    for key in ['integration_v1/release','rtl_v2/release','rtl_v1/release','next_stage_v1']:
        base=ROOT/'testdata'/key;verify(base,read(base/'evidence_manifest.json')['sha256']);verify(ROOT,read(base/'source_manifest.json'))
    packets,params=artifacts();features=np.load(ROOT/'testdata/integer_v1/fixture/encoder_input.npy',mmap_mode='r');labels=np.load(ROOT/'testdata/integer_v1/fixture/labels.npy');saved=np.load(ROOT/'testdata/integer_v1/validation/encoder_output_int8.npy',mmap_mode='r');meta=read(ROOT/'testdata/integer_v1/params/manifest.json');cache={}
    def oracle(label):
        if label not in cache:
            sample=int(np.flatnonzero(labels==label)[0]);x=np.clip(np.rint(features[sample].astype(np.float64)/meta['decode_scales']['encoder_input']),-127,127).astype(np.int8);y=Encoder(params)(x[None])[0];assert np.array_equal(y,saved[sample]);cache[label]=(x.tobytes(),y.tobytes())
        return cache[label]
    codes=0;all_labels=[];normal=[];bin_hashes=set();rows=[];summaries={}
    ac=read(out/'compare_ac/summary.json');abc=read(out/'compare_abc/summary.json');assert ac['passed'] and abc['passed']
    selected='abc' if abc['jobs'][0]['main']['cycles']<ac['jobs'][0]['main']['cycles'] else 'ac'
    for name in ['compare_ac','compare_abc',*GROUPS]:
        folder=out/name;verify(folder,read(folder/'manifest.json'));s=read(folder/'summary.json');ex=read(folder/'execution.json');assert s['passed'] and ex['passed'];summaries[name]=s
        kind=s['kind'];assert kind==('ac' if name=='compare_ac' else 'abc' if name=='compare_abc' else selected)
        assert (folder/'main.c').read_text()==(old/'p1a_null_cancel/main.c').read_text()
        assert (folder/'driver.c').read_text()==(ROOT/'rtl/integration/driver/kwt1.c').read_text() if kind=='ac' else (folder/'driver.c').read_text()==(old/'p1b_aligned/driver.c').read_text()
        for packet,data in packets.items():assert stored(folder/(packet+'.hex'))==data
        rawrows=[list(map(int,line.split())) for line in (folder/'cpu_metrics.txt').read_text().splitlines()]
        assert len(rawrows)==len(s['jobs'])==(1 if name.startswith('compare_') else 4)
        if name=='faults':assert [(r[2],r[3]) for r in rawrows]==[(1,-3),(0,0),(2,-7),(0,0)]
        for r,j in zip(rawrows,s['jobs']):
            assert j['legacy_18_fields']==r and j['main']['cycles']==r[4]==sum(j['phase_cycles'].values()) and j['main']['retired']==r[5]
            b=j['boundaries'];assert b[1]-b[0]==r[4] and b[2]-b[1]==j['report_tail']['cycles']
            assert sum(v['reads'] for w in ['ram_main','ram_tail'] for v in j[w].values())==r[16]
            assert sum(v['writes'] for w in ['ram_main','ram_tail'] for v in j[w].values())==r[17]
            assert j['accepted_parameter_words']==r[8] and j['ram_main']['code_address_range']['reads']==0 and 0<r[13]<=16384
            if r[3]==0:
                x,y=oracle(r[1]);assert stored(folder/f'input_{r[1]:03d}.hex')==x and stored(folder/f'cpu_observed_job_{r[0]:02d}.hex')==y;codes+=6336
                assert r[8:13]==[189328,13,13,0,61728] and r[15]==5058532 and j['errors']==[0,0,0]
                assert j['ram_main']['packet_staging']['reads']==(189328 if kind=='abc' else 757312)
                if name in GROUPS:normal.append(j)
                if name in GROUPS and name!='faults':all_labels.append(r[1])
            elif r[3]==-3:assert j['errors']==[-3,0,0] and r[8:12]==[19576,2,2,1]
            else:assert r[3]==-7 and j['errors']==[-2,-2,1] and r[8:12]==[64,1,1,1]
            rows.append(dict(group=name,**j))
        mem=read(folder/'memory_map.json');assert mem['__image_end']==0xa0002010 and mem['__input']==0xa0020000 and mem['__output']==0xa0022000 and mem['__packet']==0xa0024000 and mem['__stack_bottom']==0xa007c000 and mem['__stack_top']==0xa0080000
        assert mem['__itcm_start']==0x80000000 and 0<mem['__itcm_end']-mem['__itcm_start']<=65536
        elf=(folder/'firmware.elf').read_bytes();image=(folder/'firmware.bin').read_bytes();assert elf[:6]==b'\x7fELF\x01\x01' and struct.unpack_from('<H',elf,18)[0]==243 and struct.unpack_from('<I',elf,24)[0]==0xa0000000
        off=struct.unpack_from('<I',elf,28)[0];size,count=struct.unpack_from('<HH',elf,42)
        for i in range(count):
            kindn,offset,vaddr,paddr,filesz,memsz,flags,align=struct.unpack_from('<8I',elf,off+i*size)
            if kindn!=1:continue
            assert 0xa0000000<=paddr<=paddr+filesz<=0xa0020000 and elf[offset:offset+filesz]==image[paddr-0xa0000000:paddr-0xa0000000+filesz]
            if vaddr!=paddr:assert vaddr==0x80000000 and paddr==0xa0001000
        assert ex['firmware_sha256']==sha(folder/'firmware.bin')
        if name in GROUPS:bin_hashes.add(sha(folder/'firmware.bin'))
        log=(folder/'execution.log').read_text();assert 'FAIL' not in log and f'PASS E203 jobs={len(rawrows)}' in log
    assert sorted(all_labels)==list(range(12)) and codes==101376 and len(normal)==14 and len(bin_hashes)==1
    for path,digest in read(out/'compare_abc/build_bindings.json').items():assert sha(Path(path))==digest,path
    clocks=[j['main']['cycles'] for j in normal];acj=ac['jobs'][0];abcj=abc['jobs'][0];baseline=read(old/'p0_baseline/summary.json')['main']['cycles']
    report=dict(passed=True,selected=selected,scope='reference E203 RTL + unchanged accelerator RTL, optimized platform firmware; no mapped-netlist timing claim',full_classes=12,class_output_codes=76032,recovery_output_codes=12672,comparison_output_codes=12672,independently_recomputed_output_codes=codes,mismatches=0,normal_regression_tasks=14,faults=['CRC then full cold recovery','persistent callback timeout + ABORT timeout + API quarantine + accelerator hard reset confirmation then full cold recovery'],normal_outer_cycle_range=[min(clocks),max(clocks)],normal_retired_range=[min(j['main']['retired'] for j in normal),max(j['main']['retired'] for j in normal)],internal_9M_target_met=max(clocks)<=9000000,assumed_150MHz_ms_range=[min(clocks)/150000,max(clocks)/150000],gap_to_9M_cycles=max(clocks)-9000000,baseline_cycles=baseline,AC_cycles=acj['main']['cycles'],ABC_cycles=abcj['main']['cycles'],ABC_incremental_gain_over_AC_percent=100*(1-abcj['main']['cycles']/acj['main']['cycles']),ABC_total_gain_over_baseline_percent=100*(1-abcj['main']['cycles']/baseline),first_job_preparation_cycles=abcj['pre_job'][0],startup_plus_main_cycles=abcj['pre_job'][0]+abcj['main']['cycles'],ITCM_bytes=abc['ITCM_bytes'],shared_image_bytes=8208,shared_occupied_including_reserved_stack_bytes=98992,stack_highwater_bytes=max(j['stack_highwater'] for j in normal),parameter_words_per_task=189328,packet_bytes_peak=61728,compute_cycles=5058532,architecture=dict(integer_profile='v1',PE_rows=8,PE_columns=8,SRAM_macros=20),physical_signoff=False)
    sources=[Path(__file__),ROOT/'scripts/run_e203_combinations.py',ROOT/'scripts/summarize_e203_combinations.py',ROOT/'rtl/e203_combinations_20261104/window_observer.hpp',ROOT/'firmware/e203_experiments_20261104/start_itcm.S',ROOT/'firmware/e203_experiments_20261104/link_itcm.ld',ROOT/'firmware/e203_experiments_20261104/word_access.h']
    binding={p.relative_to(ROOT).as_posix():sha(p) for p in sources};(out/'source_manifest.json').write_text(json.dumps(binding,indent=2))
    for p in sources:
        dest=out/'source'/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(p.read_bytes())
    (out/'metrics.json').write_text(json.dumps(rows,indent=2));(out/'verification.json').write_text(json.dumps(report,indent=2));(out/'evidence_manifest.json').write_text(json.dumps(dict(sha256={p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file() and p.name!='evidence_manifest.json'}),indent=2));print(json.dumps(report,indent=2));return report

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();check(a.output.resolve())
