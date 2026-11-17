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

## Tuning and physical closure

After 900 ns of slow-cold settling, coarse 158 spans **298.4383–302.2498 MHz** and coarse 159 spans **299.2621–302.9997 MHz**. Their fine tuning ranges overlap across 300 MHz by **2.9877 MHz**. Coarse 160 starts at 300.0666 MHz. The period spread over the measured cycles was at most 0.002% on these six rails. The shorter 280 ns transient placed the 300 MHz overlap one code higher. [Settled rail measurements](settled-ss-upper-rails.csv)

At the same external loads, supply, temperature and control codes, the schematic/extracted measurements are 743.1583/355.6133 MHz at slow-cold 255:128 and 718.5245/296.9738 MHz at typical 52:64. The extraction includes both ground and interconnect coupling capacitance. [Schematic SS](schematic-ss-255-128.csv) · [Schematic TT](schematic-tt-52-64.csv)

The oscillator can exceed the digital clock limit when driven directly. At TT, 255:128 reached 687.4394 MHz. At FF, 48:128 reached 438.5375 MHz. The routed clocks are timed to the controller's 400 MHz acquisition guard. Configure the reference upper bound and coarse ceiling for the intended operating condition before enabling manual tuning. The characterized replay ceilings are 64 at TT, 192 at SS and 24 at FF. Their upper fine rails measured 339.4370, 323.7114 and 333.2631 MHz respectively.

The locally routed 460 × 330 µm layout passed the enabled geometry checks and full device LVS. With the pinned build's synthesized controller, OpenROAD 26Q2 and extracted wires at TT, the 400 MHz DCO and 32 MHz reference have **+0.28 ns setup**, **+0.18 ns hold**, and **0.00 ns setup TNS** at 45%, 50% and 55% DCO duty. All 44 Gray/phase capture endpoints met their 1 ns budgets, with at least 0.447 ns of margin. Signal routing, all three supply grids and antenna checks passed. [Routed verification and area record](routed-layout.json) · [Rendered GDS](../../docs/range-pll-layout.png) · [Independent pinned workflow](https://github.com/jonahsaunders/VIBE_PLL/actions/runs/44165649871)

## Closed-loop measurements

All 42 cases in the checked-in sampled sweeps passed acquisition and mean-frequency checks. Each corner has three 160-to-300 MHz retune and reference-recovery tests per detector, three spectral channels per detector and two additional narrow-bandwidth runs. The largest absolute mean error over 4,096 output cycles was 41.35 ppm. The three input tables record the measured thermometer states, including time spent using coarse fallback. The replay interpolates between measured codes. These local tables use a 650 ns settling window at coarse zero and the default static transient elsewhere. CI repeats the sweep with longer settling and more coarse settings. [TT results](sampled/tt/qualification.json) · [SS results](sampled/ss/qualification.json) · [FF results](sampled/ff/qualification.json)

| Corner | 256.25 MHz strongest line, fine / coarse | Lower adjacent channel TIE, fine / narrow | Upper adjacent channel TIE, fine / narrow |
| --- | ---: | ---: | ---: |
| TT | −55.11 / −46.66 dBc | 90.13 / 74.40 ps | 90.98 / 75.64 ps |
| SS | −64.21 / −49.70 dBc | 71.93 / 54.99 ps | 74.82 / 58.34 ps |
| FF | −31.74 / −33.97 dBc | 97.45 / 121.96 ps | 101.53 / 81.99 ps |

The adjacent channels are 250 MHz ± one ratio LSB at a 25 MHz reference. Narrow tracking reduced timing error on both sides at TT and SS. At FF it increased the error below the integer and reduced it above. The coarse detector also produced the smaller nominal spur at FF. The existing controls allow software to select coarse-only detection and near-integer bandwidth for the channel and operating condition. [Operating mode register](../../docs/design.md)

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

For fresh sweeps, the transistor bench decodes the three replica voltages with the same thermometer truth table as the RTL. The waveform record preserves the duration of valid subdivisions and intervening coarse fallback. At fast 0:0, the far replica briefly retains its previous state and 13.67% of the cycle uses fallback. At 0:64 this falls to 0.77%. The replay drives the receiver through these intervals and records how many reference samples actually use fallback. An unrepresentable reversal or an unordered coarse cycle fails the fine replay.

CI allows 900 ns for settling at every code, distributes the requested codes across five runners per corner and requires two adjacent slow-cold ranges to overlap at 300 MHz. The combine step checks the provenance, exact code pairs, supply, temperature and digest of each part before replay. A single local sweep produces the same table without partitioning.

For a fast reproduction, copy one checked-in directory such as `results/range-dco/sampled/ff` to `build/replay-ff` and run `python3 tests/qualify_pex.py replay --sampled --output build/replay-ff`. The manifest identifies the measured sweep and extraction used by that replay.

Both detectors undergo acquisition at 160 MHz, retuning to 300 MHz and reference-loss recovery at 16, 20 and 32 MHz references. Spectral runs compare the fine and coarse detectors at 256.25 MHz and at one ratio LSB either side of 250 MHz using a 25 MHz reference. They also exercise the narrower tracking bandwidth on the two adjacent channels. Each spectrum uses 524,288 output edges after 4,096 settling cycles over 1 kHz–10 MHz. These results describe deterministic timing error in a replay of static, capacitance-extracted transistor simulations. Supply noise, device noise, mismatch and harness loading need separate measurements.
