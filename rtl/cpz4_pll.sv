// SPDX-License-Identifier: Apache-2.0

module cpz4_pll (
    input  wire         ref_clk,
    input  wire         reset_n,
    input  wire         enable,
    input  wire         cfg_toggle,
    input  wire [2:0]   cfg_addr,
    input  wire [16:0]  cfg_data,
    input  wire [4:0]   dco_tap,
    output wire         dco_enable,
    output wire [254:0] dco_therm,
    output wire         clk_out,
    output wire         clk_mon,
    output wire [11:0]  status
);
    localparam [16:0] DEFAULT_RATIO = 17'd41984;  // 10.25 in unsigned Q5.12

    wire ref_reset_n, run_n, dco_reset_n;
    cpz4_reset_release config_reset(ref_clk, reset_n, ref_reset_n);
    cpz4_reset_release run_reset(ref_clk, reset_n & enable, run_n);
    cpz4_reset_release oscillator_reset(dco_tap[0], run_n, dco_reset_n);
    assign dco_enable = run_n;
    assign clk_out = dco_tap[0];

    wire clk_div2, phase_valid;
    wire [3:0] phase_bin;
    wire [11:0] cycles;
    cpz4_phase_sampler sampler(ref_clk, run_n, dco_tap, dco_reset_n, clk_div2,
                               clk_mon, phase_bin, phase_valid, cycles);

    wire watchdog_dco, watchdog_ref;
    cpz4_ref_watchdog watchdog(ref_clk, run_n, clk_div2, dco_reset_n, watchdog_dco, watchdog_ref);

    reg [16:0] ratio;
    reg manual, dither;
    reg [7:0] manual_code, code_ceiling;
    reg restart, cal_start, cal_clear, config_error;
    reg ack;
    reg [7:0] read_byte;
    (* ASYNC_REG = "TRUE" *) reg [1:0] cfg_sync;

    wire cal_busy, cal_valid, cal_error;
    wire [11:0] phase_center, read_center;
    wire [14:0] read_hits;
    cpz4_phase_cal calibration(ref_clk, ref_reset_n, manual && run_n, cal_start, cal_clear,
                               phase_valid, phase_bin, cfg_data[3:0], phase_center, read_center,
                               read_hits, cal_busy, cal_valid, cal_error);

    wire [7:0] dco_code;
    wire core_locked;
    wire [2:0] loop_fault;
    wire [12:0] gain;
    wire [3:0] loop_state;
    cpz4_loop_control loop_filter(ref_clk, run_n, restart, watchdog_ref, manual, dither,
                                  manual_code, code_ceiling, ratio, phase_valid, {cycles, phase_center},
                                  dco_code, core_locked, loop_fault, gain, loop_state);

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
    endgenerate

    wire locked = core_locked && run_n && !watchdog_dco && !watchdog_ref;
    wire fault = config_error || cal_error || watchdog_dco || (loop_fault != 0);
    assign status = {fault, cal_busy, locked, ack, read_byte};

    always @(posedge ref_clk or negedge ref_reset_n) begin
        if (!ref_reset_n) begin
            cfg_sync     <= 0;
            ack          <= 0;
            ratio        <= DEFAULT_RATIO;
            manual       <= 0;
            dither       <= 1;
            manual_code  <= 8'd128;
            code_ceiling <= 8'd255;
            restart      <= 0;
            cal_start    <= 0;
            cal_clear    <= 0;
            config_error <= 0;
            read_byte    <= 0;
        end else begin
            cfg_sync  <= {cfg_sync[0], cfg_toggle};
            restart   <= 0;
            cal_start <= 0;
            cal_clear <= 0;
            if (cfg_sync[1] != ack) begin
                ack <= cfg_sync[1];
                case (cfg_addr)
                    3'd0: begin
                        if (cfg_data >= 17'd20480 && cfg_data <= 17'd102400) begin
                            ratio   <= cfg_data;
                            restart <= 1'b1;
                        end else config_error <= 1'b1;
                    end
                    3'd1: begin
                        if (cal_busy || (cfg_data[0] && cfg_data[9:2] > code_ceiling))
                            config_error <= 1'b1;
                        else begin
                            manual      <= cfg_data[0];
                            dither      <= cfg_data[1];
                            manual_code <= cfg_data[9:2];
                            restart     <= 1'b1;
                        end
                    end
                    3'd2: begin
                        if (cfg_data[16:8] == 9'h100) begin
                            if (cfg_data[7:0] < 8'd16 || cal_busy ||
                                (manual && manual_code > cfg_data[7:0])) config_error <= 1'b1;
                            else begin
                                code_ceiling <= cfg_data[7:0];
                                restart      <= 1'b1;
                            end
                        end else case (cfg_data)
                            17'd1: begin
                                if (manual && run_n && !cal_busy) cal_start <= 1'b1;
                                else config_error <= 1'b1;
                            end
                            17'd2: begin
                                cal_clear <= 1'b1;
                                restart   <= 1'b1;
                            end
                            17'd3: restart <= 1'b1;
                            17'd4: config_error <= 1'b0;
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
                            default: read_byte <= 8'd0;
                        endcase
                    end
                    3'd6: read_byte <= read_hits[7:0];
                    3'd7: read_byte <= {1'b0, read_hits[14:8]};
                    default: config_error <= 1'b1;
                endcase
            end
        end
    end
endmodule
