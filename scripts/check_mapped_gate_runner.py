"""Mock VCS tests cache/provenance contracts; never claims mapped function."""
import argparse
import ast
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zlib
from install_mapped_gate_runner import install

ROOT = Path(__file__).resolve().parents[1]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', required=True, type=Path)
    a = ap.parse_args()
    out = a.output.resolve()
    if out.exists():
        raise ValueError('fresh output required')
    out.mkdir(parents=True)
    bundle = ROOT/'deliverables/mapped_gate_runner_20261111'
    capsule = bundle/'mapped_gate_fix'
    m = json.loads((bundle/'transfer_manifest.json').read_text())
    parts = [re.search(r"write\('([^']+)'\)", l).group(1)
             for l in (bundle/'commands.csh.txt').read_text().splitlines()[:m['parts']]]
    data = zlib.decompress(base64.b64decode(''.join(parts)))
    assert data == (bundle/'mapped_gate_fix.tar.gz').read_bytes()
    assert hashlib.sha256(data).hexdigest() == m['sha256']
    project = out/'project'
    shutil.copytree(ROOT/'deliverables/rtl_v2_python_env_project_20261111/project', project)
    dc = project/'build/dc'
    dc.mkdir(parents=True)
    net = dc/'mapped.v'
    net.write_text('module kwt1_mmio;\n'+'\n'.join('RAMSP4096X16 u%d();' % i for i in range(20))+'\nendmodule\n')
    (dc/'netlist_manifest.json').write_text(json.dumps(dict(
        source_manifest_sha256=sha(project/'manifest.json'), netlist_sha256=sha(net))))
    source = json.loads((project/'manifest.json').read_text())['files']
    before = {n: sha(project/n) for n in source}
    net_before = sha(net)
    with contextlib.redirect_stdout(io.StringIO()):
        install(project, capsule)
        install(project, capsule)
    assert sha(project/'review_tools/run_mapped_gate.sh') == m['runner_sha256']
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
    def run(case, success=True):
        p = subprocess.run([bash, '-c', 'export PATH="$KWT_MOCK_BIN:$PATH"; source "$0" "$1"',
                            'review_tools/run_mapped_gate.sh', str(case)], cwd=project,
                           env=env, capture_output=True, text=True)
        (out/('case%d_%s.log' % (case, 'pass' if success else 'reject'))).write_text(p.stdout+p.stderr)
        assert (p.returncode == 0) == success, p.stdout+p.stderr
    run(0)
    run(1)
    model = project/'build/mapped_gate_v1/model'
    assert (model/'compile_calls').read_text().splitlines() == ['compile']
    first_log = project/'build/mapped_gate_v1/c0/run.log'
    first_sha = sha(first_log)
    run(0, False)
    assert sha(first_log) == first_sha
    original_model = models[0].read_bytes()
    models[0].write_bytes(original_model+b' CHANGED')
    run(2, False)
    assert not (project/'build/mapped_gate_v1/c2/run.log').exists()
    models[0].write_bytes(original_model)
    simv = model/'simv'
    simv.write_bytes(simv.read_bytes()+b'\n# TAMPER\n')
    run(3, False)
    assert not (project/'build/mapped_gate_v1/c3/run.log').exists()
    assert before == {n: sha(project/n) for n in source} and sha(net) == net_before
    ast.parse((capsule/'install.py').read_text(), feature_version=(3, 6))
    report = dict(passed=True, source_59_files_unchanged=True, netlist_unchanged=True,
                  transport_reconstruction=True, repeated_install=True, mock_two_cases_one_compile=True,
                  prior_case_preserved=True, changed_cell_model_cache_rejected=True,
                  modified_executable_rejected=True, legacy_check_saif_pairing=True,
                  python36_installer=True, actual_VCS_or_mapped_function=False)
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
