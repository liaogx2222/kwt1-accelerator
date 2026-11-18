"""Exercise the portable P2 front end with the frozen 13 canonical packets."""
import json
from pathlib import Path
import re
import subprocess

from local_tools import ROOT, sha


def main():
    base = ROOT / 'testdata/input16_rtl_20261105'
    out = base / 'p2_block_contract'
    out.mkdir()
    fixtures = base / 'trim2_e203'
    manifest = json.loads((fixtures / 'manifest.json').read_text())
    packets = sorted(fixtures.glob('*.bin.hex'))
    assert len(packets) == 13
    for packet in packets:
        assert sha(packet) == manifest[packet.name], packet
    rtl = ROOT / 'rtl/block_transfer'
    sources = [rtl / 'kwt_verified_block_reader.sv', rtl / 'tb_verified_block_reader.sv',
               ROOT / 'rtl/input16_trim2/generated/kwt_profile.svh']
    rel = out.relative_to(ROOT).as_posix()
    fixture_path = fixtures.relative_to(ROOT).as_posix()

    def run(command, filename):
        cwd = '/mnt/e/project/ChipCompetition/keyword-transformer'
        process = subprocess.run(['wsl.exe', '-d', 'Ubuntu-24.04', '--', 'bash', '-lc', f'cd {cwd} && {command}'],
                                 capture_output=True, text=True)
        log = process.stdout + process.stderr
        (out / filename).write_text(log)
        assert process.returncode == 0, log[-2500:]
        return log

    top = 'tb_verified_block_reader'
    paths = ' '.join(p.relative_to(ROOT).as_posix() for p in sources[:2])
    run(f'verilator --binary --timing -j 2 -Wno-fatal --top-module {top} --Mdir {rel}/model '
        f'-Irtl/input16_trim2/generated {paths}', 'build.log')
    result = []
    for rate in (50, 100, 200):
        log = run(f'{rel}/model/V{top} +root={fixture_path} +rate={rate} +latency=3', f'{rate}MBps.log')
        assert 'PASS FAULTS' in log
        match = re.search(r'PASS CANONICAL\s+rate=\s*(\d+) latency=\s*(\d+) cycles=\s*(\d+) reads=\s*(\d+) words=\s*(\d+) source_stalls=\s*(\d+) sink_stalls=\s*(\d+)', log)
        assert match
        values = list(map(int, match.groups()))
        assert values[0] == rate and values[3:5] == [378656, 189328]
        result.append(dict(zip(['arrival_MBps', 'read_latency_cycles', 'cycles', 'reads', 'payload_words', 'source_stalls', 'sink_stalls'], values)))
    report = dict(passed=True, portable_frontend_only=True, actual_E203_block_transport=False,
                  complete_system_window=False, max_outstanding=1, replay_fifo_words=1,
                  requires_provider_immutable_staging=True, measured=result, scope='RTL source/consumer fixture, serial packet staging and two reads, no core compute')
    (out / 'verification.json').write_text(json.dumps(report, indent=2))
    bindings = {p.relative_to(ROOT).as_posix(): sha(p) for p in [Path(__file__), *sources, *packets]}
    (out / 'source_bindings.json').write_text(json.dumps(bindings, indent=2))
    (out / 'manifest.json').write_text(json.dumps({p.name: sha(p) for p in out.iterdir() if p.is_file()}, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
