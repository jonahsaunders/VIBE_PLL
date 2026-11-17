#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Sampled-loop linearization, jitter estimates, and supply tone budgets.

Requires NumPy. The model includes one actuation cycle and three capture cycles,
plus the accumulator's own unit delay. The default estimate uses an idealized
detector quantizer. Optional spectra supply reference, DCO, and rail noise.
"""

import argparse
import math

import numpy as np


def open_loop(normalized_frequency, a, b):
    q = np.exp(-2j * np.pi * normalized_frequency)
    return q**5 * (a + b / (1 - q)) / (1 - q)


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


def noise_budget(gear, gain_ratio, reference_hz, output_hz, spectra):
    offsets, reference, dco, supply, pushing = spectra
    loop = open_loop(offsets / reference_hz, *tracking_coefficients(gain_ratio, gear))
    detector_response = abs(loop / (1 + loop)) ** 2
    oscillator_response = abs(1 / (1 + loop)) ** 2
    # SSB phase noise in dBc/Hz converts to one-sided phase PSD by a factor of two.
    reference_psd = 2 * 10**(reference / 10) * (output_hz / reference_hz)**2 * detector_response
    dco_psd = 2 * 10**(dco / 10) * oscillator_response
    supply_psd = supply * (pushing * 1e6 / offsets)**2 * oscillator_response
    variances = np.trapezoid([reference_psd, dco_psd, supply_psd], offsets, axis=1)
    jitter_ps = np.sqrt(variances) * 1e12 / (2 * math.pi * output_hz)
    return {"reference_rms_ps": jitter_ps[0], "dco_rms_ps": jitter_ps[1], "supply_rms_ps": jitter_ps[2],
            "total_rms_ps": np.linalg.norm(jitter_ps)}


def read_noise_spectra(path, reference_hz):
    columns = ("offset_hz", "reference_dbc_hz", "dco_dbc_hz", "supply_v2_per_hz", "pushing_mhz_per_v")
    rows = np.genfromtxt(path, delimiter=",", names=True, encoding="ascii", ndmin=1)
    if rows.size < 2 or not set(columns).issubset(rows.dtype.names or ()):
        raise ValueError("Provide at least two CSV rows with columns " + ", ".join(columns))
    spectra = np.array([rows[name] for name in columns])
    offsets = spectra[0]
    if (not np.all(np.isfinite(spectra)) or np.any(spectra[3:] < 0) or offsets[0] <= 0 or
        offsets[-1] >= reference_hz / 2 or np.any(np.diff(offsets) <= 0)):
        raise ValueError("Use finite spectra with increasing offsets inside (0, reference / 2) and nonnegative supply PSD and pushing")
    return spectra


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
    poles = np.roots([1, -2, 1, 0, 0, a + b, -a])
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
    noise_group = parser.add_mutually_exclusive_group()
    noise_group.add_argument("--supply-tone", type=float, nargs=3, metavar=("OFFSET_HZ", "MHZ_PER_V", "MV_PEAK"),
                             help="model a DCO supply tone in each tracking gear")
    noise_group.add_argument("--noise-spectra", help="integrate reference, DCO, and supply spectra from a CSV")
    parser.add_argument("--tone-budget-ps", type=float, default=100,
                        help="RMS timing budget for the single supply tone")
    parser.add_argument("--gain-ratio", type=float, default=1,
                        help="actual to normalized DCO gain ratio for a tone or noise budget")
    args = parser.parse_args()
    if not all(math.isfinite(value) and value > 0 for value in (args.ref, args.out, args.gain_ratio)):
        parser.error("reference and output frequencies and gain ratio must be finite and positive")
    if args.supply_tone:
        offset, pushing, ripple = args.supply_tone
        if not all(math.isfinite(value) and value > 0 for value in
                   (offset, pushing, ripple, args.tone_budget_ps)) or offset >= args.ref / 2:
            parser.error("the supply tone requires positive finite inputs and an offset below reference / 2")
        for gear in range(4):
            data = supply_tone(gear, args.gain_ratio, args.ref, args.out, offset, pushing * 1e6,
                               ripple * 1e-3, args.tone_budget_ps)
            print(f"track gear={gear} " + " ".join(f"{key}={value:.5g}" for key, value in data.items()))
        return
    if args.noise_spectra:
        try:
            spectra = read_noise_spectra(args.noise_spectra, args.ref)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        for gear in range(4):
            data = noise_budget(gear, args.gain_ratio, args.ref, args.out, spectra)
            print(f"track gear={gear} " + " ".join(f"{key}={value:.5g}" for key, value in data.items()))
        return
    for mode in ("acquire", "track"):
        for gain_ratio in (0.75, 1.0, 1.5, 2.0, 2.5):
            data = budget(mode, gain_ratio, args.ref, args.out, args.bins, args.tracking_gear)
            metrics = " ".join(f"{key}={value:.5g}" for key, value in data.items())
            print(f"{mode} gain_ratio={gain_ratio:g} {metrics}")


if __name__ == "__main__":
    main()
