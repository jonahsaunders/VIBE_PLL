#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Measure deterministic spectral lines from simulated raw clock edges.

This is an edge-time model. It includes quantization and the chosen oscillator
transfer curve. It does not model device noise, supply modulation or pad jitter.
Requires NumPy.
"""

import argparse
import numpy as np


def estimate(times, lower_hz, upper_hz):
    index = np.arange(len(times))
    times = (times - times[0]) * 1e-12
    period, intercept = np.polyfit(index, times, 1)
    clock_hz = 1 / period
    tie = times - (index * period + intercept)
    window = np.hanning(len(times))
    envelope = np.exp(-2j * np.pi * clock_hz * tie)
    spectrum = abs(np.fft.fft(window * envelope))
    offsets = np.fft.fftfreq(len(times), period)
    candidate = np.flatnonzero((abs(offsets) >= lower_hz) & (abs(offsets) <= upper_hz))
    if not len(candidate):
        raise ValueError("No FFT bin is inside the requested offset range")
    peak = candidate[np.argmax(spectrum[candidate])]
    return {
        "clock_mhz": clock_hz / 1e6,
        "rms_tie_ps": np.std(tie) * 1e12,
        "offset_hz": offsets[peak],
        "strongest_line_dbc": 20 * np.log10(spectrum[peak] / spectrum[0]),
        "resolution_hz": clock_hz / len(times),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("edges")
    parser.add_argument("--lower", type=float, default=1e4)
    parser.add_argument("--upper", type=float, default=1e7)
    args = parser.parse_args()
    data = estimate(np.loadtxt(args.edges, skiprows=1), args.lower, args.upper)
    print(" ".join(f"{key}={value:.6g}" for key, value in data.items()))


if __name__ == "__main__":
    main()
