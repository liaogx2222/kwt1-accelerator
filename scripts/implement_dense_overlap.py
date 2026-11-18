"""Construct an isolated exact Dense retire/MAC overlap from frozen LN8."""
from pathlib import Path
import hashlib
import subprocess

ROOT=Path(__file__).resolve().parents[1]
def once(s,old,new):
    assert s.count(old)==1,(old[:100],s.count(old));return s.replace(old,new)
if __name__=='__main__':
    out=ROOT/'rtl/dense_overlap/kwt_layer_banked.sv';assert not out.exists()
    data=subprocess.check_output(['git','show','8ef274d289e1d8ba094c8b5021b9db365b906072:rtl/ln8_opt/kwt_layer_banked.sv'],cwd=ROOT)
    assert hashlib.sha256(data).hexdigest()=='a08f682fc4c06f69524ea9ba83f66d5a8e4328d47b92c5b28810ecfb3ff9f6ff'
    s=data.decode();s=once(s,'I_WAIT=93;','I_WAIT=93,D_WAIT=94;')
    s=once(s,' reg [7:0] state,return_state;', ' reg dq_active,dq_tail;reg[6:0]dq_token;\n wire dq_live=dq_active&&!fault;wire dense_tail=dq_live?dq_tail:(rows==3);\n reg [7:0] state,return_state;')
    s=once(s,'wire vector_state=state==D_RQ||','wire vector_state=dq_live||state==D_RQ||')
    s=once(s,'D_RQ:output_limit=kind==2?rows*16:(rows==3?64:128);','D_RQ:output_limit=kind==2?rows*16:0;')
    s=once(s,'  if(state==M_WAIT||state==SM_RQ)response_mask=1;','  if(dq_live)output_limit=dq_tail?64:128;\n  if(state==M_WAIT||state==SM_RQ)response_mask=1;')
    s=once(s,'state==D_RQ&&kind!=2&&rows==3&&mask_lane==3','dq_live&&dq_tail&&mask_lane==3')
    s=once(s,'(state==D_RQ&&kind!=2)?dense_write_index','dq_live?dense_write_index')
    s=once(s,'(rows==3?ml:({received[2],2\'b00}+ml))*16+\n   (rows==3?received[5:2]:received[6:3]);',
        '(dense_tail?ml:({received[2],2\'b00}+ml))*16+\n   (dense_tail?received[5:2]:received[6:3]);')
    s=once(s,'   if(state==D_RQ)begin','   if(dq_live||(state==D_RQ&&kind==2))begin')
    s=once(s,'if(kind!=2)element=(rows==3?ml:({sent[2],2\'b00}+ml))*16+(rows==3?sent[5:2]:sent[6:3]);',
        'if(dq_live)element=(dq_tail?ml:({sent[2],2\'b00}+ml))*16+(dq_tail?sent[5:2]:sent[6:3]);')
    s=once(s,'(kind!=2&&sent<output_limit&&(rows!=3||ml<3))','(dq_live&&sent<output_limit&&(!dq_tail||ml<3))')
    s=once(s,'offered=1;request_tag[ml]=element;lane_op[ml]=3;lane_a[ml]=$signed(acc[element*32+:32]);',
        'offered=1;request_tag[ml]=element;lane_op[ml]=3;lane_a[ml]=dq_live?$signed(low_pv[element]):$signed(acc[element*32+:32]);')
    begin=s.index('   D_RQ:if(kind!=2&&math_take');end=s.index('   D_STORE:begin',begin)
    writes=s[begin:end];s=s[:begin]+s[end:]
    writes=writes.replace('   D_RQ:if(kind!=2&&math_take&&!math_error)', '  if(enable&&rst_n&&dq_live&&math_take&&!math_error)')
    writes=writes.replace('target_group+dense_write_index','8+(dq_token%16)/2+dense_write_index').replace('((token/16)<<','((dq_token/16)<<')
    writes=writes.replace('    mem_en[bank_index]=1;mem_we[bank_index]=1;', '    `ifdef KWT_SIM\n    if(mem_en[bank_index])dq_collision=1;\n    `endif\n    mem_en[bank_index]=1;mem_we[bank_index]=1;')
    s=once(s,' always @* begin\n  mem_en=0;', ' `ifdef KWT_SIM\n reg dq_collision;\n `endif\n always @* begin\n  `ifdef KWT_SIM\n  dq_collision=0;\n  `endif\n  mem_en=0;')
    s=once(s,'  endcase\n end\n always @* begin\n  mac_load=0;', '  endcase\n'+writes+' end\n always @* begin\n  mac_load=0;')
    s=once(s,'   state<=IDLE;return_state<=IDLE;', '   dq_active<=0;dq_tail<=0;dq_token<=0;\n   state<=IDLE;return_state<=IDLE;')
    s=once(s,'    if(math_take&&math_error)begin fault<=1;state<=FAILED;end', '''    if(dq_live&&math_accept)sent<=sent+4;
    if(dq_live&&math_take&&!math_error)begin
     received<=received+4;if(received+4==output_limit)dq_active<=0;
    end
    if(math_take&&math_error)begin dq_active<=0;fault<=1;state<=FAILED;end''')
    start=s.index('     D_MAC:if(red==kdim-1)');end=s.index('     D_STORE:if(',start)
    s=s[:start]+'''     D_MAC:if(red==kdim-1)begin
      if(kind==2)begin sent<=0;received<=0;end
      state<=D_RQ;
     end else red<=red+1;
     D_RQ:if(kind==2)begin
      if(math_accept)sent<=sent+issue_count;
      if(math_take)begin
       for(integer ql=0;ql<4;ql=ql+1)if(response_mask[ql])codes[write_index[ql]]<=lane_result[ql][7:0];
       received<=received+take_count;
       if(received+take_count==output_limit)begin store_index<=0;state<=D_STORE;end
      end
     end else if(!dq_live)begin
      // Previous MAC is complete. Snapshot into the existing dead Q/LN
      // scratch before loading the PE for the following token block.
      for(integer z=0;z<128;z=z+1)low_pv[z]<=acc[z*32+:32];
      dq_token<=token;dq_tail<=rows==3;dq_active<=1;sent<=0;received<=0;
      // Alternating eight-row groups occupy disjoint activation banks.
      // First-layer S16 reads all eight banks; V stores also span them.
      if(!(layer==0&&kind<3)&&token+ROWS<99)begin token<=token+ROWS;state<=D_CLEAR;end
      else state<=D_WAIT;
     end
     D_WAIT:if(!dq_live)state<=D_NEXT;
'''+s[end:]
    start=s.index(' reg [127:0] stream_seen;');end=s.index(' // Independent old-storage shadow',start)
    s=s[:start]+''' reg [127:0]stream_seen;reg[4095:0]stream_acc;
 integer stream_lane,stream_element,stream_bank,stream_address;
 always @(posedge clk)begin
  if(!rst_n)stream_seen=0;
  else if(enable)begin
   if(dq_collision)$fatal(1,"DENSE_OVERLAP same-port read/write collision");
   if(state==D_RQ&&kind!=2&&!dq_live)begin stream_seen=0;stream_acc=acc;end
   if(dq_live&&math_accept)for(stream_lane=0;stream_lane<4;stream_lane=stream_lane+1)if(request_mask[stream_lane])begin
    stream_element=request_tag[stream_lane];
    if(stream_element>=(dq_tail?48:128)||lane_a[stream_lane]!=={{32{stream_acc[32*stream_element+31]}},stream_acc[32*stream_element+:32]})
     $fatal(1,"DENSE_OVERLAP snapshot consumer mismatch");
   end
   if(dq_live&&math_take&&!math_error)begin
    for(stream_lane=0;stream_lane<4;stream_lane=stream_lane+1)if(response_mask[stream_lane])begin
     stream_element=lane_tag[stream_lane];stream_bank=8+(dq_token%16)/2+(stream_element/16)/2;
     stream_address=target_base+(dq_token/16)*(kind==4?256:64)+oc+stream_element%16;
     if(stream_element>=(dq_tail?48:128)||stream_seen[stream_element]||!mem_en[stream_bank]||!mem_we[stream_bank]||
        mem_addr[stream_bank*12+:12]!=stream_address||mem_wdata[stream_bank*16+8*((stream_element/16)%2)+:8]!=lane_result[stream_lane][7:0])
      $fatal(1,"DENSE_OVERLAP wrong/duplicate retirement");
     stream_seen[stream_element]=1;
    end
    if(received+4==output_limit)for(stream_element=0;stream_element<128;stream_element=stream_element+1)
     if(stream_seen[stream_element]!=(stream_element<(dq_tail?48:128)))$fatal(1,"DENSE_OVERLAP incomplete tile");
   end
  end
 end
'''+s[end:]
    out.write_bytes(s.encode());print('DENSE SOURCE',hashlib.sha256(s.encode()).hexdigest())
