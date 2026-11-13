# Standalone physical implementation

Export the mapped controller and verify the planning footprint using the Sky130 HD library.

```sh
python tests/check_slot.py --liberty "$LIBERTY" --lef "$CELLS_LEF" \
  --slot 400 250 --dco-reserve 100 100 --edge-reserve 5 --utilization 0.65 \
  --mapped-netlist build/cpz4_sky130.v
```

Create `build` before running the export. Use the real `cpz4_dco` layout abstract for `DCO_LEF`. The macro uses the Verilog bus names `therm[254:0]`, `fine_therm[127:0]`, `tap[4:0]`, and `fine_tap[14:0]`. Map the bracketed bit names to the corresponding underscore-indexed schematic pins in the extracted netlist. The LEF needs pin geometries, obstructions, and the `vdd`, `vss`, and `enable` pins.

For the tracking-replica DCO, add `--tracking-replicas` to `check_slot.py` so the mapped controller uses the matching phase centers. Add `--max-coarse-code` with the qualified limit after evaluating range, code transitions, and routed timing. If the fastest safe code cannot reach 300 MHz at the slow corner, characterize and configure limits for each supported operating profile before selecting a common production limit.

```sh
export TECH_LEF CELLS_LEF LIBERTY DCO_LEF
export MAPPED_VERILOG=build/cpz4_sky130.v
export OUT_DIR=build/physical
openroad -exit physical/floorplan.tcl
```

Set `RUN_GLOBAL_ROUTE=1` for exploratory cell placement and signal routing. The script keeps the DCO and its halo inside the reserved corner. Override `DIE_AREA` and `CORE_AREA` with the approved coordinates, and adjust `DCO_RESERVE` and `DCO_HALO_UM` to match the analog layout. `DCO_PERIOD_NS` defaults to 2.5 ns. Set it from the shortest characterized acquisition period, including code transitions. Sweep `DCO_HIGH_NS` at both duty-cycle limits for that period and check the minimum high and low pulse widths against the library.

The reference, ring, and generated divider clocks are defined in [standalone.sdc](standalone.sdc). The asynchronous Gray and phase-tap constraints target the first-stage D pins. The max delays are routing targets. Source [capture_paths.tcl](capture_paths.tcl) after loading routed parasitics and propagated clocks at each sign-off corner. For each Gray bus, compare the earliest and latest launch-to-capture arrival across bits and transitions. Compare those arrivals with the tap paths that select the safe counter edge, including the extracted analog tap timing, capture aperture, and clock skew. Check recovery and removal for both counter edges, and keep the first- and second-stage capture flops close. Add wrapper timing, power straps, tap and filler cells, clock trees, and detailed routing during integration.

Route `VDD_DCO` on its own harness-approved supply branch, with a short return to the quiet ground connection. Put the decoupling beside the oscillator and keep digital clock and DAC switching currents off the branch where the harness permits. Include package, pad, and extracted power-grid impedance in ripple injection. Use `analysis/loop_budget.py --supply-tone` to convert the measured local supply tone and DCO pushing into a timing allocation for each gear. Use `--noise-spectra` to compare gears with measured reference, oscillator, and rail noise.

The current workspace verified Sky130 HD mapping and the planning row fit. Running OpenROAD requires the DCO LEF and a working OpenROAD installation. Standalone and wrapper DRC/LVS, parasitic extraction, and clock and supply sign-off remain pending. Use the [load sensitivity results](../results/rev3.md) to prioritize extracted tap loads and DCO supply impedance.
