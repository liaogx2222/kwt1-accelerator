"""Cancel a stalled LN2 result and cold-recover with the same E203 model."""
import argparse
import json
from pathlib import Path
import subprocess

from local_tools import ROOT, sha
from run_input16_e203_block import replace_once
from verify_e203_compact_dense_abort import observer as dense_abort_observer


def observer(source):
    source=dense_abort_observer(source)
    edits=[
        ('(13183u<<4)|3u','(6167u<<4)|3u'),
        ('dense.matrices==0 &&','dense.matrices==6 &&'),
        ('!dut.dense_valid && !dut.raw_accept && !dut.tile_valid,"failed to invalidate dense state"',
         '!dut.ln_valid && !dut.ln_write && !dut.ln_phase,"failed to invalidate LN2 state"'),
        ('dut.dense_valid && !dut.dense_result_ready && !dense_cancelled',
         'dut.ln_valid && !dut.ln_ready && dense.ln.writes>0 && !dense_cancelled'),
        ('        if(dense_cancelled && !cancel_next)\n            check(!dut.dense_valid&&!dut.raw_accept&&!dut.dense_done,"stale dense output after cancel");',
         '''        if(dense_cancelled && !cancel_next) {
            dense.ln.held=false;
            check(!dut.ln_valid&&!dut.ln_write&&!dut.ln_phase,"stale LN2 output after cancel");
        }'''),
        ('dense=DenseScoreboard{};','dense=Dense99Scoreboard{};'),
        ('PASS dense_cancel raw_before=%llu rq_before=%llu error_index=13183',
         'PASS ln2_cancel output_before=%llu writes_before=%llu error_index=6167'),
        ('(unsigned long long)session.dense.raw_codes,(unsigned long long)session.dense.rq_codes',
         '(unsigned long long)session.dense.ln.output_count,(unsigned long long)session.dense.ln.writes'),
        ('PASS DENSE FAULT stalled-result cancel and same-model hard-reset recovery',
         'PASS LN2 FAULT stalled-result cancel and same-model hard-reset recovery'),
    ]
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    base,out=args.model.resolve(),args.output.resolve()
    bindings=[base/n for n in ('observer.cpp','firmware.bin','100.log','ln2_scoreboard.hpp')]
    manifest=json.loads((base/'manifest.json').read_text())
    for path in bindings:
        assert sha(path)==manifest[path.name],path
    out.mkdir(parents=True)
    (out/'observer.cpp').write_text(observer(bindings[0].read_text()))
    model=base/'model'
    objects=[model/n for n in ('Vreference_top__ALL.a','verilated.o','verilated_threads.o')]
    def rel(path):
        return path.relative_to(ROOT).as_posix()
    frozen='testdata/input16_rtl_20261105/trim2_e203'
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'

    def linux(command,log):
        with (out/log).open('w') as fd:
            result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {command}'],
                                  stdout=fd,stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError((out/log).read_text(errors='replace')[-2500:])

    object_args=' '.join(rel(p) for p in objects)
    linux(f'g++ -std=c++17 -O2 -pthread -I{rel(model)} -I/usr/share/verilator/include '
          f'-I/usr/share/verilator/include/vltstd {rel(out)}/observer.cpp {object_args} -o {rel(out)}/observer','build.log')
    linux(f'{rel(out)}/observer {rel(base/"firmware.bin")} {frozen} 6 faults','simulation.log')
    log=(out/'simulation.log').read_text()
    assert 'PASS LN2 FAULT' in log and 'ln=76032 ln_writes=9504' in log
    sources=[Path(__file__),ROOT/'scripts/verify_e203_compact_dense_abort.py',*bindings,*objects,
             ROOT/'rtl/block_transfer/compact_ln2_golden.hpp']
    evidence=dict(passed=True,cancelled_while_LN2_stalled=True,first_error_index=6167,same_E203_model_reset=True,
                  post_reset_LN2_codes=76032,post_reset_S_writes=9504,mismatches=0,
                  source_sha256={rel(p):sha(p) for p in sources})
    (out/'verification.json').write_text(json.dumps(evidence,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(log,end='')


if __name__=='__main__':
    main()
