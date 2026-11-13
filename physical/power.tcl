# SPDX-License-Identifier: Apache-2.0
# Keep the ring oscillator's supply separate from the standard-cell grid.
add_global_connection -net VDD_CORE -pin_pattern {^(VPWR|VPB)$} -power
add_global_connection -net VSS -pin_pattern {^(VGND|VNB)$} -ground
add_global_connection -net VDD_DCO -inst_pattern {^oscillator$} -pin_pattern {^vdd$} -power
add_global_connection -net VSS -inst_pattern {^oscillator$} -pin_pattern {^vss$} -ground
global_connect
foreach {pin supply} {vdd VDD_DCO vss VSS} {
    set iterm [$dco findITerm $pin]
    if {[$iterm getNet] ne [$block findNet $supply]} {
        error "Oscillator $pin must be connected to $supply"
    }
    $iterm setSpecial
}

set_voltage_domain -name CORE -power VDD_CORE -ground VSS
define_pdn_grid -name core -voltage_domains CORE -pins {met5}
add_pdn_stripe -grid core -layer met1 -width 0.48 -pitch 5.44 -offset 0 \
    -followpins -nets {VDD_CORE VSS}
add_pdn_stripe -grid core -layer met4 -width 1.6 -pitch 40 -offset 13.57 \
    -nets {VDD_CORE VSS}
add_pdn_stripe -grid core -layer met5 -width 1.6 -pitch 40 -offset 13.60 \
    -nets {VDD_CORE VSS}
add_pdn_connect -grid core -layers {met1 met4}
add_pdn_connect -grid core -layers {met4 met5}

proc connect_dco_supply {block dco dbu} {
    # The separate analog supply has one macro terminal and one boundary
    # terminal. Keep the dedicated route on met5, with no vias to the core.
    set terminal [$dco findITerm vdd]
    set pin [$terminal getBBox]
    set net [$terminal getNet]
    set layer [[[$block getDataBase] getTech] findLayer met5]
    set x1 [expr {([$pin xMin] + [$pin xMax]) / 2}]
    set x2 [[$block getDieArea] xMax]
    set y1 [$pin yMin]
    set y2 [$pin yMax]
    $net setSpecial
    set wire [odb::dbSWire_create $net ROUTED]
    odb::dbSBox_create $wire $layer $x1 $y1 $x2 $y2 STRIPE
    set bpin [odb::dbBPin_create [$block findBTerm VDD_DCO]]
    $bpin setPlacementStatus FIRM
    odb::dbBox_create $bpin $layer [expr {$x2 - round(3.4 * $dbu)}] $y1 $x2 $y2
}

proc connect_dco_ground {block dco} {
    # The generated grid cannot extend a stripe through the macro outline.
    # Extend an existing VSS met4 stripe on the left to the DCO's met5 pin.
    set terminal [$dco findITerm vss]
    set pin [$terminal getBBox]
    set net [$terminal getNet]
    set tech [[$block getDataBase] getTech]
    set met4 [$tech findLayer met4]
    set met5 [$tech findLayer met5]
    set chosen NULL
    set right_edge 0
    set center_y [expr {([$pin yMin] + [$pin yMax]) / 2}]
    foreach wire [$net getSWires] {
        foreach box [$wire getWires] {
            if {![$box isVia] && [$box getTechLayer] eq $met4 &&
                [$box yMin] < [$pin yMin] && [$box yMax] > [$pin yMax] &&
                [$box xMax] < [$pin xMin] && [$box xMax] > $right_edge} {
                set right_edge [$box xMax]
                set chosen $box
                set stripe $wire
            }
        }
    }
    if {$chosen eq "NULL"} { error "No nearby VSS met4 stripe reaches the DCO ground pin" }
    set center_x [expr {([$chosen xMin] + $right_edge) / 2}]
    set end_x [expr {([$pin xMin] + [$pin xMax]) / 2}]
    set start_x [expr {$center_x - ([$pin yMax] - [$pin yMin]) / 2}]
    odb::dbSBox_create $stripe $met5 $start_x [$pin yMin] $end_x [$pin yMax] STRIPE
    odb::dbSBox_create $stripe [$tech findVia M4M5_PR] $center_x $center_y STRIPE
}
