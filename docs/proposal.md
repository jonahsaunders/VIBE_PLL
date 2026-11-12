# Chipalooza Challenge #4 proposal

## IP and operation

A 1.8 V Sky130 fractional-N SoC clock multiplier. A five-stage current-starved ring provides ten phase bins. Dual-edge coarse phase capture and an optional code-density LUT feed a phase-domain PI loop. The controller brackets the output frequency, estimates local DCO gain, and changes loop gains when it qualifies lock. A DCO-clocked watchdog supports reference-loss detection and holdover. The loop filter and oscillator bias are internal.

## Ports and pads

| Port | Direction | Use |
| --- | --- | --- |
| REF_CLK | Input | Request one dedicated 3.3 V digital peripheral pad with approved 1.8 V receiver |
| CLK_MON | Output | Request one dedicated 3.3 V digital peripheral pad driven by DCO/4 |
| CLK_OUT | Output | Raw 1.8 V on-chip clock for reusable macro |
| CTRL[23:0] | Input | Twenty-three slot controls used for config and enable, one spare |
| STATUS[11:0] | Output | Configuration readback, acknowledge, lock, calibration busy and fault |
| VDD_CORE, VDD_DCO, VSS | Supply | Harness-approved 1.8 V core supply branches and ground |

The macro uses two dedicated pads and zero shared analog signals. It needs no external loop filter, bias source, or reference voltage. The slot pinout and pad choice follow the official wrapper when released.

## Target specification

| Parameter | Minimum | Typical | Maximum / target |
| --- | ---: | ---: | --- |
| Reference frequency | 16 MHz | 25 MHz | 32 MHz |
| Reference duty | 45% | 50% | 55% |
| Locked core output | 160 MHz | 256.25 MHz | 300 MHz |
| Output monitor | 40 MHz | 64.0625 MHz | 75 MHz |
| Q5.12 ratio field | 5.0 | 10.25 | 25.0 |
| Core supply | 1.62 V | 1.80 V | 1.95 V |
| Temperature | 0 °C | 25 °C | 85 °C |
| Lock / relock time | | | 100 µs, LUT already loaded or disabled |
| Mean frequency error | | | ±100 ppm over ≥4,096 DCO cycles after lock |
| Reference-loss detection | | | 2 µs at an in-band output |
| Nominal active core power | | | 8 mW, excluding pads |
| Standalone core area | | | 0.10 mm² planning target |
| Nominal integrated jitter | | | 300 ps rms, 10 kHz–10 MHz at 256.25 MHz including spurs |

Valid operation uses ratios that put the output inside 160–300 MHz. The frequency increment is reference/4,096 (6.1035 kHz at 25 MHz). On-chip nodes use the 1.8 V domain and have a 1.95 V model ceiling. Apply only rated peripheral voltages through the chosen approved 3.3 V pads. Absolute electrical limits of the external pad pins follow the approved pad cell. Configure the DCO code ceiling to the characterized high-speed path limit before enabling hardware.

## Measurement plan

1. Apply a low-jitter calibrated reference at 16, 25 and 32 MHz. Measure divided output and lock on enable, at valid integer and fractional retunes, and on unsupported ratios. Refer mean accuracy to the applied reference.
2. Sweep manual tune codes within the permitted ceiling, estimate DCO gain, and compare LUTs from two asynchronous calibration offsets. Test the expected rejection of a coherent histogram.
3. Remove and restore the reference. Time lock deassertion and reacquisition while checking that DCO/4 continues in holdover.
4. Measure phase noise and discrete spurs on integer, quarter, half and near-integer ratios. Record period jitter separately. De-embed additive pad/divider noise and report integration bands and the floor of the setup.
5. Measure enabled-minus-disabled current and clock characteristics over voltage and temperature. Check extracted supply-pushing sensitivity and phase-capture routing before the slot review.

Equipment availability and designer CVs accompany the main proposal separately. The design sources use Apache-2.0. Sign-off requires standalone and harness layout, DRC/LVS, full extracted PVT, and measured characterization.

[Official Challenge #4 rules](https://opencircuitdesign.com/chipalooza/rules-4.html) · [Milestone schedule](https://opencircuitdesign.com/chipalooza/schedule-4.html)
