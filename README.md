# Sky130 fractional-N PLL for Chipalooza Challenge #4

A proposal-stage SoC clock macro with a phase-domain all-digital loop and a transistor-level Sky130A ring oscillator.

The proposed core output is **160–300 MHz**, with a **16–32 MHz** reference and a Q5.12 ratio. Choose combinations within the output band. The nominal channel is 25 MHz to 256.25 MHz. The core uses 1.8 V. A dedicated reference pad and a dedicated divided monitor pad are requested.

- [Literature review and design report](chipalooza4-sky130-pll-report.pdf)
- [Challenge proposal](docs/proposal.md)
- [Design, controls, and timing](docs/design.md)
- [Verification results](results/README.md)

## Reproduce the results

Python 3.10+ and Icarus Verilog 12+ run the RTL tests. ngspice and an open_pdks Sky130A device model library run the circuit characterization. NumPy is needed only for the linear model and spectral analysis.

```sh
python tests/run_rtl.py
python analysis/loop_budget.py
python spice/dco_deck.py --emit spice/cpz4_dco.spice
python spice/dco_deck.py --lib "$PDK_ROOT/sky130A/libs.tech/ngspice/sky130.lib.spice" \
  --corner tt --vdd 1.8 --temp 25 --codes 0,24,48,57,58,59,60,72,88,104,128,160,192,224,255 \
  --output tt.csv
python tests/run_rtl.py --spice-data tt.csv --ref 25
python tests/run_rtl.py --spice-data tt.csv --start 40961 --spectrum edges.csv
python analysis/spectrum.py edges.csv
```

Use `--iverilog` and `--vvp` if those programs are outside PATH. For ngspice, set `--ngspice` to a CLI executable or `--ngspice-dll` to a compatible shared library. `--keep-waveform` can retain the SPICE waveforms on demand. The circuit generator and netlist are kept together so sizing can be changed and the view regenerated. This archive contains the original design under Apache-2.0 and references the Sky130 models as an external dependency.

## Implementation status

The RTL compiles as a stand-alone logical boundary. Circuit measurements are schematic-level and use open Sky130A MOS, poly resistor, and MIM capacitor models. The co-simulation replays interpolated oscillator frequencies and tap widths from sampled codes. Synthesis, physical CDC checks, extracted noise, complete PVT and mismatch sign-off, and harness layout are required before tapeout.
