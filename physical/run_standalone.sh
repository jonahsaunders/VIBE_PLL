#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
destination=${1:-$root/build/standalone}
mkdir -p "$destination"
build=$(cd "$destination" && pwd)
rm -f "$build/routed.def" "$build/routed.odb" "$build/routed.v" \
    "$build/routed.spef" "$build/route-violations.txt" "$build/route-checks.txt" \
    "$build/congestion.rpt" "$build/cpz4_sky130.gds" "$build/cpz4_sky130-review.gds" \
    "$build/physical-verification.json"
platform=${ORFS_SKY130HD:-/OpenROAD-flow-scripts/flow/platforms/sky130hd}
python=${PYTHON:-python3}
klayout=${KLAYOUT:-klayout}
openroad=${OPENROAD:-openroad}
: "${SKY130A:?Set SKY130A to the installed open_pdks sky130A directory}"
export TECH_LEF="$platform/lef/sky130_fd_sc_hd.tlef"
export CELLS_LEF="$platform/lef/sky130_fd_sc_hd_merged.lef"
export LIBERTY="$platform/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
export SKY130_SET_RC="$platform/setRC.tcl"
export DCO_LEF="$build/cpz4_dco.lef"
export MAPPED_VERILOG="$build/cpz4_sky130.v"
export OUT_DIR="$build"
export RUN_DETAIL_ROUTE=1
export TRACKING_REPLICAS=${TRACKING_REPLICAS:-1}
export DIE_AREA=${DIE_AREA:-"0 0 600 400"}
export CORE_AREA=${CORE_AREA:-"5 5 595 395"}
export DCO_RESERVE=${DCO_RESERVE:-"298 123"}
if [[ -z ${RCX_RULES:-} && -r "$platform/rcx_patterns.rules" ]]; then
    export RCX_RULES="$platform/rcx_patterns.rules"
fi
replica_args=()
map_args=(--max-coarse-code "${MAX_COARSE_CODE:-255}")
case "$TRACKING_REPLICAS" in
    1) replica_args+=(--tracking-replicas); map_args+=(--tracking-replicas) ;;
    0) ;;
    *) echo "TRACKING_REPLICAS must be 0 or 1" >&2; exit 2 ;;
esac
case "${ON_CHIP_CAL:-0}" in
    1) map_args+=(--on-chip-cal) ;;
    0) ;;
    *) echo "ON_CHIP_CAL must be 0 or 1" >&2; exit 2 ;;
esac
"$python" "$root/spice/dco_deck.py" "${replica_args[@]}" --emit "$build/dco-source.spice"
"$python" "$root/physical/layout_dco.py" --schematic "$build/dco-source.spice" --output "$build"
"$python" "$root/physical/check_dco.py" --klayout "$klayout" --pdk "$SKY130A" --build "$build"
read -r die_width die_height < <("$python" -c \
    'import os; a=list(map(float,os.environ["DIE_AREA"].split())); print(a[2]-a[0],a[3]-a[1])')
read -r reserve_width reserve_height <<< "$DCO_RESERVE"
"$python" "$root/tests/check_slot.py" --liberty "$LIBERTY" --lef "$CELLS_LEF" \
    --slot "$die_width" "$die_height" --dco-reserve "$reserve_width" "$reserve_height" \
    --edge-reserve 5 --utilization 0.65 "${map_args[@]}" \
    --mapped-netlist "$MAPPED_VERILOG" | tee "$build/area.log"
route_status=0
"$openroad" -threads 4 -exit "$root/physical/floorplan.tcl" 2>&1 | tee "$build/openroad.log" || route_status=$?
if [[ ! -s "$build/routed.def" || ! -s "$build/routed.odb" ]]; then
    echo "Detailed routing did not produce a layout" >&2
    exit 1
fi
"$python" "$root/physical/stream_layout.py" \
    --technology "$platform/sky130hd.lyt" --def "$build/routed.def" \
    --lef "$TECH_LEF" "$CELLS_LEF" "$DCO_LEF" \
    --gds "$platform/gds/sky130_fd_sc_hd.gds" "$build/cpz4_dco.gds" \
    --output "$build/cpz4_sky130-review.gds"
"$openroad" -exit -python "$root/physical/export_lvs.py"
"$python" "$root/physical/check_layout.py" --klayout "$klayout" --pdk "$SKY130A" --build "$build" \
    --route-exit-code "$route_status"
exit "$route_status"
