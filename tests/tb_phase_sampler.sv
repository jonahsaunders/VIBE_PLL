// SPDX-License-Identifier: Apache-2.0
`timescale 1ps/1fs

module tb_phase_sampler;
    reg ref_clk = 0, ref_reset_n = 1, dco_reset_n = 0;
    reg [4:0] tap = 0;
    wire [3:0] bin_index;
    wire valid;
    wire [11:0] cycle_count;
    reg [11:0] positive_gray, negative_gray;

    cpz4_phase_sampler dut(.ref_clk(ref_clk), .ref_reset_n(ref_reset_n), .tap(tap),
        .fine_tap(15'd0), .dco_reset_n(dco_reset_n), .dco_div2(), .dco_div4(),
        .bin_index(bin_index), .fine_bin(), .fine_valid(), .valid(valid), .cycle_count(cycle_count));
    always #5000 ref_clk = ~ref_clk;

    function automatic [11:0] gray(input [11:0] count);
        return count ^ (count >> 1);
    endfunction

    task automatic sample(input [4:0] taps, input [11:0] positive, input [11:0] negative,
                          input [3:0] expected_bin, input expected_valid, input [11:0] expected_count);
        @(negedge ref_clk);
        tap = taps;
        positive_gray = gray(positive);
        negative_gray = gray(negative);
        repeat (2) @(negedge ref_clk);
        if (bin_index !== expected_bin || valid !== expected_valid ||
            (expected_valid && cycle_count !== expected_count))
            $fatal(1, "Incorrect phase sample: bin=%0d valid=%0d count=%0d", bin_index, valid, cycle_count);
    endtask

    initial begin
        #1 ref_reset_n = 0;
        #1 ref_reset_n = 1;
        dco_reset_n = 1;
        force dut.pos_gray = positive_gray;
        force dut.neg_gray = negative_gray;
        // A stale rising count is permitted next to the rising tap edge.
        sample(5'h0b, 12'hfff, 12'hfff, 4'd0, 1, 0);
        sample(5'h0d, 0, 12'hfff, 4'd2, 1, 0);
        sample(5'h0d, 0, 0, 4'd2, 0, 0);
        sample(5'h0d, 1, 12'hfff, 4'd2, 0, 0);
        sample(5'h05, 0, 12'hfff, 4'd3, 1, 0);
        // The falling tap edge can be sampled with the old falling count.
        sample(5'h14, 0, 12'hfff, 4'd5, 1, 0);
        sample(5'h12, 0, 0, 4'd7, 1, 0);
        sample(5'h12, 12'hfff, 0, 4'd7, 0, 0);
        sample(5'h12, 12'hfff, 12'hfff, 4'd7, 1, 12'hfff);
        $display("PASS phase sampler: count wrap, one-cycle slips, edge ambiguity");
        $finish;
    end
endmodule
