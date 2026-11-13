# SPDX-License-Identifier: Apache-2.0
# Source after reading standalone.sdc and the timing data for the chosen corner.
# Full clock paths expose launch latency and reference arrival for aperture review.
proc cpz4_report_capture_arcs {pin} {
    if {[llength [info commands sta::report_edges]]} {
        sta::report_edges -to $pin -digits 4
    }
}

dict for {net pin} $cpz4_gray_capture {
    puts "Gray capture $net"
    report_checks -from [get_clocks dco_clk] -to $pin -path_delay max \
        -endpoint_path_count 2 -format full_clock_expanded -digits 4
    cpz4_report_capture_arcs $pin
}
dict for {net pin} $cpz4_phase_capture {
    puts "Phase capture $net"
    report_checks -from $phase_sources -to $pin -path_delay max \
        -endpoint_path_count 2 -format full_clock_expanded -digits 4
    cpz4_report_capture_arcs $pin
}
