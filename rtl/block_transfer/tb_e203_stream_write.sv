module tb_e203_stream_write;
    reg clk=0, rst_n=0;
    always #5 clk=~clk;
    reg req=0, reply_ready=0;
    reg [31:0] source=32'ha0026000, words=2;
    reg cmd_ready=0, rsp_valid=0, rsp_err=0;
    reg [31:0] rsp_data=0;
    reg ready=0, sink_err=0, cancel=0;
    wire req_ready, reply, hold, cmd, rsp_ready, valid;
    wire [31:0] result, addr, data;
    integer reads=0, writes=0;
    e203_subsys_nice_core #(.TIMEOUT(4)) dut (
        .nice_clk(clk),.nice_rst_n(rst_n),.nice_active(),.nice_mem_holdup(hold),
        .nice_req_valid(req),.nice_req_ready(req_ready),.nice_req_inst(32'h5000707b),
        .nice_req_rs1(source),.nice_req_rs2(words),.nice_rsp_valid(reply),.nice_rsp_ready(reply_ready),
        .nice_rsp_rdat(result),.nice_rsp_err(),.nice_icb_cmd_valid(cmd),.nice_icb_cmd_ready(cmd_ready),
        .nice_icb_cmd_addr(addr),.nice_icb_cmd_read(),.nice_icb_cmd_wdata(),.nice_icb_cmd_size(),
        .nice_icb_rsp_valid(rsp_valid),.nice_icb_rsp_ready(rsp_ready),.nice_icb_rsp_rdata(rsp_data),
        .nice_icb_rsp_err(rsp_err),.stream_valid(valid),.stream_ready(ready),
        .stream_error(sink_err),.stream_cancel(cancel),.stream_data(data));

    always @(posedge clk) begin
        if (cmd&&cmd_ready) reads<=reads+1;
        if (valid&&ready) writes<=writes+1;
    end

    task begin_block;
        begin
            if(!req_ready) $fatal(1,"new block rejected while idle");
            req=1; @(negedge clk); req=0;
        end
    endtask
    task accept_read(input [31:0] expected);
        begin
            if(!cmd || addr!=expected) $fatal(1,"wrong read address");
            cmd_ready=1; @(negedge clk); cmd_ready=0;
        end
    endtask
    task respond(input [31:0] value, input bad);
        begin
            if(!rsp_ready) $fatal(1,"not draining the issued read");
            rsp_valid=1; rsp_data=value; rsp_err=bad;
            @(negedge clk); rsp_valid=0; rsp_err=0;
        end
    endtask
    task finish_block(input [31:0] expected);
        begin
            if(!reply || result!==expected || cmd || valid) $fatal(1,"incorrect result %08x",result);
            repeat(2) begin
                @(negedge clk);
                if(!reply || result!==expected) $fatal(1,"reply changed during stall");
            end
            reply_ready=1; @(negedge clk); reply_ready=0;
        end
    endtask
    task reset_block;
        begin
            rst_n=0; cancel=0; sink_err=0; ready=0;
            repeat(2) @(negedge clk);
            rst_n=1;
        end
    endtask

    initial begin
        reset_block();
        begin_block();
        accept_read(source);
        respond(32'ha5a53601,0);
        rsp_data=32'hffffffff;
        repeat(2) begin
            if(!valid || data!==32'ha5a53601 || cmd) $fatal(1,"unstable replay payload");
            @(negedge clk);
        end
        ready=1; @(negedge clk);
        accept_read(source+4);
        cancel=1; @(negedge clk); cancel=0;
        respond(32'h11223344,1);
        finish_block(32'h80000103);
        if(reads!=2 || writes!=1) $fatal(1,"cancellation allowed extra data");

        begin_block();
        accept_read(source);
        repeat(6) begin
            @(negedge clk);
            if(!hold || reply || valid || req_ready || !rsp_ready) $fatal(1,"missing response escaped quarantine");
        end
        respond(32'h1234,0);
        finish_block(32'h80000002);
        if(reads!=3 || writes!=1) $fatal(1,"late response committed");

        begin_block();
        accept_read(source);
        respond(0,1);
        finish_block(32'h80000001);
        begin_block();
        accept_read(source);
        ready=0; respond(32'h1234,0);
        sink_err=1; @(negedge clk); sink_err=0;
        finish_block(32'h80000004);

        begin_block();
        accept_read(source);
        repeat(6) @(negedge clk);
        if(!hold || reply || req_ready) $fatal(1,"permanent miss escaped");
        reset_block();
        words=1; ready=1;
        begin_block();
        accept_read(source);
        respond(32'h1234,0);
        finish_block(0);
        if(reads!=7 || writes!=2) $fatal(1,"cold recovery conservation");
        $display("PASS stalled payload and response, first error, cancel drain, late response, permanent miss, source/sink error, hard reset recovery");
        $finish;
    end
endmodule
