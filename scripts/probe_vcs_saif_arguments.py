"""Python 3.6; tiny native VCS SAIF argument probe, no production edits."""
from pathlib import Path
import ast
import json
import subprocess
import sys

root=Path.cwd().resolve()
out=root/'review_tools/saif_argument_probe_v1'
assert not out.exists(), 'PRESERVE_EXISTING_SAIF_PROBE'
out.mkdir(parents=True)
source=r'''`timescale 1ns/1ps
module saif_probe_dut(input clk,output reg [3:0] q=0);
 always @(posedge clk) q<=q+1;
endmodule
module saif_probe;
 reg clk=0;always #5 clk=~clk;
 wire [3:0] q;saif_probe_dut dut(clk,q);
 reg [8191:0] packed_name;
 string string_name,folder;
 initial begin
  packed_name="packed.saif";string_name="string.saif";folder=".";
  $set_toggle_region(dut);$toggle_start;
  repeat(12)@(negedge clk);$toggle_stop;
  $display("PROBE_LITERAL");
  $toggle_report("literal.saif",1.0e-9,"saif_probe.dut");
  $display("PROBE_PACKED");
  $toggle_report(packed_name,1.0e-9,"saif_probe.dut");
  $display("PROBE_STRING");
  $toggle_report(string_name,1.0e-9,"saif_probe.dut");
  $display("PROBE_CONCAT");
  $toggle_report({folder,"/concat.saif"},1.0e-9,"saif_probe.dut");
  $finish;
 end
endmodule
'''
(out/'probe.sv').write_text(source)
vcs='/eda/synopsys/vcs/vcs_2020.03-SP2-6/bin/vcs'
with (out/'compile.log').open('x') as log:
    rc=subprocess.call([vcs,'-full64','-sverilog','-lca','-top','saif_probe','probe.sv','-o','simv'],cwd=str(out),stdout=log,stderr=subprocess.STDOUT)
if rc:
    print((out/'compile.log').read_text(errors='replace')[-6000:])
    raise SystemExit('SAIF_PROBE_COMPILE_FAILED')
with (out/'run.log').open('x') as log:
    rc=subprocess.call([str(out/'simv')],cwd=str(out),stdout=log,stderr=subprocess.STDOUT)
print((out/'run.log').read_text(errors='replace')[-8000:])
files={p.name:p.stat().st_size for p in out.iterdir() if 'saif' in p.name.lower()}
report=dict(simulator_exit=rc,files=files,actual_server_probe=True,not_task_power=True)
(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
print('SAIF_ARGUMENT_PROBE_RESULT '+json.dumps(report,sort_keys=True))
queue=root.parent/'kwt_soc_input16_metrics_595724b_tt_20261112/build/progress.json'
if queue.is_file():print('CURRENT_SOC_QUEUE '+queue.read_text())
