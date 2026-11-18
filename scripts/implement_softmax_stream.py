"""Exact online score maxima and SRAM-to-RQ streaming, no new state capacity."""
from pathlib import Path
import hashlib
import subprocess

ROOT=Path(__file__).resolve().parents[1]
PARENT='5b3deec31c8e34d8e1484ae794fb1912ce4c8986'
def once(s,old,new):
    assert s.count(old)==1,(s.count(old),old[:100]);return s.replace(old,new)
if __name__=='__main__':
    out=ROOT/'rtl/softmax_stream/kwt_layer_banked.sv';assert not out.exists()
    raw=subprocess.check_output(['git','show',PARENT+':rtl/score4_opt/kwt_layer_banked.sv'],cwd=ROOT)
    assert hashlib.sha256(raw).hexdigest()=='0c18e3ee70cde1fe9af76cbbe91e38a57bece58fa23e2bd14418a3c2e9bbab0b'
    s=raw.decode()
    s=once(s,' wire signed [31:0] gamma_cache[0:63],beta_cache[0:63];', ''' // The last sixteen halfwords hold eight exact row maxima until each
 // S_LOAD consumes its row. Only row7 probability writes overlap them,
 // after all eight maxima have already been consumed.
 wire signed[31:0]score_max_cache[0:7];genvar max_row;
 generate for(max_row=0;max_row<8;max_row=max_row+1)begin:score_max_alias
  assign score_max_cache[max_row]={probabilities[777+2*max_row],probabilities[776+2*max_row]};
 end endgenerate
 function automatic signed[31:0] score_max_step(input signed[31:0] old_max,value,input first);
  reg signed[31:0] prior;begin prior=first?-32'sd2147483647:old_max;score_max_step=value>prior?value:prior;end
 endfunction
 wire signed [31:0] gamma_cache[0:63],beta_cache[0:63];''')
    s=once(s,'lane_a[ml]=$signed(row_data[sent])-$signed(maximum);','lane_a[ml]=$signed(score_rdata)-$signed(maximum);')
    start=s.index('   S_LOAD,S_CAPTURE:if(');end=s.index('   P_READ,P_MAC:',start)
    s=s[:start]+'''   S_LOAD:begin
    bank_index=2*norm_row[1:0];mem_en[bank_index]=1;mem_en[bank_index+1]=1;
    mem_addr[bank_index*12+:12]=norm_row[2]?99:0;mem_addr[(bank_index+1)*12+:12]=norm_row[2]?99:0;
   end
   SM_RQ:begin
    // Advance the synchronous score port only when its current word is
    // accepted. With no new read the SRAM output itself holds that word.
    if(math_accept&&sent<98)begin
     bank_index=2*norm_row[1:0];mem_en[bank_index]=1;mem_en[bank_index+1]=1;
     mem_addr[bank_index*12+:12]=(norm_row[2]?99:0)+sent+1;
     mem_addr[(bank_index+1)*12+:12]=(norm_row[2]?99:0)+sent+1;
    end
    if(math_take&&exp_index!=4096)begin mem_en[18]=1;mem_en[19]=1;mem_addr[18*12+:12]=exp_index;mem_addr[19*12+:12]=exp_index;end
   end
'''+s[end:]
    start=s.index('     Q_STORE:if(store_index[3:0]');end=s.index('     SM_RQ:begin',start)
    s=s[:start]+'''     Q_STORE:begin
      for(integer mx=0;mx<4;mx=mx+1)if(4*store_index[4]+mx<rows)
       {probabilities[777+2*(4*store_index[4]+mx)],probabilities[776+2*(4*store_index[4]+mx)]}<=
        score_max_step(score_max_cache[4*store_index[4]+mx],$signed(acc[((4*store_index[4]+mx)*16+store_index[3:0])*32+:32]),kg==0&&store_index[3:0]==0);
      if(store_index[3:0]==valid_keys-1)begin
       if(rows>4&&!store_index[4])store_index<=16;
       else if(kg==6)begin norm_row<=0;state<=S_LOAD;end
       else begin kg<=kg+1;state<=Q_CLEAR;end
      end else store_index<=store_index+1;
     end
     S_LOAD:begin
      maximum<=score_max_cache[norm_row];sent<=0;received<=0;exp_pending<=0;denominator<=0;state<=SM_RQ;
     end
'''+s[end:]
    s=once(s,'norm_row<=norm_row+1;ch<=0;maximum<=-2147483647;state<=S_LOAD;', 'norm_row<=norm_row+1;state<=S_LOAD;')
    s=once(s,' integer score_sr,score_sc,score_sb,score_sa,score_si;', ' integer score_sr,score_sc,score_sb,score_sa,score_si;reg signed[31:0]score_expected_max;')
    s=once(s,'''   if(state==S_CAPTURE)begin
    score_si=norm_row*99+ch;
    if(prefetch_ready||!score_written[score_si]||score_rdata!==score_shadow[score_si])
     $fatal(1,"SCORE4_CONSUMER_UNWRITTEN_OR_STALE");
   end''', '''   if(state==S_CAPTURE)$fatal(1,"SOFTMAX_STREAM legacy capture reached");
   if(state==S_LOAD)begin
    score_expected_max=-32'sd2147483647;
    for(score_sc=0;score_sc<99;score_sc=score_sc+1)begin
     score_si=norm_row*99+score_sc;
     if(!score_written[score_si])$fatal(1,"SOFTMAX_STREAM missing score before max consume");
     if($signed(score_shadow[score_si])>score_expected_max)score_expected_max=$signed(score_shadow[score_si]);
    end
    if(score_max_cache[norm_row]!==score_expected_max)$fatal(1,"SOFTMAX_STREAM wrong cached maximum");
   end
   if(state==SM_RQ&&math_accept)begin
    score_si=norm_row*99+sent;
    if(prefetch_ready||!score_written[score_si]||score_rdata!==score_shadow[score_si]||maximum!==score_expected_max||
       lane_a[0]!==($signed({{32{score_shadow[score_si][31]}},score_shadow[score_si]})-$signed({{32{score_expected_max[31]}},score_expected_max})))
     $fatal(1,"SOFTMAX_STREAM actual RQ consumer stale/wrong");
   end''')
    out.write_bytes(s.encode());print('STREAM SOURCE',hashlib.sha256(s.encode()).hexdigest())
