// SPDX-License-Identifier: Apache-2.0

module cpz4_loop_control (
    input  wire        ref_clk,
    input  wire        reset_n,
    input  wire        restart,
    input  wire        ref_timeout,
    input  wire        manual,
    input  wire        dither_enable,
    input  wire [7:0]  manual_code,
    input  wire [7:0]  code_ceiling,
    input  wire [16:0] ratio_q12,
    input  wire        phase_valid,
    input  wire [23:0] phase_q12,
    output reg  [7:0]  dco_code,
    output reg         locked,
    output reg  [2:0]  fault_code,
    output reg  [12:0] gain_q12,
    output reg  [3:0]  state
);
    localparam [3:0] START = 0, SETTLE = 1, MEASURE = 2, ALIGN = 3,
                     TRACK = 4, FAULT = 5, MANUAL = 6;
    localparam [2:0] LOW_RAIL = 0, RAMP = 1, SEARCH = 2, GAIN_LOW = 3, GAIN_HIGH = 4;
    wire [23:0] max_tune = {code_ceiling, 16'b0};

    reg [2:0] measurement;
    reg [3:0] settle_left;
    reg [4:0] measure_left;
    reg [10:0] acquire_ticks;
    reg [23:0] anchor, best_distance, gain_low_measure;
    reg [7:0] low_code, high_code, best_code;
    reg [3:0] gain_exponent;

    reg [23:0] target_phase, integrator;
    reg [15:0] dither_residue;
    reg [5:0] lock_count;
    reg [2:0] loss_count, invalid_count;

    wire [23:0] target_delta = {2'b0, ratio_q12, 5'b0};
    wire [23:0] observed_delta = phase_q12 - anchor;
    wire below_target = observed_delta < target_delta;
    wire [23:0] distance = below_target ? target_delta - observed_delta :
                                         observed_delta - target_delta;
    wire better_code = distance < best_distance;
    wire [7:0] nearest_code = better_code ? dco_code : best_code;
    wire [7:0] next_low = below_target ? dco_code : low_code;
    wire [7:0] next_high = below_target ? high_code : dco_code;
    wire [7:0] next_span = next_high - next_low;
    wire [7:0] probe_base = nearest_code < 8'd8 ? 8'd0 : nearest_code - 8'd8;
    wire [8:0] ramp_sum = {1'b0, dco_code} + (dco_code < 8'd32 ? 9'd8 : 9'd16);
    wire [7:0] ramp_code = ramp_sum > {1'b0, code_ceiling} ? code_ceiling : ramp_sum[7:0];
    wire [7:0] ramp_span = dco_code - low_code;
    wire [23:0] gain_delta = observed_delta - gain_low_measure;
    wire [23:0] rounded_gain = (gain_delta + 24'd128) >> 8;

    wire [23:0] next_phase = target_phase + {7'b0, ratio_q12};
    wire signed [23:0] phase_error = $signed(next_phase - phase_q12);
    wire signed [23:0] limited_error = phase_error > 24'sd8192 ? 24'sd8192 :
        phase_error < -24'sd8192 ? -24'sd8192 : phase_error;
    wire signed [39:0] scaled_error = {{16{limited_error[23]}}, limited_error} <<< 16;
    wire phase_close = phase_error >= -24'sd1024 && phase_error <= 24'sd1024;
    wire phase_far = phase_error < -24'sd2048 || phase_error > 24'sd2048;
    wire [4:0] p_shift = {1'b0, gain_exponent} + (locked ? 5'd5 : 5'd4);
    wire [4:0] i_shift = {1'b0, gain_exponent} + (locked ? 5'd11 : 5'd9);

    function automatic [3:0] highest_bit(input [12:0] value);
        integer index;
        begin
            highest_bit = 0;
            for (index = 0; index <= 12; index = index + 1)
                if (value[index]) highest_bit = 4'(index);
        end
    endfunction

    function automatic signed [31:0] scale_toward_zero(
        input signed [39:0] value,
        input [4:0] amount
    );
        reg signed [39:0] magnitude;
        begin
            magnitude = value < 0 ? -value : value;
            magnitude = magnitude >>> amount;
            scale_toward_zero = value < 0 ? -$signed(magnitude[31:0]) : $signed(magnitude[31:0]);
        end
    endfunction

    function automatic [23:0] clamp_tune(input signed [31:0] value, input [23:0] ceiling);
        begin
            if (value < 0) clamp_tune = 0;
            else if (value > $signed({8'b0, ceiling})) clamp_tune = ceiling;
            else clamp_tune = value[23:0];
        end
    endfunction

    wire signed [31:0] i_step = scale_toward_zero(scaled_error, i_shift);
    wire signed [31:0] p_step = scale_toward_zero(scaled_error, p_shift);
    wire [23:0] next_integrator = clamp_tune($signed({8'b0, integrator}) + i_step, max_tune);
    wire [23:0] next_tune = clamp_tune($signed({8'b0, next_integrator}) + p_step, max_tune);
    wire [16:0] residue_sum = {1'b0, dither_residue} + {1'b0, next_tune[15:0]};
    wire increment_code = dither_enable ? residue_sum[16] : next_tune[15];

    always @(posedge ref_clk or negedge reset_n) begin
        if (!reset_n) begin
            state            <= START;
            dco_code         <= 8'd0;
            locked           <= 0;
            fault_code       <= 0;
            gain_q12         <= 0;
            gain_exponent    <= 0;
            measurement      <= LOW_RAIL;
            settle_left      <= 0;
            measure_left     <= 0;
            acquire_ticks    <= 0;
            anchor           <= 0;
            best_distance    <= 0;
            gain_low_measure <= 0;
            low_code         <= 0;
            high_code        <= 8'd255;
            best_code        <= 0;
            target_phase     <= 0;
            integrator       <= 0;
            dither_residue   <= 0;
            lock_count       <= 0;
            loss_count       <= 0;
            invalid_count    <= 0;
        end else if (manual) begin
            state      <= MANUAL;
            dco_code   <= manual_code;
            locked     <= 0;
            fault_code <= 0;
        end else if (restart || ref_timeout || state == MANUAL) begin
            state      <= START;
            locked     <= 0;
            fault_code <= 0;
        end else if (!locked && state != START && state != FAULT && acquire_ticks == 11'd2047) begin
            state      <= FAULT;
            fault_code <= 3'd4;
        end else begin
            if (!locked && state != FAULT) acquire_ticks <= acquire_ticks + 11'd1;

            case (state)
                START: begin
                    state         <= SETTLE;
                    measurement   <= LOW_RAIL;
                    dco_code      <= 8'd0;
                    settle_left   <= 4'd8;
                    low_code      <= 8'd0;
                    high_code     <= code_ceiling;
                    best_distance <= 24'hffffff;
                    best_code     <= 8'd0;
                    locked        <= 0;
                    fault_code    <= 0;
                    gain_q12      <= 0;
                    acquire_ticks <= 0;
                end
                SETTLE: begin
                    if (settle_left != 0) settle_left <= settle_left - 4'd1;
                    else if (phase_valid) begin
                        anchor       <= phase_q12;
                        measure_left <= 5'd31;
                        state        <= MEASURE;
                    end
                end
                MEASURE: begin
                    if (measure_left != 0) measure_left <= measure_left - 5'd1;
                    else if (!phase_valid) state <= SETTLE;
                    else begin
                        if (measurement <= SEARCH && better_code) begin
                            best_distance <= distance;
                            best_code     <= dco_code;
                        end
                        settle_left <= 4'd8;
                        state       <= SETTLE;

                        case (measurement)
                            LOW_RAIL: begin
                                if (!below_target) begin
                                    state      <= FAULT;
                                    fault_code <= 3'd1;
                                end else begin
                                    measurement <= RAMP;
                                    dco_code    <= ramp_code;
                                end
                            end
                            RAMP: begin
                                if (dco_code == code_ceiling && observed_delta <= target_delta) begin
                                    state      <= FAULT;
                                    fault_code <= 3'd2;
                                end else if (below_target) begin
                                    low_code <= dco_code;
                                    dco_code <= ramp_code;
                                end else if (ramp_span <= 8'd1) begin
                                    measurement <= GAIN_LOW;
                                    dco_code    <= probe_base;
                                end else begin
                                    high_code   <= dco_code;
                                    measurement <= SEARCH;
                                    dco_code    <= low_code + (ramp_span >> 1);
                                end
                            end
                            SEARCH: begin
                                if (next_span <= 8'd1) begin
                                    measurement <= GAIN_LOW;
                                    dco_code    <= probe_base;
                                end else begin
                                    low_code  <= next_low;
                                    high_code <= next_high;
                                    dco_code  <= next_low + (next_span >> 1);
                                end
                            end
                            GAIN_LOW: begin
                                gain_low_measure <= observed_delta;
                                measurement      <= GAIN_HIGH;
                                dco_code         <= dco_code + 8'd8;
                            end
                            GAIN_HIGH: begin
                                if (observed_delta <= gain_low_measure || rounded_gain < 24'd16 ||
                                    rounded_gain > 24'd8191) begin
                                    state      <= FAULT;
                                    fault_code <= 3'd3;
                                end else begin
                                    gain_q12      <= rounded_gain[12:0];
                                    gain_exponent <= highest_bit(rounded_gain[12:0]);
                                    dco_code      <= best_code;
                                    integrator    <= {best_code, 16'b0};
                                    state         <= ALIGN;
                                end
                            end
                            default: state <= START;
                        endcase
                    end
                end
                ALIGN: begin
                    if (settle_left != 0) settle_left <= settle_left - 4'd1;
                    else if (phase_valid) begin
                        target_phase   <= phase_q12;
                        dither_residue <= 0;
                        lock_count     <= 0;
                        loss_count     <= 0;
                        invalid_count  <= 0;
                        state          <= TRACK;
                    end
                end
                TRACK: begin
                    target_phase <= next_phase;
                    if (phase_valid) begin
                        integrator     <= next_integrator;
                        dither_residue <= dither_enable ? residue_sum[15:0] : 16'd0;
                        dco_code       <= next_tune[23:16] + {7'b0, increment_code};
                        invalid_count  <= 0;
                    end else invalid_count <= invalid_count + 3'd1;

                    if (!locked) begin
                        if (phase_valid && phase_close) begin
                            lock_count <= lock_count + 6'd1;
                            if (lock_count == 6'd63) locked <= 1'b1;
                        end else lock_count <= 0;
                    end

                    if (locked && (!phase_valid || phase_far)) loss_count <= loss_count + 3'd1;
                    else loss_count <= 0;

                    if ((!phase_valid && invalid_count == 3'd7) ||
                        (locked && (!phase_valid || phase_far) && loss_count == 3'd7)) begin
                        locked <= 0;
                        state  <= START;
                    end
                end
                FAULT: locked <= 0;
                default: state <= START;
            endcase
        end
    end
endmodule
