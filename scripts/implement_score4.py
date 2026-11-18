"""Stripe exact QK scores across dead Q-weight SRAM banks, four rows/clock."""
from pathlib import Path
import hashlib
import subprocess

ROOT=Path(__file__).resolve().parents[1]
PARENT='9476619b7c85d8b5806744478a3419d8e5965015'
def once(s,old,new):
    assert s.count(old)==1,(s.count(old),old[:90]);return s.replace(old,new)

if __name__=='__main__':
    out=ROOT/'rtl/score4_opt/kwt_layer_banked.sv';assert not out.exists()
    raw=subprocess.check_output(['git','show',PARENT+':rtl/dense_overlap/kwt_layer_banked.sv'],cwd=ROOT)
    assert hashlib.sha256(raw).hexdigest()=='8395900e0966c1fed3a99ddc853f36a70ff783b91c44343571ef63766ebe9d5e'
    s=raw.decode();s=once(s,'// C[2048:2839] holds one 8x99 S32 score block. All bulk tensors use 20 SP macros.',
        '// Dead Q-weight banks0..7, address0..197, hold one8x99 S32 score block.\n// Four row pairs provide four32-bit score stores/clock. Same20 SP macros.')
    s=once(s,' reg [12:0] exp_index;',
        ' wire [31:0]score_rdata=mem_rdata[(norm_row[1:0]*32)+:32];\n reg [12:0] exp_index;')
    start=s.index('   Q_STORE:if(store_index%16<valid_keys)begin');end=s.index('   SM_RQ:if(math_take',start)
    s=s[:start]+'''   Q_STORE:for(j=0;j<4;j=j+1)if(4*store_index[4]+j<rows)begin
    // Q/K/V are fully materialized. Only dead Q weights0..197 are reused;
    // O768+, FC11024+, FC22048+ and all coefficient banks remain intact.
    mem_en[2*j]=1;mem_en[2*j+1]=1;mem_we[2*j]=1;mem_we[2*j+1]=1;
    mem_addr[2*j*12+:12]=(store_index[4]?99:0)+kg*16+store_index[3:0];
    mem_addr[(2*j+1)*12+:12]=(store_index[4]?99:0)+kg*16+store_index[3:0];
    mem_wdata[2*j*16+:16]=acc[((4*store_index[4]+j)*16+store_index[3:0])*32+:16];
    mem_wdata[(2*j+1)*16+:16]=acc[((4*store_index[4]+j)*16+store_index[3:0])*32+16+:16];
   end
   S_LOAD,S_CAPTURE:if(state==S_LOAD||ch<98)begin
    bank_index=2*norm_row[1:0];mem_en[bank_index]=1;mem_en[bank_index+1]=1;
    mem_addr[bank_index*12+:12]=(norm_row[2]?99:0)+ch+(state==S_CAPTURE);
    mem_addr[(bank_index+1)*12+:12]=(norm_row[2]?99:0)+ch+(state==S_CAPTURE);
   end
'''+s[end:]
    s=once(s,'''     Q_STORE:if(store_index==rows*16-1)begin
      if(kg==6)begin norm_row<=0;ch<=0;maximum<=-2147483647;state<=S_LOAD;end else begin kg<=kg+1;state<=Q_CLEAR;end
     end else store_index<=store_index+1;''', '''     Q_STORE:if(store_index[3:0]==valid_keys-1)begin
      if(rows>4&&!store_index[4])store_index<=16;
      else if(kg==6)begin norm_row<=0;ch<=0;maximum<=-2147483647;state<=S_LOAD;end
      else begin kg<=kg+1;state<=Q_CLEAR;end
     end else store_index<=store_index+1;''')
    s=once(s,'row_data[ch]<=mem_rdata[256+:32];\n      if($signed(mem_rdata[256+:32])>maximum)maximum<=$signed(mem_rdata[256+:32]);',
        'row_data[ch]<=score_rdata;\n      if($signed(score_rdata)>maximum)maximum<=$signed(score_rdata);')
    s=once(s,' // Independent old-storage shadow, copied', ''' // Independent logical old8x99 score matrix. Capture the completed PE
 // tile irrespective of physical write order, then observe real SRAM writes
 // through the inverse bank/address map and compare at the actual consumer.
 reg[31:0]score_shadow[0:791];reg[791:0]score_written;
 integer score_sr,score_sc,score_sb,score_sa,score_si;
 always @(posedge clk)begin
  if(!rst_n)score_written=0;
  else if(enable)begin
   if(state==Q_PREFETCH)score_written=0;
   if(state==Q_STORE)begin
    if(prefetch_ready||dq_live)$fatal(1,"SCORE4_BANK_OWNERSHIP");
    if(store_index==0)for(score_sr=0;score_sr<rows;score_sr=score_sr+1)
     for(score_sc=0;score_sc<valid_keys;score_sc=score_sc+1)
      score_shadow[score_sr*99+kg*16+score_sc]=acc[(score_sr*16+score_sc)*32+:32];
    for(score_sb=0;score_sb<8;score_sb=score_sb+2)if(mem_en[score_sb])begin
     score_sa=mem_addr[score_sb*12+:12];score_sr=score_sb/2+4*(score_sa/99);score_sc=score_sa%99;score_si=score_sr*99+score_sc;
     if(score_sa>=198||score_sr>=rows||score_sc/16!=kg||score_sc%16>=valid_keys||score_written[score_si]||
        !mem_we[score_sb]||!mem_en[score_sb+1]||!mem_we[score_sb+1]||mem_addr[(score_sb+1)*12+:12]!=score_sa||
        mem_wdata[score_sb*16+:32]!==score_shadow[score_si])$fatal(1,"SCORE4_WRONG_OR_DUPLICATE_STORE");
     score_written[score_si]=1;
    end
   end
   if(state==S_CAPTURE)begin
    score_si=norm_row*99+ch;
    if(prefetch_ready||!score_written[score_si]||score_rdata!==score_shadow[score_si])
     $fatal(1,"SCORE4_CONSUMER_UNWRITTEN_OR_STALE");
   end
  end
 end
 // Independent old-storage shadow, copied''')
    out.write_bytes(s.encode());print('SCORE4 SOURCE',hashlib.sha256(s.encode()).hexdigest())
