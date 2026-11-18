module soc_sram_sp(input clk,en,we,input[11:0]addr,input[15:0]wdata,output[15:0]rdata);
 RAMSP4096X16 macro_cell(.Q(rdata),.CLK(clk),.CEN(~en),.GWEN(~(en&&we)),
 .WEN(en&&we?16'h0000:16'hffff),.A(addr),.D(wdata),.EMA(3'b010),.EMAW(2'b00),.RET1N(1'b1));
endmodule
