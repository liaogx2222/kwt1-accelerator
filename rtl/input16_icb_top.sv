// Complete newly added digital logic for the S16 reference configuration.
// CPU, shared SRAM, and host endpoint are fixed/externally supplied.
module kwt_input16_icb_top(input wire clk,rst_n,accel_abort,drop_response,
 input wire pv,pread,input wire [31:0] pa,pw,input wire [3:0] pmask,
 output wire pr,prv,input wire prr,output wire [31:0] prd,
 output wire hv,hread,output wire [31:0] ha,hw,output wire [3:0] hm,input wire hr,hrv,output wire hrr,input wire [31:0] hrd,
 output wire irq,output wire signed [31:0] bus_rc,output wire [31:0] parameter_words);
 wire av,ar,awrite,arv,arr,ae;wire [31:0] aa,ad,ard;wire [3:0] am;
 icb_kwt_bridge bridge(clk,rst_n,accel_abort,16'd64,drop_response,pv,pr,pa,pw,pread,pmask,prv,prr,prd,
  hv,hr,ha,hw,hread,hm,hrv,hrr,hrd,av,ar,awrite,aa,ad,am,arv,arr,ard,ae,bus_rc,parameter_words);
 kwt1_mmio accelerator(clk,rst_n,accel_abort,1'b1,1'b1,av,ar,awrite,aa,ad,am,arv,arr,ard,ae,irq);
endmodule
