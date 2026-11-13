# Rev. 4 detector, supply, and capture verification

## Near-integer replay

At a 25 MHz reference, the ratio codes `40959` and `40961` step the sampled detector phase by ±1/4096 of a cycle on each reference edge. The ten coarse intervals repeat their unequal subdivisions about ten times per oscillator cycle. This gives a detector-error line at 61.04 kHz in the nominal replay.

The controlled experiment uses the same tuning curve, coarse phase edges, gear 2, and residue feedback for both runs. It replaces the four subdivisions of each coarse interval with equal quarters and derives a matching LUT at coarse 52, fine 64. Results use Icarus Verilog 12 and 524,288 output edges after 4,096 settling reference cycles. The integration band is 1 kHz–10 MHz.

| Ratio code | Rev. 3 strongest line | Equal-quarter strongest line | Rev. 3 band TIE | Equal-quarter band TIE |
| ---: | ---: | ---: | ---: | ---: |
| 40959 | −35.22 dBc | −46.79 dBc | 19.81 ps RMS | 7.11 ps RMS |
| 40961 | −35.33 dBc | −46.22 dBc | 19.50 ps RMS | 7.60 ps RMS |

```sh
for ratio in 40959 40961; do
  python tests/run_rtl.py --fixed-centers --spice-data results/rev2-tt.csv \
    --start "$ratio" --spectrum-edges 524288 --spectrum "base-$ratio.csv"
  python tests/run_rtl.py --fixed-centers --spice-data results/rev2-tt.csv \
    --phase-lut-point 52 64 --ideal-quarter-bins \
    --start "$ratio" --spectrum-edges 524288 --spectrum "quarter-$ratio.csv"
  python analysis/spectrum.py "base-$ratio.csv" --lower 1000
  python analysis/spectrum.py "quarter-$ratio.csv" --lower 1000
done
```

## Tracking-replica circuit

The [generated schematic](../spice/cpz4_dco_tracking.spice) uses the ring's current-starved inverter geometry, with twice the starve transistor widths in the replicas. Matched output buffers isolate their internal nodes from the routed sampling loads. The two fixed phase tables use the [TT](rev4-tt-tracking-probe.csv) and [slow-cold](rev4-ss-tracking-probe.csv) schematic probes.

At TT, 1.8 V and 25 °C, the observed nominal bin-width range tightened from 54–249 ps to 75–150 ps. The oscillator, bias and tap buffers consumed 0.990 mW, up from 0.626 mW at the legacy probe. At SS, 1.62 V and 0 °C with 10 fF added per sampled tap, the tracking prototype populated all 40 bins and the legacy circuit populated 22. At that load the tracking circuit consumed 1.136 mW, up from 0.784 mW. The results are schematic simulations using ngspice 46 and the open_pdks `b344c97eacc2aaf8e14ae7e43e2e9dc0871de2c0` Sky130A device models. [Probe data](rev4-phase-probes.csv)

The following replay applies the measured tracking-replica subdivision proportions to each row of the original TT tuning curve. It keeps the old coarse tap boundaries and uses the new schematic LUT. This isolates detector shape and is a controlled replay at one characterized detector operating point.

| Ratio code | Strongest line | Offset | Band TIE |
| ---: | ---: | ---: | ---: |
| 40959 | −48.85 dBc | 1.938 MHz | 8.41 ps RMS |
| 40961 | −48.20 dBc | 12.87 kHz | 9.04 ps RMS |

```sh
for ratio in 40959 40961; do
  python tests/run_rtl.py --fixed-centers --tracking-replicas \
    --spice-data results/rev2-tt.csv --phase-shape results/rev4-tt-tracking-probe.csv \
    --start "$ratio" --spectrum-edges 524288 --spectrum "tracking-$ratio.csv"
  python analysis/spectrum.py "tracking-$ratio.csv" --lower 1000
done
```

With the slow-cold replica probe and lookup table applied to the existing SS tuning curve, the loop locked at 300 MHz and relocked one step below it. The longest lock or relock was 58.72 µs with a 25 MHz reference and 45.88 µs with a 32 MHz reference. Both replays passed reference-loss holdover and recovery.

```sh
python tests/run_rtl.py --fixed-centers --tracking-replicas --slow-phase-profile \
  --spice-data results/rev3-ss-cold.csv --phase-shape results/rev4-ss-tracking-probe.csv \
  --ref 25 --start 49152 --retune 49151 --edge 41984
python tests/run_rtl.py --fixed-centers --tracking-replicas --slow-phase-profile \
  --spice-data results/rev3-ss-cold.csv --phase-shape results/rev4-ss-tracking-probe.csv \
  --ref 32 --start 38400 --retune 38399 --edge 20480
```

## Supply and startup

The `--filtered-bias` schematic experiment inserts a high-resistance poly resistor and a MIM capacitor between the reference generator and the DAC bias gates. A discharge device clears the filtered bias in standby. At TT, the measured 2 MHz supply pushing was 139.02 MHz/V for the legacy circuit, 55.05 MHz/V with the filter added to the legacy circuit, and 56.98 MHz/V with the filter and tracking replicas. All three used a 10 mV peak tone. The filtered probe begins ripple injection at 1.8 µs to allow bias settling. [Supply data](rev4-supply-probes.csv)

With the nominal 256.25 MHz carrier and gear 2, the sampled loop model puts a 100 ps RMS allocation for that tone at 3.23 mV peak for the legacy circuit and 7.87 mV peak for the combined prototype. These are single-tone estimates.

```sh
model="$PDK_ROOT/sky130A/libs.tech/ngspice/sky130.lib.spice"
python spice/dco_deck.py --lib "$model" --aggregate-dac --tracking-replicas --filtered-bias \
  --codes 52 --fine-codes 64 --supply-ripple-mv 10 --supply-ripple-mhz 2
python analysis/loop_budget.py --supply-tone 2e6 56.98 10 --tone-budget-ps 100
```

`python analysis/loop_budget.py --noise-spectra spectra.csv` reports reference, DCO, supply, and total RMS jitter for each tracking gear. Supply the same increasing offset grid for all columns. The CSV header is `offset_hz,reference_dbc_hz,dco_dbc_hz,supply_v2_per_hz,pushing_mhz_per_v`. Use single-sideband phase noise at the reference and free-running oscillator carriers, plus the one-sided PSD of the local DCO supply. The first and last offsets define the integration band and must lie below half the reference frequency. Integrate discrete spurs separately with the edge replay or a single-tone calculation.

With both options enabled at TT, 1.8 V and 25 °C, the first rising edge arrived 475 ns after enable at the nominal tune code and 545 ns at coarse zero, fine 64. A separate unfiltered tracking-replica test stepped from `49:64` to `52:128` with simultaneous selects and measured a 3.747 ns shortest period. Use `--cold-start` for startup from standby and `--step-to COARSE FINE` for a code change. Both report the shortest period and high and low pulse widths. `--aggregate-dac` groups devices on the same select waveform for a schematic probe with mismatch disabled. Use individual cells with `--step-skew-ps` to stagger the selects in each bank. [Startup data](rev4-filtered-startup.csv) · [Code transition data](rev4-dac-transition.csv)

```sh
python spice/dco_deck.py --lib "$model" --aggregate-dac --tracking-replicas --filtered-bias \
  --codes 0 --fine-codes 64 --cold-start
python spice/dco_deck.py --lib "$model" --aggregate-dac --tracking-replicas \
  --codes 49 --fine-codes 64 --step-to 52 128
```

The supply budget still depends on the routed DCO branch, package impedance, and oscillator noise. The filter remains a schematic option. Wider corner coverage and extracted tuning, tap, and supply data are needed before selecting it for integration.

## Capture timing and guard

The new RTL test checks the two Gray counters at wrap, forces one-cycle disagreements, and verifies edge selection where a counter can be changing. The compact regression also checks reset and writes against a compiled coarse-code limit. The 12-case TT, slow-cold, and fast replay grid passes with the Rev. 3 tuning and phase tables. Worst-case lock or relock was 74.63 µs, worst absolute mean frequency error was 27.64 ppm, and the highest modeled instantaneous frequency was 320.17 MHz.

The compact controller with the new phase tables maps to 51,899 µm² of Sky130 HD cells with Yosys 0.48. It occupies 62.40% of digital rows in the provisional slot. The Tcl endpoint selection was exercised against the mapped connectivity for all 24 Gray and 20 phase capture flops. Full routed timing, post-layout sampling aperture, mismatch, and integrated jitter remain open. Follow the [physical verification procedure](../physical/README.md) to establish an operating ceiling for the routed macro.
