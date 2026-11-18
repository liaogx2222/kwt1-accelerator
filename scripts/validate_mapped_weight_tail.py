"""Exhaustive address and read/hold contract test of the mapped SRAM selector."""
import argparse
import json
import subprocess
from pathlib import Path
from local_tools import ROOT,sha


TB='''
module kwt_tech_sram_1024x16(input clk,en,we,input [9:0] addr,input [15:0] wdata,output reg [15:0] rdata);
 reg [15:0] mem[0:1023];
 always @(posedge clk)if(en)begin if(we)mem[addr]<=wdata;else rdata<=mem[addr];end
endmodule
module tb;
 reg clk=0,en=0,we=0;reg [11:0] addr;reg [15:0] wdata;wire [15:0] rdata;
 reg [15:0] golden[0:2047],expected;reg valid=0;
 integer reads=0,writes=0,idles=0;
 kwt_weight_2048x16 dut(.clk(clk),.en(en),.we(we),.addr(addr),.wdata(wdata),.rdata(rdata));
 task step(input integer enabled,wr,location,data);
 begin
  clk=0;en=enabled;we=wr;addr=location;wdata=data;#2;
  if(en&&we)begin golden[addr]=wdata;writes=writes+1;end
  else if(en)begin expected=golden[addr];valid=1;reads=reads+1;end
  else idles=idles+1;
  clk=1;#2;if(valid&&rdata!==expected)$fatal(1,"address=%d en=%d we=%d expected=%h got=%h",addr,en,we,expected,rdata);
 end endtask
 initial begin
  for(integer i=0;i<2048;i++)step(1,1,i,i^16'hb5c9);
  for(integer i=0;i<2048;i++)begin
   step(1,0,(i*1031)%2048,0);
   step(0,i[0],(i*1023)%2048,i);
   if(i%17==0)begin step(1,1,(i*127)%2048,i^16'hfedc);step(1,0,(i*127)%2048,0);end
  end
  step(1,0,1023,0);step(1,0,1024,0);step(1,0,2047,0);step(1,0,0,0);
  $display("PASS all 2048 words reads=%0d writes=%0d idles=%0d",reads,writes,idles);$finish;
 end
endmodule
'''


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.resolve();assert not out.exists();out.mkdir(parents=True);rel=out.relative_to(ROOT).as_posix();leaf=ROOT/'testdata/input16_rtl_20261105/trim_leaf/leaf.json';lib=ROOT/'third_party/nangate45_reference/lib/NangateOpenCellLibrary_typical.lib'
    for f,h in json.loads((leaf.parent/'manifest.json').read_text()).items():assert sha(leaf.parent/f)==h
    (out/'tb.sv').write_text(TB);(out/'emit.ys').write_text(f'''read_json {leaf.relative_to(ROOT).as_posix()}
write_verilog -noattr -noexpr {rel}/leaf.v
design -reset
read_liberty -ignore_miss_func -ignore_miss_dir {lib.relative_to(ROOT).as_posix()}
write_verilog -noattr {rel}/cells.v
''')
    def run(cmd,name):
        p=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc','cd /mnt/e/project/ChipCompetition/keyword-transformer && '+cmd],capture_output=True,text=True);(out/(name+'.log')).write_text(p.stdout+p.stderr);assert p.returncode==0,(name,p.stdout[-1000:],p.stderr[-1000:]);return p.stdout
    run(f'yosys -Q -T -s {rel}/emit.ys','emit');run(f'iverilog -g2012 -s tb -o {rel}/test.vvp {rel}/tb.sv {rel}/leaf.v {rel}/cells.v','compile');result=run(f'vvp {rel}/test.vvp','simulation');assert 'PASS all 2048 words' in result
    (out/'verification.json').write_text(json.dumps(dict(passed=True,gate_scope='mapped 2x1024 selector only, same-library cells and synchronous SRAM functional contract',all_2048_addresses=True,hold_on_idle_and_write=True,result=result),indent=2));bound=[Path(__file__),leaf,lib]
    (out/'source_bindings.json').write_text(json.dumps({f.relative_to(ROOT).as_posix():sha(f) for f in bound},indent=2));(out/'manifest.json').write_text(json.dumps({f.name:sha(f) for f in out.iterdir() if f.is_file()},indent=2));print(result)


if __name__=='__main__':main()
