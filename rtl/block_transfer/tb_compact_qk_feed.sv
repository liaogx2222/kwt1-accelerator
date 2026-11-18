module tb_compact_qk_feed;
    reg clk=0,rst_n=0;
    reg in_valid=0,matrix_done=0,start=0,score_ready=0;
    reg [2:0] matrix=0,qg=0,kg=0;
    reg [12:0] tag=0;
    reg [31:0] in_data=0;
    wire in_ready,available,qread,qready,qvalid,qaccept,qerror;
    wire [1:0] qmatrix;
    wire [8:0] qindex;
    wire [127:0] qdata;
    wire [15:0] qmask;
    wire [3:0] se,sw;
    wire [11:0] sa;
    wire [63:0] sd,sq;
    kwt_compact_qkv_resident resident(clk,rst_n,1'b0,in_valid,in_ready,matrix,tag,in_data,matrix_done,
        available,1'b0,qread,qready,qmatrix,qindex,qvalid,qaccept,qdata,qmask,qerror,se,sw,sa,sd,sq);
    for(genvar i=0;i<4;i=i+1)begin:s_bank
        kwt_sram_sp bank(clk,se[i],sw[i],sa,sd[i*16+:16],sq[i*16+:16]);
    end

    wire ae,aw,mi,mir,mv,mr,ml,mread,mread_ready,mraw,mraw_ready,mrel,mrel_ready;
    wire start_ready,score_valid,done,error;
    wire [9:0] aa;
    wire [127:0] ad,aq,ma,mb,raw_data,scores;
    wire [3:0] mrow,mcol,score_row,score_col,score_mask;
    wire [15:0] mtag,raw_tag;
    kwt_compact_qk_feed feed(clk,rst_n,1'b0,start,start_ready,qg,kg,
        qread,qready,qmatrix,qindex,qvalid,qaccept,qdata,qmask,qerror,ae,aw,aa,ad,aq,
        mi,mir,mv,mr,ml,ma,mb,mread,mread_ready,mrow,mcol,mtag,mraw,raw_data,raw_tag,mraw_ready,
        mrel,mrel_ready,score_valid,score_ready,scores,score_row,score_col,score_mask,done,error);
    for(genvar j=0;j<8;j=j+1)begin:a_bank
        kwt_small_sp bank(clk,ae,aw,aa,ad[j*16+:16],aq[j*16+:16]);
    end
    kwt_tile16_mac mac(clk,rst_n,mi,mir,1'b0,512'd0,mv,mr,1'b0,1'b0,1'b0,ml,ma,mb,
        mread,mread_ready,1'b0,mrow,mcol,mtag,mraw,mraw_ready,raw_data,raw_tag,
        mrel,mrel_ready,1'b0,,);

    integer cycle=0,total=0,tile_cycles=0,max_tile=0,stalls=0;
    function automatic integer code(input integer slot,token,channel);
        code=(slot*39+token*89+channel*109+(token^channel)*13)%255-127;
    endfunction
    task automatic tick;
        begin #5;clk=1;#5;clk=0;#1;cycle=cycle+1;end
    endtask
    task automatic fill(input integer slot);
        begin
            matrix=slot==0?4:slot==1?2:5;
            for(integer tile=0;tile<4;tile=tile+1)
                for(integer group_index=0;group_index<7;group_index=group_index+1)
                    for(integer quad=0;quad<(group_index==6?1:4);quad=quad+1)
                        for(integer ch=0;ch<16;ch=ch+1)begin
                            while(!in_ready)tick();
                            tag={3'(group_index),2'b0,2'(tile),2'(quad),4'(ch)};
                            for(integer lane=0;lane<4;lane=lane+1)
                                in_data[lane*8+:8]=8'(code(slot,group_index*16+quad*4+lane,tile*16+ch));
                            in_valid=1;tick();in_valid=0;
                        end
            while(!in_ready)tick();
            matrix_done=1;tick();matrix_done=0;
        end
    endtask

    task automatic run_tile(input integer query,key);
        integer begin_cycle,rows,cols,received,expected,row0,col0;
        begin
            if(!start_ready||!available)$fatal(1,"Q/K tile could not start");
            qg=3'(query);kg=3'(key);start=1;begin_cycle=cycle;tick();start=0;
            rows=query==6?3:16;cols=key==6?3:16;received=0;
            while(!done)begin
                score_ready=cycle%11>=4;
                #1;
                if(error||cycle-begin_cycle>600)$fatal(1,"QK feed timeout or error");
                if(ae&&(aa<448||aa>511))$fatal(1,"Q cache address");
                if(score_valid)begin
                    row0=(received/cols)*4;col0=received%cols;
                    if(score_row!==4'(row0)||score_col!==4'(col0)||score_mask!==(rows==3?4'b0111:4'b1111))
                        $fatal(1,"QK score tag or mask");
                    for(integer lane=0;lane<4;lane=lane+1)if(row0+lane<rows)begin
                        expected=0;
                        for(integer ch=0;ch<64;ch=ch+1)
                            expected=expected+code(0,query*16+row0+lane,ch)*code(1,key*16+col0,ch);
                        if(scores[lane*32+:32]!==32'(expected))$fatal(1,"QK score value q=%d k=%d row=%d col=%d",query,key,row0+lane,col0);
                    end
                    if(score_ready)begin received=received+1;total=total+(rows==3?3:4);end
                    else stalls=stalls+1;
                end
                tick();
            end
            if(received!=((rows+3)/4)*cols)$fatal(1,"QK tile cardinality");
            tile_cycles=tile_cycles+cycle-begin_cycle;
            if(cycle-begin_cycle>max_tile)max_tile=cycle-begin_cycle;
            tick();
        end
    endtask

    initial begin
        tick();rst_n=1;
        fill(0);fill(1);fill(2);
        for(integer query=0;query<7;query=query+1)
            for(integer key=0;key<7;key=key+1)run_tile(query,key);
        if(total!=9801||stalls==0)$fatal(1,"QK coverage");
        $display("PASS resident QK tiles=49 scores=9801 tile_cycles=%0d max_tile=%0d stalls=%0d",tile_cycles,max_tile,stalls);
        $finish;
    end
endmodule
