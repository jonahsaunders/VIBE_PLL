# Verification results

The [area-constrained build](slot-fit.md) uses the same oscillator schematic. The closed-loop and spectral tables below record the previous self-calibrating revision; the area page reports the latest fixed-center replays.

## Sky130A schematic

The revised DCO was simulated with ngspice 44.2 and the Sky130A models in Volare release `sky130-fa87f8f4bbcc7255b6f0c0fb506960f531ae2392`. The bench uses 20 fF on tap 0 and 8 fF on each other tap and replica. The sampled grid contains 33 static operating points, all with the expected tap order. At TT, fine code 64 to 65 at coarse code 52 moves the clock from 256.8567 MHz to 257.0261 MHz. See the [adjacent-code sweep](rev2-fine-step.csv). The 169.4 kHz step is about 15 times smaller than the original DCO's 2.519 MHz step near the nominal channel.

| Sweep | Process, supply, temperature | Coarse:fine probe | Frequency | Occupied bins | Nonzero bin widths | DCO power |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| [TT](rev2-tt.csv) | TT, 1.80 V, 25 °C | 52:64 | 256.86 MHz | 40 | 54–250 ps | 0.626 mW |
| [Slow-cold](rev2-ss-cold.csv) | SS, 1.62 V, 0 °C | 176:64 | 304.00 MHz | 38 | 6–120 ps | 0.631 mW |
| [Fast](rev2-ff.csv) | FF, 1.95 V, 0 °C | 44:64 | 302.72 MHz | 40 | 38–242 ps | 0.882 mW |

The CSVs include all 40 bin widths in oscillator periods and three fine settings per coarse code. Power includes the oscillator, its bias and the tap replicas. The narrowest bins are sensitive to load and capture aperture. The slow-cold fine span at coarse code 176 is 2.32 MHz, so adjacent-code overlap needs particular attention there.

```sh
model="$PDK_ROOT/sky130A/libs.tech/ngspice/sky130.lib.spice"
python spice/dco_deck.py --lib "$model" --aggregate-dac --corner tt --vdd 1.8 --temp 25 \
  --codes 0,24,52,84 --fine-codes 0,64,128 --output tt.csv
python spice/dco_deck.py --lib "$model" --aggregate-dac --corner ss --vdd 1.62 --temp 0 \
  --codes 0,48,176 --fine-codes 0,64,128 --output ss-cold.csv
python spice/dco_deck.py --lib "$model" --aggregate-dac --corner ff --vdd 1.95 --temp 0 \
  --codes 0,20,36,44 --fine-codes 0,64,128 --output ff.csv
python spice/dco_deck.py --lib "$model" --aggregate-dac --corner tt --vdd 1.8 --temp 25 \
  --codes 52 --fine-codes 64,65 --output nominal-step.csv
```

`--aggregate-dac` uses BSIM multiplicity for identical parallel cells at static codes with mismatch disabled. Omitting the option simulates the separate instances used in the generated schematic.

## Closed-loop replay

Icarus Verilog replays the static frequencies and phase widths with piecewise-linear interpolation across each bank. The TT and slow-cold runs preload a code-density LUT near 257 MHz and 302 MHz, respectively. The FF run uses reset bin centers. Lock times exclude the 32,768-sample calibration.

| Replay | Reference | Initial lock | Retune and recovery range | Tested frequencies | Peak DCO |
| --- | ---: | ---: | ---: | --- | ---: |
| TT | 25 MHz | 27.24 µs | 29.44–29.92 µs | 256.25, 300 MHz | 308.52 MHz |
| Slow-cold | 16 MHz | 41.31 µs | 46.75–74.63 µs | 164, 192, 300 MHz | 301.71 MHz |
| Fast | 32 MHz | 20.03 µs | 14.97–18.80 µs | 160, 288, 296 MHz | 312.41 MHz |

Across these sequences the largest mean frequency error was 14.43 ppm over 4,096 cycles. Reference loss cleared lock in 0.84–1.32 µs while both DACs held their codes. The abstract-plant suite also checks count wrap, code ceilings, the startup guard and rejection of a coherent calibration histogram. The RTL synthesizes in Yosys. An isolated Sky130 HD mapped counter check at 400 MHz, with ideal clocks, 0.10 ns setup uncertainty and no routed interconnect, reported +0.21 ns worst setup slack at SS (1.60 V, 100 °C) and +1.35 ns at TT (1.80 V, 25 °C).

```sh
python tests/run_rtl.py
python tests/run_rtl.py --spice-data results/rev2-tt.csv --calibrate --cal-code 52
python tests/run_rtl.py --spice-data results/rev2-ss-cold.csv --ref 16 --edge 76800 \
  --calibrate --cal-code 174
python tests/run_rtl.py --spice-data results/rev2-ff.csv --ref 32 \
  --start 37888 --retune 36864 --edge 20480
```

## Deterministic phase error

The TT replay captures 131,072 raw DCO edges per channel with gear 2 and the calibrated detector. The 10 kHz–10 MHz band RMS is calculated from detrended edge time error. The replay includes quantization and the static DCO transfer curve. Device noise, reference noise, supply modulation, and pad effects require separate characterization.

| Q5.12 ratio | Output | Record RMS TIE | Band RMS TIE | Strongest line in band | Baseline strongest line |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 40960 | 250 MHz | 24.0 ps | 7.0 ps | −44.2 dBc | — |
| 41984 | 256.25 MHz | 8.5 ps | 7.9 ps | −46.7 dBc | −34.5 dBc |
| 43008 | 262.5 MHz | 34.6 ps | 7.5 ps | −47.7 dBc | — |
| 40961 | 250.0061 MHz | 24.8 ps | 19.6 ps | −35.1 dBc | −21.4 dBc |

```sh
python tests/run_rtl.py --spice-data results/rev2-tt.csv --calibrate --cal-code 52 \
  --start 41984 --spectrum edges.csv
python analysis/spectrum.py edges.csv
```

The baseline [spectral estimates](deterministic-spectrum.txt), `final-*.csv` sweeps, and other unversioned logs describe the [original revision](https://github.com/jonahsaunders/VIBE_PLL/tree/feb059ec1b7f6b69b3c953039adff4dc6c05cbea). These tests use three sampled corners. Full-macro extracted timing, all-code step bounds and overlap, code-switching transients, mismatch, integrated jitter and pad verification remain open.
