"""Test all 12 score-quantization profiles using the physical exp cache."""
import argparse
import json
from pathlib import Path
import subprocess

import numpy as np

from local_tools import ROOT, sha


def rne(value,divisor):
    q,r=divmod(value,divisor)
    return q+int(r>divisor-r or (r==divisor-r and q%2==1))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    out=parser.parse_args().output.resolve();out.mkdir(parents=True)
    rel=out.relative_to(ROOT).as_posix()
    params=ROOT/'testdata/accuracy_point1_20261104/input16_only/run/params/parameters.npz'
    common=ROOT/'testdata/input16_rtl_20261105/trim2_e203/common.bin.hex'
    def write(name,items,digits):
        (out/(name+'.hex')).write_text(''.join(f'{int(x)&((1<<(4*digits))-1):0{digits}x}\n' for x in items))
    data=np.load(params,allow_pickle=False)
    lut=list(map(int,data['exp_lut']))
    words=[int(x,16) for x in common.read_text().split()]
    assert words[48:]==lut[:4096] and lut[4096]==0
    write('exp',lut[:4096],8)
    rng=np.random.default_rng(20261106)
    scores=[];coeff=[];probs=[];indices=[]
    for layer in range(12):
        m=int(data[f'l{layer:02d}_score_m']);s=int(data[f'l{layer:02d}_score_s'])
        assert 0<m<2**32 and 0<s<64
        rows=[[0]*99,[-2**31]+[2**31-1]*98,[2**31-1]+[-2**31]*98,
              [int(x) for x in np.arange(-49,50,dtype=np.int64)*32768]]
        keys=rng.integers(-127,128,size=(99,64),dtype=np.int64)
        queries=rng.integers(-127,128,size=(4,64),dtype=np.int64)
        rows.extend((queries@keys.T).tolist())
        for row in rows:
            ix=[min(4096,rne((max(row)-x)*m,1<<s)) for x in row]
            values=[lut[x] for x in ix]
            denominator=sum(values)
            p=[rne(x*65535,denominator) for x in values]
            assert 65486<=sum(p)<=65584
            scores.extend(row);coeff.extend((m,s));probs.extend(p);indices.extend(ix)
    write('scores',scores,8);write('coefficients',coeff,8)
    write('probabilities',probs,4);write('indices',indices,4)
    rtl=ROOT/'rtl/block_transfer';trim=ROOT/'rtl/input16_trim2'
    sources=[rtl/n for n in ('kwt_compact_softmax_row.sv','kwt_compact_exp_cache.sv','tb_compact_softmax_row.sv')]
    sources.extend((trim/'kwt_iterative.sv',trim/'kwt_sram_sp.sv'))
    cwd='/mnt/e/project/ChipCompetition/keyword-transformer'
    def run(command,log):
        result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd {cwd} && {command}'],
                              capture_output=True,text=True)
        (out/log).write_text(result.stdout+result.stderr)
        assert result.returncode==0,(log,result.stdout,result.stderr)
        return result.stdout
    sv=' '.join(p.relative_to(ROOT).as_posix() for p in sources)
    run(f'iverilog -g2012 -DKWT_SIM -s tb_compact_softmax_row -o {rel}/test.vvp {sv}','build.log')
    result=run(f'vvp {rel}/test.vvp +root={rel}','simulation.log')
    assert 'PASS softmax rows=97 probabilities=9603 exp_indices=9603' in result
    report=dict(passed=True,profiles=12,rows=97,probability_codes=9603,exp_indices=9603,
                scope='standalone Softmax and actual compressed exp SRAM ports',mismatches=0,
                source_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in (Path(__file__),params,common,*sources)})
    (out/'verification.json').write_text(json.dumps(report,indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2))
    print(result,end='')


if __name__=='__main__':
    main()
