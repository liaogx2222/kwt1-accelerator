// Complete fixed-profile layer controller. All bulk storage is in kwt_banks.
// Scratch registers: one 99x32 row, 99x16 P row, 64x16 residual, three
// 64x8 result rows, eight low-PV accumulators and eight-channel coefficients.
// Scalar products/RNE use ONE physical kwt_math; no behavioral wide multiply.
module kwt_layer_banked(input wire clk,rst_n,enable,input wire start,output wire ready,
 input wire [3:0] layer_id,output reg done,output reg fault,output wire [7:0] debug_state,
 output reg [19:0] mem_en,mem_we,output reg [239:0] mem_addr,output reg [319:0] mem_wdata,
 input wire [319:0] mem_rdata);
 `include "kwt_profile.svh"
 localparam IDLE=0,D_COEFF=1,D_M=2,D_S=3,D_B=4,D_CLEAR=5,D_READ=6,D_MAC=7,D_RQ=8,D_STORE=9,D_NEXT=10,
 A_COEF0=11,A_COEF1=12,A_COEF2=13,A_COEF3=14,Q_CLEAR=15,Q_READ=16,Q_MAC=17,Q_STORE=18,
 SM_RQ=19,SM_EXP_READ=20,SM_EXP_STORE=21,SM_DIV=22,SM_DIV_RET=23,SM_ER=24,SM_ER_RET=25,SM_QD_RET=26,
 P_CLEAR=27,P_READ=28,P_MAC=29,P_END=30,P_RQ=31,P_STORE=32,
 N_BEGIN=33,N_C0=34,N_C1=35,N_CS=36,N_EPS=37,N_M=38,N_S=39,N_READ=40,N_A=41,N_AP=42,N_BP=43,N_RES=44,
 N_SQUARE=45,N_SUMSQ=46,N_VAR=47,N_SQRT=48,N_INV=49,N_INV_RET=50,N_CH=51,N_NORMAL=52,N_G=53,N_B=54,N_AFF=55,N_CODE=56,
 N_WRITE=57,N_RMW=58,N_WNEXT=59,G_READ=60,G_CAPTURE=61,G_LUT=62,G_LUT_RET=63,G_WRITE=64,
 COPY_READ=65,COPY_WRITE=66,LAYER_END=67,FAILED=68,
 READ16=80,RET16=81,WRITE16=82,C_READ=83,C_RET=84,C64_READ0=85,C64_RET0=86,C64_READ1=87,C64_RET1=88,
 M_REQ=90,M_WAIT=91,I_REQ=92,I_WAIT=93;
 reg [7:0] state,return_state;assign debug_state=state;assign ready=rst_n&&state==IDLE&&!fault;
 reg [3:0] layer;
 reg [2:0] kind;reg [6:0] token;reg [7:0] oc;reg [8:0] red;reg [3:0] kg;
 reg [7:0] sent,received;reg [6:0] ch;reg [3:0] ci,store_index;reg plane,norm2;
 reg [4:0] generic_bank;reg [11:0] generic_addr;reg [15:0] generic_wdata,r16;
 reg [11:0] coefficient_addr;reg [31:0] r32,low32;reg [63:0] r64;
 reg [31:0] multipliers[0:7],biases[0:7];reg signed [7:0] shifts[0:7];
 reg [7:0] codes[0:63];reg signed [7:0] context_row[0:63],vector_row[0:63];
 reg signed [31:0] row_data[0:98],low_pv[0:7];reg [15:0] probabilities[0:98];reg signed [15:0] residual[0:63];
 reg signed [31:0] maximum,sum_s;reg [63:0] sum_t;
 reg [31:0] score_m,context_m,denominator,reciprocal,ln_m,ln_recip;
 reg signed [7:0] score_s,context_s,ln_s,res_s;
 reg signed [31:0] res_m0,res_m1,normal_value,beta_value;
 reg signed [7:0] residual_x;
 reg [63:0] eps_value,residual_product,numerator,quotient,den_sqrt,h_value;
 reg [12:0] exponent_index;reg [9:0] copy_address;reg [3:0] gelu_lane;
 reg [1:0] math_op;reg [63:0] math_a,math_b,math_value;reg signed [7:0] math_shift;reg [5:0] math_sat;
 reg iter_sqrt;reg [63:0] iter_a,iter_b,iter_value,iter_rem;
 wire math_ready,math_valid,math_error;wire [63:0] math_result;wire [7:0] math_tag;
 reg logical_mvalid;reg [1:0] logical_mop;reg [63:0] logical_ma,logical_mb;reg signed [7:0] logical_ms;reg [5:0] logical_sat;reg [7:0] logical_tag;
 wire math_accept=enable&&logical_mvalid&&math_ready;
 wire math_take=enable&&math_valid&&(state==M_WAIT||state==D_RQ||state==SM_RQ||state==P_RQ||state==N_SQUARE);
 kwt_math math_unit(clk,rst_n,logical_mvalid&&enable,math_ready,logical_mop,logical_ma,logical_mb,logical_ms,logical_sat,logical_tag,
  math_valid,math_take,math_result,math_error,math_tag);
 wire iter_ready,iter_valid,iter_error;wire [63:0] iter_result,iter_remainder;
 kwt_iterative iterative_unit(clk,rst_n,enable&&state==I_REQ,iter_ready,iter_sqrt,iter_a,iter_b,
  iter_valid,enable&&state==I_WAIT,iter_result,iter_remainder,iter_error);
 reg mac_load,mac_en,mac_unsigned;reg [7:0] row_mask,col_mask;reg [63:0] mac_a,mac_b;reg [255:0] mac_bias;
 wire [2047:0] acc;
 kwt_mac8x8 pe(clk,rst_n,mac_load,mac_en,mac_unsigned,row_mask,col_mask,mac_a,mac_b,mac_bias,acc);
`ifdef KWT_SIM
 integer trace_file;reg [4095:0] trace_path;
 initial begin trace_file=0;if($value$plusargs("trace=%s",trace_path))trace_file=$fopen(trace_path,"w");end
 always @(posedge clk)if(rst_n&&trace_file)begin
  if(math_accept)$fdisplay(trace_file,"Q %0d %0d %0d %h %h %h %h %h",token,norm2,logical_mop,logical_ma,logical_mb,logical_ms,logical_sat,logical_tag);
  if(math_take)$fdisplay(trace_file,"R %0d %0d %h %h %b",token,norm2,math_tag,math_result,math_error);
 end
`endif
 integer rows,kdim,ndim,wb,cm,cs,cb,target_base,target_group,source_group,source_width;
 integer bank_index,word_address,waddress,physical_w,i,j,valid_keys;
 reg signed [31:0] folded_max;reg signed [31:0] centered;
 reg [63:0] corrected_q,corrected_prod,remainder_value;
 function automatic [15:0] word_at(input [319:0] data,input integer bank);begin word_at=data[bank*16+:16];end endfunction
 function automatic signed [7:0] byte_at(input [319:0] data,input integer bank,input integer high);begin byte_at=$signed((word_at(data,bank)>>(8*high))&16'hff);end endfunction
 function automatic signed [31:0] accumulator(input [2047:0] values,input integer index);begin accumulator=$signed(values[index*32+:32]);end endfunction
 task read_word(input integer bank,input integer address,input [7:0] resume);
  begin generic_bank<=bank;generic_addr<=address;return_state<=resume;state<=READ16;end
 endtask
 task write_word(input integer bank,input integer address,input [15:0] value,input [7:0] resume);
  begin generic_bank<=bank;generic_addr<=address;generic_wdata<=value;return_state<=resume;state<=WRITE16;end
 endtask
 task read_c32(input integer address,input [7:0] resume);
  begin coefficient_addr<=address;return_state<=resume;state<=C_READ;end
 endtask
 task read_c64(input integer address,input [7:0] resume);
  begin coefficient_addr<=address;return_state<=resume;state<=C64_READ0;end
 endtask
 task scalar(input [1:0] op,input [63:0] a,input [63:0] b,input signed [7:0] shift,input [5:0] sat,input [7:0] resume);
  begin math_op<=op;math_a<=a;math_b<=b;math_shift<=shift;math_sat<=sat;return_state<=resume;state<=M_REQ;end
 endtask
 task iterate(input sqrt_mode,input [63:0] a,input [63:0] b,input [7:0] resume);
  begin iter_sqrt<=sqrt_mode;iter_a<=a;iter_b<=b;return_state<=resume;state<=I_REQ;end
 endtask
 always @* begin
  case(kind)
   0:begin kdim=64;ndim=64;wb=WB_Q;cm=CB_Q_M;cs=CB_Q_S;cb=0;target_group=8;target_base=832;end
   1:begin kdim=64;ndim=64;wb=WB_K;cm=CB_K_M;cs=CB_K_S;cb=0;target_group=12;target_base=0;end
   2:begin kdim=64;ndim=64;wb=WB_V;cm=CB_V_M;cs=CB_V_S;cb=0;target_group=12;target_base=832;end
   3:begin kdim=64;ndim=64;wb=WB_O;cm=CB_O_M;cs=CB_O_S;cb=CB_O_B;target_group=8;target_base=1664;end
   4:begin kdim=64;ndim=256;wb=WB_FC1;cm=CB_FC1_M;cs=CB_FC1_S;cb=CB_FC1_B;target_group=12;target_base=0;end
   default:begin kdim=256;ndim=64;wb=WB_FC2;cm=CB_FC2_M;cs=CB_FC2_S;cb=CB_FC2_B;target_group=8;target_base=1664;end
  endcase
  source_group=kind==5?12:8;source_width=kind==5?256:64;
  rows=(kind==3||kind==5)?1:(token<92?8:99-token);
  waddress=wb+((oc/8)<<(kind==5?8:6))+red;
  valid_keys=kg==12?3:8;
  folded_max=maximum;for(integer fi=0;fi<8;fi=fi+1)if(fi<valid_keys&&accumulator(acc,fi)>folded_max)folded_max=accumulator(acc,fi);
  centered=($signed({{16{residual[ch][15]}},residual[ch]})<<<6)-sum_s;
  corrected_q=quotient;corrected_prod=math_value;
  if(corrected_prod>numerator)begin corrected_q=corrected_q-1;corrected_prod=corrected_prod-denominator;end
  remainder_value=numerator-corrected_prod;
 end
 always @* begin
  logical_mvalid=0;logical_mop=math_op;logical_ma=math_a;logical_mb=math_b;logical_ms=math_shift;logical_sat=math_sat;logical_tag=0;
  if(state==M_REQ)logical_mvalid=1;
  if(state==D_RQ&&sent<rows*8)begin logical_mvalid=1;logical_mop=3;logical_ma=accumulator(acc,sent);logical_mb={32'd0,multipliers[sent%8]};logical_ms=shifts[sent%8];logical_sat=8;logical_tag=sent;end
  if(state==SM_RQ&&sent<99)begin logical_mvalid=1;logical_mop=3;logical_ma=$signed(row_data[sent])-$signed(maximum);logical_mb={32'd0,score_m};logical_ms=score_s;logical_sat=0;logical_tag=sent;end
  if(state==P_RQ&&sent<8)begin
   logical_mvalid=1;logical_mop=3;logical_ma=($signed(accumulator(acc,sent))<<<8)+$signed(low_pv[sent]);logical_mb={32'd0,context_m};logical_ms=context_s;logical_sat=8;logical_tag=sent;
  end
  if(state==N_SQUARE&&sent<64)begin logical_mvalid=1;logical_mop=0;logical_ma=$signed(residual[sent]);logical_mb=$signed(residual[sent]);logical_ms=0;logical_sat=0;logical_tag=sent;end
 end
 always @* begin
  mem_en=0;mem_we=0;mem_addr=0;mem_wdata=0;
  bank_index=0;word_address=0;physical_w=0;
  if(enable&&rst_n)case(state)
   READ16,WRITE16:begin mem_en[generic_bank]=1;mem_we[generic_bank]=state==WRITE16;mem_addr[generic_bank*12+:12]=generic_addr;mem_wdata[generic_bank*16+:16]=generic_wdata;end
   C_READ,C64_READ0,C64_READ1:begin
    mem_en[16]=1;mem_en[17]=1;
    mem_addr[16*12+:12]=coefficient_addr+(state==C64_READ1);mem_addr[17*12+:12]=coefficient_addr+(state==C64_READ1);
   end
   D_READ:begin
    for(j=0;j<4;j=j+1)begin
     physical_w=2*j+(waddress/4096);mem_en[physical_w]=1;mem_addr[physical_w*12+:12]=waddress%4096;
     if(kind!=3&&kind!=5)begin mem_en[8+j]=1;mem_addr[(8+j)*12+:12]=(token/8)*64+red;end
    end
    if(kind==5)begin bank_index=12+(token%8)/2;mem_en[bank_index]=1;mem_addr[bank_index*12+:12]=(token/8)*256+red;end
   end
   D_STORE:begin
    if(kind==2)begin
     for(j=0;j<4;j=j+1)begin mem_en[12+j]=1;mem_we[12+j]=1;mem_addr[(12+j)*12+:12]=832+(token+store_index)*8+oc/8;mem_wdata[(12+j)*16+:16]={codes[store_index*8+2*j+1],codes[store_index*8+2*j]};end
    end else if(kind!=3&&kind!=5)begin
     for(j=0;j<4;j=j+1)if(2*j<rows)begin
      mem_en[target_group+j]=1;mem_we[target_group+j]=1;mem_addr[(target_group+j)*12+:12]=target_base+((token/8)<<(kind==4?8:6))+oc+store_index;
      mem_wdata[(target_group+j)*16+:16]={8'd0,codes[(2*j)*8+store_index]};
      if(2*j+1<rows)mem_wdata[(target_group+j)*16+8+:8]=codes[(2*j+1)*8+store_index];
     end
    end
   end
   Q_READ:begin
    bank_index=8+(token%8)/2;mem_en[bank_index]=1;mem_addr[bank_index*12+:12]=832+(token/8)*64+red;
    for(j=0;j<4;j=j+1)begin mem_en[12+j]=1;mem_addr[(12+j)*12+:12]=kg*64+red;end
   end
   SM_EXP_READ:if(exponent_index!=4096)begin mem_en[18]=1;mem_en[19]=1;mem_addr[18*12+:12]=exponent_index;mem_addr[19*12+:12]=exponent_index;end
   P_READ:for(j=0;j<4;j=j+1)begin mem_en[12+j]=1;mem_addr[(12+j)*12+:12]=832+red*8+oc/8;end
   G_READ:for(j=0;j<4;j=j+1)if(2*j<(token<12?8:3))begin mem_en[12+j]=1;mem_addr[(12+j)*12+:12]=token*256+oc;end
   G_WRITE:for(j=0;j<4;j=j+1)if(2*j<(token<12?8:3))begin
    mem_en[12+j]=1;mem_we[12+j]=1;mem_addr[(12+j)*12+:12]=token*256+oc;mem_wdata[(12+j)*16+:16]={8'd0,codes[j*2]};
    if(2*j+1<(token<12?8:3))mem_wdata[(12+j)*16+8+:8]=codes[j*2+1];
   end
   COPY_READ:for(j=0;j<4;j=j+1)begin mem_en[8+j]=1;mem_addr[(8+j)*12+:12]=832+copy_address;end
   COPY_WRITE:for(j=0;j<4;j=j+1)begin mem_en[8+j]=1;mem_we[8+j]=1;mem_addr[(8+j)*12+:12]=copy_address;mem_wdata[(8+j)*16+:16]=word_at(mem_rdata,8+j);end
  endcase
 end
 always @* begin
  mac_load=0;mac_en=0;mac_unsigned=0;row_mask=0;col_mask=8'hff;mac_a=0;mac_b=0;mac_bias=0;
  if(state==D_CLEAR||state==D_MAC)begin
   row_mask=(9'd1<<rows)-1;for(integer mi=0;mi<8;mi=mi+1)mac_bias[mi*32+:32]=biases[mi];
   if(kind==3)mac_a[7:0]=context_row[red];
   else if(kind==5)mac_a[7:0]=byte_at(mem_rdata,12+(token%8)/2,token%2);
   else for(integer ai=0;ai<4;ai=ai+1)mac_a[ai*16+:16]=word_at(mem_rdata,8+ai);
   for(integer bi=0;bi<4;bi=bi+1)mac_b[bi*16+:16]=word_at(mem_rdata,2*bi+(waddress/4096));
  end
  if(state==Q_CLEAR||state==Q_MAC)begin
   row_mask=1;col_mask=(9'd1<<valid_keys)-1;mac_a[7:0]=byte_at(mem_rdata,8+(token%8)/2,token%2);
   for(integer qi=0;qi<4;qi=qi+1)mac_b[qi*16+:16]=word_at(mem_rdata,12+qi);
  end
  if(state==P_CLEAR||state==P_MAC)begin
   row_mask=1;mac_unsigned=1;mac_a[7:0]=probabilities[red]>>(plane?8:0);
   for(integer pi=0;pi<4;pi=pi+1)mac_b[pi*16+:16]=word_at(mem_rdata,12+pi);
  end
  if(enable&&rst_n)begin mac_load=state==D_CLEAR||state==Q_CLEAR||state==P_CLEAR;mac_en=state==D_MAC||state==Q_MAC||state==P_MAC;end
 end
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin
   state<=IDLE;return_state<=IDLE;layer<=0;kind<=0;token<=0;oc<=0;red<=0;kg<=0;sent<=0;received<=0;ch<=0;ci<=0;store_index<=0;plane<=0;norm2<=0;
   generic_bank<=0;generic_addr<=0;generic_wdata<=0;r16<=0;coefficient_addr<=0;r32<=0;low32<=0;r64<=0;maximum<=0;sum_s<=0;sum_t<=0;
   score_m<=0;score_s<=0;context_m<=0;context_s<=0;denominator<=0;reciprocal<=0;ln_m<=0;ln_s<=0;ln_recip<=0;res_s<=0;res_m0<=0;res_m1<=0;
   normal_value<=0;beta_value<=0;residual_x<=0;eps_value<=0;residual_product<=0;numerator<=0;quotient<=0;den_sqrt<=0;h_value<=0;exponent_index<=0;copy_address<=0;gelu_lane<=0;
   math_op<=0;math_a<=0;math_b<=0;math_value<=0;math_shift<=0;math_sat<=0;iter_sqrt<=0;iter_a<=0;iter_b<=0;iter_value<=0;iter_rem<=0;done<=0;fault<=0;
  end else begin
   done<=0;
   if(enable)case(state)
    IDLE:if(start&&!fault)begin layer<=layer_id;kind<=0;token<=0;oc<=0;ci<=0;state<=D_COEFF;end
    READ16:state<=RET16;
    RET16:begin r16<=word_at(mem_rdata,generic_bank);state<=return_state;end
    WRITE16:state<=return_state;
    C_READ:state<=C_RET;
    C_RET:begin r32<={word_at(mem_rdata,17),word_at(mem_rdata,16)};state<=return_state;end
    C64_READ0:state<=C64_RET0;
    C64_RET0:begin low32<={word_at(mem_rdata,17),word_at(mem_rdata,16)};state<=C64_READ1;end
    C64_READ1:state<=C64_RET1;
    C64_RET1:begin r64<={word_at(mem_rdata,17),word_at(mem_rdata,16),low32};state<=return_state;end
    M_REQ:if(math_accept)state<=M_WAIT;
    M_WAIT:if(math_take)begin math_value<=math_result;if(math_error)begin fault<=1;state<=FAILED;end else state<=return_state;end
    I_REQ:if(iter_ready)state<=I_WAIT;
    I_WAIT:if(iter_valid)begin iter_value<=iter_result;iter_rem<=iter_remainder;if(iter_error)begin fault<=1;state<=FAILED;end else state<=return_state;end
    D_COEFF:read_c32(cm+oc+ci,D_M);
    D_M:begin multipliers[ci]<=r32;read_c32(cs+oc+ci,D_S);end
    D_S:begin shifts[ci]<=r32[7:0];if(kind<3)begin biases[ci]<=0;if(ci==7)state<=D_CLEAR;else begin ci<=ci+1;state<=D_COEFF;end end else read_c32(cb+oc+ci,D_B);end
    D_B:begin biases[ci]<=r32;if(ci==7)state<=D_CLEAR;else begin ci<=ci+1;state<=D_COEFF;end end
    D_CLEAR:begin red<=0;state<=D_READ;end
    D_READ:state<=D_MAC;
    D_MAC:if(red==kdim-1)begin sent<=0;received<=0;state<=D_RQ;end else begin red<=red+1;state<=D_READ;end
    D_RQ:begin
     if(math_accept)sent<=sent+1;
     if(math_take)begin codes[math_tag]<=math_result[7:0];received<=received+1;
      if(math_error)begin fault<=1;state<=FAILED;end
      else if(received==rows*8-1)begin store_index<=0;state<=D_STORE;end
     end
    end
    D_STORE:begin
     if(kind==3||kind==5)begin for(integer z=0;z<8;z=z+1)vector_row[oc+z]<=codes[z];state<=D_NEXT;end
     else if(store_index==(kind==2?rows-1:7))state<=D_NEXT;else store_index<=store_index+1;
    end
    D_NEXT:begin
     ci<=0;
     if(oc+8<ndim)begin oc<=oc+8;state<=D_COEFF;end
     else if(kind==3||kind==5)begin norm2<=kind==5;ch<=0;state<=N_BEGIN;end
     else if(token+8<99)begin token<=token+8;oc<=0;state<=D_COEFF;end
     else if(kind<2)begin kind<=kind+1;token<=0;oc<=0;state<=D_COEFF;end
     else if(kind==2)begin token<=0;read_c32(CB_SCORE_M,A_COEF0);end
     else begin token<=0;oc<=0;state<=G_READ;end
    end
    A_COEF0:begin score_m<=r32;read_c32(CB_SCORE_S,A_COEF1);end
    A_COEF1:begin score_s<=r32[7:0];read_c32(CB_CTX_M,A_COEF2);end
    A_COEF2:begin context_m<=r32;read_c32(CB_CTX_S,A_COEF3);end
    A_COEF3:begin context_s<=r32[7:0];kg<=0;maximum<=-2147483647;state<=Q_CLEAR;end
    Q_CLEAR:begin red<=0;state<=Q_READ;end
    Q_READ:state<=Q_MAC;
    Q_MAC:if(red==63)state<=Q_STORE;else begin red<=red+1;state<=Q_READ;end
    Q_STORE:begin
     for(integer z=0;z<8;z=z+1)if(z<valid_keys)row_data[kg*8+z]<=accumulator(acc,z);
     maximum<=folded_max;
     if(kg==12)begin sent<=0;received<=0;denominator<=0;state<=SM_RQ;end else begin kg<=kg+1;state<=Q_CLEAR;end
    end
    SM_RQ:begin
     if(math_accept)sent<=sent+1;
     if(math_take)begin
      exponent_index<=$signed(math_result)>=0?0:($signed(math_result)< -4096?4096:-$signed(math_result));
      if(math_error)begin fault<=1;state<=FAILED;end else state<=SM_EXP_READ;
     end
    end
    SM_EXP_READ:state<=SM_EXP_STORE;
    SM_EXP_STORE:begin
     row_data[received]<=exponent_index==4096?0:{word_at(mem_rdata,19),word_at(mem_rdata,18)};
     denominator<=denominator+(exponent_index==4096?0:{word_at(mem_rdata,19),word_at(mem_rdata,18)});
     received<=received+1;if(received==98)state<=SM_DIV;else state<=SM_RQ;
    end
    SM_DIV:iterate(0,64'h800000000000,{32'd0,denominator},SM_DIV_RET);
    SM_DIV_RET:begin reciprocal<=iter_value+(iter_rem!=0);ch<=0;state<=SM_ER;end
    SM_ER:scalar(1,{32'd0,row_data[ch]},{32'd0,reciprocal},0,0,SM_ER_RET);
    SM_ER_RET:begin
     numerator<=({32'd0,row_data[ch]}<<16)-{32'd0,row_data[ch]};quotient<=((math_value<<16)-math_value)>>47;
     scalar(1,((math_value<<16)-math_value)>>47,{32'd0,denominator},0,0,SM_QD_RET);
    end
    SM_QD_RET:begin
     probabilities[ch]<=corrected_q+((remainder_value>denominator-remainder_value)||(remainder_value==denominator-remainder_value&&corrected_q[0]));
     if(ch==98)begin oc<=0;plane<=0;state<=P_CLEAR;end else begin ch<=ch+1;state<=SM_ER;end
    end
    P_CLEAR:begin red<=0;state<=P_READ;end
    P_READ:state<=P_MAC;
    P_MAC:if(red==98)state<=P_END;else begin red<=red+1;state<=P_READ;end
    P_END:if(!plane)begin for(integer z=0;z<8;z=z+1)low_pv[z]<=accumulator(acc,z);plane<=1;state<=P_CLEAR;end else begin sent<=0;received<=0;state<=P_RQ;end
    P_RQ:begin
     if(math_accept)sent<=sent+1;
     if(math_take)begin codes[math_tag]<=math_result[7:0];received<=received+1;if(math_error)begin fault<=1;state<=FAILED;end else if(received==7)state<=P_STORE;end
    end
    P_STORE:begin
     for(integer z=0;z<8;z=z+1)context_row[oc+z]<=codes[z];
     if(oc<56)begin oc<=oc+8;plane<=0;state<=P_CLEAR;end else begin kind<=3;oc<=0;ci<=0;state<=D_COEFF;end
    end
    N_BEGIN:read_c64(norm2?CB_R2_COEFF:CB_R1_COEFF,N_C0);
    N_C0:begin res_m0<=r64[31:0];read_c64((norm2?CB_R2_COEFF:CB_R1_COEFF)+2,N_C1);end
    N_C1:begin res_m1<=r64[31:0];read_c64((norm2?CB_R2_COEFF:CB_R1_COEFF)+4,N_CS);end
    N_CS:begin res_s<=r64[7:0];read_c64(norm2?CB_LN2_EPS:CB_LN1_EPS,N_EPS);end
    N_EPS:begin eps_value<=r64;read_c32(norm2?CB_LN2_M:CB_LN1_M,N_M);end
    N_M:begin ln_m<=r32;read_c32(norm2?CB_LN2_S:CB_LN1_S,N_S);end
    N_S:begin ln_s<=r32[7:0];ch<=0;state<=N_READ;end
    N_READ:read_word(8+(token%8)/2,(token/8)*64+ch,N_A);
    N_A:begin residual_x<=$signed(r16>>(8*(token%2)));scalar(0,token[0]?{{56{r16[15]}},r16[15:8]}:{{56{r16[7]}},r16[7:0]},$signed(res_m0),0,0,N_AP);end
    N_AP:begin residual_product<=math_value;scalar(0,$signed(vector_row[ch]),$signed(res_m1),0,0,N_BP);end
    N_BP:scalar(2,$signed(residual_product)+$signed(math_value),0,res_s,16,N_RES);
    N_RES:begin residual[ch]<=math_value[15:0];if(ch==63)begin sent<=0;received<=0;sum_s<=0;sum_t<=0;state<=N_SQUARE;end else begin ch<=ch+1;state<=N_READ;end end
    N_SQUARE:begin
     if(math_accept)begin sent<=sent+1;sum_s<=sum_s+$signed(residual[sent]);end
     if(math_take)begin sum_t<=sum_t+math_result;received<=received+1;if(math_error)begin fault<=1;state<=FAILED;end else if(received==63)state<=N_SUMSQ;end
    end
    N_SUMSQ:scalar(0,$signed(sum_s),$signed(sum_s),0,0,N_VAR);
    N_VAR:begin h_value<=(((sum_t<<6)-math_value)<<16)+eps_value;state<=N_SQRT;end
    N_SQRT:iterate(1,h_value,0,N_INV);
    N_INV:begin den_sqrt<=iter_value;iterate(0,64'h10000000000,iter_value,N_INV_RET);end
    N_INV_RET:begin ln_recip<=iter_value+((iter_rem>den_sqrt-iter_rem)||(iter_rem==den_sqrt-iter_rem&&iter_value[0]));ch<=0;state<=N_CH;end
    N_CH:scalar(3,$signed(centered),{32'd0,ln_recip},18,0,N_NORMAL);
    N_NORMAL:begin normal_value<=math_value[31:0];read_c32((norm2?CB_LN2_G:CB_LN1_G)+ch,N_G);end
    N_G:begin math_b<=$signed(r32);read_c32((norm2?CB_LN2_B:CB_LN1_B)+ch,N_B);end
    N_B:begin beta_value<=r32;scalar(3,$signed(normal_value),math_b,14,0,N_AFF);end
    N_AFF:scalar(3,$signed(math_value)+$signed(beta_value),{32'd0,ln_m},ln_s,8,N_CODE);
    N_CODE:begin codes[ch]<=math_value[7:0];if(ch==63)begin ch<=0;state<=N_WRITE;end else begin ch<=ch+1;state<=N_CH;end end
    N_WRITE:read_word(8+(token%8)/2,(norm2?832:0)+(token/8)*64+ch,N_RMW);
    N_RMW:write_word(8+(token%8)/2,(norm2?832:0)+(token/8)*64+ch,
      token[0]?{codes[ch],r16[7:0]}:{r16[15:8],codes[ch]},N_WNEXT);
    N_WNEXT:begin
     if(ch<63)begin ch<=ch+1;state<=N_WRITE;end
     else if(!norm2)begin
      if(token<98)begin token<=token+1;kg<=0;maximum<=-2147483647;state<=Q_CLEAR;end
      else begin kind<=4;token<=0;oc<=0;ci<=0;state<=D_COEFF;end
     end else if(token<98)begin kind<=5;token<=token+1;oc<=0;ci<=0;state<=D_COEFF;end
     else if(layer<11)begin copy_address<=0;state<=COPY_READ;end else state<=LAYER_END;
    end
    G_READ:state<=G_CAPTURE;
    G_CAPTURE:begin for(integer z=0;z<8;z=z+1)if(z<(token<12?8:3))codes[z]<=byte_at(mem_rdata,12+z/2,z%2);gelu_lane<=0;state<=G_LUT;end
    G_LUT:read_word(16,1880+(($signed(codes[gelu_lane])+128)/2),G_LUT_RET);
    G_LUT_RET:begin codes[gelu_lane]<=r16>>(8*(($signed(codes[gelu_lane])+128)%2));if(gelu_lane==(token<12?7:2))state<=G_WRITE;else begin gelu_lane<=gelu_lane+1;state<=G_LUT;end end
    G_WRITE:if(oc<255)begin oc<=oc+1;state<=G_READ;end else if(token<12)begin token<=token+1;oc<=0;state<=G_READ;end else begin kind<=5;token<=0;oc<=0;ci<=0;state<=D_COEFF;end
    COPY_READ:state<=COPY_WRITE;
    COPY_WRITE:if(copy_address==831)state<=LAYER_END;else begin copy_address<=copy_address+1;state<=COPY_READ;end
    LAYER_END:begin done<=1;state<=IDLE;end
   endcase
  end
 end
endmodule
