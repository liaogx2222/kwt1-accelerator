"""Record installed tool versions/hashes without installing or changing tools."""
import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    records={}
    for name,args in [('yosys',['-V']),('yosys-abc',['-c','version']),('iverilog',['-V']),('verilator',['--version']),('g++',['--version']),('make',['--version'])]:
        resolved=subprocess.check_output(['wsl.exe','-d','Ubuntu-24.04','--','which',name],text=True).strip()
        digest=subprocess.check_output(['wsl.exe','-d','Ubuntu-24.04','--','sha256sum',resolved],text=True).split()[0]
        result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--',name,*args],text=True,capture_output=True);assert result.returncode==0,(name,result.stderr)
        (out/(name.replace('+','p')+'.txt')).write_text(result.stdout+result.stderr)
        records[name]=dict(path=resolved,sha256=digest,version_output=result.stdout[:500])
    sta=ROOT/'tools/opensta_reference/root/usr/bin/sta';rel='/mnt/e/project/ChipCompetition/keyword-transformer/'+sta.relative_to(ROOT).as_posix()
    result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--',rel,'-version'],text=True,capture_output=True);assert result.returncode==0;records['OpenSTA']=dict(path=sta.relative_to(ROOT).as_posix(),sha256=sha(sta),version_output=result.stdout+result.stderr)
    records['Python']=dict(version=sys.version,executable=sys.executable,sha256=sha(Path(sys.executable)));records['NumPy']=dict(version=np.__version__)
    report=dict(passed=True,tools=records,host=platform.platform(),scope='installed executable identity; not a portable binary distribution or physical-library signoff')
    (out/'verification.json').write_text(json.dumps(report,indent=2));sources=[Path(__file__),ROOT/'requirements-r1r2.lock',ROOT/'third_party/nangate45_reference/PROVENANCE.json']
    (out/'source_bindings.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p) for p in sources},indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2));print(json.dumps(dict(passed=True,tools=list(records)),indent=2))


if __name__=='__main__':main()
