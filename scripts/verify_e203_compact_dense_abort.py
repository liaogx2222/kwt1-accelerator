"""Exercise a stalled dense result across cancel and same-model cold recovery."""
import argparse
import json
from pathlib import Path
import subprocess

from local_tools import ROOT, sha
from run_input16_e203_block import replace_once


def observer(source):
    source=replace_once(source,'lost, range };','lost, range, dense_cancel };')
    source=replace_once(source,'    bool delayed=false,','    bool dense_cancelled=false;\n    bool delayed=false,')
    source=replace_once(source,'        case Fault::range: return (48u<<4)|9u;',
                        '''        case Fault::range: return (48u<<4)|9u;
        case Fault::dense_cancel: return frame==0 ? 0 : (13183u<<4)|3u;''')
    source=replace_once(source,'            if(fault==Fault::none) {\n                uint64_t count=',
                        '            if(fault==Fault::none || (fault==Fault::dense_cancel && frame==0)) {\n                uint64_t count=')
    source=replace_once(source,'            } else {\n                uint64_t count=',
                        '''            } else if(fault==Fault::dense_cancel) {
                check(dense_cancelled && frame==1 && dense.matrices==0 &&
                      !dut.dense_valid && !dut.raw_accept && !dut.tile_valid,"failed to invalidate dense state");
            } else {
                uint64_t count=''')
    source=replace_once(source,'        dense.observe(dut,frame,',
                        '''        if(fault==Fault::dense_cancel && dut.dense_valid && !dut.dense_result_ready && !dense_cancelled) {
            dense_cancelled=true;
            cancel_next=true;
        }
        if(dense_cancelled && !cancel_next)
            check(!dut.dense_valid&&!dut.raw_accept&&!dut.dense_done,"stale dense output after cancel");
        dense.observe(dut,frame,''')
    source=replace_once(source,'} else check(frame==1,"fault advanced to next frame");',
                        '} else check(frame==(fault==Fault::dense_cancel?2u:1u),"fault advanced to next frame");')
    source=replace_once(source,'        check(fault==Fault::lost && !dut.rst_n,"expected reset after permanent response loss");',
                        '''        check(fault==Fault::dense_cancel && done && dense_cancelled,"expected dense cancellation");
        dut.rst_n=0; dut.mrv=0; dut.hrv=0;
        dense_cancelled=false;
        auto original_input=std::move(dense.input);
        dense=DenseScoreboard{};
        dense.input=std::move(original_input);''')
    start=source.index('            for(Fault fault:')
    end=source.index('        } else {',start)
    return source[:start]+'''            Run session(argv[1],argv[2],rate,Fault::dense_cancel);
            session.run();
            std::printf("PASS dense_cancel raw_before=%llu rq_before=%llu error_index=13183\\n",
                        (unsigned long long)session.dense.raw_codes,(unsigned long long)session.dense.rq_codes);
            session.recover_same_model();
            std::puts("PASS DENSE FAULT stalled-result cancel and same-model hard-reset recovery");
'''+source[end:]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    base=args.model.resolve()
    out=args.output.resolve()
    bindings=[base/n for n in ('observer.cpp','firmware.bin','arithmetic.sv','100.log')]
    assert 'kwt_rne_dense_right #' in (base/'arithmetic.sv').read_text()
    assert 'PASS DENSE cycles=' in (base/'100.log').read_text()
    if (base/'manifest.json').is_file():
        manifest=json.loads((base/'manifest.json').read_text())
        for path in bindings:
            assert sha(path)==manifest[path.name],path
    out.mkdir(parents=True)
    (out/'observer.cpp').write_text(observer((base/'observer.cpp').read_text()))
    model=base/'model'
    objects=[model/n for n in ('Vreference_top__ALL.a','verilated.o','verilated_threads.o')]
    def relative(p):
        return p.relative_to(ROOT).as_posix()
    rel=relative(out)
    source=' '.join(relative(p) for p in objects)
    frozen='testdata/input16_rtl_20261105/trim2_e203'
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'

    def linux(command,log):
        with (out/log).open('w') as fd:
            result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {command}'],
                                  stdout=fd,stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError((out/log).read_text(errors='replace')[-2500:])

    linux(f'g++ -std=c++17 -O2 -pthread -I{relative(model)} -I/usr/share/verilator/include '
          f'-I/usr/share/verilator/include/vltstd {rel}/observer.cpp {source} -o {rel}/observer','build.log')
    linux(f'{rel}/observer {relative(base/"firmware.bin")} {frozen} 6 faults','simulation.log')
    log=(out/'simulation.log').read_text()
    assert 'PASS DENSE FAULT' in log and 'PASS DENSE cycles=' in log
    evidence=dict(passed=True,cancelled_while_result_stalled=True,same_E203_model_reset=True,
                  post_reset_raw_codes=110592,post_reset_rq_codes=110592,mismatches=0,
                  source_sha256={relative(p):sha(p) for p in [Path(__file__),*objects,*bindings,
                      ROOT/'rtl/block_transfer/compact_dense_scoreboard.hpp']})
    (out/'verification.json').write_text(json.dumps(evidence,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(log,end='')


if __name__=='__main__':
    main()
