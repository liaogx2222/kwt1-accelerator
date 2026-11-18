module tb_rne_dense_right;
    reg clk=0, rst_n=0, valid=0, ready=0, injected=0;
    always #5 clk=~clk;
    reg [63:0] value=0;
    reg signed [7:0] shift=38;
    reg [5:0] sat=8;
    reg [15:0] tag=0;
    wire r0,r1,v0,v1,e0,e1;
    wire [63:0] d0,d1;
    wire [15:0] t0,t1;
    kwt_rne_dense_right specialized(clk,rst_n,valid,r0,value,shift,sat,injected,tag,v0,ready,d0,e0,t0);
    rne_pipe generic(clk,rst_n,valid,r1,value,shift,sat,injected,tag,v1,ready,d1,e1,t1);
    integer sent=0,seen=0,cycles=0,stall=0;
    reg compare=1;
    always @(posedge clk) begin
        cycles<=cycles+1;
        if(rst_n) begin
            if(compare && (r0!==r1 || v0!==v1 || (v0 && {d0,e0,t0}!=={d1,e1,t1})))
                $fatal(1,"RNE A/B mismatch tag=%d %h %h",t0,d0,d1);
            if(v0&&ready) seen<=seen+1;
            if(v0&&!ready) stall<=stall+1;
        end
    end

    task issue(input [63:0] next_value,input integer next_shift);
        begin
            value=next_value; shift=8'(next_shift); tag=16'(sent); valid=1;
            #1;
            while(!r0)begin
                @(negedge clk); ready=cycles%7>=3; #1;
            end
            @(negedge clk); valid=0; sent=sent+1;
            ready=cycles%7>=3;
        end
    endtask

    reg [63:0] mag,lfsr=64'h7894561230abcdef;
    initial begin
        repeat(3) @(negedge clk);
        rst_n=1; ready=1; @(negedge clk);
        for(integer s=38;s<=48;s=s+1)begin
            for(integer q=0;q<=130;q=q+1)begin
                for(integer delta=-1;delta<=1;delta=delta+1)begin
                    mag=(64'(q)<<s)+(64'd1<<(s-1))+64'(delta);
                    issue(mag,s); issue(-mag,s);
                end
            end
            issue(64'h7fffffffffffffff,s);
            issue(64'h8000000000000001,s);
            issue(64'h8000000000000000,s);
        end
        for(integer k=0;k<2048;k=k+1)begin
            lfsr={lfsr[62:0],lfsr[63]^lfsr[62]^lfsr[60]^lfsr[59]};
            issue(lfsr,38+k%11);
        end
        injected=1; issue(64'd1<<38,38); injected=0;
        ready=1; repeat(3) @(negedge clk);
        if(seen!=sent || stall==0) $fatal(1,"lost result or missing backpressure");
        compare=0;
        issue(64'd1,37);
        if(!v0 || !e0 || d0!=0) $fatal(1,"illegal shift accepted");
        issue(64'd1,49);
        if(!v0 || !e0 || d0!=0) $fatal(1,"illegal shift accepted");
        sat=16; issue(64'd1,38);
        if(!v0 || !e0 || d0!=0) $fatal(1,"illegal saturation accepted");
        ready=0; rst_n=0; @(negedge clk);
        if(v0) $fatal(1,"stalled result survived reset");
        $display("PASS comparable=%d rejected=3 stall_cycles=%d",sent-3,stall);
        $finish;
    end
endmodule
