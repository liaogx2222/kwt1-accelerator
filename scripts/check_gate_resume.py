"""Mock cache/argv regression only. No real VCS, RTL or gate simulation."""
import argparse
import ast
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from install_gate_resume import install
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    out=a.output.resolve()
    if out.exists():raise ValueError('fresh output required')
    out.mkdir(parents=True);project=out/'project'
    shutil.copytree(ROOT/'deliverables/reset_anchor_20261111/project',project)
    dc=project/'build/dc';dc.mkdir(parents=True);net=dc/'mapped.v'
    net.write_text('module kwt1_mmio;\n'+'\n'.join("RAMSP4096X16 u%d(.RET1N(1'b1));"%i for i in range(20))+'\nendmodule\n')
    (dc/'netlist_manifest.json').write_text(json.dumps(dict(source_manifest_sha256=sha(project/'manifest.json'),netlist_sha256=sha(net))))
    names=json.loads((project/'manifest.json').read_text())['files']
    before={n:sha(project/n) for n in names};net_before=sha(net)
    bin_dir = out/'mockbin'
    bin_dir.mkdir()
    def executable(name, text):
        p = bin_dir/name
        p.write_bytes(text.encode())
        p.chmod(0o755)
    executable('python3', '#!/bin/bash\nexec "'+Path(sys.executable).as_posix()+'" "$@"\n')
    # MSYS defaults to a '*' binary marker; Linux's original receipt uses two spaces.
    executable('sha256sum', '#!/bin/bash\nset -euo pipefail\n/usr/bin/sha256sum "$@" | sed '+"'s/ \\*/  /'"+'\n')
    executable('vcs', '''#!/bin/bash
set -eu
echo compile >> compile_calls
cat > simv <<'SIM'
#!/bin/bash
set -eu
c=0
d=.
for a in "$@"; do
  case "$a" in +CASE=*) c=${a#+CASE=};; +SAIF_DIR=*) d=${a#+SAIF_DIR=};; esac
done
echo 'MOCK SAIF, not real activity' > "$d/kwt1_gate_c$c.saif"
printf '%s\n' "$@" > "$d/argv.txt"
echo "KWT_SAIF_WRITTEN $d/kwt1_gate_c$c.saif"
echo "KWT_OUTPUT mismatches=0 of 1584  (case $c)"
echo "PASS KWT_GATE_TASK case=$c cycles=123"
SIM
chmod +x simv
''')
    pdk = out/'pdk'
    models = []
    for vt in ['HVT', 'LVT', 'RVT']:
        p = pdk/('SCC40NLL_VHSC40_%s_V0.1/SCC40NLL_VHSC40_%s_V0p1/verilog/scc40nll_vhsc40_%s.v' % (vt, vt, vt.lower()))
        p.parent.mkdir(parents=True)
        p.write_text('MOCK STANDARD CELL MODEL')
        models.append(p)
    env = dict(os.environ, KWT_PDK_ROOT=pdk.as_posix())
    env['PATH'] = str(bin_dir)+os.pathsep+env['PATH']
    env['KWT_MOCK_BIN'] = ('/'+bin_dir.drive[0].lower()+bin_dir.as_posix()[2:] if bin_dir.drive else str(bin_dir))
    bash = shutil.which('bash')
    assert bash
    def run(script,case,mode='a5',success=True):
        p=subprocess.run([bash,'-c','export PATH="$KWT_MOCK_BIN:$PATH"; source "$0" "$1" "$2"',script,str(case),mode],cwd=project,env=env,capture_output=True,text=True)
        (out/('case%d_%s_%s_%s.log'%(case,mode,Path(script).stem,'pass' if success else 'reject'))).write_text(p.stdout+p.stderr)
        assert (p.returncode==0)==success,p.stdout+p.stderr
    run('flow/run_gate.sh',0)
    cache=project/'build/gate/model';oldlog=project/'build/gate/c0/run.log';oldlogsha=sha(oldlog)
    with contextlib.redirect_stdout(io.StringIO()):install(project);install(project)
    script='review_tools/run_gate_resume.sh'
    for case,mode in [(0,'a5'),(1,'a5'),(0,'zero'),(0,'x')]:
        run(script,case,mode)
        suffix='' if mode=='a5' else '_'+mode
        path=project/('build/gate/c%d%s_resume_20261112'%(case,suffix))
        argv=(path/'argv.txt').read_text().splitlines();assert argv and all(argv)
        assert ('+KWT_SRAM_INIT_ZERO' in argv)==(mode=='zero')
        assert ('+KWT_SRAM_INIT_X' in argv)==(mode=='x')
        assert (path/'resume_wrapper.sha256').exists()
    run(script,0,success=False);assert sha(oldlog)==oldlogsha
    original=models[0].read_bytes();models[0].write_bytes(original+b' CHANGED')
    run(script,2,success=False);assert not (project/'build/gate/c2_resume_20261112/run.log').exists()
    models[0].write_bytes(original)
    sim=cache/'simv';sim.write_bytes(sim.read_bytes()+b'\n# TAMPER\n')
    run(script,3,success=False);assert not (project/'build/gate/c3_resume_20261112/run.log').exists()
    assert (cache/'compile_calls').read_text().splitlines()==['compile']
    assert before=={n:sha(project/n) for n in names} and sha(net)==net_before
    assert 'vcs -full64' not in (project/script).read_text()
    ast.parse((ROOT/'scripts/install_gate_resume.py').read_text(),feature_version=(3,6))
    report=dict(passed=True,default_zero_x_argv_verified=True,no_empty_array_expansion=True,extra_compiles=0,
        reused_cache_hash_checked=True,original_failure_directory_preserved=True,prior_resume_refused=True,
        cell_model_change_rejected=True,binary_change_rejected=True,frozen_63_sources_unchanged=True,
        netlist_unchanged=True,Python36_installer=True,actual_EDA_or_gate_simulation=False,
        old_server_Bash_executed=False,scope='local Bash/mock argv and source/cache guards only')
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
