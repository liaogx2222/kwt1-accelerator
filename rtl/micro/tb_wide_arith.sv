`timescale 1ns/1ps
module tb_wide_arith;
    logic clk=0,rst_n=0,req_valid=0,req_ready,resp_valid,resp_ready=0;
    logic [2:0] req_op=0;logic [63:0] req_a=0,req_b=0;
    logic signed [7:0] req_shift=0;
    logic [63:0] resp_result,resp_remainder;
    logic resp_error;
    wide_arith dut(.*);
    always #5 clk=~clk;
    integer fd,status,n=0,op,shift,err,delay,watch,hold_cycles;
    integer request_stalls=0,response_stalls=0;
    logic [63:0] aa,bb,expected,rem_expected,held,held_rem;
    logic held_error;
    string vectors;
    task reset_dut;
        begin
            @(negedge clk);rst_n=0;req_valid=0;resp_ready=0;
            repeat(2) @(negedge clk);
            if(resp_valid) $fatal(1,"reset did not cancel response");
            rst_n=1;@(negedge clk);
            if(!req_ready) $fatal(1,"reset did not restore ready");
        end
    endtask
    task issue_reset(input bit held_response);
        begin
            @(negedge clk);req_op=3;req_a=64'hffffffffffffffff;req_b=37;req_valid=1;
            @(posedge clk);if(!req_ready) $fatal(1,"reset test acceptance");
            @(negedge clk);req_valid=0;
            if(held_response) begin
                wait(resp_valid);repeat(3) @(negedge clk);
            end else repeat(7) @(negedge clk);
            reset_dut();repeat(70) begin
                @(negedge clk);if(resp_valid) $fatal(1,"stale result after reset");
            end
        end
    endtask
    initial begin
        if(!$value$plusargs("vectors=%s",vectors)) $fatal(1,"need vectors");
        reset_dut();issue_reset(0);issue_reset(1);
        fd=$fopen(vectors,"r");if(!fd) $fatal(1,"vectors open failed");
        while(!$feof(fd)) begin
            status=$fscanf(fd,"%d %h %h %d %h %h %d\n",op,aa,bb,shift,expected,rem_expected,err);
            if(status!=7) $fatal(1,"vector parse failure");
            repeat(n%4) @(negedge clk);
            req_op=op;req_a=aa;req_b=bb;req_shift=shift;req_valid=1;resp_ready=0;
            @(posedge clk);if(!req_ready) $fatal(1,"unexpected request stall");
            @(negedge clk);req_valid=0;watch=0;
            // A queued request stays valid/stable while the core is busy.
            req_valid=1;req_op=op;req_a=aa;req_b=bb;req_shift=shift;
            while(!resp_valid) begin
                if(req_ready) $fatal(1,"accepted request while busy");
                request_stalls=request_stalls+1;watch=watch+1;
                if(watch>70) $fatal(1,"operation timeout");
                @(negedge clk);
            end
            held=resp_result;held_rem=resp_remainder;held_error=resp_error;
            hold_cycles=1+(n%7);
            repeat(hold_cycles) begin
                if(req_ready || !resp_valid || resp_result!==held || resp_remainder!==held_rem || resp_error!==held_error)
                    $fatal(1,"response unstable under stall");
                response_stalls=response_stalls+1;@(negedge clk);
            end
            if(resp_result!==expected || resp_remainder!==rem_expected || resp_error!==err[0])
                $fatal(1,"mismatch n=%0d op=%0d a=%h b=%h shift=%0d got=%h rem=%h err=%b expected=%h rem=%h err=%d",n,op,aa,bb,shift,resp_result,resp_remainder,resp_error,expected,rem_expected,err);
            req_valid=0;resp_ready=1;@(negedge clk);resp_ready=0;
            if(resp_valid) $fatal(1,"response did not retire");
            n=n+1;
        end
        $fclose(fd);
        $display("PASS vectors=%0d request_stalls=%0d response_stalls=%0d reset_tests=2",n,request_stalls,response_stalls);
        $finish;
    end
    initial begin #10000000;$fatal(1,"global timeout");end
endmodule
