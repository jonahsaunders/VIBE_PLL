# Design and integration

## Clock domains and phase

The five buffered ring taps produce ten legal phase patterns per cycle. Starting immediately after tap 0 rises, they are `0b,09,0d,05,15,14,16,12,1a,0a` (hex, bit 0 is tap 0). Two 12-bit counters run on opposite edges of tap 0. They use registered Gray outputs and predicted carry for the four-bit counter chunks. Reset release on the positive edge means the falling counter starts at −1 and advances to zero on its first edge.

Sample both Gray buses and all taps on the reference clock, with two capture stages. Use falling count + 1 for bins 0–2, rising count for bins 3–6, and falling count for bins 7–9. Q12 bin centers form the low 12 bits of a 24-bit modular phase word. The phase selector avoids counting on a coarse edge close to the sampled transition. It requires constrained routing and a measured skew budget.

The frequency search starts at code 0, ramps by 8 below code 32 and 16 above, and bisects after bracketing. Each observation starts after eight guard ticks and spans 32 reference cycles. Two observations across an eight-code interval provide a local gain in Q12 cycles per reference per code. The filter selects the highest gain bit and uses power-of-two normalization. Its nominal normalized proportional/integral constants are 1/16 and 1/512 in acquisition, 1/32 and 1/2048 in tracking, multiplied by true gain divided by the estimated power of two. The Q8.16 integrator and control output saturate at the programmed ceiling. Optional first-order residue feedback averages fractional DCO codes. The single registered thermometer output per cell avoids binary decoder glitches. At the low end, 80 longer-channel DAC sinks provide smaller tuning steps. Seven groups gradually increase device strength and restore drive range at high codes. This taper makes local gain measurement important at group transitions.

Two sample cycles, one register cycle, and the oscillator's integration delay produce the z^-4 factor used in `analysis/loop_budget.py`. The lock flag qualifies 64 consecutive valid samples within ±0.25 DCO cycles. Eight consecutive errors beyond ±0.5 cycles after lock, or eight invalid samples, restart the search. The lock flag is a phase qualification. The mean-frequency accuracy target uses a separate counter measurement over at least 4,096 DCO cycles.

A watchdog runs on DCO/2 and observes reference heartbeat edges. It trips after 127 monitor cycles with no edge, masks lock, and holds the last physical tune code while reference edges are absent. After the reference acknowledges the trip, the controller reacquires. Both clocks are needed to observe and qualify a system-clock failure. If both stop, the status cannot serve as an independent health monitor.

## Harness control

| Control bits | Function |
| --- | --- |
| 16:0 | Transaction payload |
| 19:17 | Transaction address |
| 20 | Request toggle |
| 21 | Enable |
| 22 | Active-low reset |
| 23 | Spare, tie low |

After reset the acknowledgment is 0. With a live reference, set the address and payload, keep them stable at least one reference cycle, then toggle the request. Hold both until acknowledgment equals the request. Allow a reference edge after acknowledgment before consuming the returned byte. This is a bundled-data handshake. The toggle is synchronized internally. Configuration is possible with enable low. Reset clears the configuration, histogram, and LUT.

| Address | Direction | Payload / readback |
| --- | --- | --- |
| 0 | Write | Unsigned Q5.12 ratio in 5.0–25.0. Default 41984 = 10.25. Keep the actual output in the proposed band. |
| 1 | Write | Bit 0 manual, bit 1 residue dither, bits 9:2 manual code. Reset is auto with dither enabled. Manual bypasses the phase loop. |
| 2 | Command | 1 start code-density calibration in manual mode, 2 clear calibration and restart, 3 restart, 4 clear configuration fault. 0x10000 + code sets the code ceiling in 16–255. Reset ceiling is 255. |
| 3 / 4 | Read | Low 8 / high 4 bits of Q12 LUT center indexed by payload bits 3:0 |
| 5 | Read | Index 0 requested DCO code, 1 / 2 gain low 8 / high 5 bits, 3 watchdog/state/loop fault, 4 status detail, 5 current bin, 6 code ceiling |
| 6 / 7 | Read | Histogram low 8 / high 7 bits indexed by payload bits 3:0 |

`status[7:0]` is the read byte. Bits 8–11 are acknowledge, lock, calibration busy, and combined fault. At diagnostic address 5 index 3, bits 2:0 are loop fault, 6:3 are state, and 7 is the synchronized watchdog trip. Loop faults 1–4 are low rail, code ceiling/high rail, invalid measured gain, and acquisition timeout. States 0–6 are start, settle, measure, align, track, fault, and manual. Index 4 bits 0–7 are calibrated, manual, valid phase, config error, calibration error, watchdog trip, run, and dither. Read multi-byte telemetry when the value is stable.

For calibration, set a fixed manual code and drive an uncorrelated or deliberately swept reference. Collect 16,384 valid samples. The hardware calculates center[i] = (2 × preceding hits + hits[i] + 4) >> 3 and commits the entire table together. The nominal occupancy window per bin is 512–4,096. Coherent or missing bins trigger failure while retaining the last good table. Compare two independent reference offsets for a production calibration. Mode and ceiling changes are rejected during collection. Read back bins and counts after busy clears. Repeat calibration after significant tuning, voltage, or temperature changes when the application needs improved linearity.

## Physical implementation and verification gates

Use matched tap buffer and sampler routes. Preserve the capture flops and constrain Gray-bus skew at the first capture bank against the minimum measured time from the selected counter edge to the sampling window. Verify recovery/removal at each local reset and protect the inverted tap-0 clock and DCO/2 generated clock. Start constraints with 31.25 ns reference period and use the highest **acquisition** or allowed manual DCO frequency for the high-speed clock. Check both polarities and the short duty-cycle case. Include thermometer routing and analog settling in the verification.

The full analog code range is a characterization facility. It can produce frequencies beyond the SoC operating band, especially at FF. Provision a safe code ceiling before enabling hardware under test. Set that ceiling from process-aware DCO characterization and extracted STA. Use lock to qualify the core clock and an SoC clock-control cell when switching between it and another source. The raw macro clock is continuous during reference holdover, and stopping or resetting the oscillator can shorten its last period.

The open-source flow uses ngspice for schematic and extracted electrical verification, a synthesis/STA flow with the chosen Sky130 libraries, Magic or KLayout for layout and DRC, and Netgen or KLayout for LVS. The DCO-to-digital interface is the `cpz4_dco` black box in `rtl/cpz4_sky130.sv`. Route both VDD_CORE and VDD_DCO to harness-approved 1.8 V supplies, with a quiet local DCO supply branch and decoupling. Verify tap skew, gain and monotonicity, supply pushing, extracted phase noise, clock transients, and bench measurements before treating the proposal targets as met.
