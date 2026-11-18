"""Review the observer window separately from legacy post-report RAM counters."""
import argparse
import json
from pathlib import Path
from local_tools import ROOT, sha


def summarize(out, commands=None, bindings=None):
    release=ROOT/'testdata/reference_e203/parallel_20261103'
    base=release/'classes_0_3'
    for name,digest in json.loads((release/'build/model/stamp.json').read_text())['inputs'].items():
        assert sha(Path(name))==digest,name
    assert (out/'firmware.bin').read_bytes()==(base/'firmware.bin').read_bytes()
    raw=list(map(int,(out/'cpu_metrics.txt').read_text().split()))
    expected=list(map(int,(base/'cpu_metrics.txt').read_text().splitlines()[0].split()))
    assert raw==expected,(raw,expected)
    assert (out/'cpu_observed_job_00.hex').read_bytes()==(base/'cpu_observed_job_00.hex').read_bytes()
    assert 'PASS E203 jobs=1' in (out/'execution.log').read_text()
    phases=['input_arrival','provider_wait','packet_owned','accelerator_compute_exclusive','output_ack','other_control']
    regions=['code_address_range','small_data','input','output','packet_staging','stack','other']
    symbols=[]
    for line in (out/'firmware.nm').read_text().splitlines():
        addr,kind,name=line.split()
        if kind.lower()=='t':symbols.append((int(addr,16),name))
    phase={};ram={};host={};events={};functions={};pcs=[]
    for line in (out/'profile_counts.txt').read_text().splitlines():
        fields=line.split();kind=fields[0];values=list(map(int,fields[1:]))
        if kind=='phase':phase[phases[values[0]]]=values[1]
        elif kind=='ram':ram[regions[values[0]]]=dict(reads=values[1],writes=values[2])
        elif kind=='host':host[values[0]]=dict(reads=values[1],writes=values[2])
        elif kind=='event':events[['ram_request_blocked','host_request_blocked','host_uses_ram_port'][values[0]]]=values[1]
        elif kind=='pc':
            pc,cycles,retired=values;name=max((s for s in symbols if s[0]<=pc),key=lambda x:x[0])[1]
            entry=functions.setdefault(name,dict(ir_residency_cycles=0,retired=0));entry['ir_residency_cycles']+=cycles;entry['retired']+=retired
            pcs.append(dict(pc=hex(pc),function=name,ir_residency_cycles=cycles,retired=retired))
    assert sum(phase.values())==raw[4]
    assert sum(r['ir_residency_cycles'] for r in functions.values())==raw[4]
    assert sum(r['retired'] for r in functions.values())==raw[5]
    # The old harness freezes end_clock at HOST[28] but computes ram_reads /
    # ram_writes later in finish_job() at HOST[4]. Do not compare those windows
    # as equal or silently add the tail to this profiler's main timing window.
    read_sum=sum(r['reads'] for r in ram.values());write_sum=sum(r['writes'] for r in ram.values())
    assert read_sum<=raw[16] and write_sum<=raw[17]
    assert ram['packet_staging']['reads']==189328*4
    assert ram['input']['reads']==6336*2 and ram['output']['writes']==6336
    if bindings:
        for name,digest in bindings.items():assert sha(Path(name))==digest,name
    else:
        bindings={str(p):sha(p) for p in [out/'sim_profile.cpp',out/'profile_e203_observer.hpp',out/'runner_executed.py']}
    summary=dict(passed=True,outer_cycles=raw[4],retired=raw[5],output_codes=6336,mismatches=0,
        all_18_original_metrics_identical=True,firmware_sha256=sha(out/'firmware.bin'),
        phase_cycles=phase,ram_transactions=ram,host_transactions=host,overlapping_events=events,
        functions=dict(sorted(functions.items(),key=lambda x:-x[1]['ir_residency_cycles'])),
        ram_counter_windows=dict(profile_reads=read_sum,profile_writes=write_sum,
            legacy_reads_to_later_finish_job=raw[16],legacy_writes_to_later_finish_job=raw[17],
            post_return_read_difference=raw[16]-read_sum,post_return_write_difference=raw[17]-write_sum),
        accelerator_compute_cycles=raw[15],compute_overlap_with_higher_priority_phases=raw[15]-phase['accelerator_compute_exclusive'],
        scope='one normal class-0 cold task; non-intrusive host observation, no optimization',
        pc_semantics='shadow inspect_pc on ir_valid_set; validate retired IR bytes against firmware; residency includes stalls, not causal/inclusive function cost',
        memory_semantics='address regions, not an IFU/LSU channel split; legacy RAM counters extend past main timing window',
        commands=commands,bindings=bindings,postprocessor_sha256=sha(Path(__file__)))
    (out/'summary.json').write_text(json.dumps(summary,indent=2))
    (out/'pc_histogram.json').write_text(json.dumps(pcs,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file() and p.name!='manifest.json'},indent=2))
    print(json.dumps({k:summary[k] for k in ['passed','outer_cycles','retired','phase_cycles','ram_transactions','functions','ram_counter_windows']},indent=2),flush=True)
    return summary


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();summarize(a.output.resolve())
