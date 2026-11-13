#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
destination=${1:-$root/build/standalone}
mkdir -p "$destination"
build=$(cd "$destination" && pwd)
# Discard prior route outputs so a failed run cannot stream stale geometry.
rm -f "$build/routed.def" "$build/routed.odb" "$build/routed.v" \
    "$build/routed.spef" "$build/route-violations.txt" "$build/route-checks.txt" \
    "$build/congestion.rpt" "$build/cpz4_sky130.gds" "$build/cpz4_sky130-review.gds"
platform=${ORFS_SKY130HD:-/OpenROAD-flow-scripts/flow/platforms/sky130hd}
python=${PYTHON:-python3}
klayout=${KLAYOUT:-klayout}
openroad=${OPENROAD:-openroad}

export TECH_LEF="$platform/lef/sky130_fd_sc_hd.tlef"
export CELLS_LEF="$platform/lef/sky130_fd_sc_hd_merged.lef"
export LIBERTY="$platform/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
export SKY130_SET_RC="$platform/setRC.tcl"
export DCO_LEF="$build/cpz4_dco.lef"
export MAPPED_VERILOG="$build/cpz4_sky130.v"
export OUT_DIR="$build"
export RUN_DETAIL_ROUTE=1
if [[ -z ${RCX_RULES:-} && -r "$platform/rcx_patterns.rules" ]]; then
    export RCX_RULES="$platform/rcx_patterns.rules"
fi

"$python" "$root/physical/layout_dco.py" --output "$build"
if [[ -n "${SKY130A:-}" ]]; then
    "$python" "$root/physical/check_dco.py" --klayout "$klayout" --pdk "$SKY130A" --build "$build"
fi
"$python" "$root/tests/check_slot.py" --liberty "$LIBERTY" --lef "$CELLS_LEF" \
    --slot 400 250 --dco-reserve 138 113 --edge-reserve 5 --utilization 0.65 \
    --mapped-netlist "$MAPPED_VERILOG" | tee "$build/area.log"
route_status=0
"$openroad" -threads 4 -exit "$root/physical/floorplan.tcl" 2>&1 | tee "$build/openroad.log" || route_status=$?
if [[ ! -s "$build/routed.def" || ! -s "$build/routed.odb" ]]; then
    echo "Detailed routing did not produce a layout" >&2
    exit 1
fi
output=cpz4_sky130.gds
if (( route_status )); then
    output=cpz4_sky130-review.gds
fi
"$python" "$root/physical/stream_layout.py" \
    --technology "$platform/sky130hd.lyt" --def "$build/routed.def" \
    --lef "$TECH_LEF" "$CELLS_LEF" "$DCO_LEF" \
    --gds "$platform/gds/sky130_fd_sc_hd.gds" "$build/cpz4_dco.gds" \
    --output "$build/$output"
exit "$route_status"
