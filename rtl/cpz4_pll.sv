// SPDX-License-Identifier: Apache-2.0

module cpz4_pll #(
    parameter ON_CHIP_CAL = 1'b1,
    parameter [479:0] FIXED_FINE_CENTERS = {
        // Schematic TT at coarse 52, fine 64. Bin zero is at the LSB.
        120'hf86ee9ea8e68dd6d46d05cc7c44bbb,
        120'hb7ab3aaa8a179d79989258ab869826,
        120'h77f6dd69c65e5db5525114d143f3af,
        120'h36e32f2ad2241e31a31230a5063020
    },
    parameter [479:0] SLOW_FINE_CENTERS = {
        // Sky130A SS, 1.62 V, 0 C at coarse 172, fine 64. Bin zero is at the LSB.
        120'hfd8f67edee5be12dcdd46ccac8dc39,
        120'hbb0b2dae4a9fa1899c96992c8b0827,
        120'h7c07646dd6616235d05474c447b436,
        120'h3af3332f52a12181961531340ca040
    },
    parameter [7:0] MAX_COARSE_CODE = 8'd255,
    parameter TRACKING_REPLICAS = 1'b0,
    parameter RANGE_DCO = 1'b0
) (
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
    localparam [479:0] TRACKING_FINE_CENTERS = {
        // TT tracking-replica schematic, coarse 52, fine 64.
        120'hfb2f38edfe81e11da4d4bce7c72c0a,
        120'hbb1b54ae3a76a1c9b89448dc88382f,
        120'h7b973b6e267e6095a25494eb47b40e,
        120'h3b53512db27321a1bc14d0e108702e
    };
    localparam [479:0] TRACKING_SLOW_CENTERS = {
        // SS tracking-replica schematic, 1.62 V, 0 C, coarse 172, fine 64.
        120'hfcef5cee6e70e1bdced58cd9c82c2e,
        120'hbb8b42aedaa0a2a9ab95590188b825,
        120'h7c97656ef6706195c554f4d9484437,
        120'h3c13422eb2972211ab15710b09502c
    };

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
    reg manual, dither, coarse_phase_only, slow_phase_profile, narrow_near_integer;
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
    generate
        if (ON_CHIP_CAL) begin : measured_centers
            cpz4_phase_cal calibration(ref_clk, ref_reset_n, manual_ready, cal_start, cal_clear,
                                       fine_valid, fine_bin, cfg_data[5:0], fine_center, read_center,
                                       read_hits, cal_busy, cal_valid, cal_error);
        end else begin : fixed_centers
            // Capacitance-extracted range-DCO probes in results/range-dco.
            // Bin 0 occupies the least significant 12 bits of each table.
            localparam [479:0] RANGE_TT = {
                120'hffffffffff3de7ae7ae7adaccdecde, 120'hcdec14b4ab4ab4aa7b9ac9ac9ac8e9,
                120'h82682682674a66e66e66e5b14f34f3, 120'h4f34123323323322701ae1ae19e0c7};
            localparam [479:0] RANGE_SS = {
                120'hffffffff7f12e35e35e35db1d2dd2d, 120'hcfdbffb31b31b1fa5d9ac9ac9888af,
                120'h7fa7fa7fa7326696696695a54e04e0, 120'h4e043f39d39d35524718018016c0ac};
            localparam [959:0] PROFILES = RANGE_DCO ? {RANGE_SS, RANGE_TT} : TRACKING_REPLICAS ?
                {TRACKING_SLOW_CENTERS, TRACKING_FINE_CENTERS} : {SLOW_FINE_CENTERS, FIXED_FINE_CENTERS};
            wire [6:0] detector_index = slow_phase_profile ? {1'b0, fine_bin} + 7'd40 : {1'b0, fine_bin};
            wire [6:0] read_index = slow_phase_profile ? {1'b0, cfg_data[5:0]} + 7'd40 : {1'b0, cfg_data[5:0]};
            assign fine_center = fine_bin < 6'd40 ? PROFILES[12*detector_index +: 12] : 12'd0;
            assign read_center = cfg_data[5:0] < 6'd40 ?
                                 PROFILES[12*read_index +: 12] : 12'd0;
            assign read_hits = 0;
            assign cal_busy = 0;
            assign cal_valid = 0;
            assign cal_error = 0;
        end
    endgenerate
    // Capture the count, decoded phase and validity from the same sample.
    // This separates the asynchronous-tap decoder from the loop arithmetic.
    reg [23:0] measured_phase;
    reg measured_valid;
    always @(posedge ref_clk or negedge run_n) begin
        if (!run_n) begin
            measured_phase <= 0;
            measured_valid <= 0;
        end else begin
            measured_phase <= {cycles, phase_center};
            measured_valid <= phase_valid;
        end
    end
    cpz4_loop_control loop_filter(.ref_clk(ref_clk), .reset_n(run_n), .restart(restart),
        .ref_timeout(watchdog_ref), .manual(manual), .dither_enable(dither),
        .narrow_near_integer(narrow_near_integer),
        .manual_code(manual_code), .code_ceiling(code_ceiling), .ref_upper_mhz(ref_upper_mhz),
        .tracking_gear(tracking_gear), .ratio_q12(ratio), .phase_valid(measured_valid),
        .phase_q12(measured_phase), .dco_code(dco_code), .fine_code(fine_code),
        .locked(core_locked), .fault_code(loop_fault), .gain_q12(gain), .state(loop_state));

    // Register each cell command to avoid decoder glitches during binary carries.
    // Clamp the common coarse command before the 255 registered decodes.
    wire [7:0] applied_coarse = dco_code < code_ceiling ? dco_code : code_ceiling;
    genvar unit_id;
    generate
        for (unit_id = 0; unit_id < 255; unit_id = unit_id + 1) begin : unit_decoder
            localparam [7:0] THRESHOLD = 8'(unit_id);
            reg unit_enable;
            always @(posedge ref_clk or negedge run_n) begin
                if (!run_n) unit_enable <= 1'b0;
                else        unit_enable <= applied_coarse > THRESHOLD;
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
            slow_phase_profile <= 0;
            narrow_near_integer <= 0;
            manual_code  <= 8'd24;
            code_ceiling <= MAX_COARSE_CODE;
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
                            slow_phase_profile <= cfg_data[11] && !ON_CHIP_CAL;
                            narrow_near_integer <= cfg_data[12];
                            restart     <= 1'b1;
                        end
                    end
                    3'd2: begin
                        if (cfg_data[16:8] == 9'h100) begin
                            if (cfg_data[7:0] < 8'd16 || cfg_data[7:0] > MAX_COARSE_CODE || cal_active ||
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
                                if (ON_CHIP_CAL && manual && run_n && !cal_active) cal_pending <= 1'b1;
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
                            17'd11: read_byte <= {7'b0, ON_CHIP_CAL};
                            17'd12: read_byte <= {5'b0, TRACKING_REPLICAS, narrow_near_integer, slow_phase_profile};
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
