// Fixed INTEGER_NUMERICS_V1. eight-query attention, eight-row O/FC2 with sixteen output columns, synchronous
// prefetch/MAC overlap; exact residual and LN/Softmax element pipelines.
// C[2048:2839] holds one 8x99 S32 score block. All bulk tensors use 20 SP macros.
module kwt_layer_banked(input wire clk,rst_n,enable,input wire start,output wire ready,
 input wire [3:0] layer_id,output reg done,output reg fault,output wire [7:0] debug_state,
 output reg [19:0] mem_en,mem_we,output reg [239:0] mem_addr,output reg [319:0] mem_wdata,input wire [319:0] mem_rdata,
 input wire parameter_slot,output reg prefetch_ready);
 `include "kwt_profile.svh"
 localparam ROWS=8;
 reg mac_load,mac_en,mac_unsigned;reg [ROWS-1:0] row_mask;reg [15:0] col_mask;reg [ROWS*16-1:0] mac_a;reg [127:0] mac_b;reg [511:0] mac_bias;wire [ROWS*16*32-1:0] acc;
 integer rows,kdim,ndim,wb,cm,cs,cb,target_base,target_group,source_group,source_base,source_width,waddress,read_red,bank_index,physical_w,j,valid_keys,row_token;
 localparam IDLE=0,D_COEFF=1,D_M=2,D_S=3,D_B=4,D_CLEAR=5,D_READ=6,D_MAC=7,D_RQ=8,D_STORE=9,D_NEXT=10,
 A_COEF0=11,A_COEF1=12,A_COEF2=13,A_COEF3=14,Q_CLEAR=15,Q_READ=16,Q_MAC=17,Q_STORE=18,
 SM_RQ=19,SM_DIV=22,SM_DIV_RET=23,SM_ER=24,SM_QD=26,
 P_CLEAR=27,P_READ=28,P_MAC=29,P_END=30,P_RQ=31,P_STORE=32,
 N_BEGIN=33,N_C0=34,N_C1=35,N_CS=36,N_EPS=37,N_M=38,N_S=39,N_LOAD_A=40,N_LOAD_B=41,N_LOAD_FIRST=42,N_RES=44,
 N_SQUARE=45,N_SUMSQ=46,N_VAR=47,N_SQRT=48,N_INV=49,N_INV_RET=50,N_PASS=51,N_CACHE_G=53,N_CACHE_B=54,N_CACHE_NEXT=55,
 N_WRITE=57,N_RMW=58,N_WNEXT=59,G_READ=60,G_CAPTURE=61,G_LUT=62,G_LUT_RET=63,G_WRITE=64,
 COPY_READ=65,COPY_WRITE=66,LAYER_END=67,FAILED=68,S_LOAD=69,S_CAPTURE=70,G_CACHE_FIRST=71,G_CACHE_LOAD=72,G_APPLY=73,
 N_PAIR_LOAD=74,N_PAIR_CACHE=75,N_PAIR_WRITE=76,Q_PREFETCH=77,Q_CAPTURE=78,
 READ16=80,RET16=81,C_READ=83,C_RET=84,C64_READ0=85,C64_RET0=86,C64_READ1=87,C64_RET1=88,M_REQ=90,M_WAIT=91,I_REQ=92,I_WAIT=93;
 reg [7:0] state,return_state;assign debug_state=state;assign ready=rst_n&&state==IDLE&&!fault;
 reg [3:0] layer;reg [2:0] kind;reg [6:0] token,ch;reg [7:0] oc;reg [8:0] sent,received;reg [8:0] red;reg [3:0] kg,ci;
 reg [7:0] store_index;reg [3:0] norm_row;reg norm2,cache_valid,cache_norm2;reg [1:0] norm_pass;
 reg [4:0] generic_bank;reg [11:0] generic_addr,coefficient_addr;reg [15:0] r16;reg [31:0] r32,low32;reg [63:0] r64;
 reg [31:0] multipliers[0:15],biases[0:15];reg signed [7:0] shifts[0:15];reg [7:0] codes[0:ROWS*16-1];
 reg signed [31:0] row_data[0:98],low_pv[0:ROWS*16-1];
 reg [15:0] probabilities[0:ROWS*99-1];
 // Attention probabilities are dead before either LN and GELU begins.
 // Reuse their first 256 halfwords for the two 64x32 coefficient caches.
 // LN gathers all eight rows: A16 operands use probabilities[256:767];
 // B8 operands use all512 bytes of low_pv. Each retired even row reuses
 // its dead B8 slots for the paired output until the following row writes.
 wire signed [31:0] gamma_cache[0:63],beta_cache[0:63];
 wire signed [23:0] residual[0:63];genvar cache_word;
 generate for(cache_word=0;cache_word<64;cache_word=cache_word+1)begin:cache_alias
  assign gamma_cache[cache_word]={probabilities[2*cache_word+1],probabilities[2*cache_word]};
  assign beta_cache[cache_word]={probabilities[128+2*cache_word+1],probabilities[128+2*cache_word]};
  assign residual[cache_word]={low_pv[2*cache_word+norm_row/4][8*(norm_row%4)+:8],probabilities[256+norm_row*64+cache_word]};
 end endgenerate
 reg signed [31:0] maximum,sum_s,res_m0,res_m1;reg [63:0] sum_t,eps_value,den_sqrt,h_value;
 reg [31:0] score_m,context_m,denominator,reciprocal,ln_m,ln_recip;reg signed [7:0] score_s,context_s,ln_s,res_s;
 reg [15:0] residual_x;reg [9:0] copy_address;reg [3:0] gelu_lane;
 reg exp_pending,exp_zero;reg [7:0] exp_tag;
 reg [2:0] math_op;reg [63:0] math_a,math_b,math_value;reg signed [7:0] math_shift;reg [5:0] math_sat;
 reg iter_sqrt;reg [63:0] iter_a,iter_b,iter_value,iter_rem;
 wire [3:0] lane_ready,lane_valid,lane_error,request_mask;reg [3:0] response_mask;
 wire [63:0] lane_result[0:3];wire [7:0] lane_tag[0:3];
 reg [2:0] lane_op[0:3];reg [63:0] lane_a[0:3],lane_b[0:3];
 reg signed [7:0] lane_shift[0:3];reg [5:0] lane_sat[0:3];reg [7:0] request_tag[0:3];
 wire vector_state=state==D_RQ||state==SM_ER||state==SM_QD||state==P_RQ||state==N_RES||state==N_SQUARE||state==N_PASS;
 wire math_ready=&(lane_ready|~request_mask);
 wire math_valid=(|response_mask)&&(&(lane_valid|~response_mask));
 wire logical_mvalid=|request_mask;
 wire [2:0] logical_mop=lane_op[0];wire [63:0] logical_ma=lane_a[0],logical_mb=lane_b[0];
 wire signed [7:0] logical_ms=lane_shift[0];wire [5:0] logical_sat=lane_sat[0];wire [7:0] logical_tag=request_tag[0];
 wire [63:0] math_result=lane_result[0];wire [7:0] math_tag=lane_tag[0];
 wire math_accept=enable&&logical_mvalid&&math_ready;
 wire math_take=enable&&math_valid;
 integer issue_count,take_count,mask_lane,output_limit;reg tag_error;
 wire math_error=(|(lane_error&lane_valid&response_mask))||tag_error;
 wire [7:0] write_index[0:3],dense_write_index[0:3];
 reg signed [31:0] sum_s_batch;reg [63:0] sum_t_batch;
 reg [63:0] corrected_q_lane[0:3],remainder_lane[0:3];
 always @*begin
  response_mask=0;output_limit=0;
  case(state)
   D_RQ:output_limit=kind==2?rows*16:(rows==3?64:128);
   P_RQ:output_limit=rows*16;
   SM_ER,SM_QD:output_limit=99;
   N_RES,N_SQUARE,N_PASS:output_limit=64;
   default:output_limit=0;
  endcase
  if(state==M_WAIT||state==SM_RQ)response_mask=1;
  else for(mask_lane=0;mask_lane<4;mask_lane=mask_lane+1)
   if(received+mask_lane<output_limit&&!(state==D_RQ&&kind!=2&&rows==3&&mask_lane==3))response_mask[mask_lane]=1;
  issue_count=0;take_count=0;tag_error=0;sum_s_batch=0;sum_t_batch=0;
  for(mask_lane=0;mask_lane<4;mask_lane=mask_lane+1)begin
   if(request_mask[mask_lane])issue_count=issue_count+1;
   if(response_mask[mask_lane])take_count=take_count+1;
   if(vector_state&&response_mask[mask_lane]&&lane_valid[mask_lane]&&
      lane_tag[mask_lane]!=((state==D_RQ&&kind!=2)?dense_write_index[mask_lane]:received+mask_lane))tag_error=1;
   if(state==N_SQUARE&&request_mask[mask_lane])sum_s_batch=sum_s_batch+$signed(residual[(sent>>2)*4+mask_lane]);
   if(state==N_SQUARE&&response_mask[mask_lane])sum_t_batch=sum_t_batch+lane_result[mask_lane];
  end
 end
 // Atomic request fork / response join. Each lane ready is independent of
 // request valid; no lane can accept alone. Masked tails need no fake request.
 kwt_math math_unit(clk,rst_n,math_accept&&request_mask[0],lane_ready[0],lane_op[0],lane_a[0],lane_b[0],lane_shift[0],lane_sat[0],request_tag[0],
  lane_valid[0],math_take&&response_mask[0],lane_result[0],lane_error[0],lane_tag[0]);
 genvar ml;
 generate for(ml=0;ml<4;ml=ml+1)begin:math_lanes
  reg offered;integer element;reg [63:0] numerator_l,product_l;
  assign request_mask[ml]=offered;
  // Non-V dense retirement visits four rows of one column at a time.
  // Each lane pair then writes one existing packed-row SRAM word.
  // Three-row tails use three active lanes, with a four-slot cursor.
  // Keep the dense permutation out of all other vector write decoders.
  assign dense_write_index[ml]=(rows==3?ml:({received[2],2'b00}+ml))*16+
   (rows==3?received[5:2]:received[6:3]);
  assign write_index[ml]={received[7:2],2'b00}+ml;
  if(ml!=0)begin:extra
   kwt_math unit_i(clk,rst_n,math_accept&&request_mask[ml],lane_ready[ml],lane_op[ml],lane_a[ml],lane_b[ml],lane_shift[ml],lane_sat[ml],request_tag[ml],
    lane_valid[ml],math_take&&response_mask[ml],lane_result[ml],lane_error[ml],lane_tag[ml]);
  end
  always @*begin
   offered=0;element=(sent>>2)*4+ml;lane_op[ml]=math_op;lane_a[ml]=math_a;lane_b[ml]=math_b;
   lane_shift[ml]=math_shift;lane_sat[ml]=math_sat;request_tag[ml]=element;
   if(state==M_REQ&&ml==0)begin offered=1;request_tag[ml]=0;end
   if(state==SM_RQ&&ml==0&&sent<99)begin
    offered=1;request_tag[ml]=sent;lane_op[ml]=3;lane_a[ml]=$signed(row_data[sent])-$signed(maximum);
    lane_b[ml]={32'd0,score_m};lane_shift[ml]=score_s;lane_sat[ml]=0;
   end
   if(state==D_RQ)begin
    if(kind!=2)element=(rows==3?ml:({sent[2],2'b00}+ml))*16+(rows==3?sent[5:2]:sent[6:3]);
    if((kind==2&&element<rows*16)||(kind!=2&&sent<output_limit&&(rows!=3||ml<3)))begin
     offered=1;request_tag[ml]=element;lane_op[ml]=3;lane_a[ml]=$signed(acc[element*32+:32]);
     lane_b[ml]={32'd0,multipliers[element%16]};lane_shift[ml]=shifts[element%16];lane_sat[ml]=8;
    end
   end
   if(state==SM_ER&&sent<99&&element<99)begin offered=1;lane_op[ml]=1;lane_a[ml]={32'd0,row_data[element]};lane_b[ml]={32'd0,reciprocal};lane_shift[ml]=0;lane_sat[ml]=0;end
   if(state==SM_QD&&sent<99&&element<99)begin offered=1;lane_op[ml]=1;lane_a[ml]={48'd0,probabilities[norm_row*99+element]};lane_b[ml]={32'd0,denominator};lane_shift[ml]=0;lane_sat[ml]=0;end
   if(state==P_RQ&&element<rows*16)begin offered=1;lane_op[ml]=3;lane_a[ml]=$signed(acc[element*32+:32]);lane_b[ml]={32'd0,context_m};lane_shift[ml]=context_s;lane_sat[ml]=8;end
   if(state==N_RES&&sent<128)begin
    element=(sent>>3)*4+ml;offered=1;lane_op[ml]=4;request_tag[ml]=(element<<1)|sent[2];
    lane_a[ml]=sent[2]?$signed(residual[element][23:16]):$signed(residual[element][15:0]);
    lane_b[ml]=sent[2]?$signed(res_m1):$signed(res_m0);lane_shift[ml]=res_s;lane_sat[ml]=16;
   end
   if(state==N_SQUARE&&element<64)begin offered=1;lane_op[ml]=0;lane_a[ml]=$signed(residual[element]);lane_b[ml]=$signed(residual[element]);lane_shift[ml]=0;lane_sat[ml]=0;end
   if(state==N_PASS&&element<64)begin
    offered=1;lane_op[ml]=3;lane_sat[ml]=norm_pass==2?8:0;
    lane_a[ml]=norm_pass==0?(($signed({{48{residual[element][15]}},residual[element][15:0]})<<<6)-$signed(sum_s)):$signed(row_data[element]);
    lane_b[ml]=norm_pass==0?{32'd0,ln_recip}:norm_pass==1?{{32{gamma_cache[element][31]}},gamma_cache[element]}:{32'd0,ln_m};
    lane_shift[ml]=norm_pass==0?18:norm_pass==1?14:ln_s;
   end
  end
  always @*begin
   numerator_l=0;product_l=0;corrected_q_lane[ml]=0;remainder_lane[ml]=0;
   if(state==SM_QD&&response_mask[ml])begin
    numerator_l=({32'd0,row_data[write_index[ml]]}<<16)-{32'd0,row_data[write_index[ml]]};
    corrected_q_lane[ml]={48'd0,probabilities[norm_row*99+write_index[ml]]};product_l=lane_result[ml];
    if(product_l>numerator_l)begin corrected_q_lane[ml]=corrected_q_lane[ml]-1;product_l=product_l-denominator;end
    remainder_lane[ml]=numerator_l-product_l;
   end
  end
 end endgenerate
 wire iter_ready,iter_valid,iter_error;wire [63:0] iter_result,iter_remainder;
 kwt_iterative #(.SHORT_CONST_DIV(1),.RADIX4_CONST(1)) iterative_unit(clk,rst_n,enable&&state==I_REQ,iter_ready,iter_sqrt,iter_a,iter_b,iter_valid,enable&&state==I_WAIT,iter_result,iter_remainder,iter_error);
 kwt_mac_array #(.ROWS(ROWS),.COLS(16)) pe(clk,rst_n,mac_load,mac_en,mac_unsigned,row_mask,col_mask,mac_a,mac_b,mac_bias,acc);
 reg [12:0] exp_index;
 function automatic [15:0] word_at(input [319:0] data,input integer bank);begin word_at=data[bank*16+:16];end endfunction
 function automatic signed [7:0] byte_at(input [319:0] data,input integer bank,input integer high);begin byte_at=$signed((word_at(data,bank)>>(8*high))&255);end endfunction
 function automatic signed [31:0] accumulator(input [ROWS*16*32-1:0] data,input integer index);begin accumulator=$signed(data[index*32+:32]);end endfunction
 function automatic [7:0] gelu_code(input [7:0] code);
  reg [7:0] index;begin index=code^8'h80;gelu_code=gamma_cache[index[7:2]]>>(8*index[1:0]);end
 endfunction
 task read_word(input integer bank,input integer address,input [7:0] resume);begin generic_bank<=bank;generic_addr<=address;return_state<=resume;state<=READ16;end endtask
 task read_c32(input integer address,input [7:0] resume);begin coefficient_addr<=address;return_state<=resume;state<=C_READ;end endtask
 task read_c64(input integer address,input [7:0] resume);begin coefficient_addr<=address;return_state<=resume;state<=C64_READ0;end endtask
 task scalar(input [2:0] op,input [63:0] a,input [63:0] b,input signed [7:0] shift,input [5:0] sat,input [7:0] resume);
  begin math_op<=op;math_a<=a;math_b<=b;math_shift<=shift;math_sat<=sat;return_state<=resume;state<=M_REQ;end endtask
 task iterate(input sqrt_mode,input [63:0] a,input [63:0] b,input [7:0] resume);begin iter_sqrt<=sqrt_mode;iter_a<=a;iter_b<=b;return_state<=resume;state<=I_REQ;end endtask
 always @* begin
  case(kind)
   0:begin kdim=64;ndim=64;wb=WB_Q;cm=CB_Q_M;cs=CB_Q_S;cb=0;target_group=8;target_base=448;end
   1:begin kdim=64;ndim=64;wb=WB_K;cm=CB_K_M;cs=CB_K_S;cb=0;target_group=8;target_base=896;end
   2:begin kdim=64;ndim=64;wb=WB_V;cm=CB_V_M;cs=CB_V_S;cb=0;target_group=8;target_base=1344;end
   3:begin kdim=64;ndim=64;wb=WB_O;cm=CB_O_M;cs=CB_O_S;cb=CB_O_B;target_group=8;target_base=2240;end
   4:begin kdim=64;ndim=256;wb=WB_FC1;cm=CB_FC1_M;cs=CB_FC1_S;cb=CB_FC1_B;target_group=8;target_base=448;end
   default:begin kdim=256;ndim=64;wb=WB_FC2;cm=CB_FC2_M;cs=CB_FC2_S;cb=CB_FC2_B;target_group=8;target_base=2240;end
  endcase
  source_group=8+(token%16)/2;target_group=source_group;source_base=kind==5?448:kind==3?1792:0;source_width=kind==5?256:64;
  rows=(token+ROWS<=99)?ROWS:99-token;row_token=token+norm_row;valid_keys=kg==6?3:16;
  read_red=red+((state==D_MAC||state==Q_MAC||state==P_MAC)?1:0);
  waddress=wb+((oc/16)<<(kind==5?8:6))+read_red+((kind==5&&parameter_slot)?1024:0);
  exp_index=$signed(math_result)>=0?0:($signed(math_result)< -4096?4096:-$signed(math_result));

 end
 always @* begin
  mem_en=0;mem_we=0;mem_addr=0;mem_wdata=0;bank_index=0;physical_w=0;
  if(enable&&rst_n)case(state)
   READ16:begin mem_en[generic_bank]=1;mem_addr[generic_bank*12+:12]=generic_addr;end
   C_READ,C64_READ0,C64_READ1:begin mem_en[16]=1;mem_en[17]=1;mem_addr[16*12+:12]=coefficient_addr+(state==C64_READ1)+(parameter_slot?2048:0);mem_addr[17*12+:12]=coefficient_addr+(state==C64_READ1)+(parameter_slot?2048:0);end
   D_READ,D_MAC:if(state==D_READ||red<kdim-1)for(j=0;j<8;j=j+1)begin
    mem_en[j]=1;mem_addr[j*12+:12]=waddress;
    if(layer==0&&kind<3)begin if(j<rows)begin mem_en[8+j]=1;mem_addr[(8+j)*12+:12]=2688+(token/8)*64+read_red;end end
    else if(2*j<rows)begin mem_en[source_group+j]=1;mem_addr[(source_group+j)*12+:12]=source_base+((token/16)<<(kind==5?8:6))+read_red;end
   end
   D_RQ:if(kind!=2&&math_take&&!math_error)for(j=0;j<2;j=j+1)if(response_mask[2*j])begin
    bank_index=target_group+dense_write_index[0][6:4]/2+j;
    mem_en[bank_index]=1;mem_we[bank_index]=1;
    mem_addr[bank_index*12+:12]=target_base+((token/16)<<(kind==4?8:6))+oc+dense_write_index[0][3:0];
    mem_wdata[bank_index*16+:16]={8'd0,lane_result[2*j][7:0]};
    if(response_mask[2*j+1])mem_wdata[bank_index*16+8+:8]=lane_result[2*j+1][7:0];
   end
   D_STORE:begin
    if(kind==2)for(j=0;j<8;j=j+1)begin mem_en[8+j]=1;mem_we[8+j]=1;mem_addr[(8+j)*12+:12]=1344+(token+store_index)*4+oc/16;mem_wdata[(8+j)*16+:16]={codes[store_index*16+2*j+1],codes[store_index*16+2*j]};end
    else for(j=0;j<8;j=j+1)if(2*j<rows)begin
     mem_en[target_group+j]=1;mem_we[target_group+j]=1;mem_addr[(target_group+j)*12+:12]=target_base+((token/16)<<(kind==4?8:6))+oc+store_index;
     mem_wdata[(target_group+j)*16+:16]={8'd0,codes[(2*j)*16+store_index]};if(2*j+1<rows)mem_wdata[(target_group+j)*16+8+:8]=codes[(2*j+1)*16+store_index];
    end
   end
   Q_PREFETCH,Q_CAPTURE:if(state==Q_PREFETCH||red<63)for(j=0;j<8;j=j+1)if(2*j<rows)begin
    mem_en[source_group+j]=1;mem_addr[(source_group+j)*12+:12]=448+(token/16)*64+red+(state==Q_CAPTURE);
   end
   Q_READ,Q_MAC:if(state==Q_READ||red<63)for(j=0;j<8;j=j+1)if(2*j<valid_keys)begin
    mem_en[8+j]=1;mem_addr[(8+j)*12+:12]=896+kg*64+read_red;
   end
   Q_STORE:if(store_index%16<valid_keys)begin
    mem_en[16]=1;mem_en[17]=1;mem_we[16]=1;mem_we[17]=1;
    mem_addr[16*12+:12]=(parameter_slot?0:2048)+(store_index/16)*99+kg*16+store_index%16;mem_addr[17*12+:12]=(parameter_slot?0:2048)+(store_index/16)*99+kg*16+store_index%16;
    mem_wdata[16*16+:16]=acc[store_index*32+:16];mem_wdata[17*16+:16]=acc[store_index*32+16+:16];
   end
   S_LOAD,S_CAPTURE:if(state==S_LOAD||ch<98)begin
    mem_en[16]=1;mem_en[17]=1;mem_addr[16*12+:12]=(parameter_slot?0:2048)+norm_row*99+ch+(state==S_CAPTURE);mem_addr[17*12+:12]=(parameter_slot?0:2048)+norm_row*99+ch+(state==S_CAPTURE);
   end
   SM_RQ:if(math_take&&exp_index!=4096)begin mem_en[18]=1;mem_en[19]=1;mem_addr[18*12+:12]=exp_index;mem_addr[19*12+:12]=exp_index;end
   P_READ,P_MAC:if(state==P_READ||red<98)for(j=0;j<8;j=j+1)begin mem_en[8+j]=1;mem_addr[(8+j)*12+:12]=1344+read_red*4+oc/16;end
   P_STORE:for(j=0;j<8;j=j+1)if(2*j<rows)begin
    mem_en[target_group+j]=1;mem_we[target_group+j]=1;mem_addr[(target_group+j)*12+:12]=1792+(token/16)*64+oc+store_index;
    mem_wdata[(target_group+j)*16+:16]={8'd0,codes[2*j*16+store_index]};if(2*j+1<rows)mem_wdata[(target_group+j)*16+8+:8]=codes[(2*j+1)*16+store_index];
   end
   N_LOAD_FIRST,N_LOAD_A,N_LOAD_B:if(state!=N_LOAD_B||ch<63)begin
    if(layer==0&&!norm2&&state!=N_LOAD_A)begin
     for(j=0;j<ROWS;j=j+1)if(j<rows)begin
      mem_en[8+j]=1;mem_addr[(8+j)*12+:12]=2688+(token/8)*64+ch+(state==N_LOAD_B);
     end
    end else for(j=0;j<ROWS/2;j=j+1)if(2*j<rows)begin
     bank_index=source_group+j;mem_en[bank_index]=1;
     mem_addr[bank_index*12+:12]=(token/16)*64+ch+(state==N_LOAD_A?2240:state==N_LOAD_B?1:0);
    end
   end
   N_WRITE,N_RMW:begin
    bank_index=8+(row_token%16)/2;mem_en[bank_index]=1;mem_addr[bank_index*12+:12]=(norm2?448:0)+(row_token/16)*64+ch;
    if(state==N_RMW)begin mem_we[bank_index]=1;mem_wdata[bank_index*16+:16]=row_token%2?{codes[ch],mem_rdata[bank_index*16+:8]}:{mem_rdata[bank_index*16+8+:8],codes[ch]};end
    if(state==N_WRITE&&layer==0&&!norm2&&row_token==98)begin mem_we[bank_index]=1;mem_wdata[bank_index*16+:16]={8'd0,codes[ch]};end
   end
   N_PAIR_WRITE:begin
    bank_index=8+(row_token%16)/2;mem_en[bank_index]=1;mem_we[bank_index]=1;
    mem_addr[bank_index*12+:12]=(norm2?448:0)+(row_token/16)*64+ch;
    mem_wdata[bank_index*16+:16]={codes[ch],low_pv[2*ch+norm_row/4][8*(norm_row%4-1)+:8]};
   end
   G_READ:for(j=0;j<8;j=j+1)if(2*j<(token<6?16:3))begin mem_en[8+j]=1;mem_addr[(8+j)*12+:12]=448+token*256+oc;end
   G_CACHE_FIRST,G_CACHE_LOAD:if(state==G_CACHE_FIRST||ch<127)begin mem_en[16]=1;mem_addr[16*12+:12]=1880+ch+(state==G_CACHE_LOAD)+(parameter_slot?2048:0);end
   G_WRITE:for(j=0;j<8;j=j+1)if(2*j<(token<6?16:3))begin mem_en[8+j]=1;mem_we[8+j]=1;mem_addr[(8+j)*12+:12]=448+token*256+oc;mem_wdata[(8+j)*16+:16]={8'd0,gelu_code(mem_rdata[(8+j)*16+:8])};if(2*j+1<(token<6?16:3))mem_wdata[(8+j)*16+8+:8]=gelu_code(mem_rdata[(8+j)*16+8+:8]);end
   COPY_READ:for(j=0;j<8;j=j+1)if(copy_address<384||j<2)begin mem_en[8+j]=1;mem_addr[(8+j)*12+:12]=448+copy_address;end
   COPY_WRITE:for(j=0;j<8;j=j+1)if(copy_address<384||j<2)begin mem_en[8+j]=1;mem_we[8+j]=1;mem_addr[(8+j)*12+:12]=copy_address;mem_wdata[(8+j)*16+:16]=mem_rdata[(8+j)*16+:16];end
  endcase
 end
 always @* begin
  mac_load=0;mac_en=0;mac_unsigned=0;row_mask=(17'd1<<rows)-1;col_mask=65535;mac_a=0;mac_b=0;mac_bias=0;
  if(state==D_CLEAR||state==D_MAC)begin
   for(integer z=0;z<16;z=z+1)mac_bias[z*32+:32]=biases[z];
   for(integer z=0;z<ROWS;z=z+1)mac_a[z*16+:16]=(layer==0&&kind<3)?word_at(mem_rdata,8+z):{{8{mem_rdata[(source_group+z/2)*16+8*(z%2)+7]}},mem_rdata[(source_group+z/2)*16+8*(z%2)+:8]};
   for(integer z=0;z<8;z=z+1)mac_b[z*16+:16]=mem_rdata[z*16+:16];
  end
  if(state==Q_CLEAR||state==Q_MAC)begin
   col_mask=(17'd1<<valid_keys)-1;
   for(integer z=0;z<ROWS;z=z+1)mac_a[z*16+:16]={{8{low_pv[red*(ROWS/4)+z/4][8*(z%4)+7]}},low_pv[red*(ROWS/4)+z/4][8*(z%4)+:8]};
   for(integer z=0;z<8;z=z+1)mac_b[z*16+:16]=mem_rdata[(8+z)*16+:16];
  end
  if(state==P_CLEAR||state==P_MAC)begin
   // The frozen S16 PE already supports U16 x S8. All99-term partial
   // sums fit signed32: 99*65535*128=830459520 < 2^31. No rounding here.
   mac_unsigned=1;for(integer z=0;z<ROWS;z=z+1)mac_a[z*16+:16]=probabilities[z*99+red];
   for(integer z=0;z<8;z=z+1)mac_b[z*16+:16]=mem_rdata[(8+z)*16+:16];
  end
  if(enable&&rst_n)begin mac_load=state==D_CLEAR||state==Q_CLEAR||state==P_CLEAR;mac_en=state==D_MAC||state==Q_MAC||state==P_MAC;end
 end
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin
   state<=IDLE;return_state<=IDLE;layer<=0;kind<=0;token<=0;ch<=0;oc<=0;sent<=0;received<=0;red<=0;kg<=0;ci<=0;store_index<=0;norm_row<=0;norm2<=0;cache_valid<=0;cache_norm2<=0;norm_pass<=0;prefetch_ready<=0;
   generic_bank<=0;generic_addr<=0;coefficient_addr<=0;r16<=0;r32<=0;low32<=0;r64<=0;maximum<=0;sum_s<=0;sum_t<=0;eps_value<=0;den_sqrt<=0;h_value<=0;
   score_m<=0;context_m<=0;denominator<=0;reciprocal<=0;ln_m<=0;ln_recip<=0;score_s<=0;context_s<=0;ln_s<=0;res_s<=0;res_m0<=0;res_m1<=0;residual_x<=0;copy_address<=0;gelu_lane<=0;exp_pending<=0;exp_zero<=0;exp_tag<=0;
   math_op<=0;math_a<=0;math_b<=0;math_value<=0;math_shift<=0;math_sat<=0;iter_sqrt<=0;iter_a<=0;iter_b<=0;iter_value<=0;iter_rem<=0;done<=0;fault<=0;
  end else begin
   done<=0;
   if(enable)begin
    if(math_take&&math_error)begin fault<=1;state<=FAILED;end
    else case(state)
     IDLE:if(start&&!fault)begin layer<=layer_id;kind<=0;token<=0;oc<=0;ci<=0;cache_valid<=0;norm_row<=0;prefetch_ready<=0;state<=D_COEFF;end
     READ16:state<=RET16;RET16:begin r16<=mem_rdata[generic_bank*16+:16];state<=return_state;end
     C_READ:state<=C_RET;C_RET:begin r32<=mem_rdata[256+:32];state<=return_state;end
     C64_READ0:state<=C64_RET0;C64_RET0:begin low32<=mem_rdata[256+:32];state<=C64_READ1;end
     C64_READ1:state<=C64_RET1;C64_RET1:begin r64<={mem_rdata[256+:32],low32};state<=return_state;end
     M_REQ:if(math_accept)state<=M_WAIT;M_WAIT:if(math_take)begin math_value<=math_result;state<=return_state;end
     I_REQ:if(iter_ready)state<=I_WAIT;I_WAIT:if(iter_valid)begin iter_value<=iter_result;iter_rem<=iter_remainder;if(iter_error)begin fault<=1;state<=FAILED;end else state<=return_state;end
     D_COEFF:read_c32(cm+oc+ci,D_M);D_M:begin multipliers[ci]<=r32;read_c32(cs+oc+ci,D_S);end
     D_S:begin shifts[ci]<=r32[7:0];if(kind<3)begin biases[ci]<=0;if(ci==15)state<=D_CLEAR;else begin ci<=ci+1;state<=D_COEFF;end end else read_c32(cb+oc+ci,D_B);end
     D_B:begin biases[ci]<=r32;if(ci==15)state<=D_CLEAR;else begin ci<=ci+1;state<=D_COEFF;end end
     D_CLEAR:begin red<=0;state<=D_READ;end D_READ:state<=D_MAC;
     D_MAC:if(red==kdim-1)begin sent<=0;received<=0;state<=D_RQ;end else red<=red+1;
     D_RQ:begin
      if(math_accept)sent<=sent+(kind==2?issue_count:4);
      if(math_take)begin
       if(kind==2)for(integer ql=0;ql<4;ql=ql+1)if(response_mask[ql])codes[write_index[ql]]<=lane_result[ql][7:0];
       received<=received+(kind==2?take_count:4);
       if(received+(kind==2?take_count:4)==output_limit)begin store_index<=0;state<=kind==2?D_STORE:D_NEXT;end
      end
     end
     D_STORE:if(store_index==(kind==2?rows-1:15))state<=D_NEXT;else store_index<=store_index+1;
     D_NEXT:begin
      ci<=0;
      // One coefficient tile serves all thirteen token blocks. Full context
      // and O/FC2 output fit the new channel/token striped activation regions.
      if(token+ROWS<99)begin token<=token+ROWS;state<=D_CLEAR;end
      else if(oc+16<ndim)begin oc<=oc+16;token<=0;state<=D_COEFF;end
      else if(kind==3||kind==5)begin norm2<=kind==5;token<=0;norm_row<=0;state<=N_BEGIN;end
      else if(kind<2)begin kind<=kind+1;token<=0;oc<=0;state<=D_COEFF;end
      else if(kind==2)begin token<=0;read_c32(CB_SCORE_M,A_COEF0);end
      else begin token<=0;oc<=0;ch<=0;cache_valid<=0;prefetch_ready<=1;state<=G_CACHE_FIRST;end
     end
     A_COEF0:begin score_m<=r32;read_c32(CB_SCORE_S,A_COEF1);end A_COEF1:begin score_s<=r32[7:0];read_c32(CB_CTX_M,A_COEF2);end
     A_COEF2:begin context_m<=r32;read_c32(CB_CTX_S,A_COEF3);end A_COEF3:begin context_s<=r32[7:0];kg<=0;red<=0;state<=Q_PREFETCH;end
     Q_PREFETCH:state<=Q_CAPTURE;
     Q_CAPTURE:begin
      for(integer z=0;z<ROWS/4;z=z+1)low_pv[red*(ROWS/4)+z]<=4*z<rows?mem_rdata[(source_group+2*z)*16+:32]:32'd0;
      if(red==63)state<=Q_CLEAR;else red<=red+1;
     end
     Q_CLEAR:begin red<=0;state<=Q_READ;end Q_READ:state<=Q_MAC;
     Q_MAC:if(red==63)begin store_index<=0;state<=Q_STORE;end else red<=red+1;
     Q_STORE:if(store_index==rows*16-1)begin
      if(kg==6)begin norm_row<=0;ch<=0;maximum<=-2147483647;state<=S_LOAD;end else begin kg<=kg+1;state<=Q_CLEAR;end
     end else store_index<=store_index+1;
     S_LOAD:state<=S_CAPTURE;
     S_CAPTURE:begin
      row_data[ch]<=mem_rdata[256+:32];
      if($signed(mem_rdata[256+:32])>maximum)maximum<=$signed(mem_rdata[256+:32]);
      if(ch==98)begin sent<=0;received<=0;exp_pending<=0;denominator<=0;state<=SM_RQ;end else ch<=ch+1;
     end
     SM_RQ:begin
      if(math_accept)sent<=sent+issue_count;
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
      if(math_accept)sent<=sent+issue_count;
      if(math_take)begin for(integer ql=0;ql<4;ql=ql+1)if(response_mask[ql])probabilities[norm_row*99+write_index[ql]]<=((lane_result[ql]<<16)-lane_result[ql])>>47;received<=received+take_count;if(received+take_count==99)begin sent<=0;received<=0;state<=SM_QD;end end
     end
     SM_QD:begin
      if(math_accept)sent<=sent+issue_count;
      if(math_take)begin
       for(integer ql=0;ql<4;ql=ql+1)if(response_mask[ql])probabilities[norm_row*99+write_index[ql]]<=corrected_q_lane[ql]+((remainder_lane[ql]>denominator-remainder_lane[ql])||(remainder_lane[ql]==denominator-remainder_lane[ql]&&corrected_q_lane[ql][0]));received<=received+take_count;
       if(received+take_count==99)begin
        if(norm_row+1<rows)begin norm_row<=norm_row+1;ch<=0;maximum<=-2147483647;state<=S_LOAD;end
        else begin oc<=0;state<=P_CLEAR;end
       end
      end
     end
     P_CLEAR:begin red<=0;state<=P_READ;end P_READ:state<=P_MAC;
     P_MAC:if(red==98)state<=P_END;else red<=red+1;
     P_END:begin sent<=0;received<=0;state<=P_RQ;end
     P_RQ:begin if(math_accept)sent<=sent+issue_count;if(math_take)begin for(integer ql=0;ql<4;ql=ql+1)if(response_mask[ql])codes[write_index[ql]]<=lane_result[ql][7:0];received<=received+take_count;if(received+take_count==rows*16)begin store_index<=0;state<=P_STORE;end end end
     P_STORE:if(store_index<15)store_index<=store_index+1;else if(oc<48)begin oc<=oc+16;state<=P_CLEAR;end
      else if(token+ROWS<99)begin token<=token+ROWS;kg<=0;red<=0;state<=Q_PREFETCH;end
      else begin kind<=3;token<=0;oc<=0;ci<=0;state<=D_COEFF;end
     N_BEGIN:if(cache_valid&&cache_norm2==norm2)begin ch<=0;state<=norm_row!=0?N_PAIR_LOAD:N_LOAD_FIRST;end else read_c64(norm2?CB_R2_COEFF:CB_R1_COEFF,N_C0);
     N_C0:begin res_m0<=r64[31:0];read_c64((norm2?CB_R2_COEFF:CB_R1_COEFF)+2,N_C1);end
     N_C1:begin res_m1<=r64[31:0];read_c64((norm2?CB_R2_COEFF:CB_R1_COEFF)+4,N_CS);end
     N_CS:begin res_s<=r64[7:0];read_c64(norm2?CB_LN2_EPS:CB_LN1_EPS,N_EPS);end
     N_EPS:begin eps_value<=r64;read_c32(norm2?CB_LN2_M:CB_LN1_M,N_M);end
     N_M:begin ln_m<=r32;read_c32(norm2?CB_LN2_S:CB_LN1_S,N_S);end
     N_S:begin ln_s<=r32[7:0];ch<=0;read_c32(norm2?CB_LN2_G:CB_LN1_G,N_CACHE_G);end
     N_CACHE_G:begin probabilities[{1'b0,ch[5:0],1'b0}]<=r32[15:0];probabilities[{1'b0,ch[5:0],1'b1}]<=r32[31:16];read_c32((norm2?CB_LN2_B:CB_LN1_B)+ch,N_CACHE_B);end
     N_CACHE_B:begin probabilities[{1'b1,ch[5:0],1'b0}]<=r32[15:0];probabilities[{1'b1,ch[5:0],1'b1}]<=r32[31:16];if(ch==63)begin cache_valid<=1;cache_norm2<=norm2;ch<=0;state<=N_LOAD_FIRST;end else begin ch<=ch+1;state<=N_CACHE_NEXT;end end
     N_CACHE_NEXT:read_c32((norm2?CB_LN2_G:CB_LN1_G)+ch,N_CACHE_G);
     N_LOAD_FIRST:state<=N_LOAD_A;
     N_LOAD_A:begin
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
     N_RES:begin
      if(math_accept)sent<=sent+issue_count;
      if(math_take)begin for(integer ql=0;ql<4;ql=ql+1)if(response_mask[ql])begin probabilities[256+norm_row*64+write_index[ql]]<=lane_result[ql][15:0];low_pv[2*write_index[ql]+norm_row/4][8*(norm_row%4)+:8]<={8{lane_result[ql][15]}};end received<=received+take_count;if(received+take_count==64)begin sent<=0;received<=0;sum_s<=0;sum_t<=0;state<=N_SQUARE;end end
     end
     N_SQUARE:begin if(math_accept)begin sent<=sent+issue_count;sum_s<=sum_s+sum_s_batch;end if(math_take)begin sum_t<=sum_t+sum_t_batch;received<=received+take_count;if(received+take_count==64)state<=N_SUMSQ;end end
     N_SUMSQ:scalar(0,$signed(sum_s),$signed(sum_s),0,0,N_VAR);
     N_VAR:begin h_value<=(((sum_t<<6)-math_value)<<16)+eps_value;state<=N_SQRT;end
     N_SQRT:iterate(1,h_value,0,N_INV);N_INV:begin den_sqrt<=iter_value;iterate(0,64'h10000000000,iter_value,N_INV_RET);end
     N_INV_RET:begin ln_recip<=iter_value+((iter_rem>den_sqrt-iter_rem)||(iter_rem==den_sqrt-iter_rem&&iter_value[0]));norm_pass<=0;sent<=0;received<=0;state<=N_PASS;end
     N_PASS:begin
      if(math_accept)sent<=sent+issue_count;
      if(math_take)begin
       for(integer ql=0;ql<4;ql=ql+1)if(response_mask[ql])begin
        if(norm_pass==2)codes[write_index[ql]]<=lane_result[ql][7:0];else row_data[write_index[ql]]<=norm_pass==1?lane_result[ql]+{{32{beta_cache[write_index[ql]][31]}},beta_cache[write_index[ql]]}:lane_result[ql];
       end
       received<=received+take_count;if(received+take_count==64)begin sent<=0;received<=0;if(norm_pass==2)begin ch<=0;state<=row_token==98?N_WRITE:norm_row[0]?N_PAIR_WRITE:N_PAIR_CACHE;end else norm_pass<=norm_pass+1;end
      end
     end
     N_WRITE:if(layer==0&&!norm2&&row_token==98)begin if(ch==63)state<=N_WNEXT;else ch<=ch+1;end else state<=N_RMW;N_RMW:if(ch==63)state<=N_WNEXT;else begin ch<=ch+1;state<=N_WRITE;end
     N_PAIR_CACHE:begin
      for(integer z=0;z<64;z=z+1)low_pv[2*z+norm_row/4][8*(norm_row%4)+:8]<=codes[z];
      state<=N_WNEXT;
     end
     N_PAIR_WRITE:if(ch==63)state<=N_WNEXT;else ch<=ch+1;
     N_WNEXT:if(norm_row+1<rows)begin norm_row<=norm_row+1;state<=N_BEGIN;end
      else if(!norm2)begin
       if(token+ROWS<99)begin token<=token+ROWS;norm_row<=0;state<=N_BEGIN;end else begin kind<=4;token<=0;oc<=0;ci<=0;state<=D_COEFF;end
      end else if(token+ROWS<99)begin token<=token+ROWS;norm_row<=0;state<=N_BEGIN;end
      else if(layer<11)begin copy_address<=0;state<=COPY_READ;end else state<=LAYER_END;
     // LN1 gamma is dead. Reuse its 256 bytes for all 256 S8 GELU codes;
     // LN2 invalidates/reloads both affine coefficient arrays before use.
     G_CACHE_FIRST:state<=G_CACHE_LOAD;
     G_CACHE_LOAD:begin
      if(ch[0])begin probabilities[{1'b0,ch[6:1],1'b0}]<=low32[15:0];probabilities[{1'b0,ch[6:1],1'b1}]<=mem_rdata[256+:16];end else low32[15:0]<=mem_rdata[256+:16];
      if(ch==127)state<=G_READ;else ch<=ch+1;
     end
     G_READ:state<=G_WRITE;G_CAPTURE:begin for(integer z=0;z<16;z=z+1)if(z<(token<6?16:3))codes[z]<=$signed(mem_rdata[(8+z/2)*16+8*(z%2)+:8]);state<=G_APPLY;end
     G_APPLY:begin for(integer z=0;z<16;z=z+1)if(z<(token<6?16:3))codes[z]<=gamma_cache[($signed(codes[z])+128)/4]>>(8*(($signed(codes[z])+128)%4));state<=G_WRITE;end
     G_LUT:read_word(16,1880+(($signed(codes[gelu_lane])+128)/2),G_LUT_RET);
     G_LUT_RET:begin codes[gelu_lane]<=r16>>(8*(($signed(codes[gelu_lane])+128)%2));if(gelu_lane==(token<6?15:2))state<=G_WRITE;else begin gelu_lane<=gelu_lane+1;state<=G_LUT;end end
     G_WRITE:if(oc<255)begin oc<=oc+1;state<=G_READ;end else if(token<6)begin token<=token+1;oc<=0;state<=G_READ;end else begin kind<=5;token<=0;oc<=0;ci<=0;state<=D_COEFF;end
     COPY_READ:state<=COPY_WRITE;COPY_WRITE:if(copy_address==447)state<=LAYER_END;else begin copy_address<=copy_address+1;state<=COPY_READ;end
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
`ifdef KWT_SIM
 // Observe complete old-layout dense tiles, independently of the new cursor.
 // Every real row/channel must be committed exactly once before D_NEXT.
 reg [127:0] stream_seen;integer stream_lane,stream_element,stream_bank,stream_address;
 always @(posedge clk)begin
  if(!rst_n)stream_seen=0;
  else if(enable)begin
   if(state==D_CLEAR)stream_seen=0;
   if(state==D_RQ&&kind!=2)begin
    if(math_error&&(|mem_we))$fatal(1,"DENSE_STREAM write on arithmetic/tag fault");
    if(math_take&&!math_error)for(stream_lane=0;stream_lane<4;stream_lane=stream_lane+1)if(response_mask[stream_lane])begin
     stream_element=lane_tag[stream_lane];
     stream_bank=8+(token%16)/2+(stream_element/16)/2;
     stream_address=target_base+(token/16)*(kind==4?256:64)+oc+stream_element%16;
     if(stream_element>=rows*16||stream_seen[stream_element]||!mem_en[stream_bank]||!mem_we[stream_bank]||
        mem_addr[stream_bank*12+:12]!=stream_address||
        mem_wdata[stream_bank*16+8*((stream_element/16)%2)+:8]!=lane_result[stream_lane][7:0])
      $fatal(1,"DENSE_STREAM duplicate/missing/wrong-layout write kind=%0d token=%0d tag=%0d",kind,token,stream_element);
     stream_seen[stream_element]=1;
    end
   end
   if(state==D_NEXT&&kind!=2)for(stream_element=0;stream_element<128;stream_element=stream_element+1)
    if(stream_seen[stream_element]!=(stream_element<rows*16))$fatal(1,"DENSE_STREAM incomplete tile");
  end
 end
 // Independent old-storage shadow, copied from the a691cc7 producer rules.
 // It never drives the DUT. Compare at actual consumers, including stalls,
 // so a lifetime/alias conflict cannot hide behind only final-tensor checks.
 reg [31:0] shadow_gamma[0:63],shadow_beta[0:63];reg [23:0] shadow_residual[0:63];
 reg [63:0] shadow_g_valid,shadow_b_valid,shadow_r_valid,shadow_r_finished;
 reg[15:0]shadow_batch_a[0:511];reg[7:0]shadow_batch_b[0:511];
 reg[511:0]shadow_a_valid,shadow_batch_valid;integer shadow_batch_row,shadow_batch_index;
 integer shadow_lane,shadow_index,shadow_row,shadow_z,shadow_code;
 task automatic check_shadow_residual(input integer index,input finished);
  begin
   if(shadow_r_valid[index]!==1'b1||residual[index]!==shadow_residual[index]||
      (finished&&shadow_r_finished[index]!==1'b1))
    $fatal(1,"CACHE_LIFETIME residual layer=%0d state=%0d index=%0d",layer,state,index);
  end
 endtask
 always @(posedge clk)begin
  if(!rst_n)begin shadow_g_valid=0;shadow_b_valid=0;shadow_r_valid=0;shadow_r_finished=0;shadow_a_valid=0;shadow_batch_valid=0;end
  else if(enable)begin
   if(math_accept)for(shadow_lane=0;shadow_lane<4;shadow_lane=shadow_lane+1)if(request_mask[shadow_lane])begin
    shadow_index=request_tag[shadow_lane];
    if(state==N_RES)check_shadow_residual(shadow_index>>1,0);
    if(state==N_SQUARE||(state==N_PASS&&norm_pass==0))check_shadow_residual(shadow_index,1);
    if(state==N_PASS&&norm_pass==1)
     if(shadow_g_valid[shadow_index]!==1'b1||gamma_cache[shadow_index]!==shadow_gamma[shadow_index])
      $fatal(1,"CACHE_LIFETIME gamma layer=%0d index=%0d",layer,shadow_index);
   end
   if(math_take&&state==N_PASS&&norm_pass==1)
    for(shadow_lane=0;shadow_lane<4;shadow_lane=shadow_lane+1)if(response_mask[shadow_lane])begin
     shadow_index=lane_tag[shadow_lane];
     if(shadow_b_valid[shadow_index]!==1'b1||beta_cache[shadow_index]!==shadow_beta[shadow_index])
      $fatal(1,"CACHE_LIFETIME beta layer=%0d index=%0d",layer,shadow_index);
    end
   if(state==G_WRITE)for(shadow_row=0;shadow_row<(token<6?16:3);shadow_row=shadow_row+1)begin
    shadow_code=$signed(mem_rdata[(8+shadow_row/2)*16+8*(shadow_row%2)+:8])+128;
    shadow_index=shadow_code/4;
    if(shadow_g_valid[shadow_index]!==1'b1||gamma_cache[shadow_index]!==shadow_gamma[shadow_index]||
       mem_wdata[(8+shadow_row/2)*16+8*(shadow_row%2)+:8]!==((shadow_gamma[shadow_index]>>(8*(shadow_code%4)))&255))
     $fatal(1,"CACHE_LIFETIME GELU layer=%0d row=%0d index=%0d",layer,shadow_row,shadow_index);
   end
   if((state==SM_ER||state==SM_QD||state==P_READ||state==P_MAC||state==P_RQ)&&cache_valid)
    $fatal(1,"CACHE_LIFETIME probability/coefficient ownership overlap");
   // Apply old producer updates AFTER checking the pre-edge consumers.
   if((state==IDLE&&start)||(state==N_BEGIN&&!(cache_valid&&cache_norm2==norm2)))begin shadow_g_valid=0;shadow_b_valid=0;end
   if(state==G_CACHE_FIRST)shadow_g_valid=0;
   if(state==N_CACHE_G)begin shadow_gamma[ch]=r32;shadow_g_valid[ch]=1;end
   if(state==N_CACHE_B)begin shadow_beta[ch]=r32;shadow_b_valid[ch]=1;end
   if(state==G_CACHE_LOAD&&ch[0])begin shadow_gamma[ch/2]={mem_rdata[256+:16],low32[15:0]};shadow_g_valid[ch/2]=1;end
   if(state==N_LOAD_FIRST||state==N_PAIR_LOAD)begin shadow_r_valid=0;shadow_r_finished=0;end
   if(state==N_LOAD_FIRST)begin shadow_a_valid=0;shadow_batch_valid=0;end
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
   if(state==N_RES&&math_take)for(shadow_lane=0;shadow_lane<4;shadow_lane=shadow_lane+1)if(response_mask[shadow_lane])begin
    shadow_index=lane_tag[shadow_lane];shadow_residual[shadow_index]={{8{lane_result[shadow_lane][15]}},lane_result[shadow_lane][15:0]};shadow_r_finished[shadow_index]=1;
   end
  end
 end
`endif
endmodule
