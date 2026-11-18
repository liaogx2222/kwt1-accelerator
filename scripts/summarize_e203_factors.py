"""One main/tail convention for all single-factor comparisons."""
import argparse,json
from pathlib import Path
from local_tools import ROOT,sha

PHASES=['input_arrival','provider_wait','packet_owned','accelerator_compute_exclusive','output_ack','other_control']
REGIONS=['code_address_range','small_data','input','output','packet_staging','stack','other']

def summarize(out):
    execution=json.loads((out/'execution.json').read_text());factor=execution['factor'];raw=list(map(int,(out/'cpu_metrics.txt').read_text().split()));assert len(raw)==18
    counts={};ram=[{},{}];pcs=[[],[]];phases={};tail=[]
    for line in (out/'window_counts.txt').read_text().splitlines():
        kind,*values=line.split();v=list(map(int,values))
        if kind=='ram':ram[v[0]][REGIONS[v[1]]]=dict(reads=v[2],writes=v[3])
        elif kind=='pc':pcs[v[0]].append(dict(pc=v[1],cycles=v[2],retired=v[3]))
        elif kind=='phase':phases[PHASES[v[0]]]=v[1]
        elif kind=='tail_read':tail.append(dict(cycle=v[0],address=v[1],pc=v[2]))
        elif kind=='window':counts['main' if v[0]==0 else 'tail']=dict(cycles=v[1],retired=v[2])
        else:counts[kind]=v
    assert counts['boundaries'][1]-counts['boundaries'][0]==counts['main']['cycles']==raw[4]==sum(phases.values())
    assert counts['boundaries'][2]-counts['boundaries'][1]==counts['tail']['cycles']
    assert counts['main']['retired']==raw[5]
    for i,key in enumerate(['main','tail']):
        assert sum(p['cycles'] for p in pcs[i])==counts[key]['cycles'] and sum(p['retired'] for p in pcs[i])==counts[key]['retired']
    assert sum(r['reads'] for w in ram for r in w.values())==raw[16] and sum(r['writes'] for w in ram for r in w.values())==raw[17]
    assert len(tail)==sum(r['reads'] for r in ram[1].values())
    base=ROOT/'testdata/reference_e203/parallel_20261103/classes_0_3'
    if factor!='misaligned':
        assert raw[3]==0 and raw[8:13]==[189328,13,13,0,61728] and raw[15]==5058532
        assert counts['words']==[189328]
        assert (out/'cpu_observed_job_00.hex').read_text().split()==(base/'expected_000.hex').read_text().split()
        assert ram[0]['packet_staging']['reads']==(189328 if factor=='aligned' else 757312)
    else:assert raw[3]==-4 and raw[8]==0 and counts['words']==[0]
    if factor=='baseline':
        assert raw==list(map(int,(base/'cpu_metrics.txt').read_text().splitlines()[0].split()))
        assert len(tail)==114 and ram[0]['code_address_range']['reads']==17804468
    symbols=[]
    for line in (out/'firmware.nm').read_text().splitlines():
        address,kind,name=line.split()
        if kind.lower()=='t':symbols.append((int(address,16),name))
    def function(pc):return max((s for s in symbols if s[0]<=pc),default=(0,'unknown'))[1]
    tail_by_function={}
    for row in tail:
        row['function']=function(row['pc']);tail_by_function[row['function']]=tail_by_function.get(row['function'],0)+1
    report=dict(passed=True,factor=factor,output_codes=0 if factor=='misaligned' else 6336,mismatches=0,main=counts['main'],report_tail=counts['tail'],phase_cycles=phases,ram_main=ram[0],ram_tail=ram[1],tail_read_function_counts=tail_by_function,boundary_clocks=counts['boundaries'],startup=dict(cycles=counts['boot'][0],external_RAM_reads=counts['boot'][1],external_RAM_writes=counts['boot'][2],first_ITCM_retirement_clock=counts['boot'][3]),main_plus_startup_cycles=raw[4]+counts['boot'][0],verified_parameter_words=counts['words'][0],stack_highwater=raw[13],legacy_18_fields=raw,firmware_sha256=sha(out/'firmware.bin'),scope='single factor/class-0; no combination approval or final platform signoff')
    if factor=='itcm':
        assert counts['boot'][3]>0 and ram[0]['code_address_range']['reads']==0
        m=json.loads((out/'memory_map.json').read_text());report['ITCM_bytes']=m['__itcm_end']-m['__itcm_start'];report['shared_image_bytes']=m['__image_end']-0xa0000000
    (out/'tail_reads.json').write_text(json.dumps(tail,indent=2));(out/'summary.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file() and p.name!='manifest.json'},indent=2));print(json.dumps(report,indent=2),flush=True)
    return report

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();summarize(a.output.resolve())
