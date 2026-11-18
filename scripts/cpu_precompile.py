"""Python 3.6 CPU-only precompile provenance and nonblocking cache inspection."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT=Path('/path/to/project/kwt_soc_input16_metrics_595724b_tt_20261112')


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def check(root):
    contract=json.loads((root/'review_tools/cpu_precompile_v1/source_contract.json').read_text())
    for n,h in contract['sources'].items():assert sha(root/n)==h,'CPU_SOURCE_CHANGED '+n
    for p,h in contract['TT_libraries'].items():assert sha(Path(p))==h,'CPU_LIBRARY_CHANGED '+p
    assert sha(root/'review_tools/cpu_precompile_v1/cpu_precompile.tcl')==contract['Tcl_sha256'],'CPU_FLOW_CHANGED'
    return contract


def outputs(root):
    out=root/'build/cpu_precompile_v1'
    text=(out/'cpu_mapped.v').read_text(errors='replace')
    assert not re.search(r'\b(?:GTECH\w*|SELECT_OP\w*)\b',text),'CPU_UNMAPPED_NETLIST'
    macros=(out/'reports/macros.txt').read_text().splitlines()
    assert len(macros)==len(set(macros))==16,'CPU_PHYSICAL_MACROS_NOT_16'
    assert '.RET1N' in text,'CPU_SRAM_RET1N_MISSING'
    return dict(DDC_sha256=sha(out/'cpu_mapped.ddc'),Verilog_sha256=sha(out/'cpu_mapped.v'),
        physical_macros=16,source_contract_sha256=sha(root/'review_tools/cpu_precompile_v1/source_contract.json'))


def ready(root):
    check(root)
    saved=json.loads((root/'build/cpu_precompile_v1/receipt.json').read_text())
    assert saved==outputs(root),'CPU_CACHE_CHANGED'
    return saved


def status(root):
    if (root/'build/cpu_precompile_v1/receipt.json').is_file():
        ready(root);return 'READY'
    log=root/'build/cpu_precompile_v1.console.log'
    if log.is_file():
        with log.open('rb') as f:f.seek(max(0,log.stat().st_size-32768));tail=f.read().decode(errors='replace')
        if re.search(r'^(?:Error:|SOC_CPU_FATAL)',tail,re.M):return 'FAILED'
    p=root/'review_tools/cpu_precompile_v1/launch.json'
    if not p.is_file():return 'NOT_STARTED'
    pid=json.loads(p.read_text())['pid']
    try:
        proc=Path('/proc')/str(pid)
        if (proc/'cwd').resolve()!=root.resolve():return 'NOT_RUNNING'
        command=(proc/'cmdline').read_bytes()
        if b'cpu_precompile.tcl' not in command:return 'NOT_RUNNING'
    except (OSError,RuntimeError):return 'NOT_RUNNING'
    return 'RUNNING'


if __name__=='__main__':
    action=sys.argv[1]
    if action=='check':check(ROOT);print('CPU_SOURCES_VERIFIED')
    elif action=='attest':
        check(ROOT);result=outputs(ROOT)
        with (ROOT/'build/cpu_precompile_v1/receipt.tmp.json').open('x') as f:json.dump(result,f,indent=2)
        os.replace(str(ROOT/'build/cpu_precompile_v1/receipt.tmp.json'),str(ROOT/'build/cpu_precompile_v1/receipt.json'))
        print('CPU_CACHE_ATTESTED')
    elif action=='ready':ready(ROOT);print('CPU_CACHE_VERIFIED')
    elif action=='status':print(status(ROOT))
    else:raise SystemExit('bad action')
