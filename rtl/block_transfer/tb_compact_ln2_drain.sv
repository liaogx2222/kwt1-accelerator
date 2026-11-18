module tb_compact_ln2_drain;
    reg clk=0,rst_n=0,clear=0,start=0,ready=0;
    wire owned,read_s,valid,last;
    wire [9:0] addr,index;
    reg [63:0] s_data=64'hcccccccccccccccc;
    wire [63:0] data;
    kwt_compact_ln2_drain dut(clk,rst_n,clear,start,owned,read_s,addr,s_data,valid,ready,index,last,data);

    function automatic [63:0] word_at(input [9:0] at);
        word_at={4'hd,at,~at,at^10'h256,at,~at,at^10'h1a7};
    endfunction
    always @(posedge clk) if(read_s) s_data<=word_at(addr);

    task automatic tick;
        begin #5; clk=1; #5; clk=0; #1; end
    endtask

    task automatic frame(input integer fault);
        integer received,issued,cycle,turnovers,stalls;
        reg held;
        begin
            received=0; issued=0; cycle=0; turnovers=0; stalls=0; held=0;
            start=1; #1;
            if(!owned||valid||read_s)$fatal(1,"start ownership");
            tick(); start=0;
            while(received<792) begin
                ready=cycle%23>=5; #1;
                if(!owned||cycle>1200)$fatal(1,"drain progress");
                if(valid) begin
                    if(index!==10'(received)||data!==word_at(10'(received))||last!==(received==791))
                        $fatal(1,"payload at %d",received);
                end else if(held)$fatal(1,"dropped stalled output");
                held=valid&&!ready;
                if(held) begin
                    ++stalls;
                    if(read_s)$fatal(1,"read during stall");
                end
                if(read_s) begin
                    if(addr!==10'(issued)||issued>=792)$fatal(1,"bad SRAM request");
                    ++issued;
                end
                if(valid&&ready) begin
                    ++received;
                    if(read_s)++turnovers;
                end
                if(fault!=0&&received>=8&&held) begin
                    if(fault==1)clear=1;
                    else rst_n=0;
                    #1;
                    if(owned||valid||read_s||last)$fatal(1,"late access after cancel/reset");
                    tick(); clear=0; rst_n=1; #1;
                    if(owned||valid||read_s||last)$fatal(1,"stale response after cancel/reset");
                    disable frame;
                end
                tick(); ++cycle;
            end
            if(fault!=0||issued!=792||turnovers!=791||stalls==0||owned||valid||read_s)
                $fatal(1,"frame conservation or finish");
        end
    endtask

    initial begin
        tick(); rst_n=1;
        frame(0); frame(1); frame(0); frame(2); frame(0);
        $display("PASS mapped drain full_frames=3 words=2376 turnovers=2373 cancel=1 reset=1");
        $finish;
    end
endmodule
