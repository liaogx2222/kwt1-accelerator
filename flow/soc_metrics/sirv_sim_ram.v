// Physical reference binding for the existing E203 TCM read protocol.
// dout is meaningful after a selected read; writes/disabled cycles hold Q.
// sd/ds/ls are unused by the inherited sirv_sim_ram interface as well.
module sirv_sim_ram #(parameter DP=512, FORCE_X2ZERO=0, DW=32, MW=4, AW=32)(
 input clk,input [DW-1:0] din,input [AW-1:0] addr,input cs,we,
 input [MW-1:0] wem,output [DW-1:0] dout);
 localparam NP=(DP+4095)/4096, NL=(DW+15)/16;
 localparam PW=AW>12?AW-12:1;
 reg [PW-1:0] page_q;
 wire [DW-1:0] page_data[0:NP-1];
 wire [PW-1:0] page=addr>>12;
 wire [11:0] macro_addr=addr;
 always @(posedge clk)if(cs&&!we)page_q<=page;
 genvar p,l,b;
 generate for(p=0;p<NP;p=p+1)begin:page_bank
  for(l=0;l<NL;l=l+1)begin:lane
   wire [15:0] wd,q,wen;
   for(b=0;b<16;b=b+1)begin:bitslice
    if(l*16+b<DW)begin:valid_bit
     assign wd[b]=din[l*16+b];
     assign wen[b]=~(cs&&we&&wem[(l*16+b)/8]);
     assign page_data[p][l*16+b]=q[b];
    end else begin:padding
     assign wd[b]=1'b0;assign wen[b]=1'b1;
    end
   end
   RAMSP4096X16 macro_cell(.Q(q),.CLK(clk),.CEN(~(cs&&page==p)),
    .GWEN(~(cs&&we)),.WEN(wen),.A(macro_addr),.D(wd),
    .EMA(3'b010),.EMAW(2'b00),.RET1N(1'b1));
  end
 end endgenerate
 assign dout=page_data[page_q];
endmodule
