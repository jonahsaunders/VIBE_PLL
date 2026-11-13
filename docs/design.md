# Design and integration

## Oscillator and phase detector

The Sky130A oscillator has five current-starved stages, a 255-cell tapered coarse DAC, and a 128-cell thermometer fine DAC. A current mirror attenuates the fine bank by a nominal 20:1. The controller parks the fine bank at code 64 during coarse acquisition and fixes the coarse bank during fine tracking. The fine bank covers several low-weight coarse steps. Its range and incremental gain must be checked at each operating point. Each DAC select is registered to avoid decode hazards. Both physical DAC commands freeze when the reference stops.

The five buffered ring taps form ten coarse phase intervals. Starting immediately after tap 0 rises, the legal patterns are `0b,09,0d,05,15,14,16,12,1a,0a` in hex, with tap 0 at bit 0. Three alternating-polarity replicas of each buffered tap subdivide the most recent coarse interval. After polarity correction, `000,001,011,111` are the four valid replica patterns. A bubble falls back to the center of the parent coarse interval. Replica delays and bin occupancy vary with frequency, supply, and temperature. A late replica can leave the corresponding fine bin empty.

Two 12-bit counters export registered Gray words on opposite edges of tap 0. The reference clock captures both counters and all phase taps in two stages. Short carry groups prepare each count one edge ahead so each Gray word needs only one XOR level before its register. The decoder uses the falling count plus one in coarse bins 0–2, the rising count in bins 3–6, and the falling count in bins 7–9. It concatenates the resulting count and the Q12 bin center into the modular phase word.

Coarse bins 2 and 7 sit in the middle of the two tap-0 half cycles. A parity check rejects a sample if the two Gray words disagree on the expected odd or even count difference. The check can detect a single one-cycle disagreement in these bins. The edge-selection margins still depend on routing and sampler aperture.

## Acquisition, tracking, and holdover

Acquisition starts at zero coarse code. The loop measures elapsed oscillator phase over 32 reference cycles, with at least eight reference cycles of settling after each code change. It ramps by up to eight codes below code 32 and up to 16 above that point, subject to the speed guard. Once it brackets the target, it bisects and tests the fine span at a bracket endpoint. If needed, it tests the other endpoint. When the first fine span is below four oscillator cycles per 32 reference periods, it remeasures both rails over four consecutive 32-cycle windows. The guard still checks every window. The final measurement requires positive gain and a span of at least one oscillator cycle per 32 reference periods. The Q8 rail measurements seed the integrator with a seven-cycle division. The 12-bit fractional phase detector stays active in tracking. A sustained fine rail or loss of phase lock restarts acquisition.

The proportional-integral filter operates on a Q8.16 fine code. It normalizes gain by the highest bit of the measured fine gain. Acquisition uses normalized coefficients of 2⁻⁴ and 2⁻⁹. Tracking gears 0, 1, and 2 scale the proportional coefficient by 1, 1/2, and 1/4, and the integral coefficient by 1, 1/4, and 1/16, relative to 2⁻⁵ and 2⁻¹¹. Gear 2 is the reset setting. A live gear change preserves the integrator. Optional first-order residue feedback averages fractional fine codes. Set configuration address 1 bit 12 to reduce gear 2's proportional gain by another 2× and integral gain by 4× on the ratios exactly one Q5.12 step above or below an integer. The optional setting takes effect after lock. Select it based on the application’s close-in spur and disturbance requirements.

The lock flag qualifies 64 consecutive valid samples within ±0.25 oscillator cycles. Eight consecutive invalid or large-error samples cause reacquisition. A separate DCO/2 watchdog observes reference heartbeat edges and masks lock after 127 monitor cycles without a heartbeat. The DAC codes stay static during the outage. Acquisition starts again after reference return.

## Startup speed guard

Program an integer MHz upper bound for the actual reference, including its tolerance. The reset bound is 32 MHz. For example, program 25 only when the source stays at or below 25 MHz, or 26 for a nominal 25 MHz source that can run slightly high. The loop compares the requested setpoint against 350 MHz using that upper bound. It adds one oscillator cycle to each phase measurement to cover endpoint quantization, reserves 32 MHz of headroom for fine motion, and allows a positive coarse step only when a 16 MHz per-code budget fits below 368 MHz. It rechecks the speed at the fine rails and during tracking or manual operation. The guard rounds the measured phase advance up to the next whole oscillator cycle before adding the endpoint margin. An overspeed fault clears the tune commands and masks lock. Manual mode ramps from zero to its requested coarse code at fine midscale.

The guard is a sampled estimator. Its startup envelope depends on the specified reference bound, code-zero startup frequency, and the characterized worst-case coarse step and fine excursion. Set the independent coarse ceiling from PVT and timing results. Close both counter edges and verify analog code-transition excursions before relying on a 400 MHz limit. The raw output can run at the code-zero frequency after a fault, so qualify the system clock with lock and an appropriate clock-control cell.

`MAX_COARSE_CODE` sets the wrapper's hard limit and the reset value of the programmable ceiling. Configure a lower ceiling through the existing command when the characterized operating point requires one. A write above the hard limit raises a configuration fault. If code-zero startup is initially below the running threshold, the loop retries up to three 32-cycle measurements before reporting a stalled start.

## Harness control

| Control bits | Function |
| --- | --- |
| 16:0 | Transaction payload |
| 19:17 | Transaction address |
| 20 | Request toggle |
| 21 | Enable |
| 22 | Active-low reset |
| 23 | Spare, tie low |

With the reference running, set address and payload at least one reference cycle before toggling the request. Hold both stable until the acknowledgment matches the request. Configuration is available with enable low. Reset clears configuration and calibration. `status[7:0]` is the read byte. Bits 8–11 are acknowledge, lock, calibration busy or pending, and combined fault.

| Address | Direction | Payload or readback |
| --- | --- | --- |
| 0 | Write | Unsigned Q5.12 ratio in 5.0–25.0. Reset ratio is 10.25. Select a ratio in the operating band. |
| 1 | Write | Bit 0 manual, bit 1 residue dither, bits 9:2 manual coarse code, bit 10 ten-bin phase fallback, bit 11 slow-cold fixed profile, bit 12 narrow tracking near integer. Reset uses auto, dither on, and the nominal fine phase profile. |
| 2 | Command | 1 starts code-density calibration in enabled manual mode. 2 clears calibration and restarts. 3 restarts. 4 clears configuration fault. 5, 6, and 7 select tracking gears 0, 1, and 2. |
| 2 | Command | `0x10000 + code` sets the coarse ceiling, 16–255. `0x10100 + MHz` sets the reference bound, 16–32. |
| 3 / 4 | Read | Low 8 / high 4 bits of the Q12 LUT center indexed by payload bits 5:0. |
| 5 | Read | 0 coarse code, 1 / 2 fine gain low 8 / high 5 bits, 3 watchdog/state/loop fault, 4 status detail, 5 coarse bin, 6 coarse ceiling, 7 fine sample, 8 fine code, 9 tracking gear, 10 reference upper bound, 11 on-chip calibration capability in bit 0, 12 slow-cold profile in bit 0, narrow tracking enable in bit 1, and tracking-replica build in bit 2. |
| 6 / 7 | Read | Low / high 8 bits of the histogram count indexed by payload bits 5:0. |

Diagnostic index 3 packs the three-bit loop fault, four-bit state, and synchronized watchdog in bit 7. Faults 1–7 are low rail, high rail or coarse ceiling, bad fine gain, acquisition timeout, speed guard, unbracketed fine range, and stalled startup. States 0–7 are start, settle, measure, align, track, fault, manual, and fine seed. Index 4 bits 0–7 are calibrated, manual, valid coarse phase, configuration fault, calibration fault, watchdog, run, and dither. Index 7 bits 5:0 report the fine bin, bit 6 reports coarse-only selection, and bit 7 indicates a legal fine sample. Read multi-byte values when the telemetry is stable.

## Fine phase calibration

The default `cpz4_sky130` build has two fixed phase tables. The nominal table is from the TT Sky130A probe at coarse 52, fine 64. The selectable slow-cold table is from the SS probe at 1.62 V, 0 °C, coarse 172, fine 64. Choose the profile based on operating conditions and measured tap loading. The readback gives the selected centers and zero histogram counts. A histogram-start command reports a configuration fault. Set `ON_CHIP_CAL=1` to use on-chip code-density calibration in the larger build.

`TRACKING_REPLICAS=1` selects centers for the DCO-biased replicas at the same two probe codes. Pair it with `spice/cpz4_dco_tracking.spice` or an equivalent generated netlist. Each delay stage tracks the ring's `bp` and `bn` biases. Matched output buffers isolate the internal delay chain from the sampler and interconnect load. Rebuild the phase tables if the replica sizing, load, or bias circuit changes.

Enable manual mode at a coarse code near the intended output. Give the free-running oscillator and reference enough relative drift to sample every coarse phase interval. A calibration request waits for the guarded manual ramp, then accumulates 32,768 valid fine samples and computes each center as `(2 * preceding_hits + hits + 8) >> 4`, clamped to the Q12 range. The table commits together after all ten coarse intervals meet the coverage check and at least 24 fine bins have at least 128 samples. A failed calibration retains the previous table. Each acquisition and tracking mode uses the same table. Recalibrate after large changes in oscillator frequency or operating conditions.

## Physical verification

Match the ring tap routes, replicas and samplers, including the dummy load on the final replica. Budget capture aperture and Gray-bus skew against the chosen coarse counter edge. Protect both counter clocks, the DCO/2 generated clock, and asynchronous reset recovery. Start STA with a 31.25 ns reference and the highest physically reachable acquisition frequency. The 400 MHz verification clock corresponds to a 2.5 ns period. Use independent ceiling characterization until the extracted speed guard envelope is established.

Keep the DCO supplies and DAC return quiet. Route the fine control bank with controlled skew and characterize code-step transients, fine DAC DNL and overlap, missing TDC bins, phase noise, and supply pushing before layout sign-off. The reusable analog boundary in `rtl/cpz4_sky130.sv` follows the pin order in `spice/cpz4_dco.spice`. The harness-level ports and two-pad request stay as in the proposal.
