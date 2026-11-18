"""Generate independent 96-profile tile operands, RTL/gate same TB replay."""
import argparse
import json
import subprocess
from pathlib import Path
import numpy as np
from local_tools import ROOT,sha
import validate_competitive_components as component
from integer_model.event_arithmetic import signed_shift


def packed(a,bits):return sum((int(v)&((1<<bits)-1))<<(i*bits) for i,v in enumerate(np.asarray(a).reshape(-1)))
def dump(path,values,width):path.write_text(''.join(f'{int(v):0{width}x}\n' for v in values))


TB=r'''
module tb;
 localparam CASES=@CASES@,MACS=@MACS@,TAGS=CASES*64+64;
 reg clk=0;always #5 clk=~clk;reg rst_n=0;
 reg init_valid=0,init_bank=0,mac_valid=0,mac_bank=0,mac_unsigned_a=0,mac_shift8=0,mac_last=0;
 reg [511:0] init_bias;reg [127:0] mac_a,mac_b;
 reg read_valid=0,read_bank=0;reg [3:0] read_row,read_col;reg [15:0] read_tag;
 wire init_ready,mac_ready,read_ready,raw_valid;wire [127:0] raw_data;wire [15:0] raw_tag;
 reg release_valid=0,release_bank=0;wire release_ready;wire [1:0] empty,done;
 wire rq_ready,rq_resp_valid;wire [31:0] rq_data;wire rq_error;wire [15:0] rq_resp_tag;
 reg direct=0,direct_valid=0;reg [15:0] direct_tag;reg [127:0] direct_a;
 reg randomize=0,gate=1,rq_resp_ready=1;reg [31:0] random_state=32'h13579bdf;
 wire rq_valid=direct?direct_valid:(raw_valid&&gate);
 wire raw_ready=(!direct)&&gate&&rq_ready;
 wire [127:0] rq_a=direct?direct_a:raw_data;wire [15:0] rq_tag=direct?direct_tag:raw_tag;
 reg [511:0] bias_mem[0:CASES-1];reg [31:0] start_mem[0:CASES-1],len_mem[0:CASES-1];
 reg [127:0] a_mem[0:MACS-1],b_mem[0:MACS-1];reg [2:0] mode_mem[0:MACS-1];
 reg [127:0] m_mem[0:TAGS-1],expected_raw[0:TAGS-1],direct_mem[0:TAGS-1];
 reg [31:0] shift_mem[0:TAGS-1],expected_rq[0:TAGS-1];reg expected_error[0:TAGS-1];
 integer raw_seen[0:CASES-1],rq_seen[0:CASES-1];integer pass,passes=2,i,j,fd,cycles=0,raw_total=0,rq_total=0,bound_seen=0,handoffs=0,rq_handoffs=0;
 integer raw_stalls=0,rq_stalls=0,bank_overlap=0;reg checking=0;
 reg raw_held=0,rq_held=0;reg [143:0] old_raw;reg [48:0] old_rq;
 string root,vec;
 kwt_arithmetic16 dut(clk,rst_n,init_valid,init_ready,init_bank,init_bias,mac_valid,mac_ready,mac_bank,mac_unsigned_a,mac_shift8,mac_last,
 mac_a,mac_b,read_valid,read_ready,read_bank,read_row,read_col,read_tag,raw_valid,raw_ready,raw_data,raw_tag,
 release_valid,release_ready,release_bank,empty,done,rq_valid,rq_ready,rq_a,m_mem[rq_tag],shift_mem[rq_tag],rq_tag,
 rq_resp_valid,rq_resp_ready,rq_data,rq_error,rq_resp_tag);
 always @(negedge clk)begin
  random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
  gate=randomize?(random_state[2:0]!=0):1;rq_resp_ready=randomize?(random_state[5:3]>1):1;
 end
 always @(posedge clk)begin
  cycles=cycles+1;if(cycles>1000000)$fatal(1,"watchdog");
  if(!rst_n)begin raw_held=0;rq_held=0;end
  else if(checking)begin
   if(raw_held&&{raw_tag,raw_data}!==old_raw)$fatal(1,"raw changed under stall");
   if(rq_held&&{rq_resp_tag,rq_error,rq_data}!==old_rq)$fatal(1,"RQ changed under stall");
   raw_held=raw_valid&&!raw_ready;old_raw={raw_tag,raw_data};
   rq_held=rq_resp_valid&&!rq_resp_ready;old_rq={rq_resp_tag,rq_error,rq_data};
   if(raw_held)raw_stalls=raw_stalls+1;if(rq_held)rq_stalls=rq_stalls+1;
   if(raw_valid&&raw_ready)begin
    if(raw_data!==expected_raw[raw_tag])$fatal(1,"raw tag %d actual %h expected %h",raw_tag,raw_data,expected_raw[raw_tag]);
    raw_seen[raw_tag/64]=raw_seen[raw_tag/64]+1;raw_total=raw_total+1;
    $fdisplay(fd,"RAW %0d %0d %032h",pass,raw_tag,raw_data);
   end
   if(rq_resp_valid&&rq_resp_ready)begin
    if(rq_data!==expected_rq[rq_resp_tag]||rq_error!==expected_error[rq_resp_tag])$fatal(1,"RQ tag %d",rq_resp_tag);
    if(rq_resp_tag<CASES*64)rq_seen[rq_resp_tag/64]=rq_seen[rq_resp_tag/64]+1;else bound_seen=bound_seen+1;
    rq_total=rq_total+1;$fdisplay(fd,"RQ %0d %0d %08h %0d",pass,rq_resp_tag,rq_data,rq_error);
   end
   if(raw_valid&&raw_ready&&read_valid&&read_ready)handoffs=handoffs+1;
   if(rq_valid&&rq_ready&&rq_resp_valid&&rq_resp_ready)rq_handoffs=rq_handoffs+1;
   if(mac_valid&&mac_ready&&raw_valid&&raw_ready)bank_overlap=bank_overlap+1;
  end
 end
 task initialize(input integer c);
 begin
  @(negedge clk);init_bank=c%2;init_bias=bias_mem[c];init_valid=1;
  do @(posedge clk);while(!init_ready);
  @(negedge clk);init_valid=0;
 end endtask
 task compute(input integer c);
 integer n,at;
 begin
  initialize(c);
  for(n=0;n<len_mem[c];n=n+1)begin
   @(negedge clk);at=start_mem[c]+n;mac_a=a_mem[at];mac_b=b_mem[at];mac_bank=c%2;
   mac_unsigned_a=mode_mem[at][0];mac_shift8=mode_mem[at][1];mac_last=mode_mem[at][2];mac_valid=1;
   @(posedge clk);if(!mac_ready)$fatal(1,"MAC II=1/ownership");
  end
  @(negedge clk);mac_valid=0;
 end endtask
 task read_case(input integer c);
 integer g;
 begin
  for(g=0;g<64;g=g+1)begin
   @(negedge clk);read_bank=c%2;read_row=(g%4)*4;read_col=g/4;read_tag=c*64+g;read_valid=1;
   do @(posedge clk);while(!read_ready);
  end
  @(negedge clk);read_valid=0;
  wait(raw_seen[c]==64&&rq_seen[c]==64);
  @(negedge clk);release_bank=c%2;release_valid=1;
  do @(posedge clk);while(!release_ready);
  @(negedge clk);release_valid=0;
 end endtask
 initial begin
  if(!$value$plusargs("root=%s",root))$fatal(1,"root");if($value$plusargs("passes=%d",passes))begin end
  vec={root,"/vectors/"};
  $readmemh({vec,"bias.hex"},bias_mem);$readmemh({vec,"start.hex"},start_mem);$readmemh({vec,"length.hex"},len_mem);
  $readmemh({vec,"a.hex"},a_mem);$readmemh({vec,"b.hex"},b_mem);$readmemh({vec,"mode.hex"},mode_mem);
  $readmemh({vec,"m.hex"},m_mem);$readmemh({vec,"shift.hex"},shift_mem);$readmemh({vec,"raw.hex"},expected_raw);
  $readmemh({vec,"rq.hex"},expected_rq);$readmemh({vec,"error.hex"},expected_error);$readmemh({vec,"direct.hex"},direct_mem);
  fd=$fopen({root,"/observed.txt"},"w");
  for(pass=0;pass<passes;pass=pass+1)begin
   checking=0;rst_n=0;direct=0;direct_valid=0;read_valid=0;mac_valid=0;init_valid=0;randomize=0;
   repeat(3)@(negedge clk);rst_n=1;
   // Reset while a MAC buffer is ACTIVE. Old payload cannot be read afterward.
   initialize(0);@(negedge clk);mac_valid=1;mac_bank=0;mac_a=a_mem[0];mac_b=b_mem[0];mac_last=0;
   repeat(3)@(negedge clk);rst_n=0;mac_valid=0;repeat(2)@(negedge clk);rst_n=1;
   // Reset with RQ in flight; explicitly flush, then reject stale responses.
   direct=1;direct_tag=CASES*64;direct_a=direct_mem[CASES*64];direct_valid=1;
   @(negedge clk);direct_valid=0;rst_n=0;repeat(2)@(negedge clk);rst_n=1;
   repeat(6)begin @(negedge clk);if(rq_resp_valid||raw_valid||empty!==2'b11)$fatal(1,"stale after reset");end
   for(i=0;i<CASES;i=i+1)begin raw_seen[i]=0;rq_seen[i]=0;end
   bound_seen=0;checking=1;
   // Sixty-four consecutive requests establish II=1 with no sink stalls.
   for(i=0;i<64;i=i+1)begin
    @(negedge clk);direct_tag=CASES*64+i;direct_a=direct_mem[CASES*64+i];direct_valid=1;
    @(posedge clk);if(!rq_ready)$fatal(1,"RQ II=1");
   end
   @(negedge clk);direct_valid=0;wait(bound_seen==64);@(negedge clk);direct=0;randomize=1;
   for(j=0;j<CASES;j=j+2)begin
    compute(j);
    fork read_case(j); compute(j+1); join
    read_case(j+1);
   end
   @(negedge clk);checking=0;
  end
  if(handoffs==0||rq_handoffs==0||raw_stalls==0||rq_stalls==0||bank_overlap==0)$fatal(1,"missing stress coverage");
  $display("PASS cases=%0d passes=%0d raw_vectors=%0d rq_vectors=%0d handoffs=%0d rq_handoffs=%0d raw_stalls=%0d rq_stalls=%0d bank_overlap=%0d",CASES,passes,raw_total,rq_total,handoffs,rq_handoffs,raw_stalls,rq_stalls,bank_overlap);
  $fclose(fd);$finish;
 end
endmodule
'''


def vectors(out):
    x,p,_=component.fixture();st=component.reference_stages(x,p);cases=[];bias=[];starts=[];lengths=[];aa=[];bb=[];modes=[];raw=[];rq=[];mult=[];shifts=[];errors=[];direct=[]
    for layer in range(12):
        prefix=f'layer_{layer:02d}/';key=f'l{layer:02d}'
        for kind in ['q','k','v','o','fc1','fc2','qk','pv']:
            if kind in ['q','k','v','o','fc1','fc2']:
                source=('encoder_input' if layer==0 else f'layer_{layer-1:02d}/layernorm2_output') if kind in ['q','k','v'] else prefix+dict(o='attention_context',fc1='layernorm1_output',fc2='gelu_output')[kind]
                a=st[source][0,:16];w=p[key+'_'+kind+'_w'][:,:16];b=p[key+'_'+kind+'_b'][:16];mm=p[key+'_'+kind+'_m'][:16];ss=p[key+'_'+kind+'_s'][:16]
            elif kind=='qk':a=st[prefix+'q_projection'][0,:16];w=st[prefix+'k_projection'][0,:16].T;b=np.zeros(16,np.int32);mm=np.ones(16,np.int32);ss=np.zeros(16,np.int32)
            else:a=st[prefix+'attention_softmax'][0,:16];w=st[prefix+'v_projection'][0,:,:16];b=np.zeros(16,np.int32);mm=np.full(16,int(p[key+'_ctx_m']),np.int32);ss=np.full(16,int(p[key+'_ctx_s']),np.int32)
            goal=a.astype(np.int64)@w.astype(np.int64)+b;assert int(goal.min())>=-(1<<31) and int(goal.max())<(1<<31)
            starts.append(len(aa));bias.append(packed(b,32));planes=2 if a.dtype in [np.dtype('int16'),np.dtype('uint16')] else 1
            for plane in range(planes):
                for red in range(a.shape[1]):
                    aa.append(packed((a[:,red].astype(np.int64)>>(8*plane))&255,8));bb.append(packed(w[red],8))
                    unsigned=a.dtype==np.uint16 or (a.dtype==np.int16 and plane==0)
                    modes.append(int(unsigned)|(plane<<1)|(4 if plane==planes-1 and red==a.shape[1]-1 else 0))
            lengths.append(len(aa)-starts[-1]);cases.append(dict(layer=layer,operation=kind,reduction=a.shape[1],planes=planes))
            for col in range(16):
                for row in range(0,16,4):
                    values=goal[row:row+4,col];raw.append(packed(values,32));mult.append(packed(np.full(4,int(mm[col])),32));shifts.append(packed(np.full(4,int(ss[col])),8))
                    rq.append(packed([max(-127,min(127,signed_shift(int(v)*int(mm[col]),int(ss[col])))) for v in values],8));errors.append(0);direct.append(0)
    for i in range(64):
        patterns=[(5,1,1),(-5,1,1),(7,1,1),(-7,1,1),(2147483647,2147483647,48),(-2147483648,-2147483648,-2),(127,1,0),(-128,1,0),(0,1,-128),(1,1,127),(3,7,-2)]
        values=[patterns[(i+j)%len(patterns)] for j in range(4)];result=[];err=0
        for a,m,s in values:
            try:result.append(max(-127,min(127,signed_shift(a*m,s))))
            except OverflowError:result.append(0);err=1
        direct.append(packed([a for a,m,s in values],32));mult.append(packed([m for a,m,s in values],32));shifts.append(packed([s for a,m,s in values],8));rq.append(packed(result,8));raw.append(0);errors.append(err)
    folder=out/'vectors';folder.mkdir()
    for name,values,width in [('bias',bias,128),('start',starts,8),('length',lengths,8),('a',aa,32),('b',bb,32),('mode',modes,1),('m',mult,32),('shift',shifts,8),('raw',raw,32),('rq',rq,8),('error',errors,1),('direct',direct,32)]:dump(folder/(name+'.hex'),values,width)
    (out/'tb.sv').write_text(TB.replace('@CASES@',str(len(cases))).replace('@MACS@',str(len(aa))))
    return cases


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--mapped',type=Path);ap.add_argument('--passes',type=int,default=2);args=ap.parse_args();out=args.output.resolve();assert not out.exists();out.mkdir(parents=True);cases=vectors(out);rel=out.relative_to(ROOT).as_posix()
    source=ROOT/'rtl/experimental/kwt_arithmetic16.sv';libsrc=[ROOT/'rtl/micro/mul_pipe.sv',ROOT/'rtl/micro/rne_pipe.sv',source]
    if args.mapped:libsrc=[args.mapped.resolve()/'mapped.v',args.mapped.resolve()/'functional_cells.v']
    def run(cmd,name):
        r=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','--','bash','-lc','cd /mnt/e/project/ChipCompetition/keyword-transformer && '+cmd],capture_output=True,text=True)
        (out/(name+'.log')).write_text(r.stdout+r.stderr);assert r.returncode==0,(name,r.stdout[-1500:],r.stderr[-1000:]);return r.stdout
    names=' '.join(p.relative_to(ROOT).as_posix() for p in libsrc)
    run(f'iverilog -g2012 -s tb -o {rel}/test.vvp {names} {rel}/tb.sv','compile')
    text=run(f'vvp {rel}/test.vvp +root={rel} +passes={args.passes}','simulation');assert 'PASS cases=96' in text,text[-1000:]
    observed=0
    raw_expected=[int(s,16) for s in (out/'vectors/raw.hex').read_text().split()];rq_expected=[int(s,16) for s in (out/'vectors/rq.hex').read_text().split()];error_expected=[int(s,16) for s in (out/'vectors/error.hex').read_text().split()]
    for line in (out/'observed.txt').read_text().splitlines():
        fields=line.split();tag=int(fields[2]);value=int(fields[3],16)
        assert value==(raw_expected[tag] if fields[0]=='RAW' else rq_expected[tag])
        if fields[0]=='RQ':assert int(fields[4])==error_expected[tag]
        observed+=4
    assert observed==49408*args.passes
    report=dict(passed=True,profiles=cases,passes=args.passes,independently_checked_scalar_codes=observed,mismatches=0,RTL_or_mapped='mapped partition' if args.mapped else 'RTL partition',
        coverage='96 first-16x16 parameter tiles + 64 RQ boundary requests; dual-buffer MAC/read overlap, II1, stalls, same-edge handoffs, in-flight reset',
        full_encoder_RTL=False,SRAM_macros_in_partition=0,summary=text)
    (out/'verification.json').write_text(json.dumps(report,indent=2));sources=[Path(__file__),source,ROOT/'rtl/micro/mul_pipe.sv',ROOT/'rtl/micro/rne_pipe.sv',component.BASE/'run/params/parameters.npz',Path(component.__file__)]
    sources+=libsrc if args.mapped else []
    (out/'source_bindings.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p) for p in sources},indent=2));(out/'manifest.json').write_text(json.dumps({p.relative_to(out).as_posix():sha(p) for p in out.rglob('*') if p.is_file()},indent=2));print(json.dumps(dict(passed=True,profiles=96,codes=observed,mode=report['RTL_or_mapped']),indent=2))


if __name__=='__main__':main()
