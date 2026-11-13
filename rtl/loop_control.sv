// SPDX-License-Identifier: Apache-2.0

module cpz4_loop_control (
    input  wire        ref_clk,
    input  wire        reset_n,
    input  wire        restart,
    input  wire        ref_timeout,
    input  wire        manual,
    input  wire        dither_enable,
    input  wire        narrow_near_integer,
    input  wire [7:0]  manual_code,
    input  wire [7:0]  code_ceiling,
    input  wire [5:0]  ref_upper_mhz,
    input  wire [1:0]  tracking_gear,
    input  wire [16:0] ratio_q12,
    input  wire        phase_valid,
    input  wire [23:0] phase_q12,
    output reg  [7:0]  dco_code,
    output reg  [7:0]  fine_code,
    output reg         locked,
    output reg  [2:0]  fault_code,
    output reg  [12:0] gain_q12,
    output reg  [3:0]  state
);
    localparam [3:0] START = 0, SETTLE = 1, MEASURE = 2, ALIGN = 3,
                     TRACK = 4, FAULT = 5, MANUAL = 6, SEED = 7;
    localparam [2:0] LOW_RAIL = 0, RAMP = 1, SEARCH = 2, FINE_LOW = 3, FINE_HIGH = 4;
    localparam [2:0] LOW_RANGE = 1, HIGH_RANGE = 2, BAD_GAIN = 3,
                     NO_LOCK = 4, SPEED_GUARD = 5, FINE_RANGE = 6;
    localparam [2:0] START_STALLED = 7;
    localparam [7:0] FINE_MID = 8'd64, FINE_MAX = 8'd128;
    localparam [23:0] MAX_TUNE = {FINE_MAX, 16'b0};

    // The guard works in MHz times the 32-cycle measurement window.
    // Reserve 32 MHz for fine motion and budget 16 MHz per coarse step.
    localparam [22:0] CLOCK_LIMIT = 23'd400 << 5;
    localparam [4:0] COARSE_STEP_BUDGET = 5'd23;
    localparam [22:0] COARSE_LIMIT = {9'b0, COARSE_STEP_BUDGET, 9'b0};
    localparam [22:0] MIN_RUNNING = 23'd48 << 5;
    localparam [22:0] SETPOINT_LIMIT = 23'd350 << 12;
    // Span in Q12 phase counts over a 32-reference-cycle measurement.
    localparam [17:0] EXTEND_FINE_SPAN = 18'd4 << 8;
    localparam [17:0] MIN_FINE_SPAN = 18'd1 << 8;

    reg [2:0] measurement;
    reg [3:0] settle_left;
    reg [4:0] measure_left;
    reg [10:0] acquire_ticks;
    reg [23:0] anchor;
    reg [17:0] fine_low_measure;
    reg [7:0] low_code, high_code;
    reg [3:0] gain_exponent;
    reg monitor_active, fine_retried, extended_fine;
    reg [1:0] fine_windows;

    // Fine acquisition uses Q8 phase. The speed guard uses whole cycles
    // and the tracking loop still uses Q12 phase.
    reg [17:0] fine_work, fine_divisor;
    reg [6:0] seed_code;
    reg [2:0] seed_left;

    reg [23:0] target_phase, integrator;
    reg [15:0] dither_residue;
    reg [5:0] lock_count;
    reg [2:0] loss_count, invalid_count;
    reg [9:0] fine_rail_ticks;

    wire [23:0] target_delta = {2'b0, ratio_q12, 5'b0};
    wire [23:0] observed_delta = phase_q12 - anchor;
    wire below_target = observed_delta < target_delta;
    wire [7:0] next_low = below_target ? dco_code : low_code;
    wire [7:0] next_high = below_target ? high_code : dco_code;
    wire [7:0] next_span = next_high - next_low;
    wire [7:0] ramp_span = dco_code - low_code;

    // Round up the measured phase delta and add the endpoint uncertainty.
    // START and measurement use the same multiplier at different times.
    wire [12:0] cycles_ceiling = {1'b0, observed_delta[23:12]} + 13'd1 +
                                {12'b0, |observed_delta[11:0]};
    wire [16:0] speed_operand = state == START ? ratio_q12 : {4'b0, cycles_ceiling};
    wire [22:0] speed_upper = speed_operand * ref_upper_mhz;
    // COARSE_LIMIT is an exact multiple of the 512-unit step budget.
    // Subtract the ceiling in steps, which avoids a 23-bit subtractor.
    wire [4:0] guarded_step_count = speed_upper[13:9] + {4'b0, |speed_upper[8:0]};
    wire [4:0] safe_steps = speed_upper < COARSE_LIMIT ? COARSE_STEP_BUDGET - guarded_step_count : 5'd0;
    wire [4:0] ramp_step = dco_code < 8'd32 ? 5'd8 : 5'd16;
    wire [4:0] guarded_step = safe_steps < ramp_step ? safe_steps : ramp_step;
    wire [8:0] ramp_sum = {1'b0, dco_code} + {4'b0, guarded_step};
    wire [7:0] ramp_limit = manual ? manual_code : code_ceiling;
    wire [7:0] ramp_code = ramp_sum > {1'b0, ramp_limit} ? ramp_limit : ramp_sum[7:0];

    wire accumulate_fine = extended_fine && measurement >= FINE_LOW;
    // The guard limits each 32-cycle advance to less than 800 cycles.
    // Sum four quarter-weighted deltas to bound the truncation to <4 Q8 LSB.
    wire [17:0] fine_total = fine_work + {2'b0, observed_delta[21:6]};
    wire [17:0] fine_measured = accumulate_fine ? fine_total : observed_delta[21:4];
    wire [18:0] fine_target = target_delta[22:4];
    wire [18:0] gain_difference = {1'b0, fine_measured} - {1'b0, fine_low_measure};
    wire [17:0] gain_delta = gain_difference[17:0];
    wire positive_gain = !gain_difference[18] && gain_delta != 0;
    // Each whole phase cycle equals one Q12 gain unit (32 cycles, 128 steps).
    wire [12:0] coarse_gain = {3'b0, gain_delta[17:8]};
    wire [12:0] rounded_gain = coarse_gain + {12'b0, gain_delta[7]};
    wire [18:0] seed_double = {fine_work, 1'b0};
    wire [19:0] seed_difference = {1'b0, seed_double} - {2'b0, fine_divisor};
    wire seed_bit = !seed_difference[19];
    wire [17:0] seed_next_rem = seed_bit ? seed_difference[17:0] : seed_double[17:0];
    wire [6:0] seed_next_code = {seed_code[5:0], seed_bit};

    wire [23:0] next_phase = target_phase + {7'b0, ratio_q12};
    wire signed [23:0] phase_error = $signed(next_phase - phase_q12);
    wire error_negative = phase_error[23];
    wire [13:0] error_magnitude = (phase_error > 24'sd8192 || phase_error < -24'sd8192) ?
        14'd8192 : error_negative ? -phase_error[13:0] : phase_error[13:0];
    wire phase_close = phase_error >= -24'sd1024 && phase_error <= 24'sd1024;
    wire phase_far = phase_error < -24'sd2048 || phase_error > 24'sd2048;
    wire [25:0] normalized_error = {error_magnitude, 12'b0} >> gain_exponent;
    // One extra bandwidth reduction for the channels nearest an integer.
    wire near_integer = ratio_q12[11:0] == 12'd1 || ratio_q12[11:0] == 12'd4095;
    wire [1:0] locked_gear = narrow_near_integer && near_integer && tracking_gear == 2'd2 ?
                             2'd3 : tracking_gear;
    wire [25:0] p_magnitude = locked ? (normalized_error >> 1) >> locked_gear :
                                      normalized_error;
    wire [20:0] i_magnitude = locked ? {2'b0, normalized_error[25:7]} >> {locked_gear, 1'b0} :
                                      normalized_error[25:5];
    wire monitoring = state == TRACK || state == MANUAL;

    function automatic [3:0] highest_bit(input [12:0] value);
        integer index;
        begin
            highest_bit = 0;
            for (index = 0; index <= 12; index = index + 1)
                if (value[index]) highest_bit = 4'(index);
        end
    endfunction

    function automatic [23:0] clamp_tune(input signed [26:0] value);
        begin
            if (value < 0) clamp_tune = 0;
            else if (value > $signed({3'b0, MAX_TUNE})) clamp_tune = MAX_TUNE;
            else clamp_tune = value[23:0];
        end
    endfunction

    wire signed [26:0] i_step = $signed({6'b0, i_magnitude} ^ {27{error_negative}});
    wire signed [26:0] p_step = $signed({1'b0, p_magnitude} ^ {27{error_negative}});
    wire [23:0] next_integrator = clamp_tune(
        $signed({3'b0, integrator}) + i_step + $signed({26'b0, error_negative}));
    wire [23:0] next_tune = clamp_tune(
        $signed({3'b0, next_integrator}) + p_step + $signed({26'b0, error_negative}));
    wire [16:0] residue_sum = {1'b0, dither_residue} + {1'b0, next_tune[15:0]};
    wire increment_code = dither_enable ? residue_sum[16] : next_tune[15];
    wire fine_rail = (next_tune == 0 && phase_error < 0) ||
                     (next_tune == MAX_TUNE && phase_error > 0);

    task automatic trip(input [2:0] reason);
        begin
            state          <= FAULT;
            fault_code     <= reason;
            dco_code       <= 0;
            fine_code      <= 0;
            locked         <= 0;
            monitor_active <= 0;
        end
    endtask

    task automatic probe_fine(input [7:0] coarse);
        begin
            measurement <= FINE_LOW;
            dco_code    <= coarse;
            fine_code   <= 0;
        end
    endtask

    always @(posedge ref_clk or negedge reset_n) begin
        if (!reset_n) begin
            state            <= START;
            dco_code         <= 0;
            fine_code        <= 0;
            locked           <= 0;
            fault_code       <= 0;
            gain_q12         <= 0;
            gain_exponent    <= 0;
            measurement      <= LOW_RAIL;
            settle_left      <= 0;
            measure_left     <= 0;
            acquire_ticks    <= 0;
            anchor           <= 0;
            fine_low_measure <= 0;
            low_code         <= 0;
            high_code        <= 0;
            monitor_active   <= 0;
            fine_retried     <= 0;
            extended_fine    <= 0;
            fine_windows     <= 0;
            fine_work        <= 0;
            fine_divisor     <= 0;
            seed_code        <= 0;
            seed_left        <= 0;
            target_phase     <= 0;
            integrator       <= 0;
            dither_residue   <= 0;
            lock_count       <= 0;
            loss_count       <= 0;
            invalid_count    <= 0;
            fine_rail_ticks  <= 0;
        end else if (restart || ref_timeout) begin
            state          <= START;
            dco_code       <= 0;
            fine_code      <= 0;
            locked         <= 0;
            fault_code     <= 0;
            monitor_active <= 0;
            dither_residue <= 0;
        end else if (!locked && state != START && state != FAULT && state != MANUAL &&
                     acquire_ticks == 11'd2047) begin
            trip(NO_LOCK);
        end else if (monitoring && monitor_active && measure_left == 0 &&
                     phase_valid && speed_upper > CLOCK_LIMIT) begin
            trip(SPEED_GUARD);
        end else begin
            if (!locked && state != FAULT && state != MANUAL)
                acquire_ticks <= acquire_ticks + 11'd1;
            if (monitoring) begin
                if (!monitor_active || measure_left == 0) begin
                    monitor_active <= phase_valid;
                    if (phase_valid) begin
                        anchor       <= phase_q12;
                        measure_left <= 5'd31;
                    end
                end else measure_left <= measure_left - 5'd1;
            end

            case (state)
                START: begin
                    if (!manual && speed_upper > SETPOINT_LIMIT) trip(SPEED_GUARD);
                    else begin
                        state          <= SETTLE;
                        measurement    <= LOW_RAIL;
                        dco_code       <= 0;
                        fine_code      <= FINE_MID;
                        settle_left    <= 4'd8;
                        low_code       <= 0;
                        high_code      <= 0;
                        locked         <= 0;
                        fault_code     <= 0;
                        gain_q12       <= 0;
                        acquire_ticks  <= 0;
                        monitor_active <= 0;
                        fine_retried   <= 0;
                        extended_fine  <= 0;
                    end
                end
                SETTLE: begin
                    if (settle_left != 0) settle_left <= settle_left - 4'd1;
                    else if (phase_valid) begin
                        anchor       <= phase_q12;
                        measure_left <= 5'd31;
                        fine_windows <= 0;
                        if (accumulate_fine) fine_work <= 0;
                        state        <= MEASURE;
                    end
                end
                MEASURE: begin
                    if (measure_left != 0) measure_left <= measure_left - 5'd1;
                    else if (!phase_valid) state <= SETTLE;
                    else if (measurement == LOW_RAIL && speed_upper < MIN_RUNNING)
                        trip(START_STALLED);
                    else if (speed_upper > (measurement <= SEARCH ? COARSE_LIMIT : CLOCK_LIMIT))
                        trip(SPEED_GUARD);
                    else if (accumulate_fine && fine_windows != 2'd3) begin
                        fine_work    <= fine_total;
                        fine_windows <= fine_windows + 2'd1;
                        anchor       <= phase_q12;
                        measure_left <= 5'd31;
                    end
                    else begin
                        settle_left <= 4'd8;
                        state       <= SETTLE;

                        case (measurement)
                            LOW_RAIL, RAMP: begin
                                if (manual && dco_code == manual_code) begin
                                    state          <= MANUAL;
                                    monitor_active <= 0;
                                end else if (manual || (below_target && dco_code != code_ceiling)) begin
                                    if (ramp_code == dco_code) trip(SPEED_GUARD);
                                    else begin
                                        low_code    <= dco_code;
                                        dco_code    <= ramp_code;
                                        measurement <= RAMP;
                                    end
                                end else begin
                                    high_code <= dco_code;
                                    if (measurement == LOW_RAIL || below_target || ramp_span <= 8'd1)
                                        probe_fine(dco_code);
                                    else begin
                                        measurement <= SEARCH;
                                        dco_code    <= low_code + (ramp_span >> 1);
                                    end
                                end
                            end
                            SEARCH: begin
                                low_code  <= next_low;
                                high_code <= next_high;
                                if (next_span <= 8'd1) probe_fine(dco_code);
                                else dco_code <= next_low + (next_span >> 1);
                            end
                            FINE_LOW: begin
                                if ({1'b0, fine_measured} > fine_target) begin
                                    if (!fine_retried && dco_code > low_code) begin
                                        fine_retried <= 1;
                                        probe_fine(low_code);
                                    end else trip(dco_code == 0 ? LOW_RANGE : FINE_RANGE);
                                end else begin
                                    fine_low_measure <= fine_measured;
                                    measurement      <= FINE_HIGH;
                                    fine_code        <= FINE_MAX;
                                end
                            end
                            FINE_HIGH: begin
                                if (!extended_fine && (!positive_gain || gain_delta < EXTEND_FINE_SPAN)) begin
                                    extended_fine <= 1;
                                    probe_fine(dco_code);
                                end else if (!positive_gain || gain_delta < MIN_FINE_SPAN) trip(BAD_GAIN);
                                else if ({1'b0, fine_measured} < fine_target) begin
                                    if (!fine_retried && dco_code < high_code) begin
                                        fine_retried <= 1;
                                        probe_fine(high_code);
                                    end else trip(dco_code == code_ceiling ? HIGH_RANGE : FINE_RANGE);
                                end else begin
                                    gain_q12      <= rounded_gain;
                                    gain_exponent <= highest_bit(coarse_gain);
                                    if ({1'b0, fine_measured} == fine_target) begin
                                        integrator <= MAX_TUNE;
                                        state      <= ALIGN;
                                    end else begin
                                        fine_divisor <= gain_delta;
                                        fine_work <= fine_target[17:0] - fine_low_measure;
                                        seed_code <= 0;
                                        seed_left <= 3'd7;
                                        state     <= SEED;
                                    end
                                end
                            end
                            default: state <= START;
                        endcase
                    end
                end
                SEED: begin
                    // Seven restoring-division steps give the initial fine code.
                    fine_work <= seed_next_rem;
                    seed_code <= seed_next_code;
                    seed_left <= seed_left - 3'd1;
                    if (seed_left == 3'd1) begin
                        fine_code  <= {1'b0, seed_next_code};
                        integrator <= {1'b0, seed_next_code, 16'b0};
                        state      <= ALIGN;
                    end
                end
                ALIGN: begin
                    if (settle_left != 0) settle_left <= settle_left - 4'd1;
                    else if (phase_valid) begin
                        target_phase   <= phase_q12;
                        dither_residue <= 0;
                        lock_count      <= 0;
                        loss_count      <= 0;
                        invalid_count   <= 0;
                        fine_rail_ticks <= 0;
                        monitor_active <= 0;
                        state          <= TRACK;
                    end
                end
                TRACK: begin
                    target_phase <= next_phase;
                    if (phase_valid) begin
                        integrator     <= next_integrator;
                        dither_residue <= dither_enable ? residue_sum[15:0] : 16'd0;
                        fine_code      <= next_tune[23:16] + {7'b0, increment_code};
                        invalid_count  <= 0;
                        fine_rail_ticks <= fine_rail ? fine_rail_ticks + 10'd1 : 10'd0;
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
                        (locked && (!phase_valid || phase_far) && loss_count == 3'd7) ||
                        (phase_valid && fine_rail && &fine_rail_ticks)) begin
                        locked    <= 0;
                        dco_code  <= 0;
                        fine_code <= 0;
                        state     <= START;
                    end
                end
                MANUAL, FAULT: locked <= 0;
                default: state <= START;
            endcase
        end
    end
endmodule
