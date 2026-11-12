// SPDX-License-Identifier: Apache-2.0

module cpz4_phase_cal (
    input  wire        clk,
    input  wire        reset_n,
    input  wire        manual_running,
    input  wire        start,
    input  wire        clear_table,
    input  wire        sample_valid,
    input  wire [3:0]  sample_bin,
    input  wire [3:0]  read_bin,
    output wire [11:0] sample_center,
    output wire [11:0] read_center,
    output wire [14:0] read_hits,
    output wire        busy,
    output reg         calibrated,
    output reg         failed
);
    localparam [2:0] IDLE = 0, GUARD = 1, COLLECT = 2, BUILD = 3, COMMIT = 4;
    reg [2:0] state;
    reg [14:0] histogram [0:9];
    reg [11:0] centers [0:9];
    reg [11:0] shadow [0:9];
    reg [3:0] index;
    reg [4:0] guard_left;
    reg [13:0] samples;
    reg [15:0] elapsed;
    reg [14:0] cumulative;
    integer bin_number;

    function automatic [11:0] ideal_center(input integer bin_id);
        begin
            case (bin_id)
                0: ideal_center = 12'd205;
                1: ideal_center = 12'd614;
                2: ideal_center = 12'd1024;
                3: ideal_center = 12'd1434;
                4: ideal_center = 12'd1843;
                5: ideal_center = 12'd2253;
                6: ideal_center = 12'd2662;
                7: ideal_center = 12'd3072;
                8: ideal_center = 12'd3482;
                9: ideal_center = 12'd3891;
                default: ideal_center = 12'd0;
            endcase
        end
    endfunction

    assign busy = state != IDLE;
    assign sample_center = sample_bin < 10 ? centers[sample_bin] : 12'd0;
    assign read_center = read_bin < 10 ? centers[read_bin] : 12'd0;
    assign read_hits = read_bin < 10 ? histogram[read_bin] : 15'd0;
    // For 16384 hits, round 4096 * (cumulative + hits/2) / 16384.
    wire [16:0] rounded_center = {1'b0, cumulative, 1'b0} +
                                  {2'b0, histogram[index]} + 17'd4;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            state      <= IDLE;
            index      <= 0;
            guard_left <= 0;
            samples    <= 0;
            elapsed    <= 0;
            cumulative <= 0;
            calibrated <= 0;
            failed     <= 0;
            for (bin_number = 0; bin_number < 10; bin_number = bin_number + 1) begin
                centers[bin_number]   <= ideal_center(bin_number);
                shadow[bin_number]    <= 0;
                histogram[bin_number] <= 0;
            end
        end else if (clear_table) begin
            state      <= IDLE;
            calibrated <= 0;
            failed     <= 0;
            for (bin_number = 0; bin_number < 10; bin_number = bin_number + 1)
                centers[bin_number] <= ideal_center(bin_number);
        end else if (start && state == IDLE) begin
            failed <= !manual_running;
            if (manual_running) begin
                state      <= GUARD;
                guard_left <= 5'd16;
                samples    <= 0;
                elapsed    <= 0;
                for (bin_number = 0; bin_number < 10; bin_number = bin_number + 1)
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
                    elapsed <= elapsed + 16'd1;
                    if (sample_valid && sample_bin < 10) begin
                        histogram[sample_bin] <= histogram[sample_bin] + 15'd1;
                        samples <= samples + 14'd1;
                    end
                    if (sample_valid && sample_bin < 10 && samples == 14'd16383) begin
                        state      <= BUILD;
                        index      <= 0;
                        cumulative <= 0;
                    end else if (&elapsed) begin
                        state  <= IDLE;
                        failed <= 1'b1;
                    end
                end
                BUILD: begin
                    if (histogram[index] < 15'd512 || histogram[index] > 15'd4096) begin
                        state  <= IDLE;
                        failed <= 1'b1;
                    end else begin
                        shadow[index] <= rounded_center[14:3];
                        cumulative    <= cumulative + histogram[index];
                        if (index == 9) state <= COMMIT;
                        else index <= index + 4'd1;
                    end
                end
                COMMIT: begin
                    for (bin_number = 0; bin_number < 10; bin_number = bin_number + 1)
                        centers[bin_number] <= shadow[bin_number];
                    calibrated <= 1'b1;
                    state      <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
