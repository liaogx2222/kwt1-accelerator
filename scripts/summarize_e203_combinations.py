"""Main/tail conservation for combined firmware and error recovery jobs."""
import json,re
from pathlib import Path
from local_tools import sha
from summarize_e203_factors import PHASES,REGIONS

def stored(p):return b''.join(int(x,16).to_bytes(4,'little') for x in p.read_text().split())
def summarize(out):
    ex=json.loads((out/'execution.json').read_text());raws=[list(map(int,line.split())) for line in (out/'cpu_metrics.txt').read_text().splitlines()];jobs=[];codes=0
    expected_jobs=4 if ex['mode']=='faults' else len(ex['labels']);assert len(raws)==expected_jobs
    for raw in raws:
        jid,label,fault,rc=raw[:4];windows={};ram=[{},{}];pcs=[[],[]];phases={};tail=[];other={}
        for line in (out/f'window_job_{jid:02d}.txt').read_text().splitlines():
            kind,*fields=line.split();v=list(map(int,fields))
            if kind=='window':windows['main' if v[0]==0 else 'tail']=dict(cycles=v[1],retired=v[2])
            elif kind=='ram':ram[v[0]][REGIONS[v[1]]]=dict(reads=v[2],writes=v[3])
            elif kind=='pc':pcs[v[0]].append(v[1:])
            elif kind=='phase':phases[PHASES[v[0]]]=v[1]
            elif kind=='tail_read':tail.append(v)
            else:other[kind]=v
        b=other['boundaries'];assert windows['main']['cycles']==raw[4]==b[1]-b[0]==sum(phases.values())
        assert windows['tail']['cycles']==b[2]-b[1] and windows['main']['retired']==raw[5]
        for i,name in enumerate(['main','tail']):assert sum(p[1] for p in pcs[i])==windows[name]['cycles'] and sum(p[2] for p in pcs[i])==windows[name]['retired']
        assert sum(v['reads'] for r in ram for v in r.values())==raw[16] and sum(v['writes'] for r in ram for v in r.values())==raw[17]
        assert len(tail)==sum(v['reads'] for v in ram[1].values()) and other['words']==[raw[8]]
        assert all(b[1]<=v[0]<b[2] for v in tail) and 0<raw[13]<=16384
        if rc==0:
            assert raw[8:13]==[189328,13,13,0,61728] and raw[15]==5058532 and other['errors']==[0,0,0]
            assert stored(out/f'cpu_observed_job_{jid:02d}.hex')==stored(out/f'expected_{label:03d}.hex');codes+=6336
            assert ram[0]['packet_staging']['reads']==(189328 if ex['kind']=='abc' else 757312)
        elif rc==-3:assert fault==1 and other['errors']==[-3,0,0] and raw[9:12]==[2,2,1]
        elif rc==-7:assert fault==2 and other['errors']==[-2,-2,1] and raw[8:12]==[64,1,1,1]
        else:raise AssertionError(('unexpected rc',rc))
        assert ram[0]['code_address_range']['reads']==0
        jobs.append(dict(job=jid,label=label,fault=fault,rc=rc,main=windows['main'],report_tail=windows['tail'],phase_cycles=phases,ram_main=ram[0],ram_tail=ram[1],boundaries=b,pre_job=other['pre_job'],accepted_parameter_words=other['words'][0],errors=other['errors'],stack_highwater=raw[13],legacy_18_fields=raw))
    log=(out/'execution.log').read_text();assert f'PASS E203 jobs={expected_jobs}' in log
    match=re.search(r'PASS E203 jobs=\d+ cycles=(\d+) retired=(\d+)',log);assert match
    m=json.loads((out/'memory_map.json').read_text());assert m['__image_end']==0xa0002010
    report=dict(passed=True,kind=ex['kind'],jobs=jobs,output_codes=codes,mismatches=0,process_cycles=int(match[1]),process_retired=int(match[2]),firmware_sha256=sha(out/'firmware.bin'),ITCM_bytes=m['__itcm_end']-m['__itcm_start'],shared_image_bytes=8208,shared_occupied_including_reserved_stack=98992,physical_signoff=False)
    (out/'summary.json').write_text(json.dumps(report,indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file() and p.name!='manifest.json'},indent=2))
    print(json.dumps(dict(passed=True,kind=ex['kind'],jobs=len(jobs),cycles=[j['main']['cycles'] for j in jobs],output_codes=codes),indent=2),flush=True);return report
