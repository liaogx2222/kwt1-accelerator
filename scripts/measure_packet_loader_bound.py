"""Actual fixed-profile loader RTL under unlimited zero-gap supply."""
import argparse
import json
import re
import sys
from pathlib import Path
from local_tools import ROOT,Tools,run,sha
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from validate_kwt1_r2 import artifacts


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args();out=args.output.resolve()
    assert not out.exists(),'New evidence directory';out.mkdir(parents=True)
    packets,_=artifacts()
    commands=[]
    for name,data in packets.items():
        path=out/(name+'.hex');path.write_text(''.join(f'{int.from_bytes(data[k:k+4],"little"):08x}\n' for k in range(0,len(data),4)))
        common=int(name=='common.bin');layer=0 if common else int(name[6:8])
        commands.append(f' send({common},{layer},"{path.as_posix()}",{len(data)//4});')
    tb='''module tb;
reg clk=0;always #5 clk=~clk;
reg rst_n=0,begin_valid=0,common_flag=0,valid=0,last=0;reg[3:0] layer=0;reg[31:0] data=0;
wire begin_ready,ready,loaded,error,active;wire[19:0] en,we;wire[239:0] addr;wire[319:0] wd;
kwt_packet_loader d(clk,rst_n,1'b1,begin_valid,begin_ready,common_flag,layer,valid,ready,data,last,loaded,error,active,en,we,addr,wd);
integer cycle=0,accepted=0,writes=0,extra=0;integer p;
always @(posedge clk)if(rst_n)begin
 cycle=cycle+1;if(valid&&ready)accepted=accepted+1;
 for(p=0;p<20;p=p+1)if(en[p]&&we[p])writes=writes+1;
 if(d.state==3)extra=extra+1;
end
reg[31:0] memory[0:15431];
task send(input integer common_value,lid,input string path,input integer words);
integer i,start,ac0,w0,e0,expected;
begin
 $readmemh(path,memory,0,words-1);
 @(negedge clk);if(!begin_ready)$fatal(1,"not idle");start=cycle;ac0=accepted;w0=writes;e0=extra;
 common_flag=common_value;layer=lid;begin_valid=1;
 @(posedge clk);#1;@(negedge clk);begin_valid=0;valid=1;data=memory[0];last=(words==1);i=0;
 while(i<words)begin
  @(posedge clk);if(ready)i=i+1;
  #1;@(negedge clk);
  if(i<words)begin data=memory[i];last=(i==words-1);end else begin valid=0;last=0;end
  if(error)$fatal(1,"loader error");
 end
 while(!loaded)begin @(posedge clk);#1;if(error)$fatal(1,"CRC/header error");end
 expected=2*words+(common_value?0:12352)+2;
 if(cycle-start!=expected||accepted-ac0!=words)$fatal(1,"cycle/count mismatch got=%0d expected=%0d",cycle-start,expected);
 $display("PACKET common=%0d layer=%0d words=%0d cycles=%0d extra=%0d writes=%0d",common_value,lid,words,cycle-start,extra-e0,writes-w0);
end endtask
initial begin
 repeat(3)@(posedge clk);@(negedge clk);rst_n=1;
'''+ '\n'.join(commands)+'''
 $display("PASS LOADER words=%0d writes=%0d",accepted,writes);$finish;
end
initial begin #10000000;$fatal(1,"watchdog");end
endmodule
'''
    path=out/'tb_loader.sv';path.write_text(tb)
    tools=Tools();sources=[ROOT/'rtl/v2/kwt_packet_loader.sv',ROOT/'rtl/v2/generated/kwt_profile.svh',Path(__file__)]
    run([tools.iverilog(),'-g2012','-I'+str(ROOT/'rtl/v2/generated'),'-s','tb','-o',out/'sim.vvp',path,sources[0]],out,'compile')
    log=run([tools.vvp(),out/'sim.vvp'],out,'simulation')
    rows=[dict(zip(['common','layer','words','cycles','extra','writes'],map(int,match))) for match in re.findall(r'PACKET common=(\d+) layer=(\d+) words=(\d+) cycles=(\d+) extra=(\d+) writes=(\d+)',log)]
    assert len(rows)==13 and 'PASS LOADER words=189328 writes=348224' in log
    total=sum(row['cycles'] for row in rows);assert total==526906
    result=dict(passed=True,actual_RTL=True,zero_gap_supply=True,packets=rows,total_loader_cycles=total,
        accepted_words=189328,SRAM_16bit_writes=348224,one_16x16_MAC_issue_candidate_plus_existing_serial_loader=362208+total,
        target_240_cycles=625000,current_core_loader_overlap=False,
        conclusion='Even ideal supply plus issue-only 16x16 does not meet 625k with existing non-overlapping loader; loading/banking/scheduling must also change',
        scope='fixed-profile standalone loader ideal service floor, no bus/CPU/source latency or final input/output costs')
    (out/'verification.json').write_text(json.dumps(result,indent=2));(out/'source_bindings.json').write_text(json.dumps({s.relative_to(ROOT).as_posix():sha(s) for s in sources},indent=2))
    (out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.is_file()},indent=2));print(json.dumps(result,indent=2))


if __name__=='__main__':main()
