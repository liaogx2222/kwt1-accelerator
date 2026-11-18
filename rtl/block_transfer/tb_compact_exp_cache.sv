module tb_compact_exp_cache;
    reg clk=0, rst_n=0, abort=0;
    always #5 clk=~clk;
    reg load_start=0, load_valid=0, load_last=0;
    reg [31:0] load_data=0;
    wire load_start_ready, load_ready, cache_valid, load_error;
    reg query_valid=0, response_ready=0;
    reg [12:0] query_index=0;
    wire query_ready, response_valid, response_error;
    wire [20:0] response_data;
    wire [7:0] bank_en, bank_we;
    wire [79:0] bank_addr;
    wire [127:0] bank_wdata, bank_rdata;
    kwt_compact_exp_cache dut (
        .clk(clk),.rst_n(rst_n),.abort(abort),.load_start(load_start),.load_start_ready(load_start_ready),
        .load_valid(load_valid),.load_ready(load_ready),.load_data(load_data),.load_last(load_last),
        .cache_valid(cache_valid),.load_error(load_error),.query_valid(query_valid),.query_ready(query_ready),
        .query_index(query_index),.response_valid(response_valid),.response_ready(response_ready),
        .response_data(response_data),.response_error(response_error),
        .bank_en(bank_en),.bank_we(bank_we),.bank_addr(bank_addr),.bank_wdata(bank_wdata),.bank_rdata(bank_rdata));

    genvar bank;
    generate for(bank=0;bank<8;bank=bank+1)begin: operand_bank
        kwt_small_sp ram(clk,bank_en[bank],bank_we[bank],bank_addr[10*bank+:10],
                         bank_wdata[16*bank+:16],bank_rdata[16*bank+:16]);
    end endgenerate
    reg [31:0] packet[0:4143];
    reg [40191:0] packed_expected;
    integer cycles=0,writes=0,reads=0,max_read_banks=0;
    integer cursor,block,n,i,width,before_load,load_cycles;
    reg [31:0] max_value,value;
    string root;

    always @(posedge clk) begin
        cycles<=cycles+1;
        if(cycles>40000) $fatal(1,"cache watchdog");
        if(rst_n && bank_we!=0)begin
            if($countones(bank_we)!=1 || !bank_we[writes%8] ||
               bank_addr[(writes%8)*10+:10]!=710+writes/8 ||
               bank_wdata[(writes%8)*16+:16]!==packed_expected[writes*16+:16])
                $fatal(1,"packed cache write mismatch %d",writes);
            writes<=writes+1;
        end else if(rst_n && bank_en!=0)begin
            for(integer j=0;j<8;j=j+1)
                if(bank_en[j] && bank_addr[10*j+:10]<710) $fatal(1,"cache read crossed operand boundary");
            reads<=reads+$countones(bank_en);
            if($countones(bank_en)>max_read_banks) max_read_banks<=$countones(bank_en);
        end
    end

    task begin_load;
        if(!load_start_ready) $fatal(1,"load_start busy");
        else begin
            load_start=1; @(negedge clk); load_start=0;
        end
    endtask
    task send_word(input [31:0] data,input last);
        begin
            while(!load_ready) @(negedge clk);
            load_valid=1; load_data=data; load_last=last;
            @(negedge clk); load_valid=0;
        end
    endtask
    task lookup(input integer address,input [31:0] data,input bad);
        begin
            if(!query_ready) $fatal(1,"query blocked");
            query_valid=1; query_index=13'(address);
            @(negedge clk); query_valid=0;
            while(!response_valid) @(negedge clk);
            repeat(address%3+1) begin
                if(!response_valid || response_data!==data[20:0] || response_error!==bad)
                    $fatal(1,"cache decode mismatch at %d expected %08x actual %08x",address,data,response_data);
                @(negedge clk);
            end
            response_ready=1; @(negedge clk); response_ready=0;
        end
    endtask

    initial begin
        if(!$value$plusargs("root=%s",root)) $fatal(1,"missing common packet");
        $readmemh(root,packet);
        packed_expected=0; cursor=0;
        for(block=0;block<16;block=block+1)begin
            max_value=0;
            for(n=0;n<256;n=n+1)begin
                i=block*256+n;
                value=i==0 ? 0 : packet[48+i];
                if(value>max_value)max_value=value;
            end
            width=0;
            while(max_value!=0)begin width=width+1; max_value=max_value>>1; end
            for(n=0;n<256;n=n+1)begin
                i=block*256+n;
                value=i==0 ? 0 : packet[48+i];
                for(integer b=0;b<width;b=b+1) packed_expected[cursor+b]=value[b];
                cursor=cursor+width;
            end
        end
        if(cursor!=40192) $fatal(1,"profile size");
        repeat(3) @(negedge clk);
        rst_n=1; @(negedge clk);
        begin_load(); send_word(0,0);
        if(!load_error || query_ready || writes!=0) $fatal(1,"bad first value published");
        begin_load(); send_word(packet[48],0);
        abort=1; @(negedge clk); abort=0; #1;
        if(cache_valid || query_ready || writes!=0) $fatal(1,"aborted prefix leaked");

        before_load=cycles;
        begin_load();
        for(i=0;i<4096;i=i+1) send_word(packet[48+i],i==4095);
        while(!cache_valid) @(negedge clk);
        load_cycles=cycles-before_load;
        if(load_error || writes!=2512) $fatal(1,"cache publication or write count");
        for(i=0;i<4096;i=i+1) lookup(i,packet[48+i],0);
        lookup(4096,0,0); lookup(4097,0,1);
        if(max_read_banks!=3) $fatal(1,"three-bank read not covered");
        @(negedge clk); rst_n=0; @(negedge clk); rst_n=1;
        if(cache_valid || response_valid || query_ready) $fatal(1,"cold cache data visible");
        $display("PASS entries=4097 packed_bytes=5024 writes=%d bank_reads=%d max_read_banks=%d load_cycles=%d",
                 writes,reads,max_read_banks,load_cycles);
        $finish;
    end
endmodule
