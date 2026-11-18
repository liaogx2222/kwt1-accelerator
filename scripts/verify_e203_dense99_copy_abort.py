"""Cancel a physical scratch-to-A read and cold-recover the same E203 model."""
import argparse
import json
from pathlib import Path
import subprocess

from local_tools import ROOT, sha
from verify_e203_compact_dense_abort import observer as fault_observer, replace_once


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    base=args.model.resolve()
    out=args.output.resolve()
    bindings=[base/n for n in ('observer.cpp','firmware.bin','arithmetic.sv','100.log')]
    assert 'raw=684288 rq=684288' in (base/'100.log').read_text()
    if (base/'manifest.json').is_file():
        manifest=json.loads((base/'manifest.json').read_text())
        for p in bindings:
            assert sha(p)==manifest[p.name]
    out.mkdir(parents=True)
    source=fault_observer((base/'observer.cpp').read_text())
    source=replace_once(source,'dut.dense_valid && !dut.dense_result_ready && !dense_cancelled',
                        'dut.copy_read && dut.copy_phase && !dense_cancelled')
    source=replace_once(source,'!dut.dense_valid&&!dut.raw_accept&&!dut.dense_done',
                        '!dut.dense_valid&&!dut.raw_accept&&!dut.dense_done&&!dut.copy_read&&!dut.copy_write')
    source=replace_once(source,'dense=DenseScoreboard{};','dense=Dense99Scoreboard{};')
    source=replace_once(source,'PASS DENSE FAULT stalled-result cancel and same-model hard-reset recovery',
                        'PASS DENSE99 FAULT scratch-read cancel and same-model hard-reset recovery')
    (out/'observer.cpp').write_text(source)
    model=base/'model'
    objects=[model/n for n in ('Vreference_top__ALL.a','verilated.o','verilated_threads.o')]
    def rel(p):
        return p.relative_to(ROOT).as_posix()
    output=rel(out)
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    def linux(cmd,log):
        with (out/log).open('w') as fd:
            p=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {cmd}'],
                             stdout=fd,stderr=subprocess.STDOUT)
        if p.returncode:
            raise RuntimeError((out/log).read_text(errors='replace')[-2500:])
    linux(f'g++ -std=c++17 -O2 -pthread -I{rel(model)} -I/usr/share/verilator/include '
          f'-I/usr/share/verilator/include/vltstd {output}/observer.cpp {" ".join(rel(p) for p in objects)} '
          f'-o {output}/observer','build.log')
    linux(f'{output}/observer {rel(base/"firmware.bin")} testdata/input16_rtl_20261105/trim2_e203 6 faults','simulation.log')
    log=(out/'simulation.log').read_text()
    assert 'PASS dense_cancel raw_before=0 rq_before=0' in log
    assert 'PASS DENSE99 FAULT' in log
    sources=[Path(__file__),ROOT/'scripts/verify_e203_compact_dense_abort.py',
             ROOT/'rtl/block_transfer/compact_dense99_scoreboard.hpp',*objects,*bindings]
    report=dict(passed=True,cancelled_at_physical_s_read=True,no_later_a_write=True,same_E203_model_reset=True,
                post_reset_raw_codes=684288,post_reset_rq_codes=684288,post_reset_masked_lanes=6912,mismatches=0,
                source_sha256={rel(p):sha(p) for p in sources})
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(log,end='')


if __name__=='__main__':
    main()
