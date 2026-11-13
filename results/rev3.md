# Rev. 3 acquisition, phase, and DCO verification

## Acquisition

The weak-gain path repeats both fine rail measurements over 128 reference cycles while the overspeed guard retains its 32-cycle cadence. The compact build passed the sampled grid at 16, 20, 25, and 32 MHz references across the TT, slow-cold, and fast Sky130A schematic replay tables. Each of the 12 cases checks startup, retune, reference-loss holdover, recovery, and an intermediate channel. The worst observed lock or relock time was 74.63 µs, the worst absolute mean frequency error was 27.64 ppm over 4,096 DCO periods, and the fastest modeled DCO period corresponded to 320.2 MHz.

The slow-cold replay now locks at 300 MHz with both 25 and 32 MHz references, which previously reported `BAD_GAIN`. New ngspice 45.2 points at coarse codes 171–176, fine codes 0, 64, and 128 show 1.70–1.83 MHz of overlap between adjacent coarse ranges. [Densified slow-cold replay table](rev3-ss-cold.csv)

```sh
python tests/run_rtl.py --fixed-centers --corner-grid
python tests/run_rtl.py --fixed-centers --slow-phase-profile --narrow-near-integer \
  --spice-data results/rev3-ss-cold.csv --ref 32 --start 38400 --retune 38399
```

## Near-integer tracking

At a 25 MHz reference, these TT replays used 524,288 DCO edges after 4,096 settling reference cycles. The reported band is 1 kHz–10 MHz. The narrow setting engages only after lock, in tracking gear 2, one ratio step away from integer.

| Output | Band RMS TIE, default | Band RMS TIE, narrow | Strongest line, default | Strongest line, narrow |
| --- | ---: | ---: | ---: | ---: |
| 249.9939 MHz | 19.81 ps | 10.68 ps | −35.22 dBc | −42.14 dBc |
| 250.0061 MHz | 19.50 ps | 11.92 ps | −35.33 dBc | −40.39 dBc |

The strongest line on both channels is near 61 kHz. The tested randomized residue mode and a fixed triangular phase correction did not consistently improve those channels. Narrow tracking retains the existing residue feedback. The numbers describe deterministic edge error from a static plant replay. Device noise and supply coupling can change the best tracking bandwidth.

```sh
python tests/run_rtl.py --fixed-centers --spice-data results/rev2-tt.csv \
  --start 40961 --narrow-near-integer --spectrum-edges 524288 --spectrum edges.csv
python analysis/spectrum.py edges.csv --lower 1000
```

Repeat with `--start 40959` for the lower channel and without `--narrow-near-integer` for the baseline. The larger self-calibrating build also passed the calibration and coherent-histogram rejection regression.

## DCO supply and loading

The TT DCO at coarse 52, fine 64, 1.8 V and 25 °C measured 139.0 MHz/V of supply pushing at 2 MHz and 129.6 MHz/V at 10 MHz, using 10 mV peak ripple on the oscillator supply. The enable and DAC control highs stay at the nominal voltage. The frequency modulation is fitted from the rising edges after one ripple period.

At SS, 1.62 V, 0 °C, coarse 172 and fine 64, the default loads give 38 populated fine bins. Adding 2 fF to each sampled tap reduced that to 32, and adding 10 fF reduced it to 22. At the latter load, 2.5× replica inverter widths gave 39 populated bins at this operating point and increased oscillator power from 0.784 to 0.914 mW. These are schematic perturbations. The production schematic retains its original sizing until extracted loads and recharacterized phase tables are available.

```sh
model="$PDK_ROOT/sky130A/libs.tech/ngspice/sky130.lib.spice"
python spice/dco_deck.py --lib "$model" --aggregate-dac --corner ss --vdd 1.62 \
  --temp 0 --codes 171,172,173,174,175,176 --fine-codes 0,64,128 --output ss-dense.csv
python spice/dco_deck.py --lib "$model" --aggregate-dac --corner tt --vdd 1.8 \
  --codes 52 --fine-codes 64 --supply-ripple-mv 10 --supply-ripple-mhz 2
python spice/dco_deck.py --lib "$model" --aggregate-dac --corner ss --vdd 1.62 \
  --temp 0 --codes 172 --fine-codes 64 --added-tap-load-ff 10 --replica-strength 2.5
```

The compact build maps to **51,930 µm²** of Sky130 HD cells. It uses 62.44% of the available digital rows and leaves 2,128 µm² of digital cell area under the 65% cap in the provisional 400 × 250 µm rectangle. [Area method](slot-fit.md) · [Physical implementation inputs](../physical/README.md)
