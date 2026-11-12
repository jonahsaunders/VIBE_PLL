# Reproducible verification results

The six transistor-level sweeps use the Sky130A model subset pinned to the Chip Foundry Volare release `sky130-fa87f8f4bbcc7255b6f0c0fb506960f531ae2392`. The sweep ran with ngspice and 20 fF on tap 0 and 8 fF on each other tap. Results use 50 sampled codes across six PVT conditions. Each curve was increasing at the sampled points and the checked tap edge order was valid.

| Sweep | Process, supply, temperature | Code 0 | Code 255 |
| --- | --- | ---: | ---: |
| [final-tt.csv](final-tt.csv) | TT, 1.8 V, 25.0 °C | 87.9 MHz | 678.8 MHz |
| [final-ss-cold.csv](final-ss-cold.csv) | SS, 1.62 V, 0.0 °C | 71.0 MHz | 346.4 MHz |
| [final-ss-hot.csv](final-ss-hot.csv) | SS, 1.62 V, 85.0 °C | 80.5 MHz | 387.3 MHz |
| [final-ff.csv](final-ff.csv) | FF, 1.95 V, 0.0 °C | 87.6 MHz | 1096.9 MHz |
| [final-sf.csv](final-sf.csv) | SF, 1.62 V, 85.0 °C | 83.4 MHz | 446.0 MHz |
| [final-fs.csv](final-fs.csv) | FS, 1.62 V, 85.0 °C | 81.5 MHz | 574.7 MHz |

The shared interval at these selected conditions spans 87.9–346.4 MHz. At TT, codes 58 and 59 straddle 256.25 MHz. The measured local step is 2.519 MHz and oscillator power is about 0.38 mW near lock. The FF analog upper rail exceeds 1 GHz. Use an appropriate code ceiling and close timing over the allowed acquisition excursions.

The digital loop passed the four behavioral tests and the six replays using linearly interpolated static SPICE frequencies and tap widths. The replay locks and retunes span 14.9–58.8 µs. The largest absolute frequency error over 4,096 DCO cycles is 19.1 ppm. The nominal channel locks in 25.7 µs. The maximum clock frequency observed in the in-band sequences is 348.4 MHz.

The noiseless edge model has 86.1 ps and 111.3 ps rms detrended TIE for the quarter and near-integer channels respectively. These values span the recorded TIE sequence and differ from band-integrated random jitter. The strongest estimated discrete lines in the 10 kHz–10 MHz analysis span are -34.5 and -21.4 dBc. The estimate uses 131,072 raw clock edges per case. There is no transistor noise, extracted parasitic or pad model in the loop replay.

See [RTL results](rtl-behavioral.txt), [PDK-backed replay](rtl-spice-replay.txt), [sampled-loop analysis](loop-budget.txt) and [spectral estimates](deterministic-spectrum.txt). Raw waves and edge data are regenerated with the commands in the root README.

To reproduce the corner replays, use `python tests/run_rtl.py --spice-data results/final-tt.csv`. For `final-ss-cold.csv` and `final-ss-hot.csv` add `--ref 16 --edge 76800`. For `final-ff.csv` add `--ref 32 --start 37888 --retune 36864 --edge 20480`. The SF and FS CSVs use the same arguments as TT.

These checks are pre-layout. All-code monotonicity, mixed-signal transients, timing and metastability, wider PVT and mismatch, full-macro power, area, and the integrated jitter target require the schematic and extracted verification gates.
