"""One physical accumulator buffer, same arithmetic and explicit bank0 IO."""
from local_tools import ROOT

def main():
    src=ROOT/'rtl/experimental/kwt_arithmetic16_shared.sv';dest=ROOT/'rtl/experimental/kwt_arithmetic16_single.sv';assert not dest.exists();text=src.read_text()
    text=text.replace('assign empty={state[1]==EMPTY,state[0]==EMPTY};assign done={state[1]==DONE,state[0]==DONE};','assign empty={1\'b1,state[0]==EMPTY};assign done={1\'b0,state[0]==DONE};')
    text=text.replace('assign init_ready=rst_n&&(state[init_bank]==EMPTY);assign mac_ready=rst_n&&(state[mac_bank]==ACTIVE);','assign init_ready=rst_n&&!init_bank&&(state[0]==EMPTY);assign mac_ready=rst_n&&!mac_bank&&(state[0]==ACTIVE);')
    text=text.replace('assign read_ready=rst_n&&(state[read_bank]==DONE)', 'assign read_ready=rst_n&&!read_bank&&(state[0]==DONE)')
    text=text.replace('assign release_ready=rst_n&&(state[release_bank]==DONE)', 'assign release_ready=rst_n&&!release_bank&&(state[0]==DONE)')
    text=text.replace('reg signed [31:0] acc0,acc1;',"reg signed [31:0] acc0;wire signed [31:0] acc1=32'd0;")
    text=text.replace('wire signed [31:0] selected_acc=mac_bank?acc1:acc0;','wire signed [31:0] selected_acc=acc0;')
    line='    if(init_fire&&init_bank)acc1<=init_bias[col*32+:32];else if(mac_fire&&mac_bank)acc1<=updated_acc;'
    assert text.count(line)==1;text=text.replace(line,'');dest.write_text(text)

if __name__=='__main__':main()
