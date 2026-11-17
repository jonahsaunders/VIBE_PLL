# Extracted range-DCO characterization

The range-DCO build doubles the ring current-starve transistor widths, uses a 0.34 µm channel length there, and increases the core-inverter widths by 50%. Each launch buffer and sample buffer sits alongside its ring stage. The MIM bottom plate has a dedicated routing column. The tracking-replica delay cells retain their original dimensions.

The same Sky130A Volare device library and Magic revision as the Rev. 4 CI run were used with ngspice 42. The oscillator passed enabled KLayout geometry DRC and device-level LVS with KLayout 0.30.13, and Magic full-style DRC before capacitance extraction. [Geometry and connectivity record](oscillator-verification.json)

| Condition | Code | Extracted MHz | Missing bins out of 40 | Oscillator mW |
| --- | --- | ---: | ---: | ---: |
| TT, 1.80 V, 25 °C | 52:64 | 238.8545 | 29 | 2.3111 |
| SS, 1.62 V, 0 °C | 255:128 | 309.9628 | 24 | 2.5798 |
| FF, 1.95 V, 0 °C | 0:64 | 126.2766 | 25 | 1.8289 |

All three probes observed the expected coarse-tap order. The TT and SS rows supply the fixed fine-bin center tables for this build. Zero-width bins have zero dwell in a replay. Quantization and the remaining bin widths determine how much improvement the fine detector provides. [TT data](tt-52-64.csv) · [Slow-cold data](ss-255-128.csv) · [Fast data](ff-0-64.csv)

At the same slow-cold maximum code, the archived Rev. 4 probe reached 151.4959 MHz and used 1.3981 mW. Running `analysis/ring_loads.py` on both Magic netlists gives maximum total incident interconnect capacitances of 27.05 fF for Rev. 4 and 29.56 fF for the range DCO. These totals include each node's coupling capacitors at their full value and exclude explicit MIM and transistor capacitance. The frequency gain comes with stronger drive and increased power. [Rev. 4 extraction](https://github.com/jonahsaunders/VIBE_PLL/actions/runs/43496481088/job/132130803171)

## Reproduction

The two fixed tables use the measured midpoint of each phase bin, rounded to the nearest Q0.12 code and capped at 4095. Each table packs bin zero in the least significant twelve bits. The revised controller registers the decoded phase, its matching cycle count, and validity together. It computes the next target phase in parallel with the PI update. The sampled-loop model includes the added reference cycle.

```sh
mkdir -p build
python spice/dco_deck.py --tracking-replicas --range-dco --emit build/range.spice
python physical/layout_dco.py --schematic build/range.spice --output build/range
python physical/check_dco.py --pdk "$PDK_ROOT/sky130A" --build build/range
root="$PWD"
(cd build/range && magic -dnull -noconsole -rcfile "$PDK_ROOT/sky130A/libs.tech/magic/sky130A.magicrc" "$root/physical/extract_dco.tcl")
model="$PDK_ROOT/sky130A/libs.tech/ngspice/sky130.lib.spice"
python analysis/ring_loads.py build/range/cpz4_dco_pex.spice
python spice/dco_deck.py --lib "$model" --tracking-replicas --range-dco --corner ss --vdd 1.62 --temp 0 --codes 255 --fine-codes 128
python spice/dco_deck.py --lib "$model" --netlist build/range/cpz4_dco_pex.spice --corner ss --vdd 1.62 --temp 0 --codes 255 --fine-codes 128
python tests/qualify_pex.py sweep --lib "$model" --netlist build/range/cpz4_dco_pex.spice --corner tt --ceiling 96 --stride 24 --extra-codes 52 53 57 58 --jobs 2 --output build/replay-tt
python tests/qualify_pex.py replay --sampled --output build/replay-tt
```

For a full adjacent-code overlap check, omit `--stride` and `--sampled`. Each selected coarse code is measured at both fine rails and the midpoint. The source record binds the sweep to its extracted netlist and the results distinguish sampled lock from continuous coverage. The replay tests 160 and 300 MHz with a 20 MHz reference, plus 256.25 MHz and the two channels immediately adjacent to 250 MHz with a 25 MHz reference. Each spectral case checks acquisition and mean frequency before capturing 524,288 edges. Results describe deterministic phase error over 1 kHz–10 MHz.
