"""Use the same ICB cold/recovery harness for RTL or the revised full netlist."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from local_tools import ROOT, sha


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--mapped', type=Path, help='directory with mapped_simple.v and its manifest')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True)
    rel = out.relative_to(ROOT).as_posix()
    base = ROOT / 'testdata/input16_rtl_20261105'
    fixtures = base / 'trim2_e203'
    manifest = json.loads((fixtures / 'manifest.json').read_text())
    for path in [*sorted(fixtures.glob('*.bin.hex')),
                 *(fixtures / f'{name}_{i:03d}.hex' for i in (0, 1) for name in ('input', 'expected'))]:
        assert sha(path) == manifest[path.name]
        shutil.copyfile(path, out / path.name)

    def execute(command, log):
        cwd = '/mnt/e/project/ChipCompetition/keyword-transformer'
        with (out / log).open('w') as handle:
            result = subprocess.run(['wsl.exe', '-d', 'Ubuntu-24.04', '--', 'bash', '-lc', f'cd {cwd} && {command}'],
                                    stdout=handle, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError((out / log).read_text()[-5000:])

    rtl = ROOT / 'rtl/input16_trim2'
    flags = ''
    if args.mapped:
        mapped = args.mapped.resolve()
        net = mapped / 'mapped_simple.v'
        assert sha(net) == json.loads((mapped / 'manifest.json').read_text())[net.name]
        cells = base / 'mapping_full/functional_cells.v'
        assert sha(cells) == json.loads((cells.parent / 'manifest.json').read_text())[cells.name]
        sram = ROOT / 'rtl/integration/tech_sram_model.sv'
        small = (out / 'small_sram.sv')
        small.write_text((sram.read_text().replace('4096', '1024').replace('[11:0]', '[9:0]').replace('4095', '1023')))
        sources = [net, cells, sram, small]
    else:
        flags = '-DKWT_SIM -Irtl/input16_trim2/generated'
        sources = [ROOT / 'rtl/micro/mul_pipe.sv', ROOT / 'rtl/micro/rne_pipe.sv',
                   *sorted(p for p in rtl.glob('*.sv') if p.name != 'kwt_tech_sram_blackbox.sv'),
                   ROOT / 'rtl/reference/icb_kwt_bridge.sv', ROOT / 'rtl/input16_icb_top.sv']
    host = ROOT / 'rtl/integration/sim_input16_icb_gate.cpp'
    bindings = {p.relative_to(ROOT).as_posix(): sha(p) for p in [Path(__file__), host, *sources]}
    (out / 'source_bindings.json').write_text(json.dumps(bindings, indent=2))
    paths = ' '.join(p.relative_to(ROOT).as_posix() for p in sources)
    top = 'kwt_input16_icb_top'
    cpp = '/mnt/e/project/ChipCompetition/keyword-transformer/' + host.relative_to(ROOT).as_posix()
    execute(f'verilator --cc --exe --no-timing -Wno-fatal --output-split 16000 --output-split-cfuncs 500 '
            f'{flags} --top-module {top} --Mdir {rel}/model {paths} {cpp}', 'generate.log')
    execute(f'make -C {rel}/model -f V{top}.mk -j 3 OPT_FAST=-O1 OPT_SLOW=-O0', 'build.log')
    execute(f'{rel}/model/V{top} {rel}', 'simulation.log')
    log = (out / 'simulation.log').read_text()
    assert 'PASS cold=2 cancelled=1 reset=1 codes=12672' in log
    for i in (0, 1):
        assert (out / f'mapped_observed_{i:03d}.hex').read_text().split() == (out / f'expected_{i:03d}.hex').read_text().split()
    result = dict(passed=True, mapped=bool(args.mapped), cold_tasks=2, in_flight_cancel=1, in_flight_reset=1, output_codes=12672, mismatches=0)
    (out / 'verification.json').write_text(json.dumps(result, indent=2))
    (out / 'manifest.json').write_text(json.dumps({p.name: sha(p) for p in out.iterdir() if p.is_file()}, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
