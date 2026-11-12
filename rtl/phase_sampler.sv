// SPDX-License-Identifier: Apache-2.0

module cpz4_reset_release (
    input  wire clk,
    input  wire async_n,
    output wire reset_n
);
    (* ASYNC_REG = "TRUE" *) reg [1:0] release_pipe;
    always @(posedge clk or negedge async_n) begin
        if (!async_n) release_pipe <= 2'b00;
        else          release_pipe <= {release_pipe[0], 1'b1};
    end
    assign reset_n = release_pipe[1];
endmodule

module cpz4_edge_counter #(
    parameter [11:0] SEED = 12'd0
) (
    input  wire        clk,
    input  wire        reset_n,
    output reg  [11:0] binary,
    output reg  [11:0] gray
);
    reg carry4, carry8;
    wire [11:0] next_count = {binary[11:8] + {3'b0, carry8},
                              binary[7:4]  + {3'b0, carry4},
                              binary[3:0]  + 4'd1};

    // Predict carry a cycle early to keep the 400 MHz increment paths short.
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            binary <= SEED;
            gray   <= SEED ^ (SEED >> 1);
            carry4 <= &SEED[3:0];
            carry8 <= &SEED[7:0];
        end else begin
            binary <= next_count;
            gray   <= next_count ^ (next_count >> 1);
            carry4 <= binary[3:0] == 4'he;
            carry8 <= binary[7:0] == 8'hfe;
        end
    end
endmodule

module cpz4_phase_sampler (
    input  wire        ref_clk,
    input  wire        ref_reset_n,
    input  wire [4:0]  tap,
    input  wire        dco_reset_n,
    output wire        dco_div2,
    output wire        dco_div4,
    output reg  [3:0]  bin_index,
    output wire        valid,
    output wire [11:0] cycle_count
);
    wire [11:0] pos_binary, pos_gray, neg_gray;
    wire dco_clk_n = ~tap[0];
    // Reset is released just after a rising tap[0] edge. The first falling
    // edge takes the falling counter from -1 to zero.
    cpz4_edge_counter positive_counter(tap[0], dco_reset_n, pos_binary, pos_gray);
    cpz4_edge_counter #(.SEED(12'hfff)) negative_counter(dco_clk_n, dco_reset_n, , neg_gray);
    assign dco_div2 = pos_binary[0];
    assign dco_div4 = pos_binary[1];

    (* ASYNC_REG = "TRUE" *) reg [11:0] pos_meta, pos_sample;
    (* ASYNC_REG = "TRUE" *) reg [11:0] neg_meta, neg_sample;
    (* ASYNC_REG = "TRUE" *) reg [4:0] tap_meta, tap_sample;
    (* ASYNC_REG = "TRUE" *) reg [1:0] ready_pipe;

    always @(posedge ref_clk or negedge ref_reset_n) begin
        if (!ref_reset_n) begin
            pos_meta   <= 0;
            pos_sample <= 0;
            neg_meta   <= 0;
            neg_sample <= 0;
            tap_meta   <= 0;
            tap_sample <= 0;
            ready_pipe <= 0;
        end else begin
            pos_meta   <= pos_gray;
            pos_sample <= pos_meta;
            neg_meta   <= neg_gray;
            neg_sample <= neg_meta;
            tap_meta   <= tap;
            tap_sample <= tap_meta;
            ready_pipe <= {ready_pipe[0], dco_reset_n};
        end
    end

    function automatic [11:0] gray_to_binary(input [11:0] code);
        integer bit_index;
        begin
            for (bit_index = 0; bit_index < 12; bit_index = bit_index + 1)
                gray_to_binary[bit_index] = ^(code >> bit_index);
        end
    endfunction

    reg legal_word;
    always @* begin
        legal_word = 1'b1;
        case (tap_sample)
            5'b01011: bin_index = 4'd0;
            5'b01001: bin_index = 4'd1;
            5'b01101: bin_index = 4'd2;
            5'b00101: bin_index = 4'd3;
            5'b10101: bin_index = 4'd4;
            5'b10100: bin_index = 4'd5;
            5'b10110: bin_index = 4'd6;
            5'b10010: bin_index = 4'd7;
            5'b11010: bin_index = 4'd8;
            5'b01010: bin_index = 4'd9;
            default: begin
                bin_index = 4'd0;
                legal_word = 1'b0;
            end
        endcase
    end

    wire [11:0] falling_count = gray_to_binary(neg_sample);
    assign cycle_count = bin_index <= 4'd2 ? falling_count + 12'd1 :
                         bin_index <= 4'd6 ? gray_to_binary(pos_sample) : falling_count;
    assign valid = ready_pipe[1] && legal_word;
endmodule

module cpz4_ref_watchdog (
    input  wire ref_clk,
    input  wire ref_reset_n,
    input  wire dco_div2,
    input  wire dco_reset_n,
    output reg  timeout_dco,
    output wire timeout_ref
);
    reg heartbeat;
    (* ASYNC_REG = "TRUE" *) reg [1:0] beat_pipe, ack_pipe, trip_pipe;
    reg last_beat;
    reg [6:0] age;

    always @(posedge ref_clk or negedge ref_reset_n) begin
        if (!ref_reset_n) begin
            heartbeat <= 1'b0;
            trip_pipe <= 0;
        end else begin
            heartbeat <= ~heartbeat;
            trip_pipe <= {trip_pipe[0], timeout_dco};
        end
    end
    assign timeout_ref = trip_pipe[1];

    always @(posedge dco_div2 or negedge dco_reset_n) begin
        if (!dco_reset_n) begin
            beat_pipe   <= 0;
            ack_pipe    <= 0;
            last_beat   <= 1'b0;
            age         <= 0;
            timeout_dco <= 1'b0;
        end else begin
            beat_pipe <= {beat_pipe[0], heartbeat};
            ack_pipe  <= {ack_pipe[0], timeout_ref};
            last_beat <= beat_pipe[1];
            if (last_beat != beat_pipe[1]) begin
                age <= 0;
                if (ack_pipe[1]) timeout_dco <= 1'b0;
            end else if (age != 7'd127) begin
                age <= age + 7'd1;
                if (age == 7'd126) timeout_dco <= 1'b1;
            end
        end
    end
endmodule
