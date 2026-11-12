#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the PLL testbench with abstract plants or an interpolated SPICE sweep."""

import argparse
import csv
import math
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
RTL = [ROOT / "rtl" / name for name in
       ("phase_sampler.sv", "loop_control.sv", "phase_cal.sv", "cpz4_pll.sv", "cpz4_sky130.sv")]
SCENARIOS = {
    "nominal": ["+calibrate"],
    "slow_endpoint": ["+ref=16", "+low=75", "+high=425", "+curve=-0.20", "+edge=76800"],
    "fast_endpoint": ["+ref=32", "+low=145", "+high=565", "+curve=0.25", "+start_n=37888", "+retune_n=36864", "+edge=20480"],
    "fast_low_rail": ["+ref=16", "+low=145", "+high=565", "+curve=0.25"],
}


def coarse_curve(points, max_code):
    codes = sorted(points)
    if len(codes) < 2 or codes[0] != 0 or codes[-1] != max_code:
        raise ValueError("Each fine setting needs coarse code zero and the same highest code")
    if any(points[b][0] <= points[a][0] for a, b in zip(codes, codes[1:])):
        raise ValueError("Nonmonotonic coarse sweep")
    interval = 0
    for code in range(max_code + 1):
        if code > codes[interval + 1]:
            interval += 1
        lo, hi = codes[interval:interval + 2]
        ratio = (code - lo) / (hi - lo)
        values = [a + ratio * (b - a) for a, b in zip(points[lo], points[hi])]
        total_width = sum(values[1:])
        yield [values[0], *(width / total_width for width in values[1:])]


def spice_table(source, destination):
    with source.open(newline="", encoding="ascii") as file:
        rows = list(csv.DictReader(file))
    if not rows or "fine_code" not in rows[0]:
        raise ValueError("Provide a coarse/fine DCO sweep from one PVT condition")
    pvt = {(r["corner"], float(r["vdd"]), float(r["temp_c"])) for r in rows}
    if len(pvt) != 1:
        raise ValueError("Provide a coarse/fine DCO sweep from one PVT condition")
    sweeps = {}
    for row in rows:
        coarse, fine = int(row["code"]), int(row["fine_code"])
        points = sweeps.setdefault(fine, {})
        if coarse in points or not (0 <= coarse <= 255 and 0 <= fine <= 128):
            raise ValueError(f"Duplicate or invalid DCO code {coarse}:{fine}")
        if int(row["bad_tap_sequences"]) or int(row["bad_fine_sequences"]):
            raise ValueError(f"Illegal phase tap order at {coarse}:{fine}")
        values = [float(row["frequency_mhz"])] + [float(row[f"fine_bin_{i}_ui"]) for i in range(40)]
        if (not all(math.isfinite(value) and value >= 0 for value in values) or
            values[0] <= 0 or not math.isclose(sum(values[1:]), 1, abs_tol=1e-5)):
            raise ValueError(f"Invalid phase-bin or frequency at {coarse}:{fine}")
        points[coarse] = values

    anchors = sorted(sweeps)
    if len(anchors) > 128 or anchors[0] != 0 or anchors[-1] != 128:
        raise ValueError("Include fine rail codes 0 and 128 and at most 128 anchors")
    max_code = max(max(points) for points in sweeps.values())
    curves = [coarse_curve(sweeps[fine], max_code) for fine in anchors]
    with destination.open("w", encoding="ascii") as file:
        file.write(f"{len(anchors)} {max_code}\n" + " ".join(map(str, anchors)) + "\n")
        for code, entries in enumerate(zip(*curves)):
            if any(b[0] <= a[0] for a, b in zip(entries, entries[1:])):
                raise ValueError(f"Nonmonotonic interpolated fine sweep at code {code}")
            for values in entries:
                file.write(" ".join(f"{value:.10f}" for value in values) + "\n")
    return max_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    parser.add_argument("--trace", type=Path, help="write a nominal transient trace CSV")
    parser.add_argument("--spice-data", type=Path, help="use a single PVT DCO sweep CSV")
    parser.add_argument("--ref", type=float, default=25.0, help="reference MHz for --spice-data")
    parser.add_argument("--edge", type=int, help="additional Q5.12 ratio for --spice-data")
    parser.add_argument("--start", type=int, help="initial Q5.12 ratio for --spice-data or --spectrum")
    parser.add_argument("--retune", type=int, help="second Q5.12 ratio for --spice-data")
    parser.add_argument("--spectrum", type=Path, help="capture 131072 raw edges at the initial ratio")
    parser.add_argument("--tracking-gear", type=int, choices=(0, 1, 2))
    parser.add_argument("--calibrate", action="store_true", help="load a manual code-density LUT")
    parser.add_argument("--cal-code", type=int, default=70, help="manual coarse code for calibration")
    parser.add_argument("--fixed-centers", action="store_true", help="use the area-saving fixed TDC table")
    parser.add_argument("--coarse-phase", action="store_true", help="use the ten-bin detector for the loop")
    parser.add_argument("--startup-delay-ps", type=float, default=173.209,
                        help="initial oscillator phase offset in the behavioral plant")
    args = parser.parse_args()
    if args.fixed_centers and args.calibrate:
        parser.error("--calibrate requires on-chip calibration")
    with tempfile.TemporaryDirectory(prefix="cpz4-rtl-") as temp:
        build = Path(temp)
        output = build / "tb_pll.vvp"
        common = [args.iverilog, "-g2012", "-Wall", "-Wno-timescale"]
        parameter = int(not args.fixed_centers)
        subprocess.run([*common, "-s", "cpz4_sky130", f"-Pcpz4_sky130.ON_CHIP_CAL={parameter}",
                        "-t", "null", *RTL], check=True)
        if not args.spice_data and not args.spectrum:
            counter = build / "tb_edge_counter.vvp"
            subprocess.run([*common, "-s", "tb_edge_counter", "-o", counter, RTL[0],
                            ROOT / "tests" / "tb_edge_counter.sv"], check=True)
            subprocess.run([args.vvp, counter], check=True)
        subprocess.run([*common, "-s", "tb_pll", f"-Ptb_pll.ON_CHIP_CAL={parameter}",
                        "-o", output, *RTL, ROOT / "tests" / "tb_pll.sv"], check=True)
        if args.spice_data:
            table = build / "dco.txt"
            max_code = spice_table(args.spice_data, table)
            extra = [f"+spice_table={table}", f"+ref={args.ref}", f"+code_ceiling={max_code}"]
            for name, value in (("edge", args.edge), ("start_n", args.start), ("retune_n", args.retune)):
                if value is not None:
                    extra.append(f"+{name}={value}")
            if args.spectrum:
                extra.append(f"+spectrum={args.spectrum.resolve()}")
            scenarios = {"spice_interpolated": extra}
        elif args.spectrum:
            extra = [f"+spectrum={args.spectrum.resolve()}"]
            if args.start is not None:
                extra.append(f"+start_n={args.start}")
            scenarios = {"behavioral_spectrum": extra}
        else:
            scenarios = {label: [arg for arg in options if arg != "+calibrate" or not args.fixed_centers]
                         for label, options in SCENARIOS.items()}
        for label, options in scenarios.items():
            print(f"CASE {label}", flush=True)
            command = [args.vvp, output, *options, f"+startup_delay_ps={args.startup_delay_ps}"]
            if args.tracking_gear is not None:
                command.append(f"+tracking_gear={args.tracking_gear}")
            if args.calibrate:
                command += ["+precalibrate", f"+cal_code={args.cal_code}"]
            if args.coarse_phase:
                command.append("+coarse_phase")
            if args.trace and label in ("nominal", "spice_interpolated"):
                command.append(f"+trace={args.trace.resolve()}")
            subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
