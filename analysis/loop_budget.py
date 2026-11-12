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


def budget(mode, gain_ratio, reference_hz, output_hz):
    p_shift, i_shift = {"acquire": (4, 9), "track": (5, 11)}[mode]
    a = gain_ratio / (2**p_shift)
    b = gain_ratio / (2**i_shift)
    f = np.linspace(1e-7, 0.5, 40001)
    loop = open_loop(f, a, b)
    gain_db = 20 * np.log10(np.abs(loop))
    phase = np.unwrap(np.angle(loop))
    cross = np.flatnonzero(gain_db <= 0)[0]
    frac = gain_db[cross - 1] / (gain_db[cross - 1] - gain_db[cross])
    unity = f[cross - 1] + frac * (f[cross] - f[cross - 1])
    phase_at_unity = phase[cross - 1] + frac * (phase[cross] - phase[cross - 1])
    noise_bw = reference_hz * np.trapezoid(abs(loop / (1 + loop))**2, f)
    rms = 1 / (10 * output_hz * math.sqrt(12)) * math.sqrt(2 * noise_bw / reference_hz)
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
    args = parser.parse_args()
    for mode in ("acquire", "track"):
        for gain_ratio in (0.75, 1.0, 1.5, 2.0, 2.5):
            data = budget(mode, gain_ratio, args.ref, args.out)
            metrics = " ".join(f"{key}={value:.5g}" for key, value in data.items())
            print(f"{mode} gain_ratio={gain_ratio:g} {metrics}")


if __name__ == "__main__":
    main()
