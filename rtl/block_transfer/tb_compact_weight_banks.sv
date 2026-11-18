module tb_compact_weight_banks;
    localparam [31:0] BASE=32'ha0026000;
    reg clk=0, rst_n=0;
    always #5 clk=~clk;
    reg start=0, leased=0, common=0, cancel=0, take_result=0, available=1;
    reg [3:0] layer=0;
    reg [15:0] epoch=0;
    reg [14:0] words=0;
    wire cmd_ready, lease_hold, bank_request, bank_grant, bank_owned;
    wire read_valid, rsp_ready, sink_valid, sink_last, sink_ready, sink_abort, aborted, done;
    wire result_valid, reset_required;
    wire [3:0] error_code;
    wire [14:0] read_index, error_index;
    wire [15:0] read_epoch;
    wire [31:0] read_addr, sink_data;
    reg pending=0;
    reg [14:0] rsp_index;
    reg [15:0] rsp_epoch;
    reg [31:0] rsp_data;
    reg [31:0] packet[0:15431];
    integer delay_count=0, cycles=0, reads=0, replay=0, writes=0, concurrent_ops=0;
    wire read_ready=!pending && cycles%7!=0;
    wire rsp_valid=pending && delay_count==0;

    kwt_verified_block_reader #(.TIMEOUT(48)) frontend (
        .clk(clk),.rst_n(rst_n),.cmd_valid(start),.cmd_ready(cmd_ready),.cmd_base(BASE),
        .cmd_words(words),.cmd_common(common),.cmd_layer(layer),.cmd_epoch(epoch),.lease_valid(leased),
        .lease_base(BASE),.lease_words(words),.lease_epoch(epoch),.lease_hold(lease_hold),.cancel(cancel),
        .read_valid(read_valid),.read_ready(read_ready),.read_addr(read_addr),.read_epoch(read_epoch),.read_index(read_index),
        .rsp_valid(rsp_valid),.rsp_ready(rsp_ready),.rsp_epoch(rsp_epoch),.rsp_index(rsp_index),.rsp_error(1'b0),
        .rsp_data(rsp_data),.bank_request(bank_request),.bank_grant(bank_grant),.bank_owned(bank_owned),
        .sink_valid(sink_valid),.sink_ready(sink_ready),.sink_data(sink_data),.sink_last(sink_last),.sink_abort(sink_abort),
        .consumer_done(done),.consumer_aborted(aborted),.result_valid(result_valid),.result_ready(take_result),
        .error_code(error_code),.error_index(error_index),.reset_required(reset_required));

    reg tile_done=0, tile_read=0;
    reg [9:0] addr=0;
    wire tile_valid,tile_deep,tile_ready,tile_response;
    wire [2:0] tile_id;
    wire [127:0] tile_data;
    wire [191:0] compute_rdata;
    // A0 and S0 concurrently exercise disjoint banks. Write on even cycles
    // and read back the same addresses on odd cycles during packet replay.
    wire [11:0] compute_en=12'h101;
    wire [11:0] compute_we=cycles[0] ? 12'h000 : 12'h101;
    kwt_compact_weight_banks dut (
        .clk(clk),.rst_n(rst_n),.bank_request(bank_request),.packet_common(common),.bank_available(available),.bank_grant(bank_grant),
        .sink_valid(sink_valid),.sink_last(sink_last),.sink_abort(sink_abort),.quarantine(reset_required),
        .sink_data(sink_data),.sink_ready(sink_ready),.consumer_aborted(aborted),.consumer_done(done),
        .tile_valid(tile_valid),.tile_id(tile_id),.tile_deep(tile_deep),.tile_done(tile_done),.tile_read(tile_read),
        .tile_addr(addr),.tile_ready(tile_ready),.tile_response(tile_response),.tile_data(tile_data),
        .compute_en(compute_en),.compute_we(compute_we),.compute_addr({36'b0,12'd2048,84'b0,12'd23}),
        .compute_wdata({48'b0,16'hca8e,112'b0,16'ha19e}),.compute_rdata(compute_rdata));

    always @(posedge clk) begin
        cycles<=cycles+1;
        if(cycles>4000000) $fatal(1,"watchdog");
        if(!rst_n)pending<=0;
        else begin
            if (read_valid && read_ready) begin
                if (!lease_hold || read_addr!=BASE+4*read_index || read_index>=words) $fatal(1,"read outside lease");
                pending<=1; rsp_index<=read_index; rsp_epoch<=read_epoch;
                rsp_data<=packet[read_index]; delay_count<=2;
                reads<=reads+1;
            end else if (rsp_valid && rsp_ready) pending<=0;
            else if (pending && delay_count>0) delay_count<=delay_count-1;
            if(sink_valid && sink_ready) replay<=replay+1;
            if(dut.write_first || dut.write_second) begin
                if(!lease_hold || !bank_owned || tile_valid) $fatal(1,"weight write outside ownership");
                writes<=writes+1;
                concurrent_ops<=concurrent_ops+2;
            end
            if(cycles>10 && !cycles[0] && (compute_rdata[15:0]!==16'ha19e || compute_rdata[143:128]!==16'hca8e))
                $fatal(1,"disjoint bank data corrupted");
        end
    end

    function automatic integer first(input integer id);
        case(id)
            0:first=8032; 1:first=25184; 2:first=42336;
            3:first=48320; 4:first=52928; default:first=57632;
        endcase
    endfunction

    integer checked=0, matrices=0;
    task consume(input integer id);
        integer reduction, depth, slot, row, j;
        reg [31:0] expected;
        begin
            while(!tile_valid) @(negedge clk);
            if(tile_id!=id || tile_deep!=(id<2) || !lease_hold || !bank_owned) $fatal(1,"tile order/ownership");
            depth=id<2 ? 1024 : 256; reduction=id==1 ? 256 : 64;
            if(id>=2) begin
                addr=10'd256; #1;
                if(tile_ready) $fatal(1,"short tile exposed stale address");
            end
            repeat(3) @(negedge clk);
            for(row=0;row<depth;row=row+1)begin
                addr=10'(row); tile_read=1;
                @(negedge clk);
                if(!tile_response || !tile_valid) $fatal(1,"one-cycle bank response missing");
                for(j=0;j<8;j=j+1)begin
                    slot=((row/reduction)*2+j/4)*reduction+row%reduction;
                    expected=packet[first(id)/4+(j%4)*depth+slot/2];
                    if(tile_data[j*16+:16] !== (slot%2 ? expected[31:16] : expected[15:0]))
                        $fatal(1,"canonical weight mismatch layer=%d matrix=%d bank=%d row=%d",layer,id,j,row);
                end
                checked=checked+8;
            end
            tile_read=0; tile_done=1;
            @(negedge clk); tile_done=0; matrices=matrices+1;
        end
    endtask

    task launch(input integer n);
        begin
            if(!cmd_ready || tile_valid) $fatal(1,"packet entry blocked");
            common=n<0; layer=n<0 ? 0 : 4'(n);
            words=n<0 ? 4144 : 15432; epoch=epoch+1;
            leased=1; start=1;
            @(negedge clk); start=0;
        end
    endtask
    task complete(input integer expected);
        begin
            while(!result_valid) @(negedge clk);
            if(error_code!=expected || reset_required || !lease_hold || bank_owned || tile_valid)
                $fatal(1,"invalid packet exit %d",error_code);
            take_result=1; @(negedge clk); take_result=0;
            if(lease_hold || !cmd_ready || tile_ready) $fatal(1,"lease or data visible after result");
            leased=0;
        end
    endtask

    string root,filename;
    integer before_reads,before_replay,before_writes,begin_cycle,success_cycles;
    initial begin
        if(!$value$plusargs("root=%s",root)) $fatal(1,"fixture path missing");
        repeat(3) @(negedge clk);
        rst_n=1; @(negedge clk); begin_cycle=cycles;
        for(integer frame=-1;frame<12;frame=frame+1)begin
            filename=frame<0 ? "common.bin.hex" : $sformatf("layer_%02d.bin.hex",frame);
            $readmemh({root,"/",filename},packet,0,frame<0 ? 4143 : 15431);
            before_reads=reads; before_replay=replay; before_writes=writes;
            launch(frame);
            if(frame>=0)begin
                for(integer matrix=0;matrix<6;matrix=matrix+1) consume(matrix);
            end
            complete(0);
            if(reads-before_reads!=2*words || replay-before_replay!=words ||
               writes-before_writes!=(frame<0 ? 0 : 24576)) $fatal(1,"packet/bank conservation");
        end
        success_cycles=cycles-begin_cycle;
        if(reads!=378656 || replay!=189328 || checked!=294912 || writes!=checked ||
           matrices!=72 || concurrent_ops!=2*writes) $fatal(1,"normal path counts");
        $display("PASS NORMAL cycles=%d source_reads=%d replay_words=%d halfwords=%d matrices=%d disjoint_ops=%d",
                 success_cycles,reads,replay,checked,matrices,concurrent_ops);

        $readmemh({root,"/layer_00.bin.hex"},packet);
        before_replay=replay; before_writes=writes; packet[100]=packet[100]^1;
        launch(0); complete(7);
        if(replay!=before_replay || writes!=before_writes) $fatal(1,"CRC rejection wrote a bank");
        packet[100]=packet[100]^1;

        available=0; launch(0);
        while(!bank_request) @(negedge clk);
        repeat(7)begin
            @(negedge clk);
            if(bank_owned || tile_valid || sink_valid || !lease_hold || writes!=before_writes)
                $fatal(1,"reader bypassed unavailable banks");
        end
        available=1;
        while(!tile_valid) @(negedge clk);
        cancel=1; @(negedge clk); cancel=0;
        complete(3);
        launch(0);
        for(integer matrix=0;matrix<6;matrix=matrix+1) consume(matrix);
        complete(0);
        $display("PASS FAULTS CRC isolation, denied bank grant, cancel on owned matrix, cold bank recovery");
        $finish;
    end
endmodule
