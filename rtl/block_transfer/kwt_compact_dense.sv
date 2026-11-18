// One group of 16 rows against the full resident B matrix. A holds low-byte
// planes at [0,K) and, for first-layer S16, high-byte planes at [K,2K).
// The owner of the A port supplies a complete group before starting.
module kwt_compact_dense (
    input wire clk,rst_n,abort,
    input wire start_valid,wide_a,
    output wire start_ready,
    input wire act_write,
    input wire [8:0] act_addr,
    input wire [127:0] act_data,
    output wire act_ready,
    output wire a_en,a_we,
    output wire [9:0] a_addr,
    output wire [127:0] a_wdata,
    input wire [127:0] a_rdata,
    input wire tile_valid,
    input wire [2:0] tile_id,
    output wire tile_done,tile_read,
    output wire [9:0] tile_addr,
    input wire tile_ready,tile_response,
    input wire [127:0] tile_data,
    output wire coeff_request,
    input wire coeff_grant,
    output wire [14:0] coeff_start,
    input wire aux_valid,
    output wire aux_ready,
    input wire [14:0] aux_index,
    input wire [31:0] aux_data,
    input wire aux_last,
    output wire raw_accept,
    output wire [9:0] raw_tag,
    output wire [127:0] raw_data,
    output wire result_valid,
    input wire result_ready,
    output wire [9:0] result_tag,
    output wire [31:0] result_data,
    output wire error,
    output wire coeff_phase,mac_phase,rq_phase
);
    localparam [3:0] IDLE=0, COEFF_REQ=1, COEFF_RSP=2, INIT=3, MAC=4, RAW=5,
                     DRAIN=6, RELEASE=7, FINISH=8, FAILED=9;
    reg [3:0] state;
    reg [2:0] matrix;
    reg wide;
    reg [3:0] col_tile, element;
    reg [1:0] coeff_kind;
    reg [5:0] output_group;
    reg [7:0] red;
    reg plane, response_plane, response_last, all_reads;
    reg [511:0] biases,multipliers;
    reg [127:0] shifts;
    reg [14:0] m_base,s_base,b_base;
    always @* begin
        case(matrix)
            0:begin m_base=1496; s_base=1752; b_base=1240; end // FC1
            1:begin m_base=6168; s_base=6232; b_base=6104; end // FC2
            2:begin m_base=10456;s_base=10520;b_base=0;    end // K
            3:begin m_base=11952;s_base=12016;b_base=11888;end // O
            4:begin m_base=13104;s_base=13168;b_base=0;    end // Q
            default:begin m_base=14280;s_base=14344;b_base=0; end // V
        endcase
    end
    wire [14:0] coeff_base = coeff_kind==0 ? m_base : coeff_kind==1 ? s_base : b_base;
    assign coeff_start = coeff_base + {7'b0,col_tile,4'b0};
    wire has_bias = matrix==0 || matrix==1 || matrix==3;
    wire red_last = matrix==1 ? red==255 : red==63;
    wire last_col = matrix==0 ? col_tile==15 : col_tile==3;
    wire local_rst_n = rst_n&&!abort;
    assign start_ready = local_rst_n && state==IDLE && tile_valid && !act_write;
    assign act_ready = local_rst_n && state==IDLE;
    assign coeff_request = local_rst_n && state==COEFF_REQ;
    assign aux_ready = local_rst_n && state==COEFF_RSP;
    assign coeff_phase = state==COEFF_REQ || state==COEFF_RSP;
    assign mac_phase = state==INIT || state==MAC;
    assign rq_phase = state==RAW || state==DRAIN || state==RELEASE;
    assign tile_done = local_rst_n && state==FINISH;
    assign tile_read = local_rst_n && state==MAC && !all_reads;
    wire read_fire = tile_read&&tile_ready;
    assign tile_addr = matrix==1 ? {col_tile[1:0],red} : {col_tile,red[5:0]};
    assign a_we = act_write&&act_ready;
    assign a_en = a_we||read_fire;
    assign a_addr = a_we ? {1'b0,act_addr} :
                    matrix==1 ? {1'b0,plane,red} : {3'b0,plane,red[5:0]};
    assign a_wdata = act_data;
    assign error = local_rst_n && state==FAILED;

    wire init_ready,mac_ready,read_ready,raw_valid,raw_ready,release_ready;
    wire rq_error;
    wire [15:0] full_raw_tag,full_result_tag;
    wire [31:0] multiplier = multipliers[full_raw_tag[3:0]*32+:32];
    wire [7:0] shift = shifts[full_raw_tag[3:0]*8+:8];
    wire mac_fire = state==MAC && tile_response && mac_ready;
    wire output_fire = result_valid&&result_ready;
    assign raw_accept = raw_valid&&raw_ready;
    assign raw_tag = full_raw_tag[9:0];
    assign result_tag = full_result_tag[9:0];
    kwt_arithmetic16 arithmetic (
        .clk(clk),.rst_n(local_rst_n),.init_valid(state==INIT),.init_ready(init_ready),
        .init_bank(1'b0),.init_bias(has_bias?biases:512'b0),
        .mac_valid(state==MAC&&tile_response),.mac_ready(mac_ready),.mac_bank(1'b0),
        .mac_unsigned_a(wide&&!response_plane),.mac_shift8(response_plane),.mac_last(response_last),
        .mac_a(a_rdata),.mac_b(tile_data),
        .read_valid(state==RAW),.read_ready(read_ready),.read_bank(1'b0),
        .read_row({output_group[5:4],2'b0}),.read_col(output_group[3:0]),.read_tag({6'b0,col_tile,output_group}),
        .raw_valid(raw_valid),.raw_ready(raw_ready),.raw_data(raw_data),.raw_tag(full_raw_tag),
        .release_valid(state==RELEASE),.release_ready(release_ready),.release_bank(1'b0),.empty(),.done(),
        .rq_valid(raw_valid),.rq_ready(raw_ready),.rq_a(raw_data),.rq_m({4{multiplier}}),
        .rq_shift({4{shift}}),.rq_tag(full_raw_tag),.rq_resp_valid(result_valid),
        .rq_resp_ready(result_ready),.rq_data(result_data),.rq_error(rq_error),.rq_resp_tag(full_result_tag));

    // Coefficient registers are overwritten in full before each use.
    always @(posedge clk) begin
        if(aux_valid&&aux_ready) begin
            case(coeff_kind)
                0:multipliers[element*32+:32]<=aux_data;
                1:shifts[element*8+:8]<=aux_data[7:0];
                2:biases[element*32+:32]<=aux_data;
                default:begin end
            endcase
        end
    end

    always @(posedge clk or negedge local_rst_n) begin
        if(!local_rst_n) begin
            state<=IDLE; matrix<=0; wide<=0; col_tile<=0; coeff_kind<=0; element<=0;
            red<=0; plane<=0; response_plane<=0; response_last<=0; all_reads<=0; output_group<=0;
        end else if(output_fire&&rq_error) state<=FAILED;
        else case(state)
            IDLE: if(start_valid&&start_ready) begin
                matrix<=tile_id; wide<=wide_a; col_tile<=0; coeff_kind<=0;
                state<=tile_id<6 ? COEFF_REQ : FAILED;
            end
            COEFF_REQ: if(coeff_grant) begin element<=0; state<=COEFF_RSP; end
            COEFF_RSP: if(aux_valid&&aux_ready) begin
                if(aux_index!=coeff_start+{11'b0,element} || aux_last!=(element==15) ||
                   (coeff_kind==1 && (aux_data<38 || aux_data>48))) state<=FAILED;
                else if(element==15) begin
                    if(coeff_kind==2 || (coeff_kind==1&&!has_bias)) state<=INIT;
                    else begin coeff_kind<=coeff_kind+1'b1; state<=COEFF_REQ; end
                end else element<=element+1'b1;
            end
            INIT: if(init_ready) begin
                red<=0; plane<=0; all_reads<=0; state<=MAC;
            end
            MAC: begin
                if(read_fire) begin
                    response_plane<=plane;
                    response_last<=red_last && (!wide||plane);
                    if(red_last) begin
                        red<=0; plane<=1;
                        if(!wide||plane) all_reads<=1;
                    end else red<=red+1'b1;
                end
                if(mac_fire&&response_last) begin output_group<=0; state<=RAW; end
            end
            RAW: if(read_ready) begin
                output_group<=output_group+1'b1;
                if(output_group==63) state<=DRAIN;
            end
            DRAIN: if(output_fire&&result_tag[5:0]==63) state<=RELEASE;
            RELEASE: if(release_ready) begin
                if(last_col) state<=FINISH;
                else begin col_tile<=col_tile+1'b1; coeff_kind<=0; state<=COEFF_REQ; end
            end
            FINISH: state<=IDLE;
            FAILED: begin end
            default: state<=FAILED;
        endcase
    end
endmodule
