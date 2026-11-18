module tb_compact_softmax_row;
    localparam ROWS=96;
    reg clk=0,rst_n=0,clear=0,start=0,sv=0,pr=0;
    reg [31:0] multiplier=0;
    reg [5:0] shift=0;
    reg signed [31:0] score=0;
    wire sr,start_ready,qv,qr,ev,er,ee,pv,error;
    wire [12:0] qi;
    wire [20:0] exponential;
    wire [6:0] pi;
    wire [15:0] probability;
    kwt_compact_softmax_row dut(clk,rst_n,clear,start,start_ready,multiplier,shift,sv,sr,score,
        qv,qr,qi,ev,er,exponential,ee,pv,pr,pi,probability,error);

    reg load_start=0,load_valid=0,load_last=0;
    reg [31:0] load_data=0;
    wire load_ready,load_start_ready,cache_valid,load_error;
    wire [7:0] en,we;
    wire [79:0] addr;
    wire [127:0] data_in,data_out;
    kwt_compact_exp_cache cache(clk,rst_n,clear,load_start,load_start_ready,load_valid,load_ready,
        load_data,load_last,cache_valid,load_error,qv,qr,qi,ev,er,exponential,ee,en,we,addr,data_in,data_out);
    for(genvar bank=0;bank<8;bank=bank+1)begin:sram
        kwt_small_sp mem(clk,en[bank],we[bank],addr[10*bank+:10],data_in[16*bank+:16],data_out[16*bank+:16]);
    end

    reg [31:0] scores[0:ROWS*99-1],coefficients[0:2*ROWS-1],lut[0:4095];
    reg [15:0] expected[0:ROWS*99-1];
    reg [12:0] expected_index[0:ROWS*99-1];
    string root;
    integer cycles=0,maximum_cycles=0,stall_total=0;
    task automatic tick;
        begin #5;clk=1;#5;clk=0;#1;end
    endtask

    task automatic load_cache;
        integer sent;
        begin
            load_start=1;tick();load_start=0;sent=0;
            while(sent<4096)begin
                load_valid=1;load_data=lut[sent];load_last=sent==4095;#1;
                if(load_ready)++sent;
                tick();
                if(load_error)$fatal(1,"exp load rejected");
            end
            load_valid=0;load_last=0;
            repeat(4)tick();
            if(!cache_valid||load_error)$fatal(1,"exp cache not ready");
        end
    endtask

    task automatic row(input integer row_id,input bit cancel);
        integer sent,queries,received,elapsed;
        reg held;
        begin
            if(!start_ready)$fatal(1,"row start while busy");
            multiplier=coefficients[2*row_id];shift=coefficients[2*row_id+1][5:0];
            start=1;tick();start=0;sent=0;queries=0;received=0;elapsed=1;held=0;
            while(received<99)begin
                sv=sent<99&&elapsed%9!=0;
                if(sv)score=scores[row_id*99+sent];
                pr=elapsed%13>=5;
                #1;
                if(error||elapsed>1500)$fatal(1,"softmax progress row=%d",row_id);
                if(sv&&sr)++sent;
                if(qv&&qr)begin
                    if(queries>=99||qi!==expected_index[row_id*99+queries])
                        $fatal(1,"exp index row=%d query=%d got=%d",row_id,queries,qi);
                    ++queries;
                end
                if(held&&!pv)$fatal(1,"stalled probability dropped");
                held=pv&&!pr;
                if(pv&&(pi!==7'(received)||probability!==expected[row_id*99+received]))
                    $fatal(1,"probability row=%d index=%d got=%d expected=%d",row_id,received,probability,expected[row_id*99+received]);
                if(held)begin
                    ++stall_total;
                    if(cancel&&received>0)begin
                        clear=1;#1;
                        if(pv||qv||er||sr)$fatal(1,"stale handshake after clear");
                        tick();clear=0;#1;
                        if(!start_ready||pv)$fatal(1,"softmax failed to reset");
                        disable row;
                    end
                end
                if(pv&&pr)++received;
                tick();++elapsed;
            end
            if(cancel||queries!=99||sent!=99||!start_ready)$fatal(1,"row conservation");
            cycles+=elapsed;
            if(elapsed>maximum_cycles)maximum_cycles=elapsed;
        end
    endtask

    initial begin
        if(!$value$plusargs("root=%s",root))$fatal(1,"missing fixture directory");
        $readmemh({root,"/scores.hex"},scores);
        $readmemh({root,"/coefficients.hex"},coefficients);
        $readmemh({root,"/exp.hex"},lut);
        $readmemh({root,"/probabilities.hex"},expected);
        $readmemh({root,"/indices.hex"},expected_index);
        tick();rst_n=1;
        load_cache();
        for(integer i=0;i<ROWS;i=i+1)row(i,0);
        row(0,1);
        load_cache();row(0,0);
        $display("PASS softmax rows=97 probabilities=9603 exp_indices=9603 cycles=%0d max_row=%0d stalls=%0d cancel=1",cycles,maximum_cycles,stall_total);
        $finish;
    end
endmodule
