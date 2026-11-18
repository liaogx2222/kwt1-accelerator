"""Independent first-review evidence gate, no combination selection implied."""
import argparse,difflib,hashlib,json,re,struct
from pathlib import Path
from local_tools import ROOT,Tools,sha

NAMES=['p0_baseline','p1a_null_cancel','p1b_aligned','p1c_itcm']
REGIONS=['code_address_range','small_data','input','output','packet_staging','stack','other']
def read(p):return json.loads(p.read_text())
def stored(p):return b''.join(int(x,16).to_bytes(4,'little') for x in p.read_text().split())
def verify(base,mapping):
    for name,digest in mapping.items():assert sha(base/name.replace('\\','/'))==digest,name

def check(out):
    if (out/'verification.json').exists():
        verify(out,read(out/'evidence_manifest.json')['sha256']);verify(ROOT,read(out/'source_manifest.json'))
        report=read(out/'verification.json');assert report['passed'];print(json.dumps(report,indent=2));return report
    release=ROOT/'testdata/reference_e203/parallel_20261103';original=release/'classes_0_3'
    verify(ROOT,read(release/'source_manifest.json'));verify(release,read(release/'evidence_manifest.json')['sha256'])
    for name,digest in read(release/'build/model/stamp.json')['inputs'].items():assert sha(Path(name))==digest,name
    for name,digest in read(release/'toolchain.json')['tools'].items():assert sha(Path(name))==digest,name
    prior=read(ROOT/'testdata/reference_e203/profile_native_20261104/summary.json')
    # Independently rederive the one selected Validation input/output.
    import sys
    sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
    import numpy as np
    from validate_kwt1_r2 import artifacts
    from integer_model.runtime import Encoder
    _,params=artifacts();case=read(original/'cases.json')[0];sample=case['sample']
    meta=read(ROOT/'testdata/integer_v1/params/manifest.json')
    features=np.load(ROOT/'testdata/integer_v1/fixture/encoder_input.npy',mmap_mode='r')
    x=np.clip(np.rint(features[sample].astype(np.float64)/meta['decode_scales']['encoder_input']),-127,127).astype(np.int8)
    expected=Encoder(params)(x[None])[0].tobytes();assert stored(original/'expected_000.hex')==expected
    results={};codes=0;bindings={}
    for name in NAMES+['p1b_reject_misaligned']:
        folder=out/name;s=read(folder/'summary.json');assert s['passed'];verify(folder,read(folder/'manifest.json'))
        for path,digest in read(folder/'build_bindings.json').items():assert sha(Path(path))==digest,path
        raw=list(map(int,(folder/'cpu_metrics.txt').read_text().split()));assert raw==s['legacy_18_fields']
        assert s['main']['cycles']==raw[4]==sum(s['phase_cycles'].values()) and s['main']['retired']==raw[5]
        b=s['boundary_clocks'];assert b[1]-b[0]==raw[4] and b[2]-b[1]==s['report_tail']['cycles']
        for column,region_key in [(16,'reads'),(17,'writes')]:
            assert sum(s[w][r][region_key] for w in ['ram_main','ram_tail'] for r in REGIONS)==raw[column]
        tail=read(folder/'tail_reads.json');assert len(tail)==sum(s['ram_tail'][r]['reads'] for r in REGIONS)
        assert all(b[1]<=r['cycle']<b[2] for r in tail)
        match=re.search(r'PASS E203 jobs=1 cycles=(\d+) retired=(\d+)',(folder/'execution.log').read_text());assert match
        process=int(match[1]);reset=8;startup=b[0]-reset;after_report=process-b[2]
        assert reset+startup+s['main']['cycles']+s['report_tail']['cycles']+after_report==process
        assert startup==s['startup']['cycles'] and after_report>=32
        # Verify every PT_LOAD against the actually installed shared-RAM image.
        elf=(folder/'firmware.elf').read_bytes();image=(folder/'firmware.bin').read_bytes()
        assert elf[:6]==b'\x7fELF\x01\x01' and struct.unpack_from('<H',elf,18)[0]==243 and struct.unpack_from('<I',elf,24)[0]==0xa0000000
        phoff=struct.unpack_from('<I',elf,28)[0];psize,pnum=struct.unpack_from('<HH',elf,42);loads=[]
        for i in range(pnum):
            kind,offset,vaddr,paddr,filesz,memsz,flags,align=struct.unpack_from('<8I',elf,phoff+i*psize)
            if kind!=1:continue
            assert 0xa0000000<=paddr<=paddr+filesz<=0xa0020000
            assert elf[offset:offset+filesz]==image[paddr-0xa0000000:paddr-0xa0000000+filesz]
            if vaddr!=paddr:assert s['factor']=='itcm' and vaddr==0x80000000 and paddr==0xa0001000 and memsz<=65536
            loads.append(dict(VMA=hex(vaddr),LMA=hex(paddr),filesz=filesz,memsz=memsz,flags=flags))
        mem=read(folder/'memory_map.json');assert mem['__image_end']==0xa0002010 and mem['__input']==0xa0020000 and mem['__output']==0xa0022000 and mem['__packet']==0xa0024000 and mem['__stack_bottom']==0xa007c000 and mem['__stack_top']==0xa0080000
        assert 0<raw[13]<=16384 and mem['__packet']+61728<mem['__stack_bottom']
        if name!='p1b_reject_misaligned':
            assert raw[3]==0 and raw[8:13]==[189328,13,13,0,61728] and raw[15]==5058532
            assert stored(folder/'input_000.hex')==x.tobytes()
            assert stored(folder/'cpu_observed_job_00.hex')==expected;codes+=6336
            assert s['verified_parameter_words']==189328
        else:assert raw[3]==-4 and raw[8:12]==[0,1,1,1] and s['verified_parameter_words']==0
        if s['factor']=='baseline':
            assert raw==list(map(int,(original/'cpu_metrics.txt').read_text().splitlines()[0].split()))
            assert s['phase_cycles']==prior['phase_cycles'] and s['ram_main']==prior['ram_transactions']
            assert s['report_tail']==dict(cycles=594,retired=71) and len(tail)==114
            assert s['ram_tail']['code_address_range']['reads']==112 and s['ram_tail']['stack']['reads']==2
        results[name]=dict(**s,process_cycles=process,reset_cycles=reset,post_report_to_process_end_cycles=after_report,ELF_loads=loads)
    assert codes==25344
    generic=(ROOT/'rtl/integration/driver/kwt1.c').read_text();main=(ROOT/'firmware/reference/main.c').read_text()
    for name in ['p1a_null_cancel','p1c_itcm']:assert (out/name/'driver.c').read_text()==generic
    for name in ['p1b_aligned','p1c_itcm']:assert (out/name/'main.c').read_text()==main
    # Persist exact C diffs to expose compiler/layout effects as well as intent.
    for name in NAMES[1:]:
        for kind,original_text in [('main',main),('driver',generic)]:
            diff=''.join(difflib.unified_diff(original_text.splitlines(True),(out/name/(kind+'.c')).read_text().splitlines(True),fromfile='frozen/'+kind+'.c',tofile=name+'/'+kind+'.c'))
            (out/(name+'_'+kind+'.diff')).write_text(diff)
    contract=read(out/'word_contract/verification.json');assert contract['passed'] and contract['words']==189328
    verify(ROOT,contract['source_sha256'])
    b=results[NAMES[0]];table=[]
    for name in NAMES:
        r=results[name];table.append(dict(name=name,cycles=r['main']['cycles'],saved_cycles=b['main']['cycles']-r['main']['cycles'],saved_percent=100*(1-r['main']['cycles']/b['main']['cycles']),retired=r['main']['retired'],packet_owned=r['phase_cycles']['packet_owned'],stack_reads=r['ram_main']['stack']['reads'],stack_writes=r['ram_main']['stack']['writes'],staging_reads=r['ram_main']['packet_staging']['reads'],external_code_region_reads=r['ram_main']['code_address_range']['reads'],startup_cycles=r['startup']['cycles'],startup_plus_main=r['main_plus_startup_cycles'],stack_highwater=r['stack_highwater'],tail_cycles=r['report_tail']['cycles']))
    sources=[Path(__file__),ROOT/'scripts/run_e203_factors.py',ROOT/'scripts/summarize_e203_factors.py',ROOT/'scripts/validate_e203_factors.py',ROOT/'rtl/e203_experiments_20261104/window_observer.hpp',ROOT/'firmware/e203_experiments_20261104/word_access.h',ROOT/'firmware/e203_experiments_20261104/start_itcm.S',ROOT/'firmware/e203_experiments_20261104/link_itcm.ld',ROOT/'tests/test_e203_word_contract.cpp',ROOT/'flow/E203_FACTOR_PROTOCOL_20261104.md']
    binding={p.relative_to(ROOT).as_posix():sha(p) for p in sources}
    for p in sources:
        target=out/'source'/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(p.read_bytes())
    (out/'source_manifest.json').write_text(json.dumps(binding,indent=2));(out/'comparison.json').write_text(json.dumps(table,indent=2))
    report=dict(passed=True,stage='P0/P1 first architecture review only',independently_recomputed_output_codes=codes,mismatches=0,single_factors=3,baseline_repeated_against_frozen_18_metrics_and_independent_profile=True,main_and_tail_separately_conserved=True,baseline_tail_RAM_reads=114,baseline_tail_breakdown=dict(code_address_region=112,stack=2),unaligned_actual_CPU_rejected_before_DATA=True,all_packet_words_checked_on_acceptance=True,shared_memory_occupied_including_stack_bytes=98992,reference_ITCM_bytes_used=results['p1c_itcm']['ITCM_bytes'],reference_CPU_ITCM_capacity_bytes=65536,combination_tested=False,P2_full_regression=False,P3_complete_mapped_regression=False,P4_complete_STA=False,physical_signoff=False,comparison=table)
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'evidence_manifest.json').write_text(json.dumps(dict(sha256={p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name!='evidence_manifest.json'}),indent=2))
    print(json.dumps(report,indent=2));return report

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();check(a.output.resolve())
