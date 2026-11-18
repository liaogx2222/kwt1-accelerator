"""Run the actual mapped top on workspace-local OpenSTA; publish scoped results."""
import argparse,json,re,subprocess,time
from pathlib import Path
from local_tools import ROOT,sha

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--netlist',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists(),'New output required';out.mkdir(parents=True)
    rel=out.relative_to(ROOT).as_posix();tool=ROOT/'tools/opensta_reference/root/usr/bin/sta'
    assert tool.is_file();mapped=ROOT/'testdata/nangate45_reference/native_compat_20261104'
    for name,digest in json.loads((mapped/'manifest.json').read_text()).items():assert sha(mapped/name)==digest,name
    netlist=a.netlist.resolve();compat=json.loads((netlist.parent/'summary.json').read_text());assert compat['passed'] and compat['netlist_sha256']==sha(netlist) and compat['SRAM_macros']==20
    sources=[netlist,mapped/'mapped.v',ROOT/'rtl/v2/kwt_tech_sram_blackbox.sv',ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib',ROOT/'flow/nangate45_reference_sta.tcl',Path(__file__)]
    binding={p.relative_to(ROOT).as_posix():sha(p) for p in sources};(out/'source_bindings.json').write_text(json.dumps(binding,indent=2))
    command=['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd /mnt/e/project/ChipCompetition/keyword-transformer && KWT_STA_NETLIST={netlist.relative_to(ROOT).as_posix()} KWT_STA_OUTPUT={rel} tools/opensta_reference/root/usr/bin/sta -exit flow/nangate45_reference_sta.tcl']
    start=time.time();p=subprocess.run(command,capture_output=True,text=True);text=p.stdout+p.stderr;(out/'execution.log').write_text(text)
    assert p.returncode==0 and 'REFERENCE_STA_FINISHED' in text and not re.search(r'^Error:',text,re.M),(p.returncode,text[-4000:])
    def value(name):return float(re.search(r'^'+name+r' (\S+)',text,re.M)[1])
    for name,digest in binding.items():assert sha(ROOT/name)==digest,name
    report=dict(reference_analysis_executed=True,tool='OpenSTA 2.0.17 Ubuntu jammy binary, workspace-local on Ubuntu24.04 WSL',tool_sha256=sha(tool),tool_provenance=json.loads((ROOT/'tools/opensta_reference/provenance.json').read_text()),elapsed_seconds=time.time()-start,library='Nangate45 typical 1.10V 25C',clock_period_ns=6.666667,clock_mode='ideal, no propagated CTS',clock_uncertainty_ns=0.0,wire_parasitics='none',input_output_delays='unset; uncovered, not assigned zero',mode_constants=dict(rst_n=1,abort_hw=0,core_enable=1,mem_enable=1),register_data_pins=int(value('REGISTER_DATA_PINS')),register_output_pins=int(value('REGISTER_OUTPUT_PINS')),register_endpoint_setup_paths=int(value('REG2REG_SETUP_PATHS')),register_to_register_setup_worst_slack_ns=value('REG2REG_WORST_SETUP_SLACK'),register_to_register_setup_TNS_ns=value('REG2REG_SETUP_TNS'),register_negative_setup_endpoints=int(value('REG2REG_NEGATIVE_SETUP_ENDPOINTS')),SRAM_macros=20,SRAM_timing_models=False,scope='standard-cell register output to data pin paths under declared ideal reference assumptions; no complete timing signoff',excluded_or_pending=['SRAM timing arcs and macro-connected paths','external I/O delays/drives/loads','reset/abort transitions, recovery/removal','stall mode constraints','clock tree/uncertainty/parasitics','other PVT corners','SMIC40 remapping and verification'],complete_STA_signoff=False,physical_signoff=False,source_sha256=binding)
    (out/'summary.json').write_text(json.dumps(report,indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2));print(json.dumps(report,indent=2),flush=True)

if __name__=='__main__':main()
