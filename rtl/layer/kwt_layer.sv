// Functional single-layer prototype, real canonical packets and integer data.
// Behavioral multi-array SRAM organization; NOT the final 20-macro placement.
// 8x8 Dense MAC array; row-serial Attention; shared elastic RQ and div/sqrt.
module kwt_layer(
 input logic clk,rst_n,core_enable,mem_enable,
 input logic frame_valid,output logic frame_ready,input logic frame_common,input logic [3:0] frame_layer,
 input logic cfg_valid,output logic cfg_ready,input logic [31:0] cfg_data,input logic cfg_last,
 input logic input_valid,output logic input_ready,input logic [31:0] input_data,input logic input_last,
 input logic start_valid,output logic start_ready,
 output logic output_valid,input logic output_ready,output logic [31:0] output_data,output logic output_last,
 output logic done,error,output logic [7:0] debug_state
);
 `include "profile_rom.svh"
 localparam IDLE=0,DI=1,DM=2,DR=3,SI=4,SM=5,SS=6,SR=7,DS=8,DW=9,PN=10,
            PI=11,PM=12,PR=13,RS=14,LS=15,LV=16,QS=17,QW=18,IS=19,IW=20,LR=21,GL=22,OUT=23;
 reg [7:0] state;assign debug_state=state;
 reg [31:0] par[0:15431],common[0:4143];
 reg signed [7:0] x[0:6335],qmem[0:6335],kmem[0:6335],vmem[0:6335],hidden[0:25343];
 reg signed [7:0] ctxmem[0:63],vector_out[0:63];
 reg signed [31:0] score[0:98],acc[0:63],normal[0:63],affine[0:63];
 reg signed [15:0] residual[0:63];reg [31:0] exponent[0:98];reg [15:0] probability[0:98];
 reg active,receiving_common,common_ok,layer_ok,input_ok,frame_bad;
 reg [3:0] layer;integer pos,input_pos,output_pos;
 reg [31:0] crc;integer kind,t,oc,red,kg,ch,sent,received,lnphase,lnnumber;
 reg signed [31:0] maximum,sum_s;reg [63:0] sum_t,hvalue,den_sqrt,reciprocal,denominator;
 reg [63:0] temp64,er,numerator,quotient,qd,remainder_n;reg signed [63:0] signed_temp;
 reg signed [31:0] max_work;integer lane,row_lane,rows,idx,base_w,kdim,ndim,base_m,base_s,base_b;
 wire rv,rr,ov,oe;wire [63:0] oq;wire [15:0] ot;
 reg signed [63:0] ra,rb;reg signed [7:0] rshift;reg [5:0] rsat;
 wire wready,wvalid,werror;wire [63:0] wq,wr;
 wire wreq=(state==DS||state==QS||state==IS)&&core_enable;
 wire [2:0] wop=(state==QS)?4:3;
 wire [63:0] wa=(state==QS)?hvalue:((state==DS)?64'h800000000000:64'h10000000000);
 wire [63:0] wb=(state==DS)?denominator:den_sqrt;
 wide_arith iterative(clk,rst_n,wreq,wready,wop,wa,wb,8'sd0,wvalid,core_enable,wq,wr,werror);
 assign rv=core_enable&&((state==DR)?sent<8*rows:((state==PR)?sent<8:((state==SR)?sent<99:((state==LR)?sent<64:1'b0))));
 rq_pipe rq(clk,rst_n,rv,rr,1'b1,ra,rb,rshift,rsat,sent[15:0],ov,core_enable,oq,oe,ot);
 function automatic [31:0] crc_word(input [31:0] old,input [31:0] data);
  reg [31:0] c;integer j;begin c=old^data;for(j=0;j<32;j=j+1)c=c[0]?(c>>1)^32'hedb88320:c>>1;crc_word=c;end
 endfunction
 function automatic [7:0] pbyte(input integer address);
  begin pbyte=par[address/4]>>(8*(address%4));end
 endfunction
 function automatic signed [31:0] p32(input integer address);
  begin p32=$signed(par[address/4]);end
 endfunction
 function automatic [63:0] p64(input integer address);
  begin p64={par[address/4+1],par[address/4]};end
 endfunction
 function automatic signed [31:0] weight(input integer base,input integer k,input integer n,input integer r,input integer c);
  integer address;begin address=base+(c%8)/2*(k*n/4)+(c/8)*k*2+r*2+c%2;weight=$signed(pbyte(address));end
 endfunction
 function automatic signed [63:0] rne64(input signed [63:0] value,input integer shift);
  reg [63:0] mag,qq,remn,dd;begin
   mag=value<0?-value:value;
   if(shift==0)qq=mag;else if(shift<0)qq=mag<<(-shift);
   else if(shift>=64)qq=0;else begin dd=64'd1<<shift;qq=mag>>shift;remn=mag&(dd-1);if(remn>dd-remn||(remn==dd-remn&&qq[0]))qq=qq+1;end
   rne64=value<0?-$signed(qq):$signed(qq);
  end
 endfunction
 function automatic signed [15:0] sat16(input signed [63:0] value);
  begin sat16=value>32767?32767:(value< -32767?-32767:value);end
 endfunction
 function automatic signed [31:0] input_lane(input integer mode,input integer row,input integer r);
  begin case(mode)3:input_lane=ctxmem[r];5:input_lane=hidden[row*256+r];default:input_lane=x[row*64+r];endcase end
 endfunction
 always @* begin
  case(kind)
   0:begin base_w=W_Q;base_m=Q_M;base_s=Q_S;base_b=-1;kdim=64;ndim=64;end
   1:begin base_w=W_K;base_m=K_M;base_s=K_S;base_b=-1;kdim=64;ndim=64;end
   2:begin base_w=W_V;base_m=V_M;base_s=V_S;base_b=-1;kdim=64;ndim=64;end
   3:begin base_w=W_O;base_m=O_M;base_s=O_S;base_b=O_B;kdim=64;ndim=64;end
   4:begin base_w=W_FC1;base_m=FC1_M;base_s=FC1_S;base_b=FC1_B;kdim=64;ndim=256;end
   default:begin base_w=W_FC2;base_m=FC2_M;base_s=FC2_S;base_b=FC2_B;kdim=256;ndim=64;end
  endcase
  rows=(kind==3||kind==5)?1:((t+8<=99)?8:99-t);
  ra=0;rb=0;rshift=0;rsat=8;
  if(state==DR&&sent<8*rows)begin ra=acc[sent];rb=p32(base_m+4*(oc+sent%8));rshift=p32(base_s+4*(oc+sent%8));end
  else if(state==SR&&sent<99)begin ra=$signed(score[sent])-$signed(maximum);rb=p32(SCORE_M);rshift=p32(SCORE_S);rsat=0;end
  else if(state==PR&&sent<8)begin ra=acc[sent];rb=p32(CTX_M);rshift=p32(CTX_S);end
  else if(state==LR&&sent<64)begin
   if(lnphase==0)begin ra=($signed(residual[sent])*64)-$signed(sum_s);rb=reciprocal;rshift=18;rsat=0;end
   else if(lnphase==1)begin ra=normal[sent];rb=p32((lnnumber==1?LN1_G:LN2_G)+sent*4);rshift=14;rsat=0;end
   else begin ra=affine[sent];rb=p32(lnnumber==1?LN1_M:LN2_M);rshift=p32(lnnumber==1?LN1_S:LN2_S);end
  end
 end
 assign frame_ready=rst_n&&state==IDLE&&!active;
 assign cfg_ready=rst_n&&active&&mem_enable&&state==IDLE;
 assign input_ready=rst_n&&state==IDLE&&!active&&mem_enable&&!input_ok;
 assign start_ready=rst_n&&state==IDLE&&!active&&common_ok&&layer_ok&&input_ok&&!error;
 assign output_valid=rst_n&&state==OUT;
 assign output_data={x[output_pos+3],x[output_pos+2],x[output_pos+1],x[output_pos]};
 assign output_last=output_pos==6332;
 always @(posedge clk or negedge rst_n) begin
  if(!rst_n)begin
   state<=IDLE;active<=0;common_ok<=0;layer_ok<=0;input_ok<=0;frame_bad<=0;
   error<=0;done<=0;pos<=0;input_pos<=0;output_pos<=0;crc<=32'hffffffff;
   receiving_common<=0;layer<=0;kind<=0;t<=0;oc<=0;red<=0;kg<=0;ch<=0;sent<=0;received<=0;
   maximum<=0;sum_s<=0;sum_t<=0;hvalue<=0;den_sqrt<=0;reciprocal<=0;denominator<=0;lnphase<=0;lnnumber<=1;
  end else begin
   done<=0;
   if(frame_valid&&frame_ready)begin
    active<=1;receiving_common<=frame_common;layer<=frame_layer;pos<=0;crc<=32'hffffffff;frame_bad<=0;error<=0;
    if(frame_common)common_ok<=0;else layer_ok<=0;
    if(frame_layer>11)begin active<=0;error<=1;end
   end
   if(cfg_valid&&cfg_ready)begin
    if(receiving_common)common[pos]<=cfg_data;else par[pos]<=cfg_data;
    if(pos<16 && cfg_data!==header_word(receiving_common,layer,pos))frame_bad<=1;
    if(pos>=16)crc<=crc_word(crc,cfg_data);
    if(cfg_last || pos==(receiving_common?4143:15431))begin
     active<=0;
     if(!cfg_last||pos!=(receiving_common?4143:15431)||frame_bad||
        (pos<16&&cfg_data!==header_word(receiving_common,layer,pos))||
        ((crc_word(crc,cfg_data)^32'hffffffff)!==header_word(receiving_common,layer,14)))begin error<=1;common_ok<=receiving_common?0:common_ok;layer_ok<=0;end
     else if(receiving_common)common_ok<=1;else layer_ok<=1;
    end
    pos<=pos+1;
   end
   if(input_valid&&input_ready)begin
    for(lane=0;lane<4;lane=lane+1)x[input_pos+lane]<=input_data>>(lane*8);
    if(input_data[7:0]==128||input_data[15:8]==128||input_data[23:16]==128||input_data[31:24]==128)error<=1;
    if(input_last!=(input_pos==6332))begin error<=1;input_pos<=0;end
    else if(input_last)begin input_ok<=1;input_pos<=0;end
    else input_pos<=input_pos+4;
   end
   if(start_valid&&start_ready)begin kind<=0;t<=0;oc<=0;state<=DI;input_ok<=0;end
   if(state==OUT)begin
    if(output_ready)begin
     if(output_last)begin state<=IDLE;output_pos<=0;done<=1;end
     else output_pos<=output_pos+4;
    end
   end else if(core_enable)case(state)
    DI:begin
     for(row_lane=0;row_lane<8;row_lane=row_lane+1)for(lane=0;lane<8;lane=lane+1)
      acc[row_lane*8+lane]<=base_b<0?0:p32(base_b+4*(oc+lane));
     red<=0;state<=DM;
    end
    DM:begin
     for(row_lane=0;row_lane<8;row_lane=row_lane+1)if(row_lane<rows)
      for(lane=0;lane<8;lane=lane+1)acc[row_lane*8+lane]<=acc[row_lane*8+lane]+input_lane(kind,t+row_lane,red)*weight(base_w,kdim,ndim,red,oc+lane);
     if(red==kdim-1)begin sent<=0;received<=0;state<=DR;end else red<=red+1;
    end
    DR:begin
     if(rv&&rr)sent<=sent+1;
     if(ov)begin
      if(oe)begin error<=1;state<=IDLE;end
      else begin
       case(kind)
        0:qmem[(t+ot/8)*64+oc+ot%8]<=oq[7:0];1:kmem[(t+ot/8)*64+oc+ot%8]<=oq[7:0];2:vmem[(t+ot/8)*64+oc+ot%8]<=oq[7:0];
        4:hidden[(t+ot/8)*256+oc+ot%8]<=oq[7:0];default:vector_out[oc+ot]<=oq[7:0];
       endcase
       received<=received+1;
       if(received==8*rows-1)begin
        if(oc+8<ndim)begin oc<=oc+8;state<=DI;end
        else if(kind==3||kind==5)begin ch<=0;lnnumber<=kind==3?1:2;state<=RS;end
        else if(t+rows<99)begin t<=t+rows;oc<=0;state<=DI;end
        else if(kind<2)begin kind<=kind+1;t<=0;oc<=0;state<=DI;end
        else if(kind==2)begin t<=0;kg<=0;maximum<=-2147483647;state<=SI;end
        else begin ch<=0;state<=GL;end
       end
      end
     end
    end
    SI:begin for(lane=0;lane<8;lane=lane+1)acc[lane]<=0;red<=0;state<=SM;end
    SM:begin
     for(lane=0;lane<8;lane=lane+1)if(kg*8+lane<99)acc[lane]<=acc[lane]+$signed(qmem[t*64+red])*$signed(kmem[(kg*8+lane)*64+red]);
     if(red==63)state<=SS;else red<=red+1;
    end
    SS:begin
     max_work=maximum;
     for(lane=0;lane<8;lane=lane+1)if(kg*8+lane<99)begin score[kg*8+lane]<=acc[lane];if(acc[lane]>max_work)max_work=acc[lane];end
     maximum<=max_work;
     if(kg==12)begin sent<=0;received<=0;denominator<=0;state<=SR;end
     else begin kg<=kg+1;state<=SI;end
    end
    SR:begin
     if(rv&&rr)sent<=sent+1;
     if(ov)begin
      idx=$signed(oq)>0?0:($signed(oq)< -4096?4096:-$signed(oq));
      temp64=idx==4096?0:common[EXP_BASE/4+idx];exponent[ot]<=temp64[31:0];denominator<=denominator+temp64;
      if(oe)begin error<=1;state<=IDLE;end
      else if(received==98)state<=DS;
      received<=received+1;
     end
    end
    DS:if(wready)state<=DW;
    DW:if(wvalid)begin if(werror)begin error<=1;state<=IDLE;end else begin reciprocal<=wq+(wr!=0);ch<=0;state<=PN;end end
    PN:begin
     er={32'd0,exponent[ch]}*reciprocal;quotient=((er<<16)-er)>>47;
     numerator=({32'd0,exponent[ch]}<<16)-{32'd0,exponent[ch]};qd=quotient*denominator;
     if(qd>numerator)begin quotient=quotient-1;qd=qd-denominator;end
     remainder_n=numerator-qd;
     if(remainder_n>denominator-remainder_n||(remainder_n==denominator-remainder_n&&quotient[0]))quotient=quotient+1;
     probability[ch]<=quotient[15:0];
     if(ch==98)begin oc<=0;state<=PI;end else ch<=ch+1;
    end
    PI:begin for(lane=0;lane<8;lane=lane+1)acc[lane]<=0;red<=0;state<=PM;end
    PM:begin
     for(lane=0;lane<8;lane=lane+1)acc[lane]<=acc[lane]+$signed({1'b0,probability[red]})*$signed(vmem[red*64+oc+lane]);
     if(red==98)begin sent<=0;received<=0;state<=PR;end else red<=red+1;
    end
    PR:begin
     if(rv&&rr)sent<=sent+1;
     if(ov)begin ctxmem[oc+ot]<=oq[7:0];received<=received+1;
      if(oe)begin error<=1;state<=IDLE;end
      else if(received==7)begin if(oc<56)begin oc<=oc+8;state<=PI;end else begin kind<=3;oc<=0;state<=DI;end end
     end
    end
    RS:begin
     signed_temp=$signed(x[t*64+ch])*$signed(p64(lnnumber==1?R1_COEFF:R2_COEFF))+
                 $signed(vector_out[ch])*$signed(p64((lnnumber==1?R1_COEFF:R2_COEFF)+8));
     residual[ch]<=sat16(rne64(signed_temp,p64((lnnumber==1?R1_COEFF:R2_COEFF)+16)));
     if(ch==63)begin ch<=0;sum_s<=0;sum_t<=0;state<=LS;end else ch<=ch+1;
    end
    LS:begin
     sum_s<=sum_s+$signed(residual[ch]);signed_temp=$signed(residual[ch]);sum_t<=sum_t+signed_temp*signed_temp;
     if(ch==63)state<=LV;else ch<=ch+1;
    end
    LV:begin signed_temp=$signed(sum_s);hvalue<=(((sum_t<<6)-signed_temp*signed_temp)<<16)+p64(lnnumber==1?LN1_EPS:LN2_EPS);state<=QS;end
    QS:if(wready)state<=QW;
    QW:if(wvalid)begin den_sqrt<=wq;state<=IS;if(werror)begin error<=1;state<=IDLE;end end
    IS:if(wready)state<=IW;
    IW:if(wvalid)begin
     reciprocal<=wq+((wr>den_sqrt-wr)||(wr==den_sqrt-wr&&wq[0]));lnphase<=0;sent<=0;received<=0;state<=LR;
     if(werror)begin error<=1;state<=IDLE;end
    end
    LR:begin
     if(rv&&rr)sent<=sent+1;
     if(ov)begin
      if(lnphase==0)normal[ot]<=$signed(oq);
      else if(lnphase==1)affine[ot]<=$signed(oq)+p32((lnnumber==1?LN1_B:LN2_B)+ot*4);
      else x[t*64+ot]<=oq[7:0];
      received<=received+1;
      if(oe)begin error<=1;state<=IDLE;end
      else if(received==63)begin
       if(lnphase<2)begin lnphase<=lnphase+1;sent<=0;received<=0;end
       else if(lnnumber==1)begin
        if(t<98)begin t<=t+1;kg<=0;maximum<=-2147483647;state<=SI;end
        else begin kind<=4;t<=0;oc<=0;state<=DI;end
       end else if(t<98)begin t<=t+1;kind<=5;oc<=0;state<=DI;end
       else begin output_pos<=0;state<=OUT;end
      end
     end
    end
    GL:begin idx=$signed(hidden[ch])+128;hidden[ch]<=pbyte(GELU_LUT+idx);
     if(ch==25343)begin kind<=5;t<=0;oc<=0;state<=DI;end else ch<=ch+1;
    end
   endcase
  end
 end
endmodule

