// SPDX-License-Identifier: Apache-2.0

module cpz4_phase_cal (
    input  wire        clk,
    input  wire        reset_n,
    input  wire        manual_running,
    input  wire        start,
    input  wire        clear_table,
    input  wire        sample_valid,
    input  wire [5:0]  sample_bin,
    input  wire [5:0]  read_bin,
    output wire [11:0] sample_center,
    output wire [11:0] read_center,
    output wire [15:0] read_hits,
    output wire        busy,
    output reg         calibrated,
    output reg         failed
);
    localparam [2:0] IDLE = 0, GUARD = 1, COLLECT = 2, BUILD = 3, COMMIT = 4;
    localparam integer BINS = 40;
    reg [2:0] state;
    reg [15:0] histogram [0:BINS-1];
    reg [11:0] centers [0:BINS-1];
    reg [11:0] shadow [0:BINS-1];
    reg [5:0] index;
    reg [4:0] guard_left;
    reg [14:0] samples;
    reg [16:0] elapsed;
    reg [15:0] cumulative;
    reg [15:0] coarse_total;
    reg [5:0] used_bins;
    integer bin_number;

    function automatic [11:0] ideal_center(input integer bin_id);
        begin
            ideal_center = 12'((4096 * (2 * bin_id + 1) + BINS) / (2 * BINS));
        end
    endfunction

    assign busy = state != IDLE;
    assign sample_center = sample_bin < BINS ? centers[sample_bin] : 12'd0;
    assign read_center = read_bin < BINS ? centers[read_bin] : 12'd0;
    assign read_hits = read_bin < BINS ? histogram[read_bin] : 16'd0;
    // For 32768 hits, round 4096 * (cumulative + hits/2) / 32768.
    wire [17:0] rounded_center = {1'b0, cumulative, 1'b0} +
                                  {2'b0, histogram[index]} + 18'd8;
    wire [15:0] next_coarse_total = coarse_total + histogram[index];
    wire [5:0] next_used_bins = used_bins + {5'b0, histogram[index] >= 16'd128};

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            state      <= IDLE;
            index      <= 0;
            guard_left <= 0;
            samples    <= 0;
            elapsed    <= 0;
            cumulative <= 0;
            coarse_total <= 0;
            used_bins  <= 0;
            calibrated <= 0;
            failed     <= 0;
            for (bin_number = 0; bin_number < BINS; bin_number = bin_number + 1) begin
                centers[bin_number]   <= ideal_center(bin_number);
                shadow[bin_number]    <= 0;
                histogram[bin_number] <= 0;
            end
        end else if (clear_table) begin
            state      <= IDLE;
            calibrated <= 0;
            failed     <= 0;
            for (bin_number = 0; bin_number < BINS; bin_number = bin_number + 1)
                centers[bin_number] <= ideal_center(bin_number);
        end else if (start && state == IDLE) begin
            failed <= !manual_running;
            if (manual_running) begin
                state      <= GUARD;
                guard_left <= 5'd16;
                samples    <= 0;
                elapsed    <= 0;
                for (bin_number = 0; bin_number < BINS; bin_number = bin_number + 1)
                    histogram[bin_number] <= 0;
            end
        end else if (!manual_running && state != IDLE) begin
            state  <= IDLE;
            failed <= 1'b1;
        end else begin
            case (state)
                GUARD: begin
                    if (guard_left == 0) state <= COLLECT;
                    else guard_left <= guard_left - 5'd1;
                end
                COLLECT: begin
                    elapsed <= elapsed + 17'd1;
                    if (sample_valid && sample_bin < BINS) begin
                        histogram[sample_bin] <= histogram[sample_bin] + 16'd1;
                        samples <= samples + 15'd1;
                    end
                    if (sample_valid && sample_bin < BINS && &samples) begin
                        state      <= BUILD;
                        index      <= 0;
                        cumulative <= 0;
                        coarse_total <= 0;
                        used_bins  <= 0;
                    end else if (&elapsed) begin
                        state  <= IDLE;
                        failed <= 1'b1;
                    end
                end
                BUILD: begin
                    // A replica can run past the next coarse edge at a corner.
                    // Allow empty fine bins, but require coverage of every coarse interval.
                    if (index[1:0] == 2'd3 && (next_coarse_total < 16'd512 ||
                        next_coarse_total > 16'd7000 || (index == BINS - 1 && next_used_bins < 6'd24))) begin
                        state  <= IDLE;
                        failed <= 1'b1;
                    end else begin
                        // An empty trailing bin has its boundary at one UI.
                        shadow[index] <= rounded_center[16] ? 12'd4095 : rounded_center[15:4];
                        cumulative    <= cumulative + histogram[index];
                        coarse_total  <= index[1:0] == 2'd3 ? 16'd0 : next_coarse_total;
                        used_bins     <= next_used_bins;
                        if (index == BINS - 1) state <= COMMIT;
                        else index <= index + 6'd1;
                    end
                end
                COMMIT: begin
                    for (bin_number = 0; bin_number < BINS; bin_number = bin_number + 1)
                        centers[bin_number] <= shadow[bin_number];
                    calibrated <= 1'b1;
                    state      <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
