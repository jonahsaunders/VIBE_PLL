# SPDX-License-Identifier: Apache-2.0
# Initialize a standalone floorplan and optionally run detailed routing.
# The DCO LEF must come from the real DCO layout, including pins and OBS.
foreach name {TECH_LEF CELLS_LEF LIBERTY DCO_LEF MAPPED_VERILOG OUT_DIR} {
    if {![info exists ::env($name)] || $::env($name) eq ""} {
        error "Set $name before running this script"
    }
}
set here [file dirname [file normalize [info script]]]
set out [file normalize $::env(OUT_DIR)]
file mkdir $out

read_lef $::env(TECH_LEF)
read_lef $::env(CELLS_LEF)
read_lef $::env(DCO_LEF)
read_liberty $::env(LIBERTY)
read_verilog $::env(MAPPED_VERILOG)
link_design cpz4_sky130

# The row-packing model uses 400 x 250 um and a 5 um edge reservation.
# Set these coordinates to the allocated wrapper dimensions for integration.
set die {0 0 400 250}
set core {5 5 395 245}
if {[info exists ::env(DIE_AREA)]} { set die $::env(DIE_AREA) }
if {[info exists ::env(CORE_AREA)]} { set core $::env(CORE_AREA) }
initialize_floorplan -site unithd -die_area $die -core_area $core

set block [ord::get_db_block]
# OpenSTA can retain a synthetic constant net even after synthesis mapped
# every sink to a tie cell. Drop only nets with no terminals or routing.
foreach name {zero_ one_} {
    set net [$block findNet $name]
    if {$net ne "NULL" && [llength [$net getITerms]] == 0 &&
        [llength [$net getBTerms]] == 0 && [$net getWire] eq "NULL" &&
        [llength [$net getSWires]] == 0} {
        odb::dbNet_destroy $net
    }
}
set dco [$block findInst oscillator]
if {$dco eq "NULL"} { error "The mapped netlist must instantiate oscillator" }
set master [$dco getMaster]
set dbu [$block getDbUnitsPerMicron]
set halo 4
set max_dco {138 113}
if {[info exists ::env(DCO_HALO_UM)]} { set halo $::env(DCO_HALO_UM) }
if {[info exists ::env(DCO_RESERVE)]} { set max_dco $::env(DCO_RESERVE) }
set width [expr {double([$master getWidth]) / $dbu}]
set height [expr {double([$master getHeight]) / $dbu}]
lassign $max_dco reserve_width reserve_height
if {$width + 2*$halo > $reserve_width || $height + 2*$halo > $reserve_height} {
    error "DCO LEF and halo exceed the reserved rectangle"
}
lassign $core left bottom right top
if {$left + $reserve_width > $right || $bottom + $reserve_height > $top} {
    error "DCO reservation extends outside the core"
}
# Keep routing channels on both sides of the DAC array. Coordinates snap
# to the 5 nm manufacturing grid, with digital sites cut around the halo.
set x [expr {5 * round(($left + $right - $width) * $dbu / 10.0)}]
set y [expr {5 * round(($bottom + ($top - $bottom) / 4.0) * $dbu / 5.0)}]
$dco setLocation $x $y
$dco setPlacementStatus FIRM
set halo_dbu [expr {round($halo * $dbu)}]
set macro_x1 [expr {$x - $halo_dbu}]
set macro_y1 [expr {$y - $halo_dbu}]
set macro_x2 [expr {$x + [$master getWidth] + $halo_dbu}]
set macro_y2 [expr {$y + [$master getHeight] + $halo_dbu}]
if {$macro_x1 < $left*$dbu || $macro_y1 < $bottom*$dbu ||
    $macro_x2 > $right*$dbu || $macro_y2 > $top*$dbu} {
    error "Placed DCO and halo extend outside the core"
}
odb::dbBlockage_create $block \
    $macro_x1 $macro_y1 $macro_x2 $macro_y2

read_sdc [file join $here standalone.sdc]
write_def [file join $out floorplan.def]
set detailed [expr {[info exists ::env(RUN_DETAIL_ROUTE)] && $::env(RUN_DETAIL_ROUTE) eq "1"}]
set global_only [expr {[info exists ::env(RUN_GLOBAL_ROUTE)] && $::env(RUN_GLOBAL_ROUTE) eq "1"}]
if {$detailed || $global_only} {
    # Use the Sky130 HD track grid instead of a generic LEF default.
    make_tracks li1  -x_offset 0.23 -x_pitch 0.46 -y_offset 0.17 -y_pitch 0.34
    make_tracks met1 -x_offset 0.17 -x_pitch 0.34 -y_offset 0.17 -y_pitch 0.34
    make_tracks met2 -x_offset 0.23 -x_pitch 0.46 -y_offset 0.23 -y_pitch 0.46
    make_tracks met3 -x_offset 0.34 -x_pitch 0.68 -y_offset 0.34 -y_pitch 0.68
    make_tracks met4 -x_offset 0.46 -x_pitch 0.92 -y_offset 0.46 -y_pitch 0.92
    make_tracks met5 -x_offset 1.70 -x_pitch 3.40 -y_offset 1.70 -y_pitch 3.40
    if {$detailed} {
        foreach net {VDD_CORE VDD_DCO VSS} {
            if {[$block findNet $net] eq "NULL"} {
                error "Expected top-level supply net $net"
            }
        }
        source [file join $here power.tcl]
        tapcell -distance 14 -halo_width_x $halo -halo_width_y $halo \
            -tapcell_master sky130_fd_sc_hd__tapvpwrvgnd_1
        connect_dco_supply $block $dco $dbu
    }
    place_pins -hor_layers met3 -ver_layers met2
    set_routing_layers -signal met1-met5 -clock met3-met5
    # Reserve track capacity around the standard-cell pins and power rails.
    set_global_routing_layer_adjustment met1-met5 0.2
    set density 0.50
    if {[info exists ::env(PLACE_DENSITY)]} { set density $::env(PLACE_DENSITY) }
    global_placement -routability_driven -density $density
    detailed_placement
    check_placement -verbose
    if {$detailed} {
        if {[info exists ::env(SKY130_SET_RC)]} { source $::env(SKY130_SET_RC) }
        global_connect
        pdngen
        connect_dco_ground $block $dco
        write_def [file join $out power.def]
        clock_tree_synthesis -root_buf sky130_fd_sc_hd__clkbuf_4 \
            -buf_list {sky130_fd_sc_hd__clkbuf_2 sky130_fd_sc_hd__clkbuf_4}
        set_propagated_clock [all_clocks]
        detailed_placement
    }
    write_def [file join $out before-route.def]
    set route_args [list -guide_file [file join $out pll.guide] \
        -congestion_report_file [file join $out congestion.rpt] -verbose]
    if {$detailed} { lappend route_args -allow_congestion }
    global_route {*}$route_args
    write_def [file join $out placed.def]
    report_checks -path_delay min_max -group_path_count 5
    source [file join $here capture_paths.tcl]
    if {$detailed} {
        if {![file exists [file join $out congestion.rpt]] ||
            [file size [file join $out congestion.rpt]] == 0} {
            repair_antennas sky130_fd_sc_hd__diode_2
        }
        detailed_placement
        global_connect
        set detail_args [list -output_drc [file join $out route-drc.rpt] \
            -drc_report_iter_step 8]
        if {[info exists ::env(DETAIL_ROUTE_ITERATIONS)]} {
            lappend detail_args -droute_end_iter $::env(DETAIL_ROUTE_ITERATIONS)
        }
        detailed_route {*}$detail_args
        set route_violations [detailed_route_num_drvs]
        filler_placement {
            sky130_fd_sc_hd__fill_8 sky130_fd_sc_hd__fill_4
            sky130_fd_sc_hd__fill_2 sky130_fd_sc_hd__fill_1
        }
        global_connect
        set count [open [file join $out route-violations.txt] w]
        puts $count $route_violations
        close $count
        puts "Detailed route DRC violations: $route_violations"
        write_def [file join $out routed.def]
        write_db [file join $out routed.odb]
        write_verilog [file join $out routed.v]
        set connected [design_is_routed -verbose]
        set antenna [check_antennas -report_file [file join $out antenna.rpt]]
        set report [open [file join $out route-checks.txt] w]
        puts $report "All signal nets routed: $connected"
        puts $report "Antenna-violating nets: $antenna"
        close $report
        set grid_ok 1
        foreach net {VDD_CORE VDD_DCO VSS} {
            if {[catch {check_power_grid -net $net} reason]} {
                puts "Power-grid check failed for $net ($reason)"
                set grid_ok 0
            }
        }
        set report [open [file join $out route-checks.txt] a]
        puts $report "Power grids connected: $grid_ok"
        close $report
        if {[info exists ::env(RCX_RULES)]} {
            define_process_corner -ext_model_index 0 sky130_tt
            extract_parasitics -ext_model_file $::env(RCX_RULES)
            set spef [file join $out routed.spef]
            write_spef $spef
            read_spef $spef
        } else {
            estimate_parasitics -global_routing
        }
        report_checks -path_delay min_max -group_path_count 10
        report_worst_slack -max
        report_worst_slack -min
        report_tns
        source [file join $here capture_paths.tcl]
        if {!$connected || !$grid_ok || $route_violations != 0 || $antenna != 0} {
            error "Standalone connectivity, routing, or antenna checks failed"
        }
    }
}
