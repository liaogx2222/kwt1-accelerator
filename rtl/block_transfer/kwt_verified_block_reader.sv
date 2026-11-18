// Conservative canonical-packet reader. One outstanding beat, then CRC-checked replay.
// The backend must return a tagged response no earlier than the next clock edge.
// The lease provider keeps staging immutable until lease_hold drops.
module kwt_verified_block_reader #(
    parameter [31:0] STAGING_FIRST = 32'ha0026000,
    parameter [31:0] STAGING_END = 32'ha0036000,
    parameter integer TIMEOUT = 1024
) (
    input wire clk, rst_n,
    input wire cmd_valid, output wire cmd_ready,
    input wire [31:0] cmd_base,
    input wire [14:0] cmd_words,
    input wire cmd_common,
    input wire [3:0] cmd_layer,
    input wire [15:0] cmd_epoch,
    input wire lease_valid,
    input wire [31:0] lease_base,
    input wire [14:0] lease_words,
    input wire [15:0] lease_epoch,
    output wire lease_hold,
    input wire cancel,

    output wire read_valid, input wire read_ready,
    output wire [31:0] read_addr,
    output wire [15:0] read_epoch,
    output wire [14:0] read_index,
    input wire rsp_valid, output wire rsp_ready,
    input wire [15:0] rsp_epoch,
    input wire [14:0] rsp_index,
    input wire rsp_error,
    input wire [31:0] rsp_data,

    output wire bank_request, input wire bank_grant,
    output reg bank_owned,
    output wire sink_valid, input wire sink_ready,
    output reg [31:0] sink_data,
    output wire sink_last,
    output wire sink_abort,
    input wire consumer_done, consumer_aborted,

    output wire result_valid, input wire result_ready,
    output reg [3:0] error_code,
    output reg [14:0] error_index,
    output wire reset_required
);
    `include "kwt_profile.svh"

    localparam [3:0] IDLE=0, ISSUE=1, WAIT_RSP=2, GRANT=3, HOLD=4,
                     CONSUME=5, ABORT_SINK=6, REPORT=7, QUARANTINE=8;
    localparam [3:0] OK=0, DESCRIPTOR=1, LEASE_LOST=2, CANCELLED=3,
                     RESPONSE=4, TAG=5, HEADER=6, CRC=7, TIMED_OUT=8;
    localparam integer TIMER_WIDTH = $clog2(TIMEOUT+1);
    localparam [TIMER_WIDTH-1:0] TIMER_LAST = TIMER_WIDTH'(TIMEOUT-1);

    reg [3:0] state;
    reg [31:0] base, crc;
    reg [14:0] words, index;
    reg [3:0] layer;
    reg [15:0] epoch;
    reg common, replay, leased, offered;
    reg [TIMER_WIDTH-1:0] timer;

    wire [32:0] cmd_end = {1'b0,cmd_base} + {16'b0,cmd_words,2'b00};
    wire descriptor_ok = lease_valid && lease_base==cmd_base && lease_words==cmd_words && lease_epoch==cmd_epoch &&
                         cmd_base[1:0]==0 && cmd_base>=STAGING_FIRST && cmd_end<={1'b0,STAGING_END} &&
                         (cmd_common ? cmd_words==4144 && cmd_layer==0 : cmd_words==15432 && cmd_layer<12);
    wire lease_changed = leased && (!lease_valid || lease_base!=base || lease_words!=words || lease_epoch!=epoch);
    wire stop = error_code!=OK || lease_changed || cancel;
    wire last_word = index==words-1;
    wire tag_matches = rsp_epoch==epoch && rsp_index==index;

    function automatic [31:0] crc_word(input [31:0] old_crc, input [31:0] value);
        reg [31:0] next_crc;
        integer bit_index;
        begin
            next_crc=old_crc^value;
            for(bit_index=0;bit_index<32;bit_index=bit_index+1)
                next_crc=next_crc[0] ? (next_crc>>1)^32'hedb88320 : next_crc>>1;
            crc_word=next_crc;
        end
    endfunction

    assign cmd_ready = rst_n && state==IDLE && !rsp_valid;
    assign lease_hold = leased;
    assign read_valid = rst_n && state==ISSUE && (!stop || offered);
    assign read_addr = base + {15'b0,index,2'b00};
    assign read_epoch = epoch;
    assign read_index = index;
    assign rsp_ready = rst_n && (state==WAIT_RSP || state==QUARANTINE);
    assign bank_request = rst_n && state==GRANT && !stop;
    assign sink_valid = rst_n && state==HOLD && !stop;
    assign sink_last = last_word;
    assign sink_abort = rst_n && state==ABORT_SINK;
    assign result_valid = rst_n && (state==REPORT || state==QUARANTINE);
    assign reset_required = state==QUARANTINE;

    task automatic fail(input [3:0] code, input fatal);
        begin
            if(error_code==OK)begin
                error_code <= lease_changed ? LEASE_LOST : cancel ? CANCELLED : code;
                error_index <= index;
            end
            state <= fatal ? QUARANTINE : bank_owned ? ABORT_SINK : REPORT;
        end
    endtask

    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin
            state<=IDLE; base<=0; words<=0; index<=0; common<=0; layer<=0; epoch<=0;
            crc<=32'hffffffff; replay<=0; leased<=0; offered<=0; timer<=0;
            bank_owned<=0; sink_data<=0; error_code<=OK; error_index<=0;
        end else if(rsp_valid && state!=WAIT_RSP && state!=QUARANTINE)begin
            fail(TAG,1'b1);
        end else begin
            // Record cancellation at once, while an already offered request is drained.
            if((state==ISSUE || state==WAIT_RSP) && error_code==OK && (lease_changed || cancel))begin
                error_code<=lease_changed ? LEASE_LOST : CANCELLED;
                error_index<=index;
            end
            case(state)
                IDLE: if(cmd_valid&&cmd_ready)begin
                    base<=cmd_base; words<=cmd_words; common<=cmd_common; layer<=cmd_layer; epoch<=cmd_epoch;
                    index<=0; crc<=32'hffffffff; replay<=0; offered<=0; timer<=0; error_index<=0;
                    leased<=descriptor_ok;
                    error_code<=descriptor_ok ? OK : DESCRIPTOR;
                    state<=descriptor_ok ? ISSUE : REPORT;
                end
                ISSUE: begin
                    if(stop&&!offered)fail(CANCELLED,1'b0);
                    else if(read_ready)begin
                        offered<=0; timer<=0; state<=WAIT_RSP;
                    end else if(timer==TIMER_LAST)fail(TIMED_OUT,1'b1);
                    else begin offered<=1; timer<=timer+1'b1; end
                end
                WAIT_RSP: begin
                    if(rsp_valid)begin
                        timer<=0;
                        if(!tag_matches)fail(TAG,1'b1);
                        else if(stop || rsp_error)fail(RESPONSE,1'b0);
                        else if(replay)begin sink_data<=rsp_data; state<=HOLD; end
                        else if(index<16 && rsp_data!=profile_header(common,layer,int'(index)))fail(HEADER,1'b0);
                        else if(last_word)begin
                            if((crc_word(crc,rsp_data)^32'hffffffff)!=profile_header(common,layer,14))fail(CRC,1'b0);
                            else begin index<=0; replay<=1; state<=GRANT; end
                        end else begin
                            if(index>=16)crc<=crc_word(crc,rsp_data);
                            index<=index+1'b1; state<=ISSUE;
                        end
                    end else if(timer==TIMER_LAST)fail(TIMED_OUT,1'b1);
                    else timer<=timer+1'b1;
                end
                GRANT: if(stop)fail(CANCELLED,1'b0);
                       else if(bank_grant)begin bank_owned<=1; state<=ISSUE; end
                HOLD: if(stop)fail(CANCELLED,1'b0);
                      else if(sink_ready)begin
                          if(last_word)state<=CONSUME;
                          else begin index<=index+1'b1; state<=ISSUE; end
                      end
                CONSUME: if(stop)fail(CANCELLED,1'b0);
                         else if(consumer_done)begin bank_owned<=0; state<=REPORT; end
                ABORT_SINK: if(consumer_aborted)begin bank_owned<=0; state<=REPORT; end
                REPORT: if(result_ready)begin leased<=0; state<=IDLE; end
                QUARANTINE: begin end
                default: state<=QUARANTINE;
            endcase
        end
    end
endmodule
