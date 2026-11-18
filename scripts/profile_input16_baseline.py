"""Observe one complete cold task on the frozen S16/trim2 CPU model."""
import json
from pathlib import Path
import shutil
import subprocess

from local_tools import ROOT, sha


def main():
    data = ROOT / 'testdata/input16_rtl_20261105'
    baseline = data / 'trim2_e203'
    out = data / 'p0_baseline'
    out.mkdir()
    manifest = json.loads((baseline / 'manifest.json').read_text())
    inputs = [baseline / 'firmware.bin', baseline / 'firmware.elf', baseline / 'sim_input16_e203.cpp']
    inputs += sorted(baseline.glob('*.bin.hex')) + [baseline / f'{n}_000.hex' for n in ('input', 'expected')]
    for path in inputs:
        assert sha(path) == manifest[path.name]
        if path.suffix == '.hex' or path.name == 'firmware.bin':
            shutil.copyfile(path, out / path.name)
    (out / 'cases.txt').write_text('0 0\n')
    observer = ROOT / 'rtl/e203_combinations_20261104/window_observer.hpp'
    header = observer.read_text().replace('kInputOffset+6336', 'kInputOffset+12672')
    header = header.replace('reference_top__DOT__bridge__DOT__', 'reference_top__DOT__path__DOT__bridge__DOT__')
    header = header.replace('reference_top__DOT__ar', 'reference_top__DOT__path__DOT__ar')
    header = header.replace('reference_top__DOT__accel__DOT__accel__DOT__', 'reference_top__DOT__path__DOT__accelerator__DOT__accel__DOT__')
    header = header.replace('static unsigned region', 'static uint64_t phase_retired[6]={}, data_ready_cycles=0, data_stall_cycles=0;\nstatic unsigned region')
    header = header.replace('phases[p]++;', '''phases[p]++;phase_retired[p]+=d.retired;
   if(r->reference_top__DOT__path__DOT__bridge__DOT__state==1&&!r->reference_top__DOT__path__DOT__bridge__DOT__read&&(r->reference_top__DOT__path__DOT__bridge__DOT__addr&65535)==16){
    if(r->reference_top__DOT__path__DOT__ar)data_ready_cycles++;else data_stall_cycles++;
   }''')
    header = header.replace(' last_finish_clock=clocks;', ''' for(unsigned k=0;k<6;k++)f<<"phase_retired "<<k<<" "<<phase_retired[k]<<"\\n";
 f<<"data_request "<<data_ready_cycles<<" "<<data_stall_cycles<<"\\n";
 last_finish_clock=clocks;''')
    (out / 'window_observer.hpp').write_text(header)
    source = (baseline / 'sim_input16_e203.cpp').read_text()
    for old, new in [
        ('static uint32_t word(uint32_t off)', '#include "window_observer.hpp"\nstatic uint32_t word(uint32_t off)'),
        (' if(d.retired)retired++;', ' observe_tick(mtake,hrq,ma,mread,ha,hread);\n if(d.retired)retired++;'),
        ('static void finish_job(int rc){', 'static void finish_job(int rc){\n observe_finish();'),
        (' std::printf("JOB %u label=%d fault=%d BEGIN', ' observe_begin();\n std::printf("JOB %u label=%d fault=%d BEGIN'),
    ]:
        assert source.count(old) == 1, old
        source = source.replace(old, new)
    (out / 'observer.cpp').write_text(source)
    model = baseline / 'model'
    objects = [model / name for name in ('Vreference_top__ALL.a', 'verilated.o', 'verilated_threads.o')]
    objects += sorted(model.glob('*.h'))
    bound = {str(p.relative_to(ROOT)): sha(p) for p in [*inputs, *objects, observer, Path(__file__)]}
    (out / 'source_bindings.json').write_text(json.dumps(bound, indent=2))
    rel = out.relative_to(ROOT).as_posix()
    mp = model.relative_to(ROOT).as_posix()

    def run(command, log):
        cwd = '/mnt/e/project/ChipCompetition/keyword-transformer'
        result = subprocess.run(['wsl.exe', '-d', 'Ubuntu-24.04', '--', 'bash', '-lc', f'cd {cwd} && {command}'],
                                capture_output=True, text=True)
        (out / log).write_text(result.stdout + result.stderr)
        assert result.returncode == 0, (log, result.stderr[-2000:])

    run(f'g++ -std=c++17 -O2 -pthread -I{mp} -I/usr/share/verilator/include -I/usr/share/verilator/include/vltstd '
        f'{rel}/observer.cpp {mp}/Vreference_top__ALL.a {mp}/verilated.o {mp}/verilated_threads.o -o {rel}/observer', 'compile.log')
    run(f'{rel}/observer {rel} batch', 'simulation.log')
    for name in ('cpu_metrics.txt', 'windows.txt'):
        assert (out / name).read_text() == (baseline / name).read_text().splitlines(keepends=True)[0]
    assert sha(out / 'cpu_observed_job_00.hex') == sha(baseline / 'cpu_observed_job_00.hex')
    lines = [line.split() for line in (out / 'window_job_00.txt').read_text().splitlines()]
    phases = ('input_arrival', 'packet_arrival', 'packet_lease', 'compute', 'output', 'other_control')
    cycles = dict(zip(phases, [int(row[2]) for row in lines if row[0] == 'phase']))
    retired = dict(zip(phases, [int(row[2]) for row in lines if row[0] == 'phase_retired']))
    data_ready, data_stall = next([int(v) for v in row[1:]] for row in lines if row[0] == 'data_request')
    assert sum(cycles.values()) == 9634904 and sum(retired.values()) == 3551070 and data_ready == 189328
    result = dict(passed=True, configuration='S16/trim2', cycles=9634904, retired=3551070,
                  phase_cycles=cycles, phase_retired=retired, accepted_parameter_words=data_ready,
                  parameter_data_request_stall_cycles=data_stall, existing_output_match=True)
    (out / 'verification.json').write_text(json.dumps(result, indent=2))
    (out / 'manifest.json').write_text(json.dumps({p.name: sha(p) for p in out.iterdir() if p.is_file()}, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
