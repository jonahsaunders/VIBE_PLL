# SPDX-License-Identifier: Apache-2.0
# Run in the build directory with the Sky130A technology already loaded.
gds read cpz4_dco.gds
load cpz4_dco
select top cell
extract all
ext2spice lvs
ext2spice subcircuit on
ext2spice scale off
ext2spice cthresh 0
ext2spice rthresh infinite
ext2spice -o cpz4_dco_pex.spice
quit -noprompt
