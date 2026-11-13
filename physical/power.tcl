# SPDX-License-Identifier: Apache-2.0
# Keep the ring oscillator's supply separate from the standard-cell grid.
add_global_connection -net VDD_CORE -pin_pattern {^(VPWR|VPB)$} -power
add_global_connection -net VSS -pin_pattern {^(VGND|VNB)$} -ground
add_global_connection -net VDD_DCO -inst_pattern {^oscillator$} -pin_pattern {^vdd$} -power
add_global_connection -net VSS -inst_pattern {^oscillator$} -pin_pattern {^vss$} -ground
global_connect

set_voltage_domain -name CORE -power VDD_CORE -ground VSS -secondary_power VDD_DCO
define_pdn_grid -name core -voltage_domains CORE -pins {met5}
add_pdn_stripe -grid core -layer met1 -width 0.48 -pitch 5.44 -offset 0 \
    -followpins -nets {VDD_CORE VSS}
add_pdn_stripe -grid core -layer met4 -width 1.6 -pitch 40 -offset 13.57 \
    -nets {VDD_CORE VSS}
add_pdn_stripe -grid core -layer met5 -width 1.6 -pitch 40 -offset 13.60 \
    -nets {VDD_CORE VSS}
add_pdn_connect -grid core -layers {met1 met4}
add_pdn_connect -grid core -layers {met4 met5}

# The DCO rail stays on met5 at its dedicated pin elevation. It has no
# met4 connection to the core grid. The DCO's ground is stitched separately.
set core_bottom [expr {double([[$block getCoreArea] yMin]) / $dbu}]
set dco_vdd_y [expr {double($y) / $dbu + 104.15}]
set dco_vss_y [expr {double($y) / $dbu + 83.53}]
add_pdn_stripe -grid core -layer met5 -width 1.6 -pitch 240 \
    -offset [expr {$dco_vdd_y - $core_bottom}] -nets {VDD_DCO} -extend_to_boundary
add_pdn_stripe -grid core -layer met5 -width 1.6 -pitch 240 \
    -offset [expr {$dco_vss_y - $core_bottom}] -nets {VSS} -extend_to_boundary
