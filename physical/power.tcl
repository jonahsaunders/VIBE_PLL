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

# Stitch the DCO's ground into the core grid at its dedicated met5 landing.
set core_bottom [expr {double([[$block getCoreArea] yMin]) / $dbu}]
set dco_vss_y [expr {double($y) / $dbu + 83.53}]
add_pdn_stripe -grid core -layer met5 -width 1.6 -pitch 240 \
    -offset [expr {$dco_vss_y - $core_bottom}] -nets {VSS} -extend_to_boundary

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
