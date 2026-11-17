# Extracted range-DCO characterization

The standalone build uses a five-stage ring with 0.23 µm current-starve channels, twice the Rev. 4 current-starve widths and 1.5 times the Rev. 4 inverter widths. Each stage has local launch and sample buffers. The original tracking-replica cells, thermometer interfaces and 290 × 115 µm oscillator footprint are preserved. The macro passed the enabled Sky130 geometry checks, Magic DRC and device-level LVS. [Verification record](oscillator-verification.json)

| Sky130A condition | Coarse:fine | Extracted MHz | Oscillator mW | Occupied phase bins |
| --- | --- | ---: | ---: | ---: |
| TT, 1.80 V, 25 °C | 40:64 | 262.6046 | 2.5074 | 12 / 40 |
| TT, 1.80 V, 25 °C | 52:64 | 296.9738 | 2.8235 | 12 / 40 |
| SS, 1.62 V, 0 °C | 136:64 | 277.0765 | 2.2067 | 14 / 40 |
| SS, 1.62 V, 0 °C | 255:128 | 355.6133 | 2.9084 | 14 / 40 |

All four fixed-code probes produced ordered coarse transitions. The design uses phase-bin centers measured at TT 40:64 and SS 136:64. The regression checks all 80 encoded constants against the measured widths. [TT phase profile](tt-40-64.csv) · [SS phase profile](ss-136-64.csv) · [TT comparison point](tt-52-64.csv) · [Slow-cold upper code](ss-255-128.csv)

At the same slow-cold maximum code, Rev. 4 measured 151.50 MHz at 1.40 mW. The first higher-drive ring reached 309.96 MHz at 2.58 mW. At coarse 223 its full fine adjustment was only 0.44 MHz near 296 MHz. The shorter current-starve channel moves the 300 MHz operating point farther from saturation. At coarse 192 its extracted rails already reach 322.48 and 323.71 MHz. The largest added ring-node interconnect load versus Rev. 4 is on n3, from 25.44 to 28.44 fF. Stage n4 has the highest absolute load, 29.56 fF. These totals count coupling at its full value and exclude transistor and explicit MIM capacitance. [First layout comparison and replay](first-pass/README.md) · [Rev. 4 baseline](https://github.com/jonahsaunders/VIBE_PLL/actions/runs/43496481088)

## Running the extracted replay

Use the pinned Sky130A, Magic and KLayout versions in the [standalone workflow](../../.github/workflows/standalone-route.yml). The commands below generate the actual layout, extract it and run the typical corner.

```sh
mkdir -p build/range
python3 spice/dco_deck.py --tracking-replicas --range-dco --emit build/range/source.spice
python3 physical/layout_dco.py --schematic build/range/source.spice --output build/range
python3 physical/check_dco.py --pdk "$PDK_ROOT/sky130A" --build build/range
root="$PWD"
(cd build/range && magic -dnull -noconsole -rcfile "$PDK_ROOT/sky130A/libs.tech/magic/sky130A.magicrc" "$root/physical/extract_dco.tcl")
model="$PDK_ROOT/sky130A/libs.tech/ngspice/sky130.lib.spice"
python3 analysis/ring_loads.py build/range/cpz4_dco_pex.spice
python3 tests/qualify_pex.py sweep --corner tt --ceiling 64 --stride 16 --extra-codes 37 38 40 52 53 --jobs 2 --lib "$model" --netlist build/range/cpz4_dco_pex.spice --output build/replay-tt
python3 tests/qualify_pex.py replay --sampled --output build/replay-tt
```

Each selected coarse code is measured at fine 0, 64 and 128. For a proof of adjacent-code coverage, omit `--stride` and `--sampled`. The report lists measured gaps and unsampled intervals. Each sweep is bound to the extracted netlist by SHA-256.

Both detectors undergo acquisition at 160 MHz, retuning to 300 MHz and reference-loss recovery at 16, 20 and 32 MHz references. Spectral runs compare the fine and coarse detectors at 256.25 MHz and at one ratio LSB either side of 250 MHz using a 25 MHz reference. They also exercise the narrower tracking bandwidth on the two adjacent channels. Each spectrum uses 524,288 output edges after 4,096 settling cycles over 1 kHz–10 MHz. These results describe deterministic timing error in a replay of static, capacitance-extracted transistor simulations. Supply noise, device noise, mismatch and harness loading need separate measurements.
