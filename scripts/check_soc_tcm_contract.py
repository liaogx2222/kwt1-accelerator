"""Four-state directed comparison against the inherited E203 RAM read contract."""
import argparse
import json
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    out=a.output.resolve();assert not out.exists();out.mkdir(parents=True)
    original=(ROOT/'deliverables/soc_joint_resetguard_20261111/project/cpu/e203/general/sirv_sim_ram.v').read_text()
    (out/'original.v').write_text(original.replace('module sirv_sim_ram','module sirv_original_ram',1))
    tb='''`timescale 1ns/1ps
module tb_tcm;
 reg clk=0,cs=0,we=0;always #5 clk=~clk;
 reg[13:0]addr=0;reg[63:0]data=0;reg[7:0]mask=0;
 wire[63:0]a,b;wire[31:0]c,d;integer i,j,reads=0;reg[31:0]rng=32'h51c9ba73;
 sirv_sim_ram #(.DP(8192),.AW(13),.DW(64),.MW(8),.FORCE_X2ZERO(0)) itcm(clk,data,addr[12:0],cs,we,mask,a);
 sirv_original_ram #(.DP(8192),.AW(13),.DW(64),.MW(8),.FORCE_X2ZERO(0)) itcm_ref(clk,data,addr[12:0],cs,we,mask,b);
 sirv_sim_ram #(.DP(16384),.AW(14),.DW(32),.MW(4),.FORCE_X2ZERO(0)) dtcm(clk,data[31:0],addr,cs,we,mask[3:0],c);
 sirv_original_ram #(.DP(16384),.AW(14),.DW(32),.MW(4),.FORCE_X2ZERO(0)) dtcm_ref(clk,data[31:0],addr,cs,we,mask[3:0],d);
 function[13:0]location(input integer n);begin
 case(n%8)0:location=0;1:location=1;2:location=4094;3:location=4095;4:location=4096;5:location=8191;6:location=8192;default:location=16383;endcase
 end endfunction
 task cycle(input valid,input write,input[13:0]ad,input[63:0]value,input[7:0]wm);
 begin @(negedge clk);cs=valid;we=write;addr=ad;data=value;mask=wm;
 @(posedge clk);#1;if(valid&&!write)begin
  if(a!==b||c!==d)$fatal(1,"TCM_READ_MISMATCH addr=%0d actual64=%h expected64=%h actual32=%h expected32=%h",ad,a,b,c,d);
  reads=reads+1;
 end end endtask
 initial begin
 for(i=0;i<8;i=i+1)cycle(1,1,location(i),64'hf10e728a9643bd50+i,8'hff);
 for(i=0;i<4096;i=i+1)begin
  rng=(rng<<1)^(rng[31]?32'h04c11db7:0);
  cycle(1,i%3!=0,location(rng[2:0]),{rng,~rng},rng[15:8]);
  if(i%7==0)cycle(0,1,location(i),64'hdeadbeefbeefdead,8'hff);
 end
 for(i=0;i<8;i=i+1)cycle(1,0,location(i),0,0);
 $display("PASS TCM_CONTRACT reads=%0d widths=32,64 pages=2,4 masked_writes=1",reads);$finish;
 end
endmodule
'''
    (out/'tb.sv').write_text(tb)
    iv=Path('C:/iverilog/bin/iverilog.exe');vvp=iv.with_name('vvp.exe')
    commands=[[str(iv),'-g2012','-s','tb_tcm','-o',str(out/'test.vvp'),str(ROOT/'flow/soc_metrics/sirv_sim_ram.v'),
        str(out/'original.v'),str(ROOT/'deliverables/reset_anchor_20261111/project/flow/sram_contract_ret1n.v'),str(out/'tb.sv')],
        [str(vvp),str(out/'test.vvp')]]
    for n,cmd in enumerate(commands):
        p=subprocess.run(cmd,capture_output=True,text=True);(out/('%d.log'%n)).write_text(p.stdout+p.stderr)
        assert p.returncode==0,str(out/('%d.log'%n))
    assert 'PASS TCM_CONTRACT' in (out/'1.log').read_text()
    result=dict(passed=True,four_state=True,widths=[32,64],depths=[16384,8192],byte_masks=True,
        page_boundaries=True,disabled_write_requests=True,comparison='inherited E203 sirv_sim_ram selected-read behavior only; write/idle output excluded',
        actual_vendor_timing_model=False)
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print((out/'1.log').read_text())


if __name__=='__main__':main()
