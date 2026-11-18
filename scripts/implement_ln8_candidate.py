"""Construct the isolated eight-row LN gather from the frozen PV16 source."""
import hashlib
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
PARENT='bc364d068c3f9d73b340a33136a998fd4ecdd05b'

def once(s,old,new):
    assert s.count(old)==1,(s.count(old),old[:80]);return s.replace(old,new)

if __name__=='__main__':
    out=ROOT/'rtl/ln8_opt/kwt_layer_banked.sv';assert not out.exists()
    data=subprocess.check_output(['git','show',PARENT+':rtl/pv16_opt/kwt_layer_banked.sv'],cwd=ROOT)
    assert hashlib.sha256(data).hexdigest()=='40302c3e56f6f7d003243065d567c7891be1acf4e5953fd8f82d901cdc6831a0'
    s=data.decode()
    s=once(s,' // Codes have already reached SRAM before LN; reuse all 128 code bytes\n // for the 64x16 residual until norm_pass2, which no longer reads it.',
        ' // LN gathers all eight rows: A16 operands use probabilities[256:767];\n // B8 operands use all512 bytes of low_pv. Each retired even row reuses\n // its dead B8 slots for the paired output until the following row writes.')
    s=once(s,'assign residual[cache_word]={probabilities[257+2*cache_word][7:0],probabilities[256+2*cache_word]};',
        'assign residual[cache_word]={low_pv[2*cache_word+norm_row/4][8*(norm_row%4)+:8],probabilities[256+norm_row*64+cache_word]};')
    old='''   N_LOAD_FIRST,N_LOAD_A,N_LOAD_B:if(state!=N_LOAD_B||ch<63)begin
    bank_index=8+(row_token%16)/2;mem_en[bank_index]=1;
    mem_addr[bank_index*12+:12]=(row_token/16)*64+ch+(state==N_LOAD_A?2240:state==N_LOAD_B?1:0);
    if(layer==0&&!norm2&&state!=N_LOAD_A)begin
     mem_en[bank_index]=0;
     mem_en[8+row_token%8]=1;mem_addr[(8+row_token%8)*12+:12]=2688+(row_token/8)*64+ch+(state==N_LOAD_B);
     if(row_token<98)begin mem_en[8+(row_token+1)%8]=1;mem_addr[(8+(row_token+1)%8)*12+:12]=2688+((row_token+1)/8)*64+ch+(state==N_LOAD_B);end
    end
   end'''
    new='''   N_LOAD_FIRST,N_LOAD_A,N_LOAD_B:if(state!=N_LOAD_B||ch<63)begin
    if(layer==0&&!norm2&&state!=N_LOAD_A)begin
     for(j=0;j<ROWS;j=j+1)if(j<rows)begin
      mem_en[8+j]=1;mem_addr[(8+j)*12+:12]=2688+(token/8)*64+ch+(state==N_LOAD_B);
     end
    end else for(j=0;j<ROWS/2;j=j+1)if(2*j<rows)begin
     bank_index=source_group+j;mem_en[bank_index]=1;
     mem_addr[bank_index*12+:12]=(token/16)*64+ch+(state==N_LOAD_A?2240:state==N_LOAD_B?1:0);
    end
   end'''
    s=once(s,old,new)
    s=once(s,'mem_wdata[bank_index*16+:16]={codes[ch],low_pv[ch][31:24]};',
        'mem_wdata[bank_index*16+:16]={codes[ch],low_pv[2*ch+norm_row/4][8*(norm_row%4-1)+:8]};')
    s=once(s,'state<=norm_row[0]?N_PAIR_LOAD:N_LOAD_FIRST;', 'state<=norm_row!=0?N_PAIR_LOAD:N_LOAD_FIRST;')
    start=s.index('     N_LOAD_A:begin');end=s.index('     N_RES:begin',start)
    s=s[:start]+'''     N_LOAD_A:begin
      for(integer z=0;z<ROWS;z=z+1)if(z<rows)
       probabilities[256+z*64+ch]<=layer==0&&!norm2?word_at(mem_rdata,8+z):
        {{8{mem_rdata[(source_group+z/2)*16+8*(z%2)+7]}},mem_rdata[(source_group+z/2)*16+8*(z%2)+:8]};
      state<=N_LOAD_B;
     end
     N_LOAD_B:begin
      for(integer z=0;z<ROWS;z=z+1)if(z<rows)
       low_pv[2*ch+z/4][8*(z%4)+:8]<=mem_rdata[(source_group+z/2)*16+8*(z%2)+:8];
      if(ch==63)begin sent<=0;received<=0;state<=N_RES;end else begin ch<=ch+1;state<=N_LOAD_A;end
     end
     N_PAIR_LOAD:begin sent<=0;received<=0;state<=N_RES;end
'''+s[end:]
    s=once(s,'probabilities[256+2*write_index[ql]]<=lane_result[ql][15:0];probabilities[257+2*write_index[ql]]<={16{lane_result[ql][15]}};',
        'probabilities[256+norm_row*64+write_index[ql]]<=lane_result[ql][15:0];low_pv[2*write_index[ql]+norm_row/4][8*(norm_row%4)+:8]<={8{lane_result[ql][15]}};')
    s=once(s,'for(integer z=0;z<64;z=z+1)low_pv[z][31:24]<=codes[z];',
        'for(integer z=0;z<64;z=z+1)low_pv[2*z+norm_row/4][8*(norm_row%4)+:8]<=codes[z];')
    s=once(s,' reg [63:0] shadow_g_valid,shadow_b_valid,shadow_r_valid,shadow_r_finished;',
        ' reg [63:0] shadow_g_valid,shadow_b_valid,shadow_r_valid,shadow_r_finished;\n reg[15:0]shadow_batch_a[0:511];reg[7:0]shadow_batch_b[0:511];\n reg[511:0]shadow_a_valid,shadow_batch_valid;integer shadow_batch_row,shadow_batch_index;')
    s=once(s,'if(!rst_n)begin shadow_g_valid=0;shadow_b_valid=0;shadow_r_valid=0;shadow_r_finished=0;end',
        'if(!rst_n)begin shadow_g_valid=0;shadow_b_valid=0;shadow_r_valid=0;shadow_r_finished=0;shadow_a_valid=0;shadow_batch_valid=0;end')
    start=s.index('   if(state==N_LOAD_B)begin shadow_residual');end=s.index('   if(state==N_RES&&math_take)',start)
    s=s[:start]+'''   if(state==N_LOAD_FIRST)begin shadow_a_valid=0;shadow_batch_valid=0;end
   if(state==N_LOAD_A)for(shadow_batch_row=0;shadow_batch_row<rows;shadow_batch_row=shadow_batch_row+1)begin
    shadow_batch_index=shadow_batch_row*64+ch;
    shadow_batch_a[shadow_batch_index]=layer==0&&!norm2?word_at(mem_rdata,8+shadow_batch_row):
     {{8{mem_rdata[(source_group+shadow_batch_row/2)*16+8*(shadow_batch_row%2)+7]}},mem_rdata[(source_group+shadow_batch_row/2)*16+8*(shadow_batch_row%2)+:8]};
    shadow_a_valid[shadow_batch_index]=1;
   end
   if(state==N_LOAD_B)for(shadow_batch_row=0;shadow_batch_row<rows;shadow_batch_row=shadow_batch_row+1)begin
    shadow_batch_index=shadow_batch_row*64+ch;
    if(!shadow_a_valid[shadow_batch_index])$fatal(1,"LN8_SHADOW missing A before B");
    shadow_batch_b[shadow_batch_index]=mem_rdata[(source_group+shadow_batch_row/2)*16+8*(shadow_batch_row%2)+:8];
    shadow_batch_valid[shadow_batch_index]=1;
    if(shadow_batch_row==0)begin shadow_residual[ch]={shadow_batch_b[shadow_batch_index],shadow_batch_a[shadow_batch_index]};shadow_r_valid[ch]=1;end
   end
   if(state==N_PAIR_LOAD)for(shadow_z=0;shadow_z<64;shadow_z=shadow_z+1)begin
    shadow_batch_index=norm_row*64+shadow_z;
    if(!shadow_batch_valid[shadow_batch_index])$fatal(1,"LN8_SHADOW missing batch row");
    shadow_residual[shadow_z]={shadow_batch_b[shadow_batch_index],shadow_batch_a[shadow_batch_index]};shadow_r_valid[shadow_z]=1;
   end
'''+s[end:]
    out.write_bytes(s.encode());print('CREATED',out,'SHA256',hashlib.sha256(s.encode()).hexdigest())
