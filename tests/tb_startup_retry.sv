// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps

module tb_startup_retry;
    reg clk = 0, reset_n = 1;
    reg [23:0] phase = 0;
    reg warmed = 0;
    wire [7:0] coarse;
    wire [2:0] fault;

    always #20 clk = ~clk;
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) phase <= 0;
        else phase <= phase + (warmed ? 24'd16384 : 24'd4096);
    end

    cpz4_loop_control dut(.ref_clk(clk), .reset_n(reset_n), .restart(1'b0), .ref_timeout(1'b0),
        .manual(1'b0), .dither_enable(1'b1), .narrow_near_integer(1'b0), .manual_code(8'd0),
        .code_ceiling(8'd96), .ref_upper_mhz(6'd25), .tracking_gear(2'd2), .ratio_q12(17'd41984),
        .phase_valid(1'b1), .phase_q12(phase), .dco_code(coarse), .fine_code(), .locked(),
        .fault_code(fault), .gain_q12(), .state());

    initial begin
        #1 reset_n = 0;
        @(negedge clk);
        reset_n = 1;
        repeat (80) @(negedge clk);
        if (coarse !== 0 || fault !== 0) $fatal(1, "Slow startup raised the code or faulted prematurely");
        warmed = 1;
        repeat (30) @(negedge clk);
        if (coarse === 0 || fault !== 0) $fatal(1, "Bias recovery did not resume acquisition");
        reset_n = 0;
        warmed = 0;
        @(negedge clk);
        reset_n = 1;
        repeat (150) @(negedge clk);
        if (coarse !== 0 || fault !== 7) $fatal(1, "Persistent low frequency did not report a startup stall");
        $display("PASS bounded startup retries");
        $finish;
    end
endmodule
