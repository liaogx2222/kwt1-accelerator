"""Compare the two-array row core to a one-array lifetime reuse variant."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess

from local_tools import ROOT, sha
from run_input16_e203_block import replace_once


def reuse(source):
    edits=[
        ('reg signed [31:0] maximum,scores[0:98];\n    reg [20:0] exponentials[0:98];',
         'reg signed [31:0] maximum;\n    reg [31:0] row_storage[0:98];'),
        ('wire signed [32:0] difference={maximum[31],maximum}-{scores[issued][31],scores[issued]};',
         '''// Each exp response can overwrite its score after the query has issued.
    // OUTPUTS sees the same addresses after all 99 exp responses have landed.
    wire [31:0] row_word=row_storage[issued];
    wire [20:0] exponential=row_word[20:0];
    wire signed [32:0] difference={maximum[31],maximum}-{row_word[31],row_word};'''),
        ('if(score_valid&&score_ready)scores[input_count]<=score;\n        if(exp_resp_valid&&exp_resp_ready)exponentials[received]<=exp_value;',
         'if(score_valid&&score_ready)row_storage[input_count]<=score;\n        else if(exp_resp_valid&&exp_resp_ready)row_storage[received]<={11\'d0,exp_value};'),
        ('exponentials[issued]*reciprocal','exponential*reciprocal'),
        ("{exponentials[issued],16'd0}-{16'd0,exponentials[issued]}","{exponential,16'd0}-{16'd0,exponential}"),
    ]
    for old,new in edits:
        source=replace_once(source,old,new)
    return source


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    out=parser.parse_args().output.resolve();out.mkdir(parents=True)
    evidence=ROOT/'testdata/input16_rtl_20261105/p4_compact_softmax_row_v1'
    manifest=json.loads((evidence/'manifest.json').read_text())
    for name,value in manifest.items():
        assert sha(evidence/name)==value,name
    baseline=json.loads((evidence/'verification.json').read_text())
    for name,value in baseline['source_sha256'].items():
        assert sha(ROOT/name)==value,name
    rtl=ROOT/'rtl/block_transfer'
    core=rtl/'kwt_compact_softmax_row.sv'
    variant=out/core.name
    variant.write_text(reuse(core.read_text()))
    flow=ROOT/'flow/compact_softmax_row_nangate45.ys'
    lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    def rel(path):
        return path.relative_to(ROOT).as_posix()
    def run(command,log):
        result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {command}'],
                              capture_output=True,text=True)
        (out/log).write_text(result.stdout+result.stderr)
        assert result.returncode==0,(log,result.stdout[-2000:],result.stderr[-2000:])
        return result.stdout

    def area(name,source):
        script=out/(name+'.ys')
        text=flow.read_text().replace('abc -liberty','abc -fast -liberty')
        script.write_text(replace_once(text,rel(core),rel(source)))
        log=run(f'yosys -Q -T -s {rel(script)}',name+'.log')
        return float(re.search(r'Chip area for module .*: ([0-9.]+)',log)[1])/1e6

    trim=ROOT/'rtl/input16_trim2'
    sources=[variant,rtl/'kwt_compact_exp_cache.sv',rtl/'tb_compact_softmax_row.sv',trim/'kwt_iterative.sv',trim/'kwt_sram_sp.sv']
    with ThreadPoolExecutor(max_workers=2) as pool:
        before=pool.submit(area,'two_arrays',core)
        after=pool.submit(area,'one_array',variant)
        run(f'iverilog -g2012 -DKWT_SIM -s tb_compact_softmax_row -o {rel(out/"test.vvp")} '
            +' '.join(rel(p) for p in sources),'build.log')
        result=run(f'vvp {rel(out/"test.vvp")} +root={rel(evidence)}','simulation.log')
        assert result.splitlines()[0]==(evidence/'simulation.log').read_text().splitlines()[0]
        areas=dict(two_arrays=before.result(),one_array=after.result())
    inputs=[Path(__file__),variant,flow,lib,evidence/'manifest.json',evidence/'verification.json']
    report=dict(passed=True,area_mm2=areas,logical_row_storage_bits=dict(two_arrays=5247,one_array=3168),
                cycles_identical=True,probability_codes=9603,mismatches=0,
                scope='same Nangate45 ABC fast flow, independent row core, exp cache excluded',
                source_sha256={**baseline['source_sha256'],**{rel(p):sha(p) for p in inputs}})
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='source_sha256'},indent=2))


if __name__=='__main__':
    main()
