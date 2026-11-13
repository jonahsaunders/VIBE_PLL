# SPDX-License-Identifier: Apache-2.0
# Standalone timing constraints. Supply DCO_PERIOD_NS from the characterized
# maximum acquisition frequency. The default is the 400 MHz guard limit.
set ref_period 31.25
set dco_period 2.5
if {[info exists ::env(DCO_PERIOD_NS)]} {
    set dco_period $::env(DCO_PERIOD_NS)
}
create_clock -name ref_clk -period $ref_period [get_ports ref_clk]
set tap0 [get_pins -quiet -regexp {^oscillator/tap\[0\]$}]
if {[llength $tap0] != 1} { error {Expected one oscillator tap[0] pin} }
create_clock -name dco_clk -period $dco_period $tap0

# Locate the two registered divider outputs by their connected nets.
foreach {net_name clock_name divide} {
    {^controller\.clk_div2$|^controller\.sampler\.positive_counter\.binary\[0\]$} dco_div2 2
    {^clk_mon$|^controller\.sampler\.positive_counter\.binary\[1\]$} dco_div4 4
} {
    set nets [get_nets -quiet -regexp $net_name]
    if {[llength $nets] == 0} { error "Could not find the $clock_name divider net" }
    set outputs [lsort -unique [get_pins -of_objects $nets -filter {direction==output}]]
    if {[llength $outputs] != 1} { error "Expected one driver for $clock_name" }
    create_generated_clock -name $clock_name -source $tap0 \
        -divide_by $divide $outputs
}

# Inter-domain paths terminate at explicit two-stage capture chains. Keep
# their routing short while the physical skew and aperture are reviewed.
set_max_delay -ignore_clock_latency 1.0 -from [get_clocks {dco_clk dco_div2}] -to [get_clocks ref_clk]
set_max_delay -ignore_clock_latency 2.0 -from [get_clocks ref_clk] -to [get_clocks dco_div2]
set_false_path -hold -from [get_clocks {dco_clk dco_div2}] -to [get_clocks ref_clk]
set_false_path -hold -from [get_clocks ref_clk] -to [get_clocks dco_div2]
set_clock_uncertainty 0.1 [get_clocks {dco_clk dco_div2 dco_div4}]
set_clock_uncertainty 0.2 [get_clocks ref_clk]
