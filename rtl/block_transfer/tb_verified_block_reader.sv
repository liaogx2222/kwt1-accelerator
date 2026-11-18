module tb_verified_block_reader;
    localparam [31:0] BASE=32'ha0026000;
    reg clk=0, rst_n=0;
    always #5 clk=~clk;

    reg cmd_valid=0, cmd_common=0, lease_valid=0, cancel=0;
    reg [31:0] cmd_base=BASE;
    reg [14:0] cmd_words=0;
    reg [3:0] cmd_layer=0;
    reg [15:0] epoch=0;
    reg bank_allow=1, result_ready=0;
    wire cmd_ready, lease_hold, bank_request, bank_owned, sink_valid, sink_last, sink_abort;
    wire result_valid, reset_required, read_valid, rsp_ready;
    wire [31:0] read_addr, sink_data;
    wire [15:0] read_epoch;
    wire [14:0] read_index, error_index;
    wire [3:0] error_code;

    reg [31:0] packet[0:15431];
    integer cycle=0, reads=0, writes=0, data_stalls=0, offer_stalls=0, latency=3;
    integer rd_before, wr_before, start_cycle, rate=100, n, total_cycles=0;
    integer rsp_delay=0, consumer_delay=0;
    reg pending=0, rsp_bad_tag=0, rsp_drop=0, rsp_bus_error=0;
    reg [14:0] rsp_index=0;
    reg [15:0] rsp_epoch=0;
    reg [31:0] rsp_data=0;
    reg stalled_offer=0, stalled_sink=0;
    reg [31:0] previous_address, previous_data;
    reg abort_ack=1;

    wire read_ready = !pending && cycle%7!=0;
    wire rsp_valid = pending && rsp_delay==0 && !rsp_drop;
    wire bank_grant = bank_allow && cycle%5==0;
    wire sink_ready = cycle%6>=2;
    wire consumer_done = consumer_delay==1;
    kwt_verified_block_reader #(.TIMEOUT(40)) dut (
        .clk(clk),.rst_n(rst_n),.cmd_valid(cmd_valid),.cmd_ready(cmd_ready),.cmd_base(cmd_base),.cmd_words(cmd_words),
        .cmd_common(cmd_common),.cmd_layer(cmd_layer),.cmd_epoch(epoch),.lease_valid(lease_valid),
        .lease_base(BASE),.lease_words(cmd_words),.lease_epoch(epoch),.lease_hold(lease_hold),.cancel(cancel),
        .read_valid(read_valid),.read_ready(read_ready),.read_addr(read_addr),.read_epoch(read_epoch),.read_index(read_index),
        .rsp_valid(rsp_valid),.rsp_ready(rsp_ready),.rsp_epoch(rsp_epoch),.rsp_index(rsp_index),
        .rsp_error(rsp_bus_error),.rsp_data(rsp_data),.bank_request(bank_request),.bank_grant(bank_grant),.bank_owned(bank_owned),
        .sink_valid(sink_valid),.sink_ready(sink_ready),.sink_data(sink_data),.sink_last(sink_last),.sink_abort(sink_abort),
        .consumer_done(consumer_done),.consumer_aborted(sink_abort&&abort_ack),.result_valid(result_valid),
        .result_ready(result_ready),.error_code(error_code),.error_index(error_index),.reset_required(reset_required));

    always @(posedge clk) begin
        cycle<=cycle+1;
        if(!rst_n)begin
            pending<=0;
            rsp_delay<=0;
            consumer_delay<=0;
            stalled_offer<=0;
            stalled_sink<=0;
        end else begin
            if(stalled_offer && !reset_required && (!read_valid || read_addr!==previous_address))
                $fatal(1,"request changed while offered");
            if(stalled_sink && !cancel && lease_valid && !reset_required && !sink_abort &&
               (!sink_valid || sink_data!==previous_data)) $fatal(1,"sink payload changed under backpressure");
            stalled_offer<=read_valid&&!read_ready;
            stalled_sink<=sink_valid&&!sink_ready;
            previous_address<=read_addr;
            previous_data<=sink_data;
            if(read_valid&&!read_ready)offer_stalls<=offer_stalls+1;
            if(sink_valid&&!sink_ready)data_stalls<=data_stalls+1;

            if(read_valid&&read_ready)begin
                if(!lease_hold || read_addr!=BASE+4*read_index || read_index>=cmd_words)
                    $fatal(1,"read outside the active lease");
                reads<=reads+1;
                pending<=1;
                rsp_index<=read_index;
                rsp_epoch<=rsp_bad_tag ? read_epoch^16'h1 : read_epoch;
                rsp_data<=packet[read_index];
                rsp_delay<=latency-1;
            end else if(rsp_valid&&rsp_ready)pending<=0;
            else if(pending&&rsp_delay>0)rsp_delay<=rsp_delay-1;

            if(consumer_delay>0)consumer_delay<=consumer_delay-1;
            if(sink_valid&&sink_ready)begin
                if(!lease_hold || !bank_owned || reads-rd_before<=cmd_words ||
                   sink_data!==packet[writes-wr_before] || sink_last!=(writes-wr_before==cmd_words-1))
                    $fatal(1,"invalid replay word or ownership");
                writes<=writes+1;
                if(sink_last)consumer_delay<=7;
            end
        end
    end

    task reset_dut;
        begin
            @(negedge clk); rst_n=0; cmd_valid=0; lease_valid=0; cancel=0;
            rsp_bad_tag=0; rsp_drop=0; rsp_bus_error=0; bank_allow=1; abort_ack=1;
            repeat(3) @(negedge clk);
            rst_n=1;
        end
    endtask

    task begin_packet(input integer layer);
        begin
            @(negedge clk);
            if(!cmd_ready) $fatal(1,"descriptor entry blocked");
            cmd_common=layer<0;
            cmd_layer=layer<0 ? 0 : layer;
            cmd_words=layer<0 ? 4144 : 15432;
            epoch=epoch+1;
            lease_valid=1;
            rd_before=reads; wr_before=writes;
            cmd_valid=1;
            @(negedge clk); cmd_valid=0;
        end
    endtask

    task check_result(input integer expected, input integer fatal_expected);
        integer watchdog;
        begin
            watchdog=0;
            while(!result_valid)begin
                @(negedge clk); watchdog=watchdog+1;
                if(watchdog>300000) $fatal(1,"no completion");
            end
            if(error_code!=expected || reset_required!=fatal_expected) $fatal(1,"unexpected completion %d/%d",error_code,reset_required);
            result_ready=1;
            @(negedge clk); result_ready=0;
            if(!fatal_expected)begin
                if(lease_hold || bank_owned || !cmd_ready) $fatal(1,"ownership retained after completion");
                lease_valid=0;
            end else if(cmd_ready || !lease_hold) $fatal(1,"quarantine released live lease");
        end
    endtask

    string root, filename;
    initial begin
        if(!$value$plusargs("root=%s",root)) $fatal(1,"missing fixture directory");
        if($value$plusargs("rate=%d",rate))begin end
        if($value$plusargs("latency=%d",latency))begin end
        reset_dut();
        for(integer layer=-1;layer<12;layer=layer+1)begin
            n=layer<0 ? 4144 : 15432;
            filename=layer<0 ? "common.bin.hex" : $sformatf("layer_%02d.bin.hex",layer);
            $readmemh({root,"/",filename},packet,0,n-1);
            start_cycle=cycle;
            repeat(n*(600/rate)) @(negedge clk);
            begin_packet(layer);
            check_result(0,0);
            if(reads-rd_before!=2*n || writes-wr_before!=n) $fatal(1,"two-pass conservation");
            total_cycles=total_cycles+cycle-start_cycle;
        end
        if(reads!=378656 || writes!=189328) $fatal(1,"canonical packet count");
        $display("PASS CANONICAL rate=%d latency=%d cycles=%d reads=%d words=%d source_stalls=%d sink_stalls=%d",rate,latency,total_cycles,reads,writes,offer_stalls,data_stalls);

        $readmemh({root,"/common.bin.hex"},packet,0,4143);
        packet[100]=packet[100]^1;
        begin_packet(-1); check_result(7,0);
        if(writes!=wr_before || reads-rd_before!=4144) $fatal(1,"CRC failure exposed data");
        packet[100]=packet[100]^1;
        packet[0]=packet[0]^1;
        begin_packet(-1); check_result(6,0);
        if(writes!=wr_before || reads-rd_before!=1) $fatal(1,"header failure exposed data");
        packet[0]=packet[0]^1;

        cmd_base=BASE+2;
        begin_packet(-1); check_result(1,0);
        if(reads!=rd_before) $fatal(1,"invalid descriptor reached backend");
        cmd_base=BASE;

        begin_packet(-1);
        while(!pending) @(negedge clk);
        cancel=1;
        @(negedge clk); cancel=0;
        check_result(3,0);
        if(writes!=wr_before || reads-rd_before!=1) $fatal(1,"in-flight cancellation leaked request");

        begin_packet(-1);
        while(writes-wr_before<3) @(negedge clk);
        abort_ack=0; cancel=1;
        @(negedge clk); cancel=0;
        while(!sink_abort) @(negedge clk);
        repeat(6)begin
            @(negedge clk);
            if(!lease_hold || !bank_owned || result_valid) $fatal(1,"early owner release before consumer abort");
        end
        abort_ack=1;
        check_result(3,0);

        rsp_bus_error=1;
        begin_packet(-1); check_result(4,0);
        rsp_bus_error=0;

        rsp_drop=1;
        begin_packet(-1); check_result(8,1);
        reset_dut();
        rsp_bad_tag=1;
        begin_packet(-1); check_result(5,1);
        reset_dut();
        begin_packet(-1); check_result(0,0);
        $display("PASS FAULTS crc header descriptor cancel-read cancel-replay bus-error timeout stale-tag and cold recovery");
        $finish;
    end
endmodule
