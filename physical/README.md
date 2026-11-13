# Standalone physical implementation

Export the mapped controller and verify the planning footprint using the Sky130 HD library.

```sh
python tests/check_slot.py --liberty "$LIBERTY" --lef "$CELLS_LEF" \
  --slot 400 250 --dco-reserve 100 100 --edge-reserve 5 --utilization 0.65 \
  --mapped-netlist build/cpz4_sky130.v
```

Create `build` before running the export. Use the real `cpz4_dco` layout abstract for `DCO_LEF`. The macro uses the Verilog bus names `therm[254:0]`, `fine_therm[127:0]`, `tap[4:0]`, and `fine_tap[14:0]`. Map the bracketed bit names to the corresponding underscore-indexed schematic pins in the extracted netlist. The LEF needs pin geometries, obstructions, and the `vdd`, `vss`, and `enable` pins.

```sh
export TECH_LEF CELLS_LEF LIBERTY DCO_LEF
export MAPPED_VERILOG=build/cpz4_sky130.v
export OUT_DIR=build/physical
openroad -exit physical/floorplan.tcl
```

Set `RUN_GLOBAL_ROUTE=1` for exploratory cell placement and signal routing. The script keeps the DCO and its halo inside the reserved corner. Override `DIE_AREA` and `CORE_AREA` with the approved coordinates, and adjust `DCO_RESERVE` and `DCO_HALO_UM` to match the analog layout. `DCO_PERIOD_NS` defaults to 2.5 ns. Set it from the largest characterized acquisition clock frequency.

The reference, ring, and generated divider clocks are defined in [standalone.sdc](standalone.sdc). The inter-domain max delays are initial routing targets. Review Gray-bus skew, tap arrival time, reset release, and sampling aperture separately. Add wrapper timing, power straps, tap and filler cells, clock trees, and detailed routing during integration.

The current workspace verified Sky130 HD mapping and the planning row fit. Running OpenROAD requires the DCO LEF and a working OpenROAD installation. Standalone and wrapper DRC/LVS, parasitic extraction, and clock and supply sign-off remain pending. Use the [load sensitivity results](../results/rev3.md) to prioritize extracted tap loads and DCO supply impedance.
