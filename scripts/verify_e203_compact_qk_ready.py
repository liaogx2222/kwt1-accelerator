"""Relink the shared-QK reference model with an always-ready score sink."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from local_tools import ROOT, sha
from run_input16_e203_block import replace_once


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    base,out=args.model.resolve(),args.output.resolve();out.mkdir(parents=True)
    evidence=ROOT/'testdata/input16_rtl_20261105'
    firmware=evidence/'p3_e203_compact_ln2_v2/firmware.bin'
    frozen=evidence/'trim2_e203'
    model=base/'model'
    observer=base/'observer.cpp'
    old_log=base/'reuse.log'
    manifest=json.loads((base/'manifest.json').read_text())
    for path in (observer,old_log,base/'verification.json'):
        assert sha(path)==manifest[path.name],path
    baseline=json.loads((base/'verification.json').read_text())
    assert sha(firmware)==baseline['source_sha256'][firmware.relative_to(ROOT).as_posix()]
    new=out/observer.name
    new.write_text(replace_once(observer.read_text(),'dut.qk_score_ready=clocks%11>=4;', 'dut.qk_score_ready=1;'))
    # The original observer requires positive stalls. Keep that assertion in
    # the frozen parent and change it only in the copy used by this test.
    probe=ROOT/'rtl/block_transfer/compact_qk_integrated_probe.hpp'
    header=out/probe.name
    header.write_text(replace_once(probe.read_text(),'&&stalls>0','&&stalls==0'))
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    def rel(path):
        return path.relative_to(ROOT).as_posix()
    new.write_text(replace_once(new.read_text(),f'{cwd}/{rel(probe)}',f'{cwd}/{rel(header)}'))
    objects=[model/n for n in ('Vreference_top__ALL.a','verilated.o','verilated_threads.o')]
    object_args=' '.join(rel(p) for p in objects)
    before={rel(p):sha(p) for p in objects}
    def run(command,log):
        result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {command}'],
                              capture_output=True,text=True)
        text=result.stdout+result.stderr
        (out/log).write_text(text)
        assert result.returncode==0,(log,text[-2000:])
        return text
    run(f'g++ -std=c++17 -O2 -pthread -I{rel(model)} -I/usr/share/verilator/include '
        f'-I/usr/share/verilator/include/vltstd {rel(new)} {object_args} -o {rel(out/"observer")}','build.log')
    log=run(f'env -u KWT_QK_RELOAD KWT_DRAIN_READY=1 {rel(out/"observer")} {rel(firmware)} {rel(frozen)} 6 normal','simulation.log')
    def metrics(prefix):
        line=next(s for s in log.splitlines() if s.startswith(prefix))
        return {k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)}
    qk,dense,bank=(metrics(p) for p in ('PASS SHARED_QK ','PASS DENSE ','PASS BANKS '))
    original=baseline['cases']['reuse']
    assert qk['codes']==original['qk']['codes'] and qk['stalls']==0
    assert bank==original['bank']
    assert {rel(p):sha(p) for p in objects}==before
    report=dict(passed=True,qk=qk,dense=dense,bank=bank,baseline_cycles=original['dense']['cycles'],
                source_sha256={**before,**{rel(p):sha(p) for p in (Path(__file__),probe,header,new,observer,old_log,
                                firmware,base/'manifest.json',base/'verification.json')}})
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(log,end='')


if __name__=='__main__':
    main()
