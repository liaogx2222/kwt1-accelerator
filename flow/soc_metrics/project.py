"""Python 3.6 complete digital SoC source, netlist and activity provenance."""
import hashlib
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1]


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def check():
    m=json.loads((ROOT/'manifest.json').read_text())
    for n,h in m['files'].items():
        assert sha(ROOT/n)==h, 'SOC_SOURCE_CHANGED '+n
    print('SOC_FULL_SOURCE_VERIFIED '+m['RTL_revision'])
    return m


def receipt():
    p=ROOT/'build/dc/mapped.v';text=p.read_text(errors='replace')
    assert not re.search(r'\b(?:GTECH\w*|SELECT_OP\w*)\b',text), 'UNMAPPED_SOC_NETLIST'
    # A hierarchical module definition may be instantiated more than once.
    # Count physical hierarchical instances from DC, not textual definitions.
    inventory=ROOT/'build/dc/reports/macro_instances.txt'
    names=inventory.read_text().splitlines()
    assert len(names)==100 and len(set(names))==100,'SOC_PHYSICAL_MACROS_NOT_100'
    assert re.search(r'\bRAMSP4096X16\b',text) and '.RET1N' in text,'SOC_SRAM_REFERENCE_MISSING'
    return dict(manifest_sha256=sha(ROOT/'manifest.json'),netlist_sha256=sha(p),
        frozen_accelerator_receipt_sha256=sha(ROOT/'frozen_accel/input.json'),macro_inventory_sha256=sha(inventory))


def netlist():
    check();assert json.loads((ROOT/'build/dc/receipt.json').read_text())==receipt(), 'SOC_NETLIST_CHANGED'
    print('SOC_FULL_NETLIST_VERIFIED '+receipt()['netlist_sha256'])


def activity():
    netlist();run=ROOT/'build/gate/cold'
    proof=json.loads((run/'inputs.json').read_text())
    assert proof['netlist_sha256']==receipt()['netlist_sha256'], 'SOC_SAIF_WRONG_NETLIST'
    assert proof['manifest_sha256']==sha(ROOT/'manifest.json'), 'SOC_SAIF_WRONG_SOURCE'
    text=(run/'run.log').read_text(errors='replace')
    assert 'PASS SOC_INPUT16_GATE recovery=0' in text and 'mismatches=0' in text, 'SOC_GATE_NOT_PASSED'
    p=run/'task.saif';assert p.stat().st_size>0, 'EMPTY_SOC_SAIF'
    assert json.loads((run/'result.json').read_text())['saif_sha256']==sha(p), 'SOC_SAIF_CHANGED'
    print('SOC_FULL_ACTIVITY_VERIFIED '+sha(p))


if __name__=='__main__':
    action=sys.argv[1]
    if action=='check':check()
    elif action=='attest':
        check()
        with (ROOT/'build/dc/receipt.json').open('x') as f:json.dump(receipt(),f,indent=2)
    elif action=='check-netlist':netlist()
    elif action=='check-activity':activity()
    else:raise SystemExit('bad action')
