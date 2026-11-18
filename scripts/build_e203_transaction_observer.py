"""Add host-only transaction and macro-counter evidence, reuse frozen CPU/DUT."""
import argparse
import json
from pathlib import Path
from local_tools import ROOT, sha
import run_e203_combinations as build


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    out = args.output.resolve()
    assert not out.exists(), 'Use a new build directory'
    out.mkdir(parents=True)
    original = ROOT / 'rtl/e203_combinations_20261104/window_observer.hpp'
    source = original.read_text()
    state = '''static uint64_t metric_acc_reads=0,metric_acc_writes=0,metric_data=0,metric_input=0;
static uint64_t metric_error_queries=0,metric_unaccepted_errors=0;
static bool metric_pending=false;
'''
    source = source.replace('static void observe_begin(){', state + '''static void observe_begin(){
 metric_acc_reads=metric_acc_writes=metric_data=metric_input=0;
 metric_error_queries=metric_unaccepted_errors=0;metric_pending=false;
''')
    hook = ''' const auto*r=d.rootp;
 if(active&&rc_event==999){
  if(r->reference_top__DOT__bridge__DOT__state==1&&r->reference_top__DOT__ar){
   require(!metric_pending,"next ACC transaction before previous error query");metric_pending=true;
   if(r->reference_top__DOT__bridge__DOT__read)metric_acc_reads++;
   else{metric_acc_writes++;unsigned a=r->reference_top__DOT__bridge__DOT__addr&65535;
    if(a==16)metric_data++;if(a==20)metric_input++;
   }
  }
  if(hrq&&hread&&(ha&65535)==32){
   metric_error_queries++;
   if(!metric_pending){require(int32_t(d.bus_rc)!=0,"error query without ACC or transport error");metric_unaccepted_errors++;}
   metric_pending=false;
  }
  if(hrq&&!hread&&(ha&65535)==28)require(!metric_pending,"driver returned before last error query");
 }
'''
    assert source.count(' const auto*r=d.rootp;') == 1
    source = source.replace(' const auto*r=d.rootp;\n', hook)
    marker = 'static void observe_finish(){'
    finish = '''static void observe_finish(){
 {char name[64];std::sprintf(name,"transactions_job_%02u.txt",unsigned(ji));std::ofstream m(root+"/"+name);
  m<<"acc_reads "<<metric_acc_reads<<"\\nacc_writes "<<metric_acc_writes<<"\\nparameter_writes "<<metric_data<<"\\ninput_writes "<<metric_input;
  m<<"\\nerror_queries "<<metric_error_queries<<"\\nunaccepted_error_queries "<<metric_unaccepted_errors<<"\\npending "<<metric_pending;
  m<<"\\nSRAM_reads "<<(uint64_t(acc_counters[4])|(uint64_t(acc_counters[5])<<32));
  m<<"\\nSRAM_writes "<<(uint64_t(acc_counters[6])|(uint64_t(acc_counters[7])<<32))<<"\\n";
 }
'''
    assert source.count(marker) == 1
    source = source.replace(marker, finish)
    (out / 'source').mkdir()
    header = out / 'source/window_observer.hpp'
    header.write_text(source)
    build.OBS = header
    model = build.build(out)
    bindings = json.loads((out / 'build_bindings.json').read_text())
    for path in [Path(__file__), original]:
        bindings[str(path)] = sha(path)
    (out / 'build_bindings.json').write_text(json.dumps(bindings, indent=2))
    result = dict(passed=True, model_sha256=sha(model), observer_sha256=sha(header),
                  CPU_and_accelerator_objects='unchanged frozen baseline part1..11',
                  scope='host-only instrumentation, no DUT input/state changes')
    (out / 'summary.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
