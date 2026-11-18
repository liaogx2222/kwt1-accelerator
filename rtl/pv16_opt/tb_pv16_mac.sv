`timescale 1ns/1ps
module tb_pv16_mac;
 reg clk=0,rst_n=0,load=0,en=0;always #5 clk=~clk;
 reg [7:0] rm=8'hff;reg [15:0] cm=16'hffff;
 reg [127:0] full_a=0,lo_a=0,hi_a=0,b=0;
 wire [4095:0] full_acc,lo_acc,hi_acc;reg [511:0] bias=0;
 kwt_mac_array #(.ROWS(8),.COLS(16)) full_pe(clk,rst_n,load,en,1'b1,rm,cm,full_a,b,bias,full_acc);
 kwt_mac_array #(.ROWS(8),.COLS(16)) old_lo(clk,rst_n,load,en,1'b1,rm,cm,lo_a,b,bias,lo_acc);
 kwt_mac_array #(.ROWS(8),.COLS(16)) old_hi(clk,rst_n,load,en,1'b1,rm,cm,hi_a,b,bias,hi_acc);
 integer trial,k,r,c,i;reg [31:0] rng=32'h20261113;reg [15:0] p;reg signed[7:0] v;
 reg signed[63:0] expected,got;reg [4095:0] held;integer checks=0,stalls=0,resets=0;
 function [31:0] next_random(input [31:0] x);next_random=x*32'd1664525+32'd1013904223;endfunction
 task compare;
 begin
  for(i=0;i<128;i=i+1)begin
   expected=$signed(lo_acc[i*32+:32]);expected=expected+($signed({{32{hi_acc[i*32+31]}},hi_acc[i*32+:32]})<<<8);
   got=$signed(full_acc[i*32+:32]);
   if(got!==expected)$fatal(1,"PV16_MISMATCH trial=%0d term=%0d PE=%0d new=%0d old=%0d",trial,k,i,got,expected);
   checks=checks+1;
  end
 end
 endtask
 initial begin
  repeat(2)@(negedge clk);rst_n=1;
  for(trial=0;trial<256;trial=trial+1)begin
   rm=trial%3==0?8'h07:8'hff;cm=trial%5==0?16'h0007:16'hffff;
   load=1;en=0;@(negedge clk);load=0;
   for(k=0;k<99;k=k+1)begin
    for(r=0;r<8;r=r+1)begin
     rng=next_random(rng);p=rng[15:0];
     if(trial==0)p=65535;if(trial==1)p=32768;if(trial==2)p=256;if(trial==3)p=255;if(trial==4)p=0;
     full_a[16*r+:16]=p;lo_a[16*r+:16]={8'd0,p[7:0]};hi_a[16*r+:16]={8'd0,p[15:8]};
    end
    for(c=0;c<16;c=c+1)begin
     rng=next_random(rng);v=rng[7:0];if(trial==0)v=-128;if(trial==1)v=127;b[8*c+:8]=v;
    end
    en=1;@(negedge clk);compare();
    if(k%13==4)begin
     held=full_acc;en=0;full_a='x;lo_a='x;hi_a='x;b='x;
     repeat(3)begin @(negedge clk);if(full_acc!==held)$fatal(1,"PV16_STALL_CHANGED");compare();stalls=stalls+1;end
    end
    if(trial%17==0&&k==47)begin
     en=0;rst_n=0;@(negedge clk);
     if(full_acc!==0||lo_acc!==0||hi_acc!==0)$fatal(1,"PV16_RESET");
     rst_n=1;resets=resets+1;
    end
   end
   en=0;
  end
  $display("PASS PV16_MAC four_state=1 checks=%0d stalls=%0d inflight_resets=%0d",checks,stalls,resets);$finish;
 end
 initial begin #1000000;$fatal(1,"PV16_WATCHDOG");end
endmodule
