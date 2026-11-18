"""Compare the exact bounded radix-4 reciprocal with the legacy divider."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess

from local_tools import ROOT, sha
from run_input16_e203_block import replace_once


def specialize(source):
    start=source.index('    wire [63:0] div_numerator=')
    end=source.index('\n\n',start)
    return source[:start]+'''    assign quotient[63:28]=0;
    kwt_compact_softmax_recip divider(clk,live,state==DIV_REQ,div_ready,denominator,
                                     div_valid,state==DIV_WAIT,quotient[27:0],div_error);'''+source[end:]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    out=parser.parse_args().output.resolve();out.mkdir(parents=True)
    evidence=ROOT/'testdata/input16_rtl_20261105'
    fixture=evidence/'p4_compact_softmax_row_v1'
    compact=evidence/'p4_compact_softmax_storage_v2'
    b_flow=evidence/'p4_compact_softmax_from_b_v1'
    for folder in (fixture,compact,b_flow):
        manifest=json.loads((folder/'manifest.json').read_text())
        for name,digest in manifest.items():
            assert sha(folder/name)==digest,name
    rtl=ROOT/'rtl/block_transfer';trim=ROOT/'rtl/input16_trim2'
    lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    old_core=compact/'kwt_compact_softmax_row.sv'
    core=out/old_core.name
    core.write_text(specialize(old_core.read_text()))
    reciprocal=rtl/'kwt_compact_softmax_recip.sv'
    bench=b_flow/'tb_compact_softmax_row.sv'
    common=[rtl/'kwt_compact_qk_score_store.sv',rtl/'kwt_compact_exp_cache.sv',trim/'kwt_sram_sp.sv']
    iterative=trim/'kwt_iterative.sv'
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    def rel(path):
        return path.relative_to(ROOT).as_posix()
    def run(command,log):
        result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {command}'],
                              capture_output=True,text=True)
        text=result.stdout+result.stderr
        (out/log).write_text(text)
        assert result.returncode==0,(log,text[-2000:])
        return text
    def area(name,sources):
        script=out/(name+'.ys')
        script.write_text(f'''read_verilog -sv {' '.join(rel(p) for p in sources)}
synth -top kwt_compact_softmax_row -flatten -noabc -noshare
read_liberty -lib {rel(lib)}
dfflibmap -liberty {rel(lib)}
abc -fast -liberty {rel(lib)}
clean
check -assert
stat -liberty {rel(lib)}
''')
        text=run(f'yosys -Q -T -s {rel(script)}',name+'.log')
        return float(re.search(r'Chip area for module .*: ([0-9.]+)',text)[1])/1e6

    with ThreadPoolExecutor(max_workers=2) as pool:
        legacy=pool.submit(area,'iterative',[old_core,iterative])
        optimized=pool.submit(area,'radix4',[core,reciprocal])
        run(f'iverilog -g2012 -DKWT_SIM -s tb_compact_softmax_row -o {rel(out/"test.vvp")} '
            +' '.join(rel(p) for p in (bench,core,reciprocal,*common)),'build.log')
        text=run(f'vvp {rel(out/"test.vvp")} +root={rel(fixture)}','simulation.log')
        match=re.search(r'PASS B softmax rows=97 probabilities=9603 exp_indices=9603 cycles=(\d+) max_row=(\d+) stalls=(\d+) cancel=1',text)
        assert match,text
        areas=dict(iterative=legacy.result(),radix4=optimized.result())
    prior=json.loads((b_flow/'verification.json').read_text())
    assert int(match[1])<prior['cycles']
    inputs=[Path(__file__),bench,old_core,core,reciprocal,iterative,*common,lib,
            *[d/'manifest.json' for d in (fixture,compact,b_flow)]]
    report=dict(passed=True,rows=97,probabilities=9603,mismatches=0,area_mm2=areas,
                cycles=int(match[1]),max_row=int(match[2]),stalls=int(match[3]),baseline_cycles=prior['cycles'],
                baseline_max_row=prior['max_row'],baseline_stalls=prior['stalls'],integrated_E203=False,
                scope='same B and exp SRAM, isolated row kernel Nangate45 ABC fast area',
                source_sha256={rel(p):sha(p) for p in inputs})
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(text,end='')


if __name__=='__main__':
    main()
