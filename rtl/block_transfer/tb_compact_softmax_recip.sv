module tb_compact_softmax_recip;
    reg clk=0,rst_n=0,request=0,accept=0;
    reg [26:0] denominator=0;
    wire ready,valid,error;
    wire [27:0] quotient;
    kwt_compact_softmax_recip dut(clk,rst_n,request,ready,denominator,valid,accept,quotient,error);
    integer checked=0;
    reg [31:0] random_bits=32'hf17a8693;
    task automatic tick;
        begin #5;clk=1;#5;clk=0;#1;end
    endtask
    task automatic run(input [26:0] d,input integer stall);
        reg [63:0] expected;
        integer elapsed;
        begin
            expected=d<27'h100000 ? 0 : (64'd140737488355328+{37'd0,d}-1)/d;
            if(!ready)$fatal(1,"reciprocal request blocked while idle");
            denominator=d;request=1;accept=0;tick();request=0;
            elapsed=0;
            while(!valid)begin
                if(ready||elapsed>14)$fatal(1,"reciprocal busy or progress");
                tick();elapsed=elapsed+1;
            end
            if(elapsed!=(d<27'h100000 ? 0 : 14))$fatal(1,"reciprocal latency");
            repeat(stall+1)begin
                if(!valid||ready||quotient!==expected[27:0]||error!==(d<27'h100000))
                    $fatal(1,"reciprocal denominator=%h quotient=%h expected=%h",d,quotient,expected);
                tick();
            end
            accept=1;tick();accept=0;#1;
            if(valid||!ready)$fatal(1,"reciprocal response did not retire");
            checked=checked+1;
        end
    endtask
    initial begin
        tick();rst_n=1;#1;
        run(0,3);run(27'hfffff,3);
        for(integer power=20;power<=26;power=power+1)begin
            run(27'd1<<power,1);
            run((27'd1<<power)+1,2);
            run((27'd1<<power)-1,3);
        end
        run(27'd103809024,3);run(27'h7ffffff,4);
        for(integer i=0;i<1024;i=i+1)begin
            random_bits=random_bits^(random_bits<<13);
            random_bits=random_bits^(random_bits>>17);
            random_bits=random_bits^(random_bits<<5);
            run(27'h100000|random_bits[26:0],i%4);
        end
        denominator=27'd103809024;request=1;tick();request=0;repeat(5)tick();
        rst_n=0;#1;
        if(valid||ready)$fatal(1,"stale in-flight result after reset");
        tick();rst_n=1;#1;
        run(27'h100000,3);
        if(checked!=1050)$fatal(1,"reciprocal coverage");
        $display("PASS reciprocal denominators=%0d bounded_steps=14 stalled_reset=1",checked);
        $finish;
    end
endmodule
