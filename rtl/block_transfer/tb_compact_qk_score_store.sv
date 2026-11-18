module tb_compact_qk_score_store;
    reg clk=0,rst_n=0,clear=0,start=0,tail=0,sv=0,close_group=0,release_group=0;
    reg rv=0,pr=0;
    reg [1:0] squad=0;
    reg [6:0] skey=0,rkey=0;
    reg [3:0] smask=0,rrow=0;
    reg [127:0] scores=0;
    wire start_ready,sready,available,error,rready,pv;
    wire signed [31:0] probability_input;
    wire [7:0] en,we;
    wire [9:0] addr;
    wire [127:0] wd,rd;
    kwt_compact_qk_score_store dut(clk,rst_n,clear,start,tail,start_ready,sv,sready,squad,skey,smask,
        scores,close_group,release_group,available,error,rv,rready,rrow,rkey,pv,pr,probability_input,
        en,we,addr,wd,rd);
    for(genvar i=0;i<8;i=i+1)begin:b_bank
        kwt_small_sp bank(clk,en[i],we[i],addr,wd[16*i+:16],rd[16*i+:16]);
    end
    integer cycles=0,completed=0,stalls=0,turnovers=0;
    function automatic signed [31:0] value(input integer seed,row_index,key_index);
        value=32'sh60000000-32'(seed*1779033703+row_index*3456781+key_index*1300711);
    endfunction
    task automatic tick;
        begin #5;clk=1;#5;clk=0;#1;cycles=cycles+1;end
    endtask
    task automatic group(input integer seed,rows,input bit cancel);
        integer sent,got,total;
        reg held;
        begin
            if(!start_ready)$fatal(1,"B score owner not idle");
            start=1;tail=rows==3;tick();start=0;
            for(integer q=0;q<(rows+3)/4;q=q+1)
                for(integer k=0;k<99;k=k+1)begin
                    sv=1;squad=2'(q);skey=7'(k);smask=tail?7:15;
                    for(integer i=0;i<4;i=i+1)scores[32*i+:32]=value(seed,4*q+i,k);
                    #1;
                    if(!sready||error||en!==(tail?8'h3f:8'hff)||we!==en||addr!==10'(q*99+k))
                        $fatal(1,"B score write address/mask");
                    tick();
                end
            sv=0;close_group=1;tick();close_group=0;
            if(!available||error)$fatal(1,"score group not published");
            sent=0;got=0;total=rows*99;held=0;
            while(got<total)begin
                rv=sent<total;rrow=4'(sent/99);rkey=7'(sent%99);pr=cycles%9>=3;
                #1;
                if(!available||error)$fatal(1,"lost B score lease");
                if(held&&!pv)$fatal(1,"stalled B response lost");
                held=pv&&!pr;
                if(pv&&probability_input!==value(seed,got/99,got%99))
                    $fatal(1,"physical score mismatch index=%d",got);
                if(held)begin
                    if(en!=0)$fatal(1,"B SRAM advanced during stall");
                    stalls=stalls+1;
                    if(cancel&&got>=8)begin
                        clear=1;#1;
                        if(available||pv||en!=0)$fatal(1,"stale B response on cancel");
                        tick();clear=0;rv=0;pr=0;#1;
                        if(!start_ready||pv)$fatal(1,"stale B state after clear");
                        disable group;
                    end
                end
                if(rv&&rready)begin
                    if(en!==(8'd3<<((sent/99%4)*2))||we!=0||addr!==10'(sent/99/4*99+sent%99))
                        $fatal(1,"B score read address/mask");
                    sent=sent+1;
                    if(pv&&pr)turnovers=turnovers+1;
                end
                if(pv&&pr)got=got+1;
                tick();
            end
            if(cancel||sent!=total)$fatal(1,"B score read conservation");
            completed=completed+got;
            rv=0;release_group=1;tick();release_group=0;
        end
    endtask
    initial begin
        tick();rst_n=1;#1;
        group(1,16,0);group(2,3,0);group(3,16,1);group(4,16,0);
        if(completed!=3465||turnovers==0||stalls==0)$fatal(1,"B score coverage");
        $display("PASS physical B scores=3465 stalls=%0d turnovers=%0d cancel=1",stalls,turnovers);
        $finish;
    end
endmodule
