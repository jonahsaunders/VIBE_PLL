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
matches the 870-device schematic. The layout uses a folded stage order to
shorten the ring interconnect and distributes the DAC input pins across the
upper routing layers. The CI extraction includes capacitance and uses the
original schematic bench loads. See the measured operating points below.

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
GDS views. The script uses the platform's RCX rules when available.
Set RCX_RULES to supply a different rule file.

The Linux build maps 5,992 cells and occupies 49,977.93 µm². It uses 64.49%
of the 77,494.32 µm² of digital rows in the planning model. The row-area
check measures the mapped cells before tap insertion and clock tree synthesis.
The mapped controller uses fixed phase centers. Refer to
[standalone.sdc](standalone.sdc) and the [load sensitivity results](../results/rev3.md)
when reviewing timing, CDC and tap loading.

## Physical verification

The checked-in oscillator layout uses a folded ring. The folding reduced
the largest extracted ring-node interconnect capacitance from 40.48 fF to
19.65 fF in the matched extraction experiment. That comparison uses the
same transistor schematic and five explicit MIM capacitors.

The oscillator passed both the enabled KLayout geometry checks and Magic
`drc(full)` with zero markers. KLayout LVS matched the schematic. The GDS
from Linux and Windows has the same SHA-256,
`ead7d89d68cd50b798ee1402250d4c88fe9066a37403a813827fa2feb35d2352`.

| Corner and bench conditions | Coarse:fine code | Frequency | Missing fine bins |
| --- | ---: | ---: | ---: |
| TT, 1.80 V, 25 °C | 52:64 | 117.65 MHz | 0 of 40 |
| TT, 1.80 V, 25 °C | 255:128 | 348.66 MHz | 11 of 40 |
| SS, 1.62 V, 0 °C | 255:128 | 179.41 MHz | 8 of 40 |

The capacitance-extracted DCO falls short of the 300 MHz target at SS.
The tests use fixed DAC codes and lumped bench loads on the taps.
[Oscillator layout and simulation outputs](https://github.com/jonahsaunders/VIBE_PLL/actions/runs/43351731743/artifacts/14004726090)

A 900 ns slow-corner transient on the preceding folded layout measured
35.82 MHz at the controller's initial coarse:fine setting of 0:64. The
existing startup guard requires 48 MHz. That is an additional bring-up
check for the next extracted characterization.

The compact RTL passed 12 corner replays with a maximum 74.625 µs lock or
relock time using schematic-based frequency and phase tables. The extracted
oscillator needs a new plant table and closed-loop replay after tuning
closure.

## Harness integration

Use the official Chipalooza #4 slot outline, supply connections and approved
pad cells for wrapper integration. The core operates at 1.8 V. The proposed
dedicated reference and monitor pads use the approved 3.3 V peripheral cells.
Foundry handoff requires the integrated wrapper and its DRC, LVS, antenna,
density, power and timing results, plus extracted oscillator operating-range
and phase-noise verification.
