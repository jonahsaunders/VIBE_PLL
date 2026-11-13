# SPDX-License-Identifier: Apache-2.0
# Initialize a standalone floorplan and optionally run placement/global routing.
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
set dco [$block findInst oscillator]
if {$dco eq "NULL"} { error "The mapped netlist must instantiate oscillator" }
set master [$dco getMaster]
set dbu [$block getDbUnitsPerMicron]
set halo 5
set max_dco {100 100}
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
set x [expr {round(($left + $halo) * $dbu)}]
set y [expr {round(($bottom + $halo) * $dbu)}]
$dco setLocation $x $y
$dco setPlacementStatus FIRM
odb::dbBlockage_create $block \
    [expr {round($left*$dbu)}] [expr {round($bottom*$dbu)}] \
    [expr {round(($left+$reserve_width)*$dbu)}] [expr {round(($bottom+$reserve_height)*$dbu)}]

read_sdc [file join $here standalone.sdc]
write_def [file join $out floorplan.def]
if {[info exists ::env(RUN_GLOBAL_ROUTE)] && $::env(RUN_GLOBAL_ROUTE) eq "1"} {
    # Use the Sky130 HD track grid instead of a generic LEF default.
    make_tracks li1  -x_offset 0.23 -x_pitch 0.46 -y_offset 0.17 -y_pitch 0.34
    make_tracks met1 -x_offset 0.17 -x_pitch 0.34 -y_offset 0.17 -y_pitch 0.34
    make_tracks met2 -x_offset 0.23 -x_pitch 0.46 -y_offset 0.23 -y_pitch 0.46
    make_tracks met3 -x_offset 0.34 -x_pitch 0.68 -y_offset 0.34 -y_pitch 0.68
    make_tracks met4 -x_offset 0.46 -x_pitch 0.92 -y_offset 0.46 -y_pitch 0.92
    make_tracks met5 -x_offset 1.70 -x_pitch 3.40 -y_offset 1.70 -y_pitch 3.40
    place_pins -hor_layers met3 -ver_layers met2
    global_placement -density 0.65
    detailed_placement
    check_placement -verbose
    set_routing_layers -signal met1-met5
    global_route -guide_file [file join $out pll.guide]
    write_def [file join $out placed.def]
    report_checks -path_delay min_max -group_path_count 5
}
