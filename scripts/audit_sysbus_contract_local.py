"""Read-only route/source/committed-regression audit; no new RTL run claimed."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
def sha(b):return hashlib.sha256(b).hexdigest()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--project',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path);a=ap.parse_args();p=a.project.resolve();out=a.output.resolve()
    assert not out.exists();out.mkdir(parents=True)
    manifest=json.loads((p/'source_manifest.json').read_text())
    assert all(sha((p/n).read_bytes())==h for n,h in manifest['files'].items())
    mem=p/'cpu/e203/subsys/e203_subsys_mems.v'
    original=ROOT.parent/'e203_hbirdv2/rtl/e203/subsys/e203_subsys_mems.v'
    assert mem.read_bytes().replace(b'\r\n',b'\n')==original.read_bytes().replace(b'\r\n',b'\n')
    main=(p/'cpu/e203/subsys/e203_subsys_main.v').read_text()
    assert 'kwt_sysbus_arbiter3 system_bus_masters(' in main
    assert '.mem_icb_cmd_valid  (bus_icb_cmd_valid)' in main or re.search(r'\.mem_icb_cmd_valid\s*\(bus_icb_cmd_valid\)',main)
    top=(p/'soc/local_kwt_soc_joint.sv').read_text()
    assert 'kwt_cpu_nice_arbiter cpu_nice_arbiter(' not in top
    assert 'assign phy_valid=sysmem_icb_cmd_valid' in top
    ram=(p/'soc/kwt_soc_shared_sram.sv').read_text();ports=ram[ram.index('module kwt_soc_shared_sram'):ram.index('localparam PW')]
    assert not re.search(r'\bhost_(?:en|addr|wdata|ready)\b',ports)
    assert 'parameter DW = 32' in ports
    evidence=json.loads((ROOT/'manifest/sysbus_v1_first_release_20261113.json').read_text())
    raw_hash_checks={}
    paths=['testdata/sysbus_v1_20261113_rtl_v2/cold/run.log','testdata/sysbus_v1_20261113_rtl_v2/recovery/run.log']+[
        'testdata/sysbus_v1_20261113_other_classes/case_%02d/run.log'%i for i in range(1,12)]
    metrics=[]
    for n in paths:
        b=(ROOT/n).read_bytes();expected=evidence['evidence_sha256'][n]
        normalized=b.replace(b'\r\n',b'\n');forms=[b,normalized,normalized.replace(b'\n',b'\r\n')]
        assert expected in [sha(x) for x in forms],'committed report mismatch '+n
        text=b.decode();rows=re.findall(r'SOC_GATE_METRICS cycles=(\d+) params=(\d+) input_words=(\d+) output_words=(\d+) host_words=(\d+)',text)
        assert len(rows)==1 and list(map(int,rows[0]))==[2783869,189328,3168,1584,192508]
        assert 'mismatches=0' in text
        raw_hash_checks[n]=dict(working_bytes_sha256=sha(b),original_evidence_sha256=expected,EOL_only_normalization_required=sha(b)!=expected)
        metrics.append(dict(log=n,cycles=int(rows[0][0])))
    accuracy=json.loads((ROOT.parent/'arch60-input16/manifest/input16_fast_20261112.json').read_text())['accuracy']
    assert accuracy['validation_samples']==4445 and accuracy['integer_correct']==4345 and accuracy['accuracy_drop_pp']<=0.1
    result=dict(passed=True,audit_only=True,new_RTL_simulation_claimed=False,parent='2cf2dfa',
        original_System_Bus_decoder_canonical_sha256=sha(mem.read_bytes().replace(b'\r\n',b'\n')),
        original_decoder_unchanged=True,upstream_CPU_NICE_loader_arbitration=True,
        shared_SRAM_32bit_original_ICB_only=True,no_backend_arbiter=True,no_direct_SRAM_host_port=True,
        committed_twelve_cold_codes=76032,committed_recovery_codes=6336,committed_metric_rows=metrics,
        committed_log_hash_checks=raw_hash_checks,accuracy_inherited_from_unchanged_frozen_S16_profile=accuracy,
        changed_RTL=False,new_physical_frequency_area_power_energy_evidence=False,
        limits=['static source/route audit is not official interface acceptance',
                'prior Verilator two-state timed SV reports are not new four-state or mapped runs',
                'arbitrary new sample end-to-end scripts and official600 acceptance require separate complete delivery audit'])
    (out/'audit.json').write_text(json.dumps(result,indent=2)+'\n');print('PASS SOURCE/ROUTE AUDIT;13 committed successful task windows verified; no new RTL run claimed')

if __name__=='__main__':main()
