"""Own implementation: select accumulator bank BEFORE one shared PE adder."""
from local_tools import ROOT

def main():
    source=ROOT/'rtl/experimental/kwt_arithmetic16_banked.sv';dest=ROOT/'rtl/experimental/kwt_arithmetic16_shared.sv';assert not dest.exists()
    text=source.read_text();old='''   reg signed [31:0] acc0,acc1;
   always @(posedge clk)begin
    if(init_fire&&!init_bank)acc0<=init_bias[col*32+:32];else if(mac_fire&&!mac_bank)acc0<=acc0+term;
    if(init_fire&&init_bank)acc1<=init_bias[col*32+:32];else if(mac_fire&&mac_bank)acc1<=acc1+term;
   end'''
    new='''   reg signed [31:0] acc0,acc1;
   wire signed [31:0] selected_acc=mac_bank?acc1:acc0;
   wire signed [31:0] updated_acc=selected_acc+term;
   always @(posedge clk)begin
    if(init_fire&&!init_bank)acc0<=init_bias[col*32+:32];else if(mac_fire&&!mac_bank)acc0<=updated_acc;
    if(init_fire&&init_bank)acc1<=init_bias[col*32+:32];else if(mac_fire&&mac_bank)acc1<=updated_acc;
   end'''
    assert text.count(old)==1;dest.write_text(text.replace(old,new))

if __name__=='__main__':main()
