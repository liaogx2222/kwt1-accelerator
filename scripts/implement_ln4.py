"""Four-row exact normalization and packed SRAM retirement using old storage."""
from pathlib import Path
import hashlib
import subprocess
ROOT=Path(__file__).resolve().parents[1]
PARENT='eb7277e3774b147c2c69ecfbbdaaeeb148363c3d'
def once(s,old,new):
    assert s.count(old)==1,(s.count(old),old[:90]);return s.replace(old,new)
if __name__=='__main__':
    out=ROOT/'rtl/ln4_opt/kwt_layer_banked.sv';assert not out.exists()
    raw=subprocess.check_output(['git','show',PARENT+':rtl/iter_fast/kwt_layer_banked.sv'],cwd=ROOT)
    assert hashlib.sha256(raw).hexdigest()=='8df08f33566980195ed53e780a55e27e8751f20f9d46db81400c65c15049dc6d'
    s=raw.decode();s=once(s,'I_WAIT=93,D_WAIT=94;','I_WAIT=93,D_WAIT=94,N4_PASS=95;')
    s=once(s,' wire vector_state=dq_live||state==D_RQ||',' wire vector_state=state==N4_PASS||dq_live||state==D_RQ||')
    s=once(s,'   N_RES,N_SQUARE,N_PASS:output_limit=64;','   N_RES,N_SQUARE,N_PASS,N4_PASS:output_limit=64;')
    s=once(s,'  if(state==M_WAIT||state==SM_RQ)response_mask=1;',"  if(state==N4_PASS)response_mask=received<64?4'b1111:0;\n  else if(state==M_WAIT||state==SM_RQ)response_mask=1;")
    s=once(s,'lane_tag[mask_lane]!=(dq_live?dense_write_index[mask_lane]:received+mask_lane)',
        'lane_tag[mask_lane]!=(state==N4_PASS?received:dq_live?dense_write_index[mask_lane]:received+mask_lane)')
    s=once(s,' wire signed [23:0] residual[0:63];genvar cache_word;', ''' // Full8-row LN first caches sum/reciprocal in dead row_data[0..15].
 // Four even rows then four odd rows normalize in parallel. Intermediate
 // low16 stays in each row's old residual slot, high16 in dead low_pv.
 // Even S8 results remain in their own dead probability slot for paired
 // SRAM words, leaving all odd residuals and affine coefficients intact.
 wire [31:0]n4_operand[0:3],n4_value[0:3];genvar n4_lane;
 generate for(n4_lane=0;n4_lane<4;n4_lane=n4_lane+1)begin:n4_alias
  assign n4_operand[n4_lane]={low_pv[2*sent[5:0]+n4_lane/2][16*(n4_lane%2)+:16],
   probabilities[256+(2*n4_lane+norm_row[0])*64+sent[5:0]]};
  assign n4_value[n4_lane]=norm_pass==1?lane_result[n4_lane][31:0]+beta_cache[received[5:0]]:lane_result[n4_lane][31:0];
 end endgenerate
 wire signed [23:0] residual[0:63];genvar cache_word;''')
    at=s.index('   if(state==N_PASS&&element<64)begin');end=s.index('\n  end\n  always @*begin',at)
    s=s[:end]+'''\n   if(state==N4_PASS&&sent<64)begin
    offered=1;request_tag[ml]=sent;lane_op[ml]=3;lane_sat[ml]=norm_pass==2?8:0;
    lane_a[ml]=norm_pass==0?(($signed({{48{probabilities[256+(2*ml+norm_row[0])*64+sent[5:0]][15]}},
      probabilities[256+(2*ml+norm_row[0])*64+sent[5:0]]})<<<6)-$signed(row_data[4*ml+2*norm_row[0]])):$signed(n4_operand[ml]);
    lane_b[ml]=norm_pass==0?{32'd0,row_data[4*ml+2*norm_row[0]+1]}:
      norm_pass==1?{{32{gamma_cache[sent[5:0]][31]}},gamma_cache[sent[5:0]]}:{32'd0,ln_m};
    lane_shift[ml]=norm_pass==0?18:norm_pass==1?14:ln_s;
   end'''+s[end:]
    s=once(s,'   N_PAIR_WRITE:begin','''   N4_PASS:if(norm_pass==2&&norm_row[0]&&math_take&&!math_error)for(j=0;j<4;j=j+1)begin
    bank_index=source_group+j;mem_en[bank_index]=1;mem_we[bank_index]=1;
    mem_addr[bank_index*12+:12]=(norm2?448:0)+(token/16)*64+received[5:0];
    mem_wdata[bank_index*16+:16]={lane_result[j][7:0],probabilities[256+(2*j)*64+received[5:0]][7:0]};
   end
   N_PAIR_WRITE:begin''')
    old='     N_INV_RET:begin ln_recip<=iter_value+((iter_rem>den_sqrt-iter_rem)||(iter_rem==den_sqrt-iter_rem&&iter_value[0]));norm_pass<=0;sent<=0;received<=0;state<=N_PASS;end'
    s=once(s,old,'''     N_INV_RET:begin
      ln_recip<=iter_value+((iter_rem>den_sqrt-iter_rem)||(iter_rem==den_sqrt-iter_rem&&iter_value[0]));
      norm_pass<=0;sent<=0;received<=0;
      if(rows==8)begin
       row_data[2*norm_row]<=sum_s;
       row_data[2*norm_row+1]<=iter_value+((iter_rem>den_sqrt-iter_rem)||(iter_rem==den_sqrt-iter_rem&&iter_value[0]));
       if(norm_row<7)begin norm_row<=norm_row+1;state<=N_PAIR_LOAD;end
       else begin norm_row<=0;state<=N4_PASS;end
      end else state<=N_PASS;
     end
     N4_PASS:begin
      if(math_accept)sent<=sent+1;
      if(math_take)begin
       for(integer nl=0;nl<4;nl=nl+1)begin
        if(norm_pass==2)begin
         if(!norm_row[0])probabilities[256+(2*nl)*64+received[5:0]]<={8'd0,lane_result[nl][7:0]};
        end else begin
         probabilities[256+(2*nl+norm_row[0])*64+received[5:0]]<=n4_value[nl][15:0];
         low_pv[2*received[5:0]+nl/2][16*(nl%2)+:16]<=n4_value[nl][31:16];
        end
       end
       received<=received+1;
       if(received==63)begin
        sent<=0;received<=0;
        if(norm_pass<2)norm_pass<=norm_pass+1;
        else if(!norm_row[0])begin norm_row<=1;norm_pass<=0;end
        else begin norm_row<=7;state<=N_WNEXT;end
       end
      end
     end''')
    shadow=''' // Logical producer/consumer shadow independent of the reused physical slots.
 reg signed[15:0]n4_ref_res[0:511];reg[511:0]n4_ref_valid;
 reg signed[31:0]n4_ref_sum[0:7];reg[31:0]n4_ref_recip[0:7];reg[7:0]n4_stat_valid;
 reg[31:0]n4_ref_value[0:511];reg[7:0]n4_ref_output[0:511];
 reg[63:0]n4_request_seen[0:5],n4_response_seen[0:5];reg[255:0]n4_written;
 integer nr,nc,ni,ns,nb,naddr;reg signed[63:0]n4_expected_a,n4_expected_b,n4_expected_sum;
 always @(posedge clk)begin
  if(!rst_n)begin
   n4_ref_valid=0;n4_stat_valid=0;n4_written=0;
   for(ns=0;ns<6;ns=ns+1)begin n4_request_seen[ns]=0;n4_response_seen[ns]=0;end
  end else if(enable)begin
   if(state==N_LOAD_FIRST)begin
    n4_ref_valid=0;n4_stat_valid=0;n4_written=0;
    for(ns=0;ns<6;ns=ns+1)begin n4_request_seen[ns]=0;n4_response_seen[ns]=0;end
   end
   if(rows==8&&state==N_RES&&math_take&&!math_error)for(ns=0;ns<4;ns=ns+1)if(response_mask[ns])begin
    ni=norm_row*64+lane_tag[ns];n4_ref_res[ni]=lane_result[ns][15:0];n4_ref_valid[ni]=1;
   end
   if(rows==8&&state==N_INV_RET)begin
    n4_expected_sum=0;
    for(nc=0;nc<64;nc=nc+1)begin
     ni=norm_row*64+nc;if(!n4_ref_valid[ni])$fatal(1,"LN4 missing residual before statistics");
     n4_expected_sum=n4_expected_sum+$signed(n4_ref_res[ni]);
    end
    if($signed(sum_s)!==n4_expected_sum)$fatal(1,"LN4 statistic sum mismatch");
    n4_ref_sum[norm_row]=sum_s;
    n4_ref_recip[norm_row]=iter_value+((iter_rem>den_sqrt-iter_rem)||(iter_rem==den_sqrt-iter_rem&&iter_value[0]));n4_stat_valid[norm_row]=1;
   end
   if(state==N4_PASS)begin
    if(rows!=8||norm_row>1||dq_live||!cache_valid||cache_norm2!=norm2||n4_stat_valid!=255)
     $fatal(1,"LN4 context or ownership mismatch");
    ns=3*norm_row[0]+norm_pass;
    if(math_accept)begin
     nc=sent;if(nc>=64||n4_request_seen[ns][nc]||request_mask!=15)$fatal(1,"LN4 duplicate/invalid request");
     n4_request_seen[ns][nc]=1;
     for(nr=0;nr<4;nr=nr+1)begin
      ni=(2*nr+norm_row[0])*64+nc;
      n4_expected_a=norm_pass==0?($signed({{48{n4_ref_res[ni][15]}},n4_ref_res[ni]})<<<6)-$signed(n4_ref_sum[2*nr+norm_row[0]]):$signed(n4_ref_value[ni]);
      n4_expected_b=norm_pass==0?{32'd0,n4_ref_recip[2*nr+norm_row[0]]}:
        norm_pass==1?{{32{shadow_gamma[nc][31]}},shadow_gamma[nc]}:{32'd0,ln_m};
      if(lane_a[nr]!==n4_expected_a||lane_b[nr]!==n4_expected_b||request_tag[nr]!=nc||
         (norm_pass==1&&!shadow_g_valid[nc]))$fatal(1,"LN4 actual operand lifetime mismatch pass=%0d row=%0d ch=%0d",norm_pass,2*nr+norm_row[0],nc);
     end
    end
    if(math_take&&!math_error)begin
     nc=received;if(nc>=64||n4_response_seen[ns][nc]||response_mask!=15)$fatal(1,"LN4 duplicate/invalid response");
     n4_response_seen[ns][nc]=1;
     for(nr=0;nr<4;nr=nr+1)begin
      ni=(2*nr+norm_row[0])*64+nc;
      if(norm_pass<2)begin
       if(norm_pass==1&&!shadow_b_valid[nc])$fatal(1,"LN4 missing beta");
       n4_ref_value[ni]=norm_pass==1?lane_result[nr][31:0]+shadow_beta[nc]:lane_result[nr][31:0];
      end else begin
       if(norm_row[0])begin
        nb=8+(token%16)/2+nr;naddr=(norm2?448:0)+(token/16)*64+nc;
        if(n4_written[nr*64+nc]||!mem_en[nb]||!mem_we[nb]||mem_addr[nb*12+:12]!=naddr||
           mem_wdata[nb*16+:16]!=={lane_result[nr][7:0],n4_ref_output[(2*nr)*64+nc]})$fatal(1,"LN4 paired physical write mismatch");
        n4_written[nr*64+nc]=1;
       end
       n4_ref_output[ni]=lane_result[nr][7:0];
      end
     end
     if(nc==63&&(&n4_request_seen[ns])!==1'b1)$fatal(1,"LN4 missing requests at pass drain");
    end
   end
   if(rows==8&&state==N_WNEXT&&norm_row==7)begin
    if(n4_written!=={256{1'b1}})$fatal(1,"LN4 incomplete SRAM tile");
    for(ns=0;ns<6;ns=ns+1)if(n4_response_seen[ns]!=={64{1'b1}})$fatal(1,"LN4 incomplete phase");
   end
  end
 end
'''
    s=once(s,'`endif\nendmodule',shadow+'`endif\nendmodule')
    out.write_bytes(s.encode());print('LN4 SOURCE',hashlib.sha256(s.encode()).hexdigest())
