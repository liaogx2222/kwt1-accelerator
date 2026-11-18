"""Explicit no-software-ABORT steady diagnostic; does not replace baseline STA."""
import argparse,json,re,subprocess
from pathlib import Path
from local_tools import ROOT,sha
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True);rel=out.relative_to(ROOT).as_posix()
    base=ROOT/'testdata/nangate45_reference/sta_valid_20261104';summary=json.loads((base/'summary.json').read_text());assert summary['reference_analysis_executed']
    for name,digest in json.loads((base/'manifest.json').read_text()).items():assert sha(base/name)==digest,name
    script=(ROOT/'flow/nangate45_reference_sta.tcl').read_text();anchor='set out $::env(KWT_STA_OUTPUT)';assert script.count(anchor)==1
    script=script.replace(anchor,'# Diagnostic ONLY: software ABORT stays inactive throughout this mode.\nset_case_analysis 0 [get_pins _617031_/Q]\n'+anchor)
    (out/'steady.tcl').write_text(script)
    p=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc',f'cd /mnt/e/project/ChipCompetition/keyword-transformer && KWT_STA_NETLIST=testdata/nangate45_reference/sta_compat_20261104/mapped_simple.v KWT_STA_OUTPUT={rel} tools/opensta_reference/root/usr/bin/sta -exit {rel}/steady.tcl'],capture_output=True,text=True)
    text=p.stdout+p.stderr;(out/'execution.log').write_text(text);assert p.returncode==0 and 'REFERENCE_STA_FINISHED' in text and not re.search(r'^Error:',text,re.M),text[-3000:]
    def value(name):return float(re.search(r'^'+name+r' (\S+)',text,re.M)[1])
    report=dict(analysis_executed=True,scope='steady diagnostic ONLY; internal sw_abort output Q fixed0 in addition to base running-mode constants. Reset/abort transitions excluded. Does not replace failing baseline timing or signoff.',internal_case_pin='_617031_/Q',internal_case_net='sw_abort',register_data_pins=int(value('REGISTER_DATA_PINS')),timed_register_setup_paths=int(value('REG2REG_SETUP_PATHS')),worst_setup_slack_ns=value('REG2REG_WORST_SETUP_SLACK'),setup_TNS_ns=value('REG2REG_SETUP_TNS'),negative_setup_endpoints=int(value('REG2REG_NEGATIVE_SETUP_ENDPOINTS')),clock_period_ns=6.666667,ideal_clock=True,uncertainty_ns=0,parasitics=False,SRAM_timing=False,IO_delays=False,physical_signoff=False,baseline_summary_sha256=sha(base/'summary.json'),script_sha256=sha(Path(__file__)),SDC_Tcl_sha256=sha(out/'steady.tcl'))
    (out/'summary.json').write_text(json.dumps(report,indent=2));(out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2));print(json.dumps(report,indent=2),flush=True)
if __name__=='__main__':main()
