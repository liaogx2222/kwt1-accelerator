// Fixed INTEGER_NUMERICS_V1. 8-query attention, eight-row O/FC2, synchronous
// prefetch/MAC overlap; exact residual and LN/Softmax element pipelines.
// C[2048:2839] holds one 8x99 S32 score block. All bulk tensors use 20 SP macros.
module kwt_layer_banked(input wire clk,rst_n,enable,input wire start,output wire ready,
 input wire [3:0] layer_id,output reg done,output reg fault,output wire [7:0] debug_state,
 output reg [19:0] mem_en,mem_we,output reg [239:0] mem_addr,output reg [319:0] mem_wdata,input wire [319:0] mem_rdata);
 `include "kwt_profile.svh"
 localparam IDLE=0,D_COEFF=1,D_M=2,D_S=3,D_B=4,D_CLEAR=5,D_READ=6,D_MAC=7,D_RQ=8,D_STORE=9,D_NEXT=10,
 A_COEF0=11,A_COEF1=12,A_COEF2=13,A_COEF3=14,Q_CLEAR=15,Q_READ=16,Q_MAC=17,Q_STORE=18,
 SM_RQ=19,SM_DIV=22,SM_DIV_RET=23,SM_ER=24,SM_QD=26,
 P_CLEAR=27,P_READ=28,P_MAC=29,P_END=30,P_RQ=31,P_STORE=32,
 N_BEGIN=33,N_C0=34,N_C1=35,N_CS=36,N_EPS=37,N_M=38,N_S=39,N_LOAD_A=40,N_LOAD_B=41,N_LOAD_FIRST=42,N_RES=44,
 N_SQUARE=45,N_SUMSQ=46,N_VAR=47,N_SQRT=48,N_INV=49,N_INV_RET=50,N_PASS=51,N_CACHE_G=53,N_CACHE_B=54,N_CACHE_NEXT=55,
 N_WRITE=57,N_RMW=58,N_WNEXT=59,G_READ=60,G_CAPTURE=61,G_LUT=62,G_LUT_RET=63,G_WRITE=64,
 COPY_READ=65,COPY_WRITE=66,LAYER_END=67,FAILED=68,S_LOAD=69,S_CAPTURE=70,G_CACHE_FIRST=71,G_CACHE_LOAD=72,G_APPLY=73,
 N_PAIR_LOAD=74,N_PAIR_CACHE=75,N_PAIR_WRITE=76,
 READ16=80,RET16=81,C_READ=83,C_RET=84,C64_READ0=85,C64_RET0=86,C64_READ1=87,C64_RET1=88,M_REQ=90,M_WAIT=91,I_REQ=92,I_WAIT=93;
 reg [7:0] state,return_state;assign debug_state=state;assign ready=rst_n&&state==IDLE&&!fault;
 reg [3:0] layer;reg [2:0] kind;reg [6:0] token,ch;reg [7:0] oc,sent,received;reg [8:0] red;reg [3:0] kg,ci;
 reg [5:0] store_index;reg [2:0] norm_row;reg plane,norm2,cache_valid,cache_norm2;reg [1:0] norm_pass;
 reg [4:0] generic_bank;reg [11:0] generic_addr,coefficient_addr;reg [15:0] r16;reg [31:0] r32,low32;reg [63:0] r64;
 reg [31:0] multipliers[0:7],biases[0:7];reg signed [7:0] shifts[0:7];reg [7:0] codes[0:63];
 reg signed [31:0] row_data[0:98],low_pv[0:63],gamma_cache[0:63],beta_cache[0:63];
 reg [15:0] probabilities[0:791];reg signed [15:0] residual[0:63];
 reg signed [31:0] maximum,sum_s,res_m0,res_m1;reg [63:0] sum_t,eps_value,den_sqrt,h_value;
 reg [31:0] score_m,context_m,denominator,reciprocal,ln_m,ln_recip;reg signed [7:0] score_s,context_s,ln_s,res_s;
 reg [7:0] residual_x;reg [9:0] copy_address;reg [3:0] gelu_lane;
 reg exp_pending,exp_zero;reg [7:0] exp_tag;
 reg [2:0] math_op;reg [63:0] math_a,math_b,math_value;reg signed [7:0] math_shift;reg [5:0] math_sat;
 reg iter_sqrt;reg [63:0] iter_a,iter_b,iter_value,iter_rem;
 wire math_ready,math_valid,math_error;wire [63:0] math_result;wire [7:0] math_tag;
 reg logical_mvalid;reg [2:0] logical_mop;reg [63:0] logical_ma,logical_mb;reg signed [7:0] logical_ms;reg [5:0] logical_sat;reg [7:0] logical_tag;
 wire math_accept=enable&&logical_mvalid&&math_ready;
 wire math_take=enable&&math_valid&&(state==M_WAIT||state==D_RQ||state==SM_RQ||state==SM_ER||state==SM_QD||state==P_RQ||state==N_RES||state==N_SQUARE||state==N_PASS);
 kwt_math math_unit(clk,rst_n,logical_mvalid&&enable,math_ready,logical_mop,logical_ma,logical_mb,logical_ms,logical_sat,logical_tag,
  math_valid,math_take,math_result,math_error,math_tag);
 wire iter_ready,iter_valid,iter_error;wire [63:0] iter_result,iter_remainder;
 kwt_iterative iterative_unit(clk,rst_n,enable&&state==I_REQ,iter_ready,iter_sqrt,iter_a,iter_b,iter_valid,enable&&state==I_WAIT,iter_result,iter_remainder,iter_error);
 reg mac_load,mac_en,mac_unsigned;reg [7:0] row_mask,col_mask;reg [63:0] mac_a,mac_b;reg [255:0] mac_bias;wire [2047:0] acc;
 kwt_mac8x8 pe(clk,rst_n,mac_load,mac_en,mac_unsigned,row_mask,col_mask,mac_a,mac_b,mac_bias,acc);
 integer rows,kdim,ndim,wb,cm,cs,cb,target_base,target_group,source_group,source_base,source_width,waddress,read_red,bank_index,physical_w,j,valid_keys,row_token;
 reg [63:0] numerator,corrected_q,corrected_prod,remainder_value;reg [12:0] exp_index;
 function automatic [15:0] word_at(input [319:0] data,input integer bank);begin word_at=data[bank*16+:16];end endfunction
 function automatic signed [7:0] byte_at(input [319:0] data,input integer bank,input integer high);begin byte_at=$signed((word_at(data,bank)>>(8*high))&255);end endfunction
 function automatic signed [31:0] accumulator(input [2047:0] data,input integer index);begin accumulator=$signed(data[index*32+:32]);end endfunction
 task read_word(input integer bank,input integer address,input [7:0] resume);begin generic_bank<=bank;generic_addr<=address;return_state<=resume;state<=READ16;end endtask
 task read_c32(input integer address,input [7:0] resume);begin coefficient_addr<=address;return_state<=resume;state<=C_READ;end endtask
 task read_c64(input integer address,input [7:0] resume);begin coefficient_addr<=address;return_state<=resume;state<=C64_READ0;end endtask
 task scalar(input [2:0] op,input [63:0] a,input [63:0] b,input signed [7:0] shift,input [5:0] sat,input [7:0] resume);
  begin math_op<=op;math_a<=a;math_b<=b;math_shift<=shift;math_sat<=sat;return_state<=resume;state<=M_REQ;end endtask
 task iterate(input sqrt_mode,input [63:0] a,input [63:0] b,input [7:0] resume);begin iter_sqrt<=sqrt_mode;iter_a<=a;iter_b<=b;return_state<=resume;state<=I_REQ;end endtask
 always @* begin
  case(kind)
   0:begin kdim=64;ndim=64;wb=WB_Q;cm=CB_Q_M;cs=CB_Q_S;cb=0;target_group=8;target_base=832;end
   1:begin kdim=64;ndim=64;wb=WB_K;cm=CB_K_M;cs=CB_K_S;cb=0;target_group=12;target_base=0;end
   2:begin kdim=64;ndim=64;wb=WB_V;cm=CB_V_M;cs=CB_V_S;cb=0;target_group=12;target_base=832;end
   3:begin kdim=64;ndim=64;wb=WB_O;cm=CB_O_M;cs=CB_O_S;cb=CB_O_B;target_group=8;target_base=2496;end
   4:begin kdim=64;ndim=256;wb=WB_FC1;cm=CB_FC1_M;cs=CB_FC1_S;cb=CB_FC1_B;target_group=12;target_base=0;end
   default:begin kdim=256;ndim=64;wb=WB_FC2;cm=CB_FC2_M;cs=CB_FC2_S;cb=CB_FC2_B;target_group=8;target_base=2496;end
  endcase
  source_group=kind==5?12:8;source_base=kind==3?1664:0;source_width=kind==5?256:64;
  rows=token<92?8:99-token;row_token=token+norm_row;valid_keys=kg==12?3:8;
  read_red=red+((state==D_MAC||state==Q_MAC||state==P_MAC)?1:0);
  waddress=wb+((oc/8)<<(kind==5?8:6))+read_red;
  exp_index=$signed(math_result)>=0?0:($signed(math_result)< -4096?4096:-$signed(math_result));
  numerator=({32'd0,row_data[math_tag]}<<16)-{32'd0,row_data[math_tag]};
  corrected_q={48'd0,probabilities[norm_row*99+math_tag]};corrected_prod=math_result;
  if(corrected_prod>numerator)begin corrected_q=corrected_q-1;corrected_prod=corrected_prod-denominator;end
  remainder_value=numerator-corrected_prod;
 end
 always @* begin
  logical_mvalid=0;logical_mop=math_op;logical_ma=math_a;logical_mb=math_b;logical_ms=math_shift;logical_sat=math_sat;logical_tag=sent;
  if(state==M_REQ)begin logical_mvalid=1;logical_tag=0;end
  if(state==D_RQ&&sent<rows*8)begin logical_mvalid=1;logical_mop=3;logical_ma=$signed(acc[sent*32+:32]);logical_mb={32'd0,multipliers[sent%8]};logical_ms=shifts[sent%8];logical_sat=8;end
  if(state==SM_RQ&&sent<99)begin logical_mvalid=1;logical_mop=3;logical_ma=$signed(row_data[sent])-$signed(maximum);logical_mb={32'd0,score_m};logical_ms=score_s;logical_sat=0;end
  if(state==SM_ER&&sent<99)begin logical_mvalid=1;logical_mop=1;logical_ma={32'd0,row_data[sent]};logical_mb={32'd0,reciprocal};logical_ms=0;logical_sat=0;end
  if(state==SM_QD&&sent<99)begin logical_mvalid=1;logical_mop=1;logical_ma={48'd0,probabilities[norm_row*99+sent]};logical_mb={32'd0,denominator};logical_ms=0;logical_sat=0;end
  if(state==P_RQ&&sent<rows*8)begin logical_mvalid=1;logical_mop=3;logical_ma=($signed($signed(acc[sent*32+:32]))<<<8)+$signed(low_pv[sent]);logical_mb={32'd0,context_m};logical_ms=context_s;logical_sat=8;end
  if(state==N_RES&&sent<128)begin
   logical_mvalid=1;logical_mop=4;logical_ma=sent[0]?$signed(residual[sent/2][15:8]):$signed(residual[sent/2][7:0]);
   logical_mb=sent[0]?$signed(res_m1):$signed(res_m0);logical_ms=res_s;logical_sat=16;
  end
  if(state==N_SQUARE&&sent<64)begin logical_mvalid=1;logical_mop=0;logical_ma=$signed(residual[sent]);logical_mb=$signed(residual[sent]);logical_ms=0;logical_sat=0;end
  if(state==N_PASS&&sent<64)begin
   logical_mvalid=1;logical_mop=3;logical_sat=norm_pass==2?8:0;
   logical_ma=norm_pass==0?(($signed({{48{residual[sent][15]}},residual[sent]})<<<6)-$signed(sum_s)):$signed(row_data[sent]);
   logical_mb=norm_pass==0?{32'd0,ln_recip}:norm_pass==1?{{32{gamma_cache[sent][31]}},gamma_cache[sent]}:{32'd0,ln_m};
   logical_ms=norm_pass==0?18:norm_pass==1?14:ln_s;
  end
 end
 always @* begin
  mem_en=0;mem_we=0;mem_addr=0;mem_wdata=0;bank_index=0;physical_w=0;
  if(enable&&rst_n)case(state)
   READ16:begin mem_en[generic_bank]=1;mem_addr[generic_bank*12+:12]=generic_addr;end
   C_READ,C64_READ0,C64_READ1:begin mem_en[16]=1;mem_en[17]=1;mem_addr[16*12+:12]=coefficient_addr+(state==C64_READ1);mem_addr[17*12+:12]=coefficient_addr+(state==C64_READ1);end
   D_READ,D_MAC:if(state==D_READ||red<kdim-1)for(j=0;j<4;j=j+1)begin
    physical_w=2*j+(waddress/4096);mem_en[physical_w]=1;mem_addr[physical_w*12+:12]=waddress%4096;
    mem_en[source_group+j]=1;mem_addr[(source_group+j)*12+:12]=source_base+((token/8)<<(kind==5?8:6))+read_red;
   end
   D_STORE:begin
    if(kind==2)for(j=0;j<4;j=j+1)begin mem_en[12+j]=1;mem_we[12+j]=1;mem_addr[(12+j)*12+:12]=832+(token+store_index)*8+oc/8;mem_wdata[(12+j)*16+:16]={codes[store_index*8+2*j+1],codes[store_index*8+2*j]};end
    else for(j=0;j<4;j=j+1)if(2*j<rows)begin
     mem_en[target_group+j]=1;mem_we[target_group+j]=1;mem_addr[(target_group+j)*12+:12]=target_base+((token/8)<<(kind==4?8:6))+oc+store_index;
     mem_wdata[(target_group+j)*16+:16]={8'd0,codes[(2*j)*8+store_index]};if(2*j+1<rows)mem_wdata[(target_group+j)*16+8+:8]=codes[(2*j+1)*8+store_index];
    end
   end
   Q_READ,Q_MAC:if(state==Q_READ||red<63)for(j=0;j<4;j=j+1)begin
    mem_en[8+j]=1;mem_addr[(8+j)*12+:12]=832+(token/8)*64+read_red;
    mem_en[12+j]=1;mem_addr[(12+j)*12+:12]=kg*64+read_red;
   end
   Q_STORE:if(store_index%8<valid_keys)begin
    mem_en[16]=1;mem_en[17]=1;mem_we[16]=1;mem_we[17]=1;
    mem_addr[16*12+:12]=2048+(store_index/8)*99+kg*8+store_index%8;mem_addr[17*12+:12]=2048+(store_index/8)*99+kg*8+store_index%8;
    mem_wdata[16*16+:16]=acc[store_index*32+:16];mem_wdata[17*16+:16]=acc[store_index*32+16+:16];
   end
   S_LOAD,S_CAPTURE:if(state==S_LOAD||ch<98)begin
    mem_en[16]=1;mem_en[17]=1;mem_addr[16*12+:12]=2048+norm_row*99+ch+(state==S_CAPTURE);mem_addr[17*12+:12]=2048+norm_row*99+ch+(state==S_CAPTURE);
   end
   SM_RQ:if(math_take&&exp_index!=4096)begin mem_en[18]=1;mem_en[19]=1;mem_addr[18*12+:12]=exp_index;mem_addr[19*12+:12]=exp_index;end
   P_READ,P_MAC:if(state==P_READ||red<98)for(j=0;j<4;j=j+1)begin mem_en[12+j]=1;mem_addr[(12+j)*12+:12]=832+read_red*8+oc/8;end
   P_STORE:for(j=0;j<4;j=j+1)if(2*j<rows)begin
    mem_en[8+j]=1;mem_we[8+j]=1;mem_addr[(8+j)*12+:12]=1664+(token/8)*64+oc+store_index;
    mem_wdata[(8+j)*16+:16]={8'd0,codes[2*j*8+store_index]};if(2*j+1<rows)mem_wdata[(8+j)*16+8+:8]=codes[(2*j+1)*8+store_index];
   end
   N_LOAD_FIRST,N_LOAD_A,N_LOAD_B:if(state!=N_LOAD_B||ch<63)begin
    bank_index=8+(row_token%8)/2;mem_en[bank_index]=1;
    mem_addr[bank_index*12+:12]=(row_token/8)*64+ch+(state==N_LOAD_A?2496:state==N_LOAD_B?1:0);
   end
   N_WRITE,N_RMW:begin
    bank_index=8+(row_token%8)/2;mem_en[bank_index]=1;mem_addr[bank_index*12+:12]=(norm2?832:0)+(row_token/8)*64+ch;
    if(state==N_RMW)begin mem_we[bank_index]=1;mem_wdata[bank_index*16+:16]=row_token%2?{codes[ch],mem_rdata[bank_index*16+:8]}:{mem_rdata[bank_index*16+8+:8],codes[ch]};end
   end
   N_PAIR_WRITE:begin
    bank_index=8+(row_token%8)/2;mem_en[bank_index]=1;mem_we[bank_index]=1;
    mem_addr[bank_index*12+:12]=(norm2?832:0)+(row_token/8)*64+ch;
    mem_wdata[bank_index*16+:16]={codes[ch],low_pv[ch][23:16]};
   end
   G_READ:for(j=0;j<4;j=j+1)if(2*j<(token<12?8:3))begin mem_en[12+j]=1;mem_addr[(12+j)*12+:12]=token*256+oc;end
   G_CACHE_FIRST,G_CACHE_LOAD:if(state==G_CACHE_FIRST||ch<127)begin mem_en[16]=1;mem_addr[16*12+:12]=1880+ch+(state==G_CACHE_LOAD);end
   G_WRITE:for(j=0;j<4;j=j+1)if(2*j<(token<12?8:3))begin mem_en[12+j]=1;mem_we[12+j]=1;mem_addr[(12+j)*12+:12]=token*256+oc;mem_wdata[(12+j)*16+:16]={8'd0,codes[2*j]};if(2*j+1<(token<12?8:3))mem_wdata[(12+j)*16+8+:8]=codes[2*j+1];end
   COPY_READ:for(j=0;j<4;j=j+1)begin mem_en[8+j]=1;mem_addr[(8+j)*12+:12]=832+copy_address;end
   COPY_WRITE:for(j=0;j<4;j=j+1)begin mem_en[8+j]=1;mem_we[8+j]=1;mem_addr[(8+j)*12+:12]=copy_address;mem_wdata[(8+j)*16+:16]=mem_rdata[(8+j)*16+:16];end
  endcase
 end
 always @* begin
  mac_load=0;mac_en=0;mac_unsigned=0;row_mask=(9'd1<<rows)-1;col_mask=255;mac_a=0;mac_b=0;mac_bias=0;
  if(state==D_CLEAR||state==D_MAC)begin
   for(integer z=0;z<8;z=z+1)mac_bias[z*32+:32]=biases[z];
   for(integer z=0;z<4;z=z+1)begin mac_a[z*16+:16]=mem_rdata[(source_group+z)*16+:16];mac_b[z*16+:16]=mem_rdata[(2*z+((wb+((oc/8)<<(kind==5?8:6))+red)/4096))*16+:16];end
  end
  if(state==Q_CLEAR||state==Q_MAC)begin col_mask=(9'd1<<valid_keys)-1;for(integer z=0;z<4;z=z+1)begin mac_a[z*16+:16]=mem_rdata[(8+z)*16+:16];mac_b[z*16+:16]=mem_rdata[(12+z)*16+:16];end end
  if(state==P_CLEAR||state==P_MAC)begin
   mac_unsigned=1;for(integer z=0;z<8;z=z+1)mac_a[z*8+:8]=probabilities[z*99+red]>>(plane?8:0);
   for(integer z=0;z<4;z=z+1)mac_b[z*16+:16]=mem_rdata[(12+z)*16+:16];
  end
  if(enable&&rst_n)begin mac_load=state==D_CLEAR||state==Q_CLEAR||state==P_CLEAR;mac_en=state==D_MAC||state==Q_MAC||state==P_MAC;end
 end
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin
   state<=IDLE;return_state<=IDLE;layer<=0;kind<=0;token<=0;ch<=0;oc<=0;sent<=0;received<=0;red<=0;kg<=0;ci<=0;store_index<=0;norm_row<=0;plane<=0;norm2<=0;cache_valid<=0;cache_norm2<=0;norm_pass<=0;
   generic_bank<=0;generic_addr<=0;coefficient_addr<=0;r16<=0;r32<=0;low32<=0;r64<=0;maximum<=0;sum_s<=0;sum_t<=0;eps_value<=0;den_sqrt<=0;h_value<=0;
   score_m<=0;context_m<=0;denominator<=0;reciprocal<=0;ln_m<=0;ln_recip<=0;score_s<=0;context_s<=0;ln_s<=0;res_s<=0;res_m0<=0;res_m1<=0;residual_x<=0;copy_address<=0;gelu_lane<=0;exp_pending<=0;exp_zero<=0;exp_tag<=0;
   math_op<=0;math_a<=0;math_b<=0;math_value<=0;math_shift<=0;math_sat<=0;iter_sqrt<=0;iter_a<=0;iter_b<=0;iter_value<=0;iter_rem<=0;done<=0;fault<=0;
  end else begin
   done<=0;
   if(enable)begin
    if(math_take&&math_error)begin fault<=1;state<=FAILED;end
    else case(state)
     IDLE:if(start&&!fault)begin layer<=layer_id;kind<=0;token<=0;oc<=0;ci<=0;cache_valid<=0;norm_row<=0;state<=D_COEFF;end
     READ16:state<=RET16;RET16:begin r16<=mem_rdata[generic_bank*16+:16];state<=return_state;end
     C_READ:state<=C_RET;C_RET:begin r32<=mem_rdata[256+:32];state<=return_state;end
     C64_READ0:state<=C64_RET0;C64_RET0:begin low32<=mem_rdata[256+:32];state<=C64_READ1;end
     C64_READ1:state<=C64_RET1;C64_RET1:begin r64<={mem_rdata[256+:32],low32};state<=return_state;end
     M_REQ:if(math_accept)state<=M_WAIT;M_WAIT:if(math_take)begin math_value<=math_result;state<=return_state;end
     I_REQ:if(iter_ready)state<=I_WAIT;I_WAIT:if(iter_valid)begin iter_value<=iter_result;iter_rem<=iter_remainder;if(iter_error)begin fault<=1;state<=FAILED;end else state<=return_state;end
     D_COEFF:read_c32(cm+oc+ci,D_M);D_M:begin multipliers[ci]<=r32;read_c32(cs+oc+ci,D_S);end
     D_S:begin shifts[ci]<=r32[7:0];if(kind<3)begin biases[ci]<=0;if(ci==7)state<=D_CLEAR;else begin ci<=ci+1;state<=D_COEFF;end end else read_c32(cb+oc+ci,D_B);end
     D_B:begin biases[ci]<=r32;if(ci==7)state<=D_CLEAR;else begin ci<=ci+1;state<=D_COEFF;end end
     D_CLEAR:begin red<=0;state<=D_READ;end D_READ:state<=D_MAC;
     D_MAC:if(red==kdim-1)begin sent<=0;received<=0;state<=D_RQ;end else red<=red+1;
     D_RQ:begin if(math_accept)sent<=sent+1;if(math_take)begin codes[math_tag]<=math_result[7:0];received<=received+1;if(received==rows*8-1)begin store_index<=0;state<=D_STORE;end end end
     D_STORE:if(store_index==(kind==2?rows-1:7))state<=D_NEXT;else store_index<=store_index+1;
     D_NEXT:begin
      ci<=0;
      // One coefficient tile serves all thirteen token blocks. Full context
      // and O/FC2 output already fit the existing A1664/A2496 SRAM regions.
      if(token+8<99)begin token<=token+8;state<=D_CLEAR;end
      else if(oc+8<ndim)begin oc<=oc+8;token<=0;state<=D_COEFF;end
      else if(kind==3||kind==5)begin norm2<=kind==5;token<=0;norm_row<=0;state<=N_BEGIN;end
      else if(kind<2)begin kind<=kind+1;token<=0;oc<=0;state<=D_COEFF;end
      else if(kind==2)begin token<=0;read_c32(CB_SCORE_M,A_COEF0);end
      else begin token<=0;oc<=0;ch<=0;cache_valid<=0;state<=G_CACHE_FIRST;end
     end
     A_COEF0:begin score_m<=r32;read_c32(CB_SCORE_S,A_COEF1);end A_COEF1:begin score_s<=r32[7:0];read_c32(CB_CTX_M,A_COEF2);end
     A_COEF2:begin context_m<=r32;read_c32(CB_CTX_S,A_COEF3);end A_COEF3:begin context_s<=r32[7:0];kg<=0;state<=Q_CLEAR;end
     Q_CLEAR:begin red<=0;state<=Q_READ;end Q_READ:state<=Q_MAC;
     Q_MAC:if(red==63)begin store_index<=0;state<=Q_STORE;end else red<=red+1;
     Q_STORE:if(store_index==rows*8-1)begin
      if(kg==12)begin norm_row<=0;ch<=0;maximum<=-2147483647;state<=S_LOAD;end else begin kg<=kg+1;state<=Q_CLEAR;end
     end else store_index<=store_index+1;
     S_LOAD:state<=S_CAPTURE;
     S_CAPTURE:begin
      row_data[ch]<=mem_rdata[256+:32];
      if($signed(mem_rdata[256+:32])>maximum)maximum<=$signed(mem_rdata[256+:32]);
      if(ch==98)begin sent<=0;received<=0;exp_pending<=0;denominator<=0;state<=SM_RQ;end else ch<=ch+1;
     end
     SM_RQ:begin
      if(math_accept)sent<=sent+1;
      exp_pending<=math_take;if(math_take)begin exp_tag<=math_tag;exp_zero<=exp_index==4096;end
      if(exp_pending)begin
       row_data[exp_tag]<=exp_zero?0:mem_rdata[288+:32];
       denominator<=denominator+(exp_zero?0:mem_rdata[288+:32]);received<=received+1;
       if(received==98)begin exp_pending<=0;state<=SM_DIV;end
      end
     end
     SM_DIV:iterate(0,64'h800000000000,{32'd0,denominator},SM_DIV_RET);
     SM_DIV_RET:begin reciprocal<=iter_value+(iter_rem!=0);sent<=0;received<=0;state<=SM_ER;end
     SM_ER:begin
      if(math_accept)sent<=sent+1;
      if(math_take)begin probabilities[norm_row*99+math_tag]<=((math_result<<16)-math_result)>>47;received<=received+1;if(received==98)begin sent<=0;received<=0;state<=SM_QD;end end
     end
     SM_QD:begin
      if(math_accept)sent<=sent+1;
      if(math_take)begin
       probabilities[norm_row*99+math_tag]<=corrected_q+((remainder_value>denominator-remainder_value)||(remainder_value==denominator-remainder_value&&corrected_q[0]));received<=received+1;
       if(received==98)begin
        if(norm_row+1<rows)begin norm_row<=norm_row+1;ch<=0;maximum<=-2147483647;state<=S_LOAD;end
        else begin oc<=0;plane<=0;state<=P_CLEAR;end
       end
      end
     end
     P_CLEAR:begin red<=0;state<=P_READ;end P_READ:state<=P_MAC;
     P_MAC:if(red==98)state<=P_END;else red<=red+1;
     P_END:if(!plane)begin for(integer z=0;z<64;z=z+1)low_pv[z]<=$signed(acc[z*32+:32]);plane<=1;state<=P_CLEAR;end else begin sent<=0;received<=0;state<=P_RQ;end
     P_RQ:begin if(math_accept)sent<=sent+1;if(math_take)begin codes[math_tag]<=math_result[7:0];received<=received+1;if(received==rows*8-1)begin store_index<=0;state<=P_STORE;end end end
     P_STORE:if(store_index<7)store_index<=store_index+1;else if(oc<56)begin oc<=oc+8;plane<=0;state<=P_CLEAR;end
      else if(token+8<99)begin token<=token+8;kg<=0;state<=Q_CLEAR;end
      else begin kind<=3;token<=0;oc<=0;ci<=0;state<=D_COEFF;end
     N_BEGIN:if(cache_valid&&cache_norm2==norm2)begin ch<=0;state<=norm_row[0]?N_PAIR_LOAD:N_LOAD_FIRST;end else read_c64(norm2?CB_R2_COEFF:CB_R1_COEFF,N_C0);
     N_C0:begin res_m0<=r64[31:0];read_c64((norm2?CB_R2_COEFF:CB_R1_COEFF)+2,N_C1);end
     N_C1:begin res_m1<=r64[31:0];read_c64((norm2?CB_R2_COEFF:CB_R1_COEFF)+4,N_CS);end
     N_CS:begin res_s<=r64[7:0];read_c64(norm2?CB_LN2_EPS:CB_LN1_EPS,N_EPS);end
     N_EPS:begin eps_value<=r64;read_c32(norm2?CB_LN2_M:CB_LN1_M,N_M);end
     N_M:begin ln_m<=r32;read_c32(norm2?CB_LN2_S:CB_LN1_S,N_S);end
     N_S:begin ln_s<=r32[7:0];ch<=0;read_c32(norm2?CB_LN2_G:CB_LN1_G,N_CACHE_G);end
     N_CACHE_G:begin gamma_cache[ch]<=r32;read_c32((norm2?CB_LN2_B:CB_LN1_B)+ch,N_CACHE_B);end
     N_CACHE_B:begin beta_cache[ch]<=r32;if(ch==63)begin cache_valid<=1;cache_norm2<=norm2;ch<=0;state<=N_LOAD_FIRST;end else begin ch<=ch+1;state<=N_CACHE_NEXT;end end
     N_CACHE_NEXT:read_c32((norm2?CB_LN2_G:CB_LN1_G)+ch,N_CACHE_G);
     N_LOAD_FIRST:state<=N_LOAD_A;
     N_LOAD_A:begin r16<=mem_rdata[(8+(row_token%8)/2)*16+:16];residual_x<=mem_rdata[(8+(row_token%8)/2)*16+:8];state<=N_LOAD_B;end
     N_LOAD_B:begin
      residual[ch]<={mem_rdata[(8+(row_token%8)/2)*16+:8],residual_x};
      // PV has retired before either LN. Its scratch words hold the other
      // packed row's two S8 residual operands until that row is normalized.
      low_pv[ch][15:0]<={mem_rdata[(8+(row_token%8)/2)*16+8+:8],r16[15:8]};
      if(ch==63)begin sent<=0;received<=0;state<=N_RES;end else begin ch<=ch+1;state<=N_LOAD_A;end
     end
     N_PAIR_LOAD:begin
      for(integer z=0;z<64;z=z+1)residual[z]<=low_pv[z][15:0];
      sent<=0;received<=0;state<=N_RES;
     end
     N_RES:begin
      if(math_accept)sent<=sent+1;
      if(math_take)begin residual[math_tag]<=math_result[15:0];received<=received+1;if(received==63)begin sent<=0;received<=0;sum_s<=0;sum_t<=0;state<=N_SQUARE;end end
     end
     N_SQUARE:begin if(math_accept)begin sent<=sent+1;sum_s<=sum_s+$signed(residual[sent]);end if(math_take)begin sum_t<=sum_t+math_result;received<=received+1;if(received==63)state<=N_SUMSQ;end end
     N_SUMSQ:scalar(0,$signed(sum_s),$signed(sum_s),0,0,N_VAR);
     N_VAR:begin h_value<=(((sum_t<<6)-math_value)<<16)+eps_value;state<=N_SQRT;end
     N_SQRT:iterate(1,h_value,0,N_INV);N_INV:begin den_sqrt<=iter_value;iterate(0,64'h10000000000,iter_value,N_INV_RET);end
     N_INV_RET:begin ln_recip<=iter_value+((iter_rem>den_sqrt-iter_rem)||(iter_rem==den_sqrt-iter_rem&&iter_value[0]));norm_pass<=0;sent<=0;received<=0;state<=N_PASS;end
     N_PASS:begin
      if(math_accept)sent<=sent+1;
      if(math_take)begin
       if(norm_pass==2)codes[math_tag]<=math_result[7:0];else row_data[math_tag]<=norm_pass==1?math_result+{{32{beta_cache[math_tag][31]}},beta_cache[math_tag]}:math_result;
       received<=received+1;if(received==63)begin sent<=0;received<=0;if(norm_pass==2)begin ch<=0;state<=row_token==98?N_WRITE:norm_row[0]?N_PAIR_WRITE:N_PAIR_CACHE;end else norm_pass<=norm_pass+1;end
      end
     end
     N_WRITE:state<=N_RMW;N_RMW:if(ch==63)state<=N_WNEXT;else begin ch<=ch+1;state<=N_WRITE;end
     N_PAIR_CACHE:begin
      for(integer z=0;z<64;z=z+1)low_pv[z][23:16]<=codes[z];
      state<=N_WNEXT;
     end
     N_PAIR_WRITE:if(ch==63)state<=N_WNEXT;else ch<=ch+1;
     N_WNEXT:if(norm_row+1<rows)begin norm_row<=norm_row+1;state<=N_BEGIN;end
      else if(!norm2)begin
       if(token+8<99)begin token<=token+8;norm_row<=0;state<=N_BEGIN;end else begin kind<=4;token<=0;oc<=0;ci<=0;state<=D_COEFF;end
      end else if(token+8<99)begin token<=token+8;norm_row<=0;state<=N_BEGIN;end
      else if(layer<11)begin copy_address<=0;state<=COPY_READ;end else state<=LAYER_END;
     // LN1 gamma is dead. Reuse its 256 bytes for all 256 S8 GELU codes;
     // LN2 invalidates/reloads both affine coefficient arrays before use.
     G_CACHE_FIRST:state<=G_CACHE_LOAD;
     G_CACHE_LOAD:begin
      if(ch[0])gamma_cache[ch/2]<={mem_rdata[256+:16],low32[15:0]};else low32[15:0]<=mem_rdata[256+:16];
      if(ch==127)state<=G_READ;else ch<=ch+1;
     end
     G_READ:state<=G_CAPTURE;G_CAPTURE:begin for(integer z=0;z<8;z=z+1)if(z<(token<12?8:3))codes[z]<=$signed(mem_rdata[(12+z/2)*16+8*(z%2)+:8]);state<=G_APPLY;end
     G_APPLY:begin for(integer z=0;z<8;z=z+1)if(z<(token<12?8:3))codes[z]<=gamma_cache[($signed(codes[z])+128)/4]>>(8*(($signed(codes[z])+128)%4));state<=G_WRITE;end
     G_LUT:read_word(16,1880+(($signed(codes[gelu_lane])+128)/2),G_LUT_RET);
     G_LUT_RET:begin codes[gelu_lane]<=r16>>(8*(($signed(codes[gelu_lane])+128)%2));if(gelu_lane==(token<12?7:2))state<=G_WRITE;else begin gelu_lane<=gelu_lane+1;state<=G_LUT;end end
     G_WRITE:if(oc<255)begin oc<=oc+1;state<=G_READ;end else if(token<12)begin token<=token+1;oc<=0;state<=G_READ;end else begin kind<=5;token<=0;oc<=0;ci<=0;state<=D_COEFF;end
     COPY_READ:state<=COPY_WRITE;COPY_WRITE:if(copy_address==831)state<=LAYER_END;else begin copy_address<=copy_address+1;state<=COPY_READ;end
     LAYER_END:begin done<=1;state<=IDLE;end
     // No `default` here means the ~186 unused 8-bit state encodings are
     // don't-care for synthesis.  DC may then leave dangling inputs in the
     // next-state mux, and once `state` picks up an X it can never recover:
     // X matches no branch, so D = Q = X forever.  Gate-level sim on the
     // dc_synth5 netlist hit exactly that -- debug_state stuck at P_RQ(31)
     // then X, busy/done/error/common_ok all X in the next cycle while the
     // sticky-OR flags input_ok/layer_ok stayed 1 (status = 0000003X).
     // Fail closed instead of holding an undefined state.
     default:begin fault<=1;state<=FAILED;end
    endcase
   end
  end
 end
endmodule
