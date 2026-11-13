# Sky130 physical implementation

## Oscillator macro

The standalone DCO occupies **130 × 105 µm** and implements the 406-port,
870-device [schematic](../spice/cpz4_dco.spice). Its GDS, LEF and flat LVS
reference are generated from the same netlist. The LEF uses Verilog bus names
and the LVS reference retains the schematic's underscore-indexed pin names.
The DCO and digital logic have separate 1.8 V supplies with a common ground.

```sh
python3 -m pip install klayout==0.30.13
python3 physical/layout_dco.py --output build/standalone
python3 physical/check_dco.py --pdk "$PDK_ROOT/sky130A" --build build/standalone
```

The KLayout check uses open_pdks Sky130A revision
fa87f8f4bbcc7255b6f0c0fb506960f531ae2392. The wrapper normalizes the LVS
reader's casing and preserves the explicit resistor and capacitor parameters.
The layout passes the deck's enabled front-end, back-end and grid checks and
matches the 870-device schematic. The DCO netlist extracted for LVS oscillated
at 254.044 MHz at TT, 1.8 V, 25 °C, coarse code 52 and fine code 64 using the
schematic bench loads. That simulation includes extracted device geometry and
omits interconnect parasitics.

To run the capacitance-extracted bench, run Magic in the directory that
contains cpz4_dco.gds, with PDK_ROOT set to the installed PDK parent.

```sh
root=$(pwd)
( cd build/standalone &&
  magic -dnull -noconsole -rcfile "$PDK_ROOT/sky130A/libs.tech/magic/sky130A.magicrc" \
    "$root/physical/extract_dco.tcl" )
python3 spice/dco_deck.py --lib "$PDK_ROOT/sky130A/libs.tech/ngspice/sky130.lib.spice" \
  --netlist build/standalone/cpz4_dco_pex.spice --codes 52 --fine-codes 64
```

## Standalone routing

The provisional die is **400 × 250 µm**. A 4 µm placement halo around
the DCO occupies a **138 × 113 µm** reservation. The source floorplan uses a
5 µm outer margin. The matched Sky130 HD library, the real DCO abstract
and the existing PLL constraints are the inputs to OpenROAD.

```sh
export ORFS_SKY130HD=/path/to/OpenROAD-flow-scripts/flow/platforms/sky130hd
export SKY130A="$PDK_ROOT/sky130A"
bash physical/run_standalone.sh build/standalone
```

The [Linux workflow](../.github/workflows/standalone-route.yml) pins the
OpenROAD image and publishes the build outputs for review. OpenROAD reads
the mapped controller, places the DCO, inserts substrate taps and
standard-cell power rails, builds the clock trees and runs signal routing.
The stream-out script combines the routed DEF with the standard-cell and DCO
GDS views. Set RCX_RULES to use an external RCX rule file.

The row-area check measures the mapped cells before tap cells, tie fanout
repair and clock tree synthesis. Review routed timing, CDC and tap loading
against [standalone.sdc](standalone.sdc) and the
[load sensitivity results](../results/rev3.md).

## Harness integration

Use the official Chipalooza #4 slot outline, supply connections and approved
pad cells for wrapper integration. The core operates at 1.8 V. The proposed
dedicated reference and monitor pads use the approved 3.3 V peripheral cells.
Foundry handoff requires the integrated wrapper and its DRC, LVS, antenna,
density, power and timing results, plus extracted oscillator operating-range
and phase-noise verification.
