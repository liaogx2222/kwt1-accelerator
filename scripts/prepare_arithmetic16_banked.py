"""Static grouping for four legal read lanes; remove unreachable mux inputs."""
from local_tools import ROOT

def main():
    src=ROOT/'rtl/experimental/kwt_arithmetic16_structural.sv';dest=ROOT/'rtl/experimental/kwt_arithmetic16_banked.sv';assert not dest.exists()
    text=src.read_text().replace('wire [8191:0] matrix0,matrix1;','wire [8191:0] lane_matrix0,lane_matrix1;')
    text=text.replace('assign matrix0[(row*16+col)*32+:32]=acc0;assign matrix1[(row*16+col)*32+:32]=acc1;',
        'assign lane_matrix0[((row%4)*64+(row/4)*16+col)*32+:32]=acc0;assign lane_matrix1[((row%4)*64+(row/4)*16+col)*32+:32]=acc1;')
    old='''     for(lane=0;lane<4;lane=lane+1)raw_data[lane*32+:32]<=read_bank?
      matrix1[((read_row[3:2]*4+lane)*16+read_col)*32+:32]:matrix0[((read_row[3:2]*4+lane)*16+read_col)*32+:32];'''
    assert old in text;text=text.replace(old,'')
    text=text.replace('raw_valid<=0;raw_data<=0;raw_tag<=0;raw_bank<=0;','raw_valid<=0;raw_tag<=0;raw_bank<=0;')
    insert=''' genvar rd;
 generate for(rd=0;rd<4;rd=rd+1)begin: read_lanes
  always @(posedge clk or negedge rst_n)begin
   if(!rst_n)raw_data[rd*32+:32]<=0;
   else if(read_fire)raw_data[rd*32+:32]<=read_bank?
    lane_matrix1[rd*2048+{read_row[3:2],read_col,5'b0}+:32]:lane_matrix0[rd*2048+{read_row[3:2],read_col,5'b0}+:32];
  end
 end endgenerate
'''
    text=text.replace(' integer lane;\n',insert)
    assert 'matrix0[((read' not in text;dest.write_text(text)

if __name__=='__main__':main()
