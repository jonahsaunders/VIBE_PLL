// SPDX-License-Identifier: Apache-2.0

module cpz4_pll (
    input  wire         ref_clk,
    input  wire         reset_n,
    input  wire         enable,
    input  wire         cfg_toggle,
    input  wire [2:0]   cfg_addr,
    input  wire [16:0]  cfg_data,
    input  wire [4:0]   dco_tap,
    input  wire [14:0]  dco_fine_tap,
    output wire         dco_enable,
    output wire [254:0] dco_therm,
    output wire [127:0] dco_fine_therm,
    output wire         clk_out,
    output wire         clk_mon,
    output wire [11:0]  status
);
    localparam [16:0] DEFAULT_RATIO = 17'd41984;  // 10.25 in unsigned Q5.12
    localparam [119:0] COARSE_CENTERS = {12'd3891, 12'd3482, 12'd3072, 12'd2662,
        12'd2253, 12'd1843, 12'd1434, 12'd1024, 12'd614, 12'd205};

    wire ref_reset_n, run_n, dco_reset_n;
    cpz4_reset_release config_reset(ref_clk, reset_n, ref_reset_n);
    cpz4_reset_release run_reset(ref_clk, reset_n & enable, run_n);
    cpz4_reset_release oscillator_reset(dco_tap[0], run_n, dco_reset_n);
    assign dco_enable = run_n;
    assign clk_out = dco_tap[0];

    wire clk_div2, phase_valid, fine_valid;
    wire [3:0] phase_bin;
    wire [5:0] fine_bin;
    wire [11:0] cycles;
    cpz4_phase_sampler sampler(.ref_clk(ref_clk), .ref_reset_n(run_n), .tap(dco_tap),
        .fine_tap(dco_fine_tap), .dco_reset_n(dco_reset_n), .dco_div2(clk_div2),
        .dco_div4(clk_mon), .bin_index(phase_bin), .fine_bin(fine_bin), .fine_valid(fine_valid),
        .valid(phase_valid), .cycle_count(cycles));

    wire watchdog_dco, watchdog_ref;
    cpz4_ref_watchdog watchdog(ref_clk, run_n, clk_div2, dco_reset_n, watchdog_dco, watchdog_ref);

    reg [16:0] ratio;
    reg manual, dither, coarse_phase_only;
    reg [7:0] manual_code, code_ceiling;
    reg [5:0] ref_upper_mhz;
    reg [1:0] tracking_gear;
    reg restart, cal_start, cal_pending, cal_clear, config_error;
    reg ack;
    reg [7:0] read_byte;
    (* ASYNC_REG = "TRUE" *) reg [1:0] cfg_sync;

    wire cal_busy, cal_valid, cal_error;
    wire cal_active = cal_pending || cal_start || cal_busy;
    wire [11:0] fine_center, read_center;
    wire [11:0] phase_center = fine_valid && !coarse_phase_only ?
                              fine_center : COARSE_CENTERS[12 * phase_bin +: 12];
    wire [15:0] read_hits;
    wire [7:0] dco_code, fine_code;
    wire core_locked;
    wire [2:0] loop_fault;
    wire [12:0] gain;
    wire [3:0] loop_state;
    wire manual_ready = manual && run_n && loop_state == 4'd6;
    cpz4_phase_cal calibration(ref_clk, ref_reset_n, manual_ready, cal_start, cal_clear,
                               fine_valid, fine_bin, cfg_data[5:0], fine_center, read_center,
                               read_hits, cal_busy, cal_valid, cal_error);
    cpz4_loop_control loop_filter(.ref_clk(ref_clk), .reset_n(run_n), .restart(restart),
        .ref_timeout(watchdog_ref), .manual(manual), .dither_enable(dither),
        .manual_code(manual_code), .code_ceiling(code_ceiling), .ref_upper_mhz(ref_upper_mhz),
        .tracking_gear(tracking_gear), .ratio_q12(ratio), .phase_valid(phase_valid),
        .phase_q12({cycles, phase_center}), .dco_code(dco_code), .fine_code(fine_code),
        .locked(core_locked), .fault_code(loop_fault), .gain_q12(gain), .state(loop_state));

    // Register each cell command to avoid decoder glitches during binary carries.
    genvar unit_id;
    generate
        for (unit_id = 0; unit_id < 255; unit_id = unit_id + 1) begin : unit_decoder
            localparam [7:0] THRESHOLD = 8'(unit_id);
            reg unit_enable;
            always @(posedge ref_clk or negedge run_n) begin
                if (!run_n) unit_enable <= 1'b0;
                else        unit_enable <= dco_code > THRESHOLD && code_ceiling > THRESHOLD;
            end
            assign dco_therm[unit_id] = unit_enable;
        end
        for (unit_id = 0; unit_id < 128; unit_id = unit_id + 1) begin : fine_decoder
            localparam [7:0] THRESHOLD = 8'(unit_id);
            reg unit_enable;
            always @(posedge ref_clk or negedge run_n) begin
                if (!run_n) unit_enable <= 1'b0;
                else        unit_enable <= fine_code > THRESHOLD;
            end
            assign dco_fine_therm[unit_id] = unit_enable;
        end
    endgenerate

    wire locked = core_locked && run_n && !watchdog_dco && !watchdog_ref;
    wire fault = config_error || cal_error || watchdog_dco || (loop_fault != 0);
    assign status = {fault, cal_active, locked, ack, read_byte};

    always @(posedge ref_clk or negedge ref_reset_n) begin
        if (!ref_reset_n) begin
            cfg_sync     <= 0;
            ack          <= 0;
            ratio        <= DEFAULT_RATIO;
            manual       <= 0;
            dither       <= 1;
            coarse_phase_only <= 0;
            manual_code  <= 8'd24;
            code_ceiling <= 8'd255;
            ref_upper_mhz <= 6'd32;
            tracking_gear <= 2'd2;
            restart      <= 0;
            cal_start    <= 0;
            cal_pending  <= 0;
            cal_clear    <= 0;
            config_error <= 0;
            read_byte    <= 0;
        end else begin
            cfg_sync  <= {cfg_sync[0], cfg_toggle};
            restart   <= 0;
            cal_start <= 0;
            cal_clear <= 0;
            if (cal_pending) begin
                if (!run_n || loop_fault != 0) cal_pending <= 0;
                else if (manual_ready) begin
                    cal_start   <= 1'b1;
                    cal_pending <= 0;
                end
            end
            if (cfg_sync[1] != ack) begin
                ack <= cfg_sync[1];
                case (cfg_addr)
                    3'd0: begin
                        if (!cal_active && cfg_data >= 17'd20480 && cfg_data <= 17'd102400) begin
                            ratio   <= cfg_data;
                            restart <= 1'b1;
                        end else config_error <= 1'b1;
                    end
                    3'd1: begin
                        if (cal_active || (cfg_data[0] && cfg_data[9:2] > code_ceiling))
                            config_error <= 1'b1;
                        else begin
                            manual      <= cfg_data[0];
                            dither      <= cfg_data[1];
                            manual_code <= cfg_data[9:2];
                            coarse_phase_only <= cfg_data[10];
                            restart     <= 1'b1;
                        end
                    end
                    3'd2: begin
                        if (cfg_data[16:8] == 9'h100) begin
                            if (cfg_data[7:0] < 8'd16 || cal_active ||
                                (manual && manual_code > cfg_data[7:0])) config_error <= 1'b1;
                            else begin
                                code_ceiling <= cfg_data[7:0];
                                restart      <= 1'b1;
                            end
                        end else if (cfg_data[16:8] == 9'h101) begin
                            if (cfg_data[7:0] < 8'd16 || cfg_data[7:0] > 8'd32 || cal_active)
                                config_error <= 1'b1;
                            else begin
                                ref_upper_mhz <= cfg_data[5:0];
                                restart       <= 1'b1;
                            end
                        end else case (cfg_data)
                            17'd1: begin
                                if (manual && run_n && !cal_active) cal_pending <= 1'b1;
                                else config_error <= 1'b1;
                            end
                            17'd2: begin
                                cal_clear <= 1'b1;
                                restart   <= 1'b1;
                                cal_pending <= 1'b0;
                            end
                            17'd3: begin
                                if (cal_active) config_error <= 1'b1;
                                else restart <= 1'b1;
                            end
                            17'd4: config_error <= 1'b0;
                            17'd5: tracking_gear <= 2'd0;
                            17'd6: tracking_gear <= 2'd1;
                            17'd7: tracking_gear <= 2'd2;
                            default: config_error <= 1'b1;
                        endcase
                    end
                    3'd3: read_byte <= read_center[7:0];
                    3'd4: read_byte <= {4'b0, read_center[11:8]};
                    3'd5: begin
                        case (cfg_data)
                            17'd0: read_byte <= dco_code;
                            17'd1: read_byte <= gain[7:0];
                            17'd2: read_byte <= {3'b0, gain[12:8]};
                            17'd3: read_byte <= {watchdog_ref, loop_state, loop_fault};
                            17'd4: read_byte <= {dither, run_n, watchdog_ref, cal_error,
                                                  config_error, phase_valid, manual, cal_valid};
                            17'd5: read_byte <= {4'b0, phase_bin};
                            17'd6: read_byte <= code_ceiling;
                            17'd7: read_byte <= {fine_valid, coarse_phase_only, fine_bin};
                            17'd8: read_byte <= fine_code;
                            17'd9: read_byte <= {6'b0, tracking_gear};
                            17'd10: read_byte <= {2'b0, ref_upper_mhz};
                            default: read_byte <= 8'd0;
                        endcase
                    end
                    3'd6: read_byte <= read_hits[7:0];
                    3'd7: read_byte <= read_hits[15:8];
                    default: config_error <= 1'b1;
                endcase
            end
        end
    end
endmodule
