# First higher-drive oscillator iteration

These measurements apply to the 0.34 µm current-starve devices and hardware tables at [`615123b`](https://github.com/jonahsaunders/VIBE_PLL/tree/615123b). Use that revision to reproduce this comparison. [Current range-DCO design](../README.md)

The range-DCO build doubles the ring current-starve transistor widths, uses a 0.34 µm channel length there, and increases the core-inverter widths by 50%. Each launch buffer and sample buffer sits alongside its ring stage. The MIM bottom plate has a dedicated routing column. The tracking-replica delay cells retain their original dimensions.

The same Sky130A Volare device library and Magic revision as the Rev. 4 CI run were used with ngspice 42. The oscillator passed enabled KLayout geometry DRC and device-level LVS with KLayout 0.30.13, and Magic full-style DRC before capacitance extraction. [Geometry and connectivity record](oscillator-verification.json)

| Condition | Code | Extracted MHz | Missing bins out of 40 | Oscillator mW |
| --- | --- | ---: | ---: | ---: |
| TT, 1.80 V, 25 °C | 52:64 | 238.8545 | 29 | 2.3111 |
| SS, 1.62 V, 0 °C | 255:128 | 309.9628 | 24 | 2.5798 |
| FF, 1.95 V, 0 °C | 0:64 | 126.2766 | 25 | 1.8289 |

All three probes observed the expected coarse-tap order. The TT and SS rows supply the fixed fine-bin center tables for this build. Zero-width bins have zero dwell in a replay. Quantization and the remaining bin widths determine how much improvement the fine detector provides. [TT data](tt-52-64.csv) · [Slow-cold data](ss-255-128.csv) · [Fast data](ff-0-64.csv)

At the same slow-cold maximum code, the archived Rev. 4 probe reached 151.4959 MHz and used 1.3981 mW. Running `analysis/ring_loads.py` on both Magic netlists gives maximum total incident interconnect capacitances of 27.05 fF for Rev. 4 and 29.56 fF for the range DCO. These totals include each node's coupling capacitors at their full value and exclude explicit MIM and transistor capacitance. The frequency gain comes with stronger drive and increased power. [Rev. 4 extraction](https://github.com/jonahsaunders/VIBE_PLL/actions/runs/43496481088/job/132130803171)

## Same-load comparison

| Circuit and code | Schematic MHz | Extracted MHz |
| --- | ---: | ---: |
| Rev. 4, slow-cold 255:128 | 346.52 | 151.50 |
| Range DCO, slow-cold 255:128 | 654.60 | 309.96 |
| Range DCO, typical 52:64 | 588.35 | 238.85 |

Both netlists used individual DAC cells, the same PDK, supply, temperature, control codes, external tap loads and transient settings for each comparison. The largest added ring-node interconnect load relative to Rev. 4 was on n3 (25.44 to 28.44 fF). The most heavily loaded stage in both layouts was n4 (27.05 to 29.56 fF).

Adjacent measured typical-corner fine ranges overlap by 20.83 MHz at coarse 57/58, 20.70 MHz at 58/59, 20.61 MHz at 59/60, and 18.50 MHz at 79/80. At the fast corner the overlap is 43.86 MHz at coarse 31/32. At slow-cold, coarse 254 at fine 128 reached 309.6491 MHz and coarse 255 at fine zero reached 309.8744 MHz, leaving a 0.2253 MHz gap above the operating band. Each overlap is the lower coarse setting's fine-high frequency minus the next coarse setting's fine-low frequency. [Measured adjacent rails](adjacent-rails.csv)

## Closed-loop replay at typical conditions

At a 20 MHz reference the fine detector reached 160 MHz in 25.70 µs and retuned to 300 MHz in 40.30 µs. Mean errors over 4,096 cycles were −5.38 ppm and +4.91 ppm. Both detector settings passed reference dropout and recovery. This first sweep interpolates between coarse codes 0, 52 and 96, each measured at fine 0, 64 and 128. Continuous tuning coverage remains open between the sampled codes. [Input sweep](tt-sampled-sweep.csv) · [Replay and spectral results](tt-sampled.json)

| Channel at 25 MHz reference | Fine band TIE | Coarse band TIE | Fine strongest line | Coarse strongest line |
| --- | ---: | ---: | ---: | ---: |
| 256.25 MHz | 6.68 ps | 6.61 ps | −59.66 dBc | −52.58 dBc |
| 250 MHz − 1 LSB | 58.90 ps | 59.56 ps | −24.23 dBc | −24.13 dBc |
| 250 MHz + 1 LSB | 59.12 ps | 59.97 ps | −24.12 dBc | −24.07 dBc |

The integration band is 1 kHz–10 MHz. Each case captured 524,288 output edges after 4,096 reference cycles. At the nominal channel the fine mode reduced the strongest line by 7.08 dB. At both adjacent channels the deterministic error was dominated by a line near 61 kHz. Enabling the narrower near-integer bandwidth at those channels reduced band TIE to 35.84 and 35.50 ps and the lines to −29.37 and −29.34 dBc, respectively. These replays include the measured tuning and static bin widths. Device noise and power-supply noise still need separate characterization.

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

For a full adjacent-code overlap check, omit `--stride` and `--sampled`. Each selected coarse code is measured at both fine rails and the midpoint. The source record binds the sweep to its extracted netlist and the results distinguish sampled lock from continuous coverage. The replay tests 160 and 300 MHz at 16, 20 and 32 MHz references, plus 256.25 MHz and the two channels immediately adjacent to 250 MHz with a 25 MHz reference. Each spectral case checks acquisition and mean frequency before capturing 524,288 edges. Results describe deterministic phase error over 1 kHz–10 MHz.
