"""Replay the verified block ELF on the same CPU model at three arrival rates."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from local_tools import ROOT, sha
from run_input16_e203_block import phase_report, replace_once


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verified', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    source, out = args.verified.resolve(), args.output.resolve()
    manifest = json.loads((source/'manifest.json').read_text())
    inputs = [source/'observer.cpp', source/'window_observer.hpp', source/'verification.json',
              source/'firmware.bin', *sorted((source/'block').glob('*.hex')), source/'block/cases.txt']
    inputs = [p for p in inputs if not p.name.startswith('cpu_observed')]
    for path in inputs:
        assert sha(path) == manifest[path.relative_to(source).as_posix()]

    out.mkdir(parents=True)
    observer = replace_once((source/'observer.cpp').read_text(), 'static uint64_t clocks=0,retired=0;',
                            'static unsigned arrival_ticks=6;\nstatic uint64_t clocks=0,retired=0;')
    observer = observer.replace('input_due=clocks+6', 'input_due=clocks+arrival_ticks')
    observer = observer.replace('input_due+=6', 'input_due+=arrival_ticks')
    observer = observer.replace('packet_due=clocks+1024+6', 'packet_due=clocks+1024+arrival_ticks')
    observer = observer.replace('packet_due+=6', 'packet_due+=arrival_ticks')
    observer = replace_once(observer, '  Verilated::commandArgs(argc,argv);',
                            '''  require(argc==4,"root, mode and arrival ticks required");
  arrival_ticks=std::stoul(argv[3]);
  require(arrival_ticks==3||arrival_ticks==6||arrival_ticks==12,"unsupported arrival rate");
  Verilated::commandArgs(argc,argv);''')
    (out/'observer.cpp').write_text(observer)
    shutil.copyfile(source/'window_observer.hpp', out/'window_observer.hpp')
    rel = out.relative_to(ROOT).as_posix()
    model = (source/'model').relative_to(ROOT).as_posix()
    objects = [f'{model}/{name}' for name in ('Vreference_top__ALL.a','verilated.o','verilated_threads.o')]
    cwd = '/mnt/e/project/ChipCompetition/keyword-transformer'

    def linux(command, log):
        with (out/log).open('w') as handle:
            subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {command}'],
                           stdout=handle, stderr=subprocess.STDOUT, check=True)

    linux(f'g++ -std=c++17 -O2 -pthread -I{model} -I/usr/share/verilator/include '
          f'-I/usr/share/verilator/include/vltstd {rel}/observer.cpp {" ".join(objects)} -o {rel}/observer', 'build.log')
    cases = []
    for rate, ticks in ((50,12), (100,6), (200,3)):
        folder = out/str(rate)
        folder.mkdir()
        for path in inputs[3:]:
            shutil.copyfile(path, folder/path.name)
        linux(f'{rel}/observer {rel}/{rate} batch {ticks}', f'{rate}.log')
        assert 'PASS E203 jobs=1 ' in (out/f'{rate}.log').read_text()
        assert (folder/'cpu_observed_job_00.hex').read_text().split() == (folder/'expected_000.hex').read_text().split()
        case, = phase_report(folder)
        assert case['words'] == case['staging_reads'] == 189328
        if rate == 100:
            assert case == json.loads((source/'verification.json').read_text())['cases']['block'][0]
        cases.append(dict(arrival_MBps_at_assumed_150MHz=rate, cycles_per_staging_word=ticks, **case))
    report = dict(passed=True, actual_E203=True, shared_RAM_model='single port, host arrival gets priority',
                  output_codes=3*6336, mismatches=0, cases=cases,
                  source_sha256={p.relative_to(ROOT).as_posix():sha(p)
                                 for p in [*inputs, *(ROOT/p for p in objects), Path(__file__)]})
    (out/'verification.json').write_text(json.dumps(report, indent=2))
    (out/'manifest.json').write_text(json.dumps({p.relative_to(out).as_posix():sha(p) for p in out.rglob('*')
                                                if p.is_file() and p.name != 'observer'}, indent=2))
    print(json.dumps(cases, indent=2))


if __name__ == '__main__':
    main()
