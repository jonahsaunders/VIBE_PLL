// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps

module tb_edge_counter;
    localparam [11:0] OTHER_SEED = 12'h42f;
    reg clk = 0;
    reg reset_n = 1;
    wire [11:0] rising_count, rising_gray, falling_count, falling_gray, other_count, other_gray;
    cpz4_edge_counter rising(clk, reset_n, rising_count, rising_gray);
    cpz4_edge_counter #(.SEED(12'hfff)) falling(~clk, reset_n, falling_count, falling_gray);
    cpz4_edge_counter #(.SEED(OTHER_SEED)) other(clk, reset_n, other_count, other_gray);
    always #1 clk = ~clk;

    task automatic check_count(input [11:0] count, code, expected);
        if (count !== expected || code !== (expected ^ (expected >> 1)))
            $fatal(1, "Count or Gray mismatch: count=%h gray=%h expected count=%h", count, code, expected);
    endtask

    integer tick;
    initial begin
        #0.2 reset_n = 0;
        #0.3;
        check_count(rising_count, rising_gray, 12'd0);
        check_count(falling_count, falling_gray, 12'hfff);
        check_count(other_count, other_gray, OTHER_SEED);
        reset_n = 1;
        for (tick = 1; tick <= 8192; tick = tick + 1) begin
            @(negedge clk);
            #0.001;
            check_count(rising_count, rising_gray, 12'(tick));
            check_count(falling_count, falling_gray, 12'(tick - 1));
            check_count(other_count, other_gray, OTHER_SEED + 12'(tick));
        end
        $display("PASS Gray counters: three seeds across two wraps");
        $finish;
    end
endmodule
