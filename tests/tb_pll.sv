// SPDX-License-Identifier: Apache-2.0
`timescale 1ps/1fs

module tb_pll;
    reg ref_clk = 0, ref_running = 1;
    reg reset_n = 1, enable = 0, cfg_toggle = 0;
    reg [2:0] cfg_addr = 0;
    reg [16:0] cfg_data = 0;
    reg [4:0] ring = 0;
    reg corrupt_taps = 0, coherent_calibration = 0;
    wire [4:0] taps = corrupt_taps ? {4'b0, ring[0]} : ring;
    wire dco_enable, clk_out, clk_mon;
    wire [254:0] therm;
    wire [11:0] status;

    cpz4_pll dut(ref_clk, reset_n, enable, cfg_toggle, cfg_addr, cfg_data, taps,
                 dco_enable, therm, clk_out, clk_mon, status);

    real ref_mhz = 25.0;
    real low_mhz = 100.0;
    real high_mhz = 485.0;
    real curvature = 0.18;
    real ref_half_ps, period_ps, fraction, model_value;
    real widths [0:9];
    real plant_frequency [0:255];
    real plant_widths [0:2559];
    reg [4:0] patterns [0:9];
    integer phase_id, throwaway, model_file, model_row, model_col, model_status, active_code;
    string model_path;
    reg use_spice_model = 0;
    integer applied_code;
    always @* applied_code = $countones(therm);

    initial begin
        throwaway = $value$plusargs("ref=%f", ref_mhz);
        throwaway = $value$plusargs("low=%f", low_mhz);
        throwaway = $value$plusargs("high=%f", high_mhz);
        throwaway = $value$plusargs("curve=%f", curvature);
        ref_half_ps = 500000.0 / ref_mhz;
        forever begin
            #(ref_half_ps);
            ref_clk = ref_running ? ~ref_clk : 1'b0;
        end
    end

    initial begin
        patterns[0] = 5'h0b; patterns[1] = 5'h09; patterns[2] = 5'h0d;
        patterns[3] = 5'h05; patterns[4] = 5'h15; patterns[5] = 5'h14;
        patterns[6] = 5'h16; patterns[7] = 5'h12; patterns[8] = 5'h1a; patterns[9] = 5'h0a;
        widths[0] = 0.08; widths[1] = 0.12; widths[2] = 0.09; widths[3] = 0.11;
        widths[4] = 0.13; widths[5] = 0.06; widths[6] = 0.15; widths[7] = 0.07;
        widths[8] = 0.10; widths[9] = 0.09;
        if ($value$plusargs("spice_table=%s", model_path)) begin
            model_file = $fopen(model_path, "r");
            if (model_file == 0) $fatal(1, "Could not open the SPICE plant table");
            for (model_row = 0; model_row < 256; model_row = model_row + 1) begin
                model_status = $fscanf(model_file, "%f", model_value);
                if (model_status != 1) $fatal(1, "Bad SPICE plant frequency row %d", model_row);
                plant_frequency[model_row] = model_value;
                for (model_col = 0; model_col < 10; model_col = model_col + 1) begin
                    model_status = $fscanf(model_file, "%f", model_value);
                    if (model_status != 1) $fatal(1, "Bad SPICE plant tap row %d", model_row);
                    plant_widths[10 * model_row + model_col] = model_value;
                end
            end
            $fclose(model_file);
            use_spice_model = 1;
        end
        forever begin
            wait (dco_enable === 1'b1);
            #173.209;
            while (dco_enable) begin
                active_code = applied_code;
                fraction = active_code / 255.0;
                if (use_spice_model) period_ps = 1000000.0 / plant_frequency[active_code];
                else period_ps = 1000000.0 / (low_mhz + (high_mhz - low_mhz) *
                                 (fraction + curvature * fraction * (1.0 - fraction)));
                if (coherent_calibration) period_ps = 100000.0 / ref_mhz;
                for (phase_id = 0; phase_id < 10 && dco_enable; phase_id = phase_id + 1) begin
                    ring = patterns[phase_id];
                    if (use_spice_model) #(period_ps * plant_widths[10 * active_code + phase_id]);
                    else #(period_ps * widths[phase_id]);
                end
            end
            ring = 0;
        end
    end

    integer trace_file = 0;
    string trace_path;
    initial begin
        if ($value$plusargs("trace=%s", trace_path)) begin
            trace_file = $fopen(trace_path, "w");
            if (trace_file == 0) $fatal(1, "Could not open trace file");
            $fdisplay(trace_file, "time_us,state,locked,code,gain_q12,phase_error_q12,valid,ratio_q12");
        end
    end

    always @(negedge ref_clk) begin
        if (trace_file != 0 && reset_n && enable && $realtime < 130000000)
            $fdisplay(trace_file, "%.6f,%0d,%0d,%0d,%0d,%0d,%0d,%0d", $realtime / 1.0e6,
                      dut.loop_state, status[9], dut.dco_code, dut.gain,
                      $signed(dut.loop_filter.phase_error), dut.phase_valid, dut.ratio);
    end

    task automatic transact(input [2:0] addr, input [16:0] data);
        integer tries;
        begin
            @(negedge ref_clk);
            cfg_addr = addr;
            cfg_data = data;
            @(negedge ref_clk);
            cfg_toggle = ~cfg_toggle;
            tries = 0;
            while (status[8] !== cfg_toggle && tries < 12) begin
                @(negedge ref_clk);
                tries = tries + 1;
            end
            if (status[8] !== cfg_toggle) $fatal(1, "Configuration handshake timed out");
        end
    endtask

    task automatic require_unlock;
        integer ticks;
        begin
            ticks = 0;
            while (status[9] !== 1'b0 && ticks < 16) begin
                @(negedge ref_clk);
                ticks = ticks + 1;
            end
            if (status[9] !== 1'b0) $fatal(1, "Lock should have cleared");
        end
    endtask

    task automatic acquire(input string label, input real started_ps);
        integer ticks;
        real elapsed_us;
        begin
            ticks = 0;
            while (status[9] !== 1'b1 && ticks < 3200 && dut.loop_fault == 0) begin
                @(negedge ref_clk);
                ticks = ticks + 1;
            end
            elapsed_us = ($realtime - started_ps) / 1.0e6;
            if (status[9] !== 1'b1 || elapsed_us > 100.0)
                $fatal(1, "%s acquisition %.3f us, state=%d fault=%d", label, elapsed_us,
                       dut.loop_state, dut.loop_fault);
            $display("LOCK %s us=%.3f gain_q12=%0d code=%0d peak_MHz=%.2f",
                     label, elapsed_us, dut.gain, dut.dco_code, peak_mhz);
            peak_mhz = 0;
        end
    endtask

    task automatic measure_frequency(input real target_mhz);
        real start_ps, actual, ppm;
        integer edge_number;
        begin
            @(posedge clk_mon);
            start_ps = $realtime;
            for (edge_number = 0; edge_number < 1024; edge_number = edge_number + 1) begin
                @(posedge clk_mon);
                if (!status[9]) $fatal(1, "Unexpected unlock during frequency test");
            end
            actual = 4096.0e6 / ($realtime - start_ps);
            ppm = (actual / target_mhz - 1.0) * 1.0e6;
            if (ppm > 100.0 || ppm < -100.0) $fatal(1, "Frequency error %.2f ppm", ppm);
            $display("FREQ target_MHz=%.7f measured_MHz=%.7f error_ppm=%+.2f", target_mhz, actual, ppm);
        end
    endtask

    task automatic do_calibration(input bit expect_failure);
        integer ticks;
        begin
            transact(3'd2, 17'd1);
            repeat (4) @(negedge ref_clk);
            if (!status[10]) $fatal(1, "Calibration did not start");
            transact(3'd1, 17'd471);
            if (!dut.config_error || dut.manual_code != 8'd116)
                $fatal(1, "Manual code changed during calibration");
            transact(3'd2, 17'd4);
            ticks = 0;
            while (status[10] && ticks < 18000) begin
                @(negedge ref_clk);
                ticks = ticks + 1;
            end
            if (status[10] || status[11] !== expect_failure)
                $fatal(1, "Calibration result mismatched expectation");
        end
    endtask

    real started, lost_us, hold_start, peak_mhz, last_edge_ps, edge_mhz;
    integer initial_ratio, retune_ratio, value_unused;
    integer spectrum_file, edge_id;
    string spectrum_path;
    always @(posedge clk_out) begin
        if (last_edge_ps != 0 && $realtime > last_edge_ps) begin
            edge_mhz = 1000000.0 / ($realtime - last_edge_ps);
            if (edge_mhz > peak_mhz) peak_mhz = edge_mhz;
        end
        last_edge_ps = $realtime;
    end
    integer cal_index, sum_hits, hits, center, center_lo, error;
    integer rail_wait, edge_ratio;
    real model_low, model_high;
    real ideal_center, cumulative_width;
    initial begin
        initial_ratio = 41984;
        retune_ratio = 49152;
        value_unused = $value$plusargs("start_n=%d", initial_ratio);
        value_unused = $value$plusargs("retune_n=%d", retune_ratio);
        #1 reset_n = 0;
        repeat (5) @(negedge ref_clk);
        reset_n = 1;
        repeat (5) @(negedge ref_clk);
        if (initial_ratio != 41984) transact(3'd0, 17'(initial_ratio));
        started = $realtime;
        enable = 1;
        acquire("fractional_default", started);
        measure_frequency(ref_mhz * initial_ratio / 4096.0);
        if ($value$plusargs("spectrum=%s", spectrum_path)) begin
            spectrum_file = $fopen(spectrum_path, "w");
            if (spectrum_file == 0) $fatal(1, "Could not open edge times file");
            $fdisplay(spectrum_file, "time_ps");
            repeat (128) @(posedge ref_clk);
            for (edge_id = 0; edge_id < 131072; edge_id = edge_id + 1) begin
                @(posedge clk_out);
                if (!status[9]) $fatal(1, "Unlock in spectral test");
                $fdisplay(spectrum_file, "%.3f", $realtime);
            end
            $fclose(spectrum_file);
            $display("PASS SPECTRUM raw_edges=131072");
            $finish;
        end

        started = $realtime;
        transact(3'd0, 17'(retune_ratio));
        require_unlock();
        acquire("integer_retune", started);
        measure_frequency(ref_mhz * retune_ratio / 4096.0);

        transact(3'd0, 17'd102401);
        if (!status[11] || !status[9] || dut.ratio != 17'(retune_ratio))
            $fatal(1, "Invalid configuration changed the active ratio or lock");
        transact(3'd2, 17'd4);
        if (status[11]) $fatal(1, "Configuration fault did not clear");

        @(negedge ref_clk);
        started = $realtime;
        ref_running = 0;
        wait (status[9] == 0);
        lost_us = ($realtime - started) / 1.0e6;
        if (lost_us > 2.0 || !status[11]) $fatal(1, "Reference-loss detection %.3f us", lost_us);
        @(posedge clk_mon);
        hold_start = $realtime;
        repeat (64) @(posedge clk_mon);
        if (status[9] || !dco_enable || ($realtime - hold_start) > 2.0e6)
            $fatal(1, "Holdover clock did not continue");
        $display("WATCHDOG us=%.3f monitor_edges=64", lost_us);
        started = $realtime;
        ref_running = 1;
        acquire("reference_return", started);

        corrupt_taps = 1;
        require_unlock();
        repeat (5) @(negedge ref_clk);
        started = $realtime;
        corrupt_taps = 0;
        acquire("invalid_sample_recovery", started);

        model_low = use_spice_model ? plant_frequency[0] : low_mhz;
        model_high = use_spice_model ? plant_frequency[255] : high_mhz;
        if ($value$plusargs("edge=%d", edge_ratio)) begin
            started = $realtime;
            transact(3'd0, 17'(edge_ratio));
            require_unlock();
            acquire("range_endpoint", started);
            measure_frequency(ref_mhz * edge_ratio / 4096.0);
        end

        if (ref_mhz * 25.0 > model_high) begin
            transact(3'd0, 17'd102400);
            rail_wait = 0;
            while (!status[11] && rail_wait < 1450) begin
                @(negedge ref_clk);
                rail_wait = rail_wait + 1;
            end
            if (!status[11] || status[9] || dut.loop_fault != 3'd2)
                $fatal(1, "High rail should reject an unreachable ratio");
            $display("HIGH_RAIL_REJECTED");
        end

        if (ref_mhz * 5.0 < model_low) begin
            transact(3'd0, 17'd20480);
            repeat (4) @(negedge ref_clk);
            rail_wait = 0;
            while (!status[11] && rail_wait < 100) begin
                @(negedge ref_clk);
                rail_wait = rail_wait + 1;
            end
            if (!status[11] || status[9] || dut.loop_fault != 3'd1)
                $fatal(1, "Low rail should reject an unreachable ratio");
            $display("LOW_RAIL_REJECTED");
        end

        if ($test$plusargs("calibrate")) begin
            transact(3'd2, 17'h10040);
            transact(3'd0, 17'd49152);
            repeat (4) @(negedge ref_clk);
            rail_wait = 0;
            while (!status[11] && rail_wait < 400) begin
                @(negedge ref_clk);
                rail_wait = rail_wait + 1;
            end
            if (!status[11] || status[9] || dut.loop_fault != 3'd2 || applied_code > 64)
                $fatal(1, "Configured ceiling was bypassed");
            $display("PROGRAMMABLE_CEILING_CHECKED");
            transact(3'd2, 17'h100ff);
            transact(3'd1, 17'd467);  // manual code 116, dither enabled for later auto mode
            do_calibration(0);
            sum_hits = 0;
            cumulative_width = 0.0;
            for (cal_index = 0; cal_index < 10; cal_index = cal_index + 1) begin
                transact(3'd6, 17'(cal_index));
                hits = int'(status[7:0]);
                transact(3'd7, 17'(cal_index));
                hits = hits + 256 * int'(status[7:0]);
                transact(3'd3, 17'(cal_index));
                center_lo = int'(status[7:0]);
                transact(3'd4, 17'(cal_index));
                center = center_lo + 256 * int'(status[7:0]);
                if (center != ((2 * sum_hits + hits + 4) / 8))
                    $fatal(1, "LUT rounding does not match histogram at bin %d", cal_index);
                ideal_center = 4096.0 * (cumulative_width + widths[cal_index] / 2.0);
                error = int'(center - ideal_center);
                if (error > 20 || error < -20) $fatal(1, "Calibrated bin %0d off by %0d Q12", cal_index, error);
                cumulative_width = cumulative_width + widths[cal_index];
                sum_hits = sum_hits + hits;
                $display("CAL bin=%0d hits=%0d center_q12=%0d ideal_q12=%.2f", cal_index, hits, center, ideal_center);
            end
            if (sum_hits != 16384) $fatal(1, "Wrong histogram total %0d", sum_hits);
            transact(3'd5, 17'd4);
            if (!status[0]) $fatal(1, "Calibration valid flag missing");
            transact(3'd0, 17'd40961);
            started = $realtime;
            transact(3'd1, 17'd2);
            acquire("calibrated_near_integer", started);
            measure_frequency(ref_mhz * (10.0 + 1.0 / 4096.0));
            transact(3'd1, 17'd467);
            coherent_calibration = 1;
            repeat (40) @(negedge ref_clk);
            do_calibration(1);
            transact(3'd5, 17'd4);
            if (!status[0]) $fatal(1, "Rejected calibration erased the prior table");
            $display("COHERENT_CAL_REJECTED");
        end

        enable = 0;
        #1;
        if (dco_enable || status[9]) $fatal(1, "Disable did not take effect");
        if (trace_file != 0) $fclose(trace_file);
        $display("PASS ref=%0.1f MHz modeled range=%0.1f..%0.1f MHz", ref_mhz, model_low, model_high);
        $finish;
    end

    initial begin
        #3500000000;
        $fatal(1, "Global simulation timeout");
    end
endmodule
