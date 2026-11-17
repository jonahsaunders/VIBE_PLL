# SPDX-License-Identifier: Apache-2.0
# Standalone timing constraints. Supply DCO_PERIOD_NS from the characterized
# maximum acquisition frequency. The default is the 400 MHz guard limit.
set ref_period 31.25
set dco_period 2.5
if {[info exists ::env(DCO_PERIOD_NS)]} {
    set dco_period $::env(DCO_PERIOD_NS)
}
set dco_high [expr {$dco_period * 0.5}]
if {[info exists ::env(DCO_HIGH_NS)]} {
    set dco_high $::env(DCO_HIGH_NS)
}
if {$dco_high <= 0 || $dco_high >= $dco_period} {
    error {DCO_HIGH_NS must be between zero and DCO_PERIOD_NS}
}
create_clock -name ref_clk -period $ref_period [get_ports ref_clk]
set oscillator [get_cells -quiet oscillator]
if {[llength $oscillator] != 1} { error {Expected one oscillator instance} }
set phase_sources [get_pins -quiet -of_objects $oscillator -filter {direction==output}]
if {[llength $phase_sources] != 20} { error {Expected 20 oscillator phase output pins} }
set tap0 {}
foreach pin $phase_sources {
    if {[regexp {/tap\[0\]$} [get_full_name $pin]]} { lappend tap0 $pin }
}
if {[llength $tap0] != 1} { error {Expected one oscillator tap[0] pin} }
create_clock -name dco_clk -period $dco_period -waveform [list 0 $dco_high] $tap0

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

# Locate the first-stage D pins by their Q nets. The launch Gray nets
# can feed DCO-domain logic as well as the reference capture chain.
proc cpz4_capture_flop_inputs {nets count} {
    if {[llength $nets] != $count} { error "Expected $count first-stage nets" }
    set inputs [dict create]
    foreach net $nets {
        set name [get_full_name $net]
        set q [get_pins -quiet -of_objects $net -filter {direction==output}]
        if {[llength $q] != 1} { error "Expected one first-stage flop on $name" }
        set cell [get_cells -quiet -of_objects $q]
        set data {}
        foreach pin [get_pins -quiet -of_objects $cell -filter {direction==input}] {
            if {[regexp {/D$} [get_full_name $pin]]} { lappend data $pin }
        }
        if {[llength $data] != 1} { error "Expected one capture D pin on $name" }
        dict set inputs $name [lindex $data 0]
    }
    return $inputs
}

set gray_nets [get_nets -quiet -regexp {^controller\.sampler\.(pos_meta|neg_meta)\[[0-9]+\]$}]
set cpz4_gray_capture [cpz4_capture_flop_inputs $gray_nets 24]

set_max_delay -ignore_clock_latency 1.0 -from [get_clocks dco_clk] -to [dict values $cpz4_gray_capture]
set_false_path -hold -from [get_clocks dco_clk] -to [dict values $cpz4_gray_capture]

# Phase taps are analog macro outputs. Constrain their route from the pin
# to the receiver separately from the clocked Gray launch path.
set phase_nets [get_nets -quiet -regexp {^controller\.sampler\.(tap_meta|fine_meta)\[[0-9]+\]$}]
set cpz4_phase_capture [cpz4_capture_flop_inputs $phase_nets 20]
set_max_delay -ignore_clock_latency 1.0 -from $phase_sources -to [dict values $cpz4_phase_capture]
set_false_path -hold -through $phase_sources -to [dict values $cpz4_phase_capture]

# Apply the same endpoint discipline to the one-bit crossings.
foreach {pattern count source budget} {
    {^controller\.sampler\.ready_pipe\[0\]$} 1 dco_clk 1.0
    {^controller\.watchdog\.trip_pipe\[0\]$} 1 dco_div2 1.0
    {^controller\.watchdog\.(beat_pipe|ack_pipe)\[0\]$} 2 ref_clk 2.0
} {
    set inputs [cpz4_capture_flop_inputs [get_nets -quiet -regexp $pattern] $count]
    set_max_delay -ignore_clock_latency $budget -from [get_clocks $source] -to [dict values $inputs]
    set_false_path -hold -from [get_clocks $source] -to [dict values $inputs]
}
set_clock_uncertainty 0.1 [get_clocks {dco_clk dco_div2 dco_div4}]
set_clock_uncertainty 0.2 [get_clocks ref_clk]

# run_reset is asynchronous to the oscillator. Only the reset inputs of
# its two release synchronizer stages may deassert asynchronously. Time
# the synchronizer data path and every downstream recovery/removal check.
set release_nets [get_nets -regexp {^controller\.oscillator_reset\.release_pipe\[[01]\]$}]
set release_data [cpz4_capture_flop_inputs $release_nets 2]
foreach pin [dict values $release_data] {
    set reset_pin [get_pins -of_objects [get_cells -of_objects $pin] -filter {name==RESET_B}]
    if {[llength $reset_pin] != 1} { error "Missing oscillator release reset pin on $pin" }
    set_false_path -from [get_clocks ref_clk] -to $reset_pin
}
