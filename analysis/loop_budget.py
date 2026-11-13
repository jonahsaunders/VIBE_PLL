#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Sampled-loop linearization and a TDC-only jitter estimate.

Requires NumPy. The model includes one actuation cycle and two capture cycles,
plus the accumulator's own unit delay. It excludes nonlinearities and noise
other than a white, idealized detector quantizer.
"""

import argparse
import math

import numpy as np


def open_loop(normalized_frequency, a, b):
    q = np.exp(-2j * np.pi * normalized_frequency)
    return q**4 * (a + b / (1 - q)) / (1 - q)


def tracking_coefficients(gain_ratio, tracking_gear):
    return gain_ratio / 2**(5 + tracking_gear), gain_ratio / 2**(11 + 2 * tracking_gear)


def supply_tone(gear, gain_ratio, reference_hz, output_hz, offset_hz, pushing_hz_v, ripple_v, budget_ps):
    # Integrate the sinusoidal frequency deviation, then apply oscillator
    # disturbance sensitivity. The sampled model applies below ref / 2.
    loop = open_loop(offset_hz / reference_hz, *tracking_coefficients(gain_ratio, gear))
    sensitivity = abs(1 / (1 + loop))
    ps_per_v = 1e12 * pushing_hz_v / (2 * math.pi * offset_hz * output_hz * math.sqrt(2))
    return {"dco_sensitivity": sensitivity, "open_loop_tie_ps": ps_per_v * ripple_v,
            "closed_loop_tie_ps": ps_per_v * ripple_v * sensitivity,
            "ripple_budget_mv_peak": 1000 * budget_ps / (ps_per_v * sensitivity)}


def budget(mode, gain_ratio, reference_hz, output_hz, bins=40, tracking_gear=2):
    if mode == "acquire":
        a, b = gain_ratio / 2**4, gain_ratio / 2**9
    else:
        a, b = tracking_coefficients(gain_ratio, tracking_gear)
    f = np.linspace(1e-7, 0.5, 40001)
    loop = open_loop(f, a, b)
    gain_db = 20 * np.log10(np.abs(loop))
    phase = np.unwrap(np.angle(loop))
    cross = np.flatnonzero(gain_db <= 0)[0]
    frac = gain_db[cross - 1] / (gain_db[cross - 1] - gain_db[cross])
    unity = f[cross - 1] + frac * (f[cross] - f[cross - 1])
    phase_at_unity = phase[cross - 1] + frac * (phase[cross] - phase[cross - 1])
    noise_bw = reference_hz * np.trapezoid(abs(loop / (1 + loop))**2, f)
    rms = 1 / (bins * output_hz * math.sqrt(12)) * math.sqrt(2 * noise_bw / reference_hz)
    poles = np.roots([1, -2, 1, 0, a + b, -a])
    return {
        "a": a, "b": b, "unity_hz": unity * reference_hz,
        "phase_margin_deg": 180 + math.degrees(phase_at_unity),
        "noise_bw_hz": noise_bw, "tdc_rms_ps": 1e12 * rms,
        "max_pole_radius": max(abs(poles)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", type=float, default=25e6)
    parser.add_argument("--out", type=float, default=256.25e6)
    parser.add_argument("--bins", type=int, choices=(10, 40), default=40)
    parser.add_argument("--tracking-gear", type=int, choices=(0, 1, 2, 3), default=2,
                        help="gear 3 models the optional near-integer setting")
    parser.add_argument("--supply-tone", type=float, nargs=3, metavar=("OFFSET_HZ", "MHZ_PER_V", "MV_PEAK"),
                        help="model a DCO supply tone in each tracking gear")
    parser.add_argument("--tone-budget-ps", type=float, default=100,
                        help="RMS timing budget for the single supply tone")
    parser.add_argument("--gain-ratio", type=float, default=1,
                        help="actual to normalized DCO gain ratio for --supply-tone")
    args = parser.parse_args()
    if not all(math.isfinite(value) and value > 0 for value in (args.ref, args.out)):
        parser.error("reference and output frequencies must be finite and positive")
    if args.supply_tone:
        offset, pushing, ripple = args.supply_tone
        if not all(math.isfinite(value) and value > 0 for value in
                   (offset, pushing, ripple, args.tone_budget_ps, args.gain_ratio)) or offset >= args.ref / 2:
            parser.error("the supply tone requires positive finite inputs and an offset below reference / 2")
        for gear in range(4):
            data = supply_tone(gear, args.gain_ratio, args.ref, args.out, offset, pushing * 1e6,
                               ripple * 1e-3, args.tone_budget_ps)
            print(f"track gear={gear} " + " ".join(f"{key}={value:.5g}" for key, value in data.items()))
        return
    for mode in ("acquire", "track"):
        for gain_ratio in (0.75, 1.0, 1.5, 2.0, 2.5):
            data = budget(mode, gain_ratio, args.ref, args.out, args.bins, args.tracking_gear)
            metrics = " ".join(f"{key}={value:.5g}" for key, value in data.items())
            print(f"{mode} gain_ratio={gain_ratio:g} {metrics}")


if __name__ == "__main__":
    main()
