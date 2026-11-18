"""Reproduce P0 -> P1-A -> P1-B -> P1-C and stop at architecture review 1."""
import argparse,json,subprocess,sys
from pathlib import Path
from local_tools import ROOT,Tools,SUFFIX,run,sha

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stage',choices=['all','check'],default='all');ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve()
    if a.stage=='all':
        assert not out.exists(),'Use a fresh output root';out.mkdir(parents=True)
        tests=out/'word_contract';tests.mkdir();exe=tests/('contract'+SUFFIX);tools=Tools()
        inputs=[ROOT/'tests/test_e203_word_contract.cpp',ROOT/'firmware/e203_experiments_20261104/word_access.h']
        run([*tools.cxx(),'-std=c++17','-O2','-fstrict-aliasing','-I'+str(inputs[1].parent),inputs[0],'-o',exe],tests,'compile')
        result=run([exe,ROOT/'testdata/reference_e203/parallel_20261103/classes_0_3'],tests,'contract');assert 'PASS aligned words=189328' in result
        (tests/'verification.json').write_text(json.dumps(dict(passed=True,words=189328,result=result,source_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in inputs}),indent=2))
        for factor,name in [('baseline','p0_baseline'),('null_cancel','p1a_null_cancel'),('aligned','p1b_aligned'),('misaligned','p1b_reject_misaligned'),('itcm','p1c_itcm')]:
            subprocess.run([sys.executable,str(ROOT/'scripts/run_e203_factors.py'),'--factor',factor,'--output',str(out/name)],cwd=ROOT,check=True)
    from check_e203_factors import check
    check(out)

if __name__=='__main__':main()
