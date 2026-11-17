#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the PLL testbench with abstract plants or an interpolated SPICE sweep."""

import argparse
import csv
import json
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


def phase_centers(widths):
    total = sum(widths)
    edge = 0.0
    centers = []
    for width in widths:
        centers.append(min(4095, int(4096 * (edge + width / 2) / total + 0.5)))
        edge += width
    return centers


def spice_table(source, destination, *, ideal_quarter_bins=False, lut_point=None, phase_shape=None,
                coarse_only=False):
    with source.open(newline="", encoding="ascii") as file:
        rows = list(csv.DictReader(file))
    if not rows or "fine_code" not in rows[0]:
        raise ValueError("Provide a coarse/fine DCO sweep from one PVT condition")
    pvt = {(r["corner"], float(r["vdd"]), float(r["temp_c"])) for r in rows}
    if len(pvt) != 1:
        raise ValueError("Provide a coarse/fine DCO sweep from one PVT condition")
    proportions = [0.25] * 40 if ideal_quarter_bins else None
    if phase_shape is not None:
        with phase_shape.open(newline="", encoding="ascii") as file:
            shapes = list(csv.DictReader(file))
        if len(shapes) != 1:
            raise ValueError("Provide one SPICE row for the replacement phase shape")
        shape = shapes[0]
        if (shape["corner"], float(shape["vdd"]), float(shape["temp_c"])) not in pvt:
            raise ValueError("The replacement phase shape and sweep must have the same PVT condition")
        if int(shape["bad_tap_sequences"]) or int(shape["bad_fine_sequences"]):
            raise ValueError("The replacement phase shape has an illegal tap sequence")
        widths = [float(shape[f"fine_bin_{i}_ui"]) for i in range(40)]
        if (not all(math.isfinite(width) and width >= 0 for width in widths) or
            not math.isclose(sum(widths), 1, abs_tol=1e-5)):
            raise ValueError("Invalid replacement phase-bin widths")
        proportions = []
        for start in range(0, 40, 4):
            group = widths[start:start + 4]
            if sum(group) <= 0:
                raise ValueError("The replacement phase shape must cover all coarse intervals")
            proportions.extend(width / sum(group) for width in group)
    sweeps = {}
    for row in rows:
        coarse, fine = int(row["code"]), int(row["fine_code"])
        points = sweeps.setdefault(fine, {})
        if coarse in points or not (0 <= coarse <= 255 and 0 <= fine <= 128):
            raise ValueError(f"Duplicate or invalid DCO code {coarse}:{fine}")
        has_coarse = coarse_only and all(row.get(f"bin_{i}_ui") for i in range(10))
        if int(row["bad_tap_sequences"]) or (not has_coarse and int(row["bad_fine_sequences"])):
            raise ValueError(f"Illegal phase tap order at {coarse}:{fine}")
        if has_coarse:
            widths = [width for i in range(10)
                      for width in (float(row[f"bin_{i}_ui"]), 0.0, 0.0, 0.0)]
        else:
            widths = [float(row[f"fine_bin_{i}_ui"]) for i in range(40)]
        values = [float(row["frequency_mhz"]), *widths]
        if (not all(math.isfinite(value) and value >= 0 for value in values) or
            values[0] <= 0 or not math.isclose(sum(values[1:]), 1, abs_tol=1e-5)):
            raise ValueError(f"Invalid phase-bin or frequency at {coarse}:{fine}")
        if proportions is not None:
            # Preserve the measured coarse edges and the entire tuning curve.
            for start in range(0, 40, 4):
                interval = sum(values[start + 1:start + 5])
                values[start + 1:start + 5] = [interval * share for share in proportions[start:start + 4]]
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
    if lut_point is not None:
        coarse, fine = lut_point
        if fine not in sweeps or coarse not in sweeps[fine]:
            raise ValueError(f"Phase LUT point {coarse}:{fine} must be present in the sweep")
        centers = phase_centers(sweeps[fine][coarse][1:])
        destination.with_suffix(".lut").write_text(
            "".join(f"{center:03x}\n" for center in centers), encoding="ascii")
    return max_code


def corner_grid():
    """Sample both output endpoints and one intermediate channel at each PVT."""
    ratios = {
        16: (40960, 76800, 65664),
        20: (32768, 61440, 48128),
        25: (26215, 49152, 41984),
        32: (20480, 38400, 32769),
    }
    for corner, filename in (("tt", "rev2-tt.csv"), ("ss-cold", "rev3-ss-cold.csv"), ("ff", "rev2-ff.csv")):
        for reference, (start, retune, edge) in ratios.items():
            yield corner, ROOT / "results" / filename, reference, start, retune, edge


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    parser.add_argument("--compiled-testbench", type=Path,
                        help="reuse a tb_pll.vvp compiled with the matching calibration and replica settings")
    parser.add_argument("--trace", type=Path, help="write a nominal transient trace CSV")
    parser.add_argument("--report", type=Path, help="write the outcome of each scenario as JSON")
    parser.add_argument("--spice-data", type=Path, help="use a single PVT DCO sweep CSV")
    parser.add_argument("--corner-grid", action="store_true", help="run the fixed-center PVT regression grid")
    parser.add_argument("--ref", type=float, default=25.0, help="reference MHz for --spice-data")
    parser.add_argument("--edge", type=int, help="additional Q5.12 ratio for --spice-data")
    parser.add_argument("--start", type=int, help="initial Q5.12 ratio for --spice-data or --spectrum")
    parser.add_argument("--retune", type=int, help="second Q5.12 ratio for --spice-data")
    parser.add_argument("--spectrum", type=Path, help="capture raw edges at the initial ratio")
    parser.add_argument("--spectrum-edges", type=int, default=131072, help="raw edges to capture")
    parser.add_argument("--spectrum-settle", type=int, default=4096, help="reference cycles before capture")
    parser.add_argument("--tracking-gear", type=int, choices=(0, 1, 2))
    parser.add_argument("--calibrate", action="store_true", help="load a manual code-density LUT")
    parser.add_argument("--cal-code", type=int, default=70, help="manual coarse code for calibration")
    parser.add_argument("--fixed-centers", action="store_true", help="use the area-saving fixed TDC table")
    parser.add_argument("--coarse-phase", action="store_true", help="use the ten-bin detector for the loop")
    parser.add_argument("--slow-phase-profile", action="store_true", help="use the slow-cold fixed table")
    parser.add_argument("--tracking-replicas", action="store_true",
                        help="use the tracking-replica fixed tables with a matching SPICE sweep")
    parser.add_argument("--range-dco", action="store_true", help="use the range-DCO extracted phase tables")
    parser.add_argument("--phase-lut-point", type=int, nargs=2, metavar=("COARSE", "FINE"),
                        help="derive the fixed replay LUT from this measured sweep point")
    phase_group = parser.add_mutually_exclusive_group()
    phase_group.add_argument("--ideal-quarter-bins", action="store_true",
                             help="split each measured coarse interval into equal quarters in the replay")
    phase_group.add_argument("--phase-shape", type=Path,
                             help="use the fine-bin proportions from a single SPICE probe at the same PVT")
    parser.add_argument("--no-dither", action="store_true", help="disable fine-DAC residue feedback")
    parser.add_argument("--narrow-near-integer", action="store_true",
                        help="reduce tracking bandwidth one step at +/-1 LSB from integer ratios")
    parser.add_argument("--startup-delay-ps", type=float, default=173.209,
                        help="initial oscillator phase offset in the behavioral plant")
    args = parser.parse_args()
    if args.range_dco and not args.tracking_replicas:
        parser.error("--range-dco requires --tracking-replicas")
    if args.fixed_centers and args.calibrate:
        parser.error("--calibrate requires on-chip calibration")
    if args.corner_grid and (not args.fixed_centers or args.spice_data or args.spectrum):
        parser.error("--corner-grid requires --fixed-centers and uses the repository sweeps")
    if args.slow_phase_profile and (not args.fixed_centers or args.coarse_phase):
        parser.error("--slow-phase-profile requires the fixed fine detector")
    if args.tracking_replicas and (not args.spice_data or not args.fixed_centers):
        parser.error("--tracking-replicas requires a matching SPICE sweep and fixed centers")
    if args.phase_lut_point and (not args.spice_data or not args.fixed_centers or
                                 args.coarse_phase or args.slow_phase_profile):
        parser.error("--phase-lut-point requires a single SPICE sweep and the fixed fine detector")
    if args.ideal_quarter_bins and not args.phase_lut_point:
        parser.error("--ideal-quarter-bins requires --phase-lut-point for the matching phase centers")
    if args.phase_shape and (not args.spice_data or not args.fixed_centers or args.coarse_phase or
                             not (args.tracking_replicas or args.phase_lut_point)):
        parser.error("--phase-shape requires a single SPICE sweep and matching fixed phase centers")
    if args.spectrum_edges < 2 or args.spectrum_settle < 0:
        parser.error("spectrum capture requires at least two edges and nonnegative settling")
    compiled = args.compiled_testbench.resolve(strict=True) if args.compiled_testbench else None
    results = []
    if args.report:
        args.report.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="cpz4-rtl-") as temp:
        build = Path(temp)
        output = compiled or build / "tb_pll.vvp"
        common = [args.iverilog, "-g2012", "-Wall", "-Wno-timescale"]
        parameter = int(not args.fixed_centers)
        replicas = int(args.tracking_replicas)
        range_dco = int(args.range_dco)
        if compiled is None:
            subprocess.run([*common, "-s", "cpz4_sky130", f"-Pcpz4_sky130.ON_CHIP_CAL={parameter}",
                            f"-Pcpz4_sky130.TRACKING_REPLICAS={replicas}", f"-Pcpz4_sky130.RANGE_DCO={range_dco}",
                            "-t", "null", *RTL], check=True)
            subprocess.run([*common, "-s", "tb_pll", f"-Ptb_pll.ON_CHIP_CAL={parameter}",
                            f"-Ptb_pll.TRACKING_REPLICAS={replicas}", f"-Ptb_pll.RANGE_DCO={range_dco}",
                            "-o", output, *RTL, ROOT / "tests" / "tb_pll.sv"], check=True)
        if not args.spice_data and not args.spectrum and not args.corner_grid and compiled is None:
            for top, module in (("tb_edge_counter", "phase_sampler.sv"),
                                ("tb_phase_sampler", "phase_sampler.sv"),
                                ("tb_startup_retry", "loop_control.sv")):
                unit_test = build / f"{top}.vvp"
                subprocess.run([*common, "-s", top, "-o", unit_test, ROOT / "rtl" / module,
                                ROOT / "tests" / f"{top}.sv"], check=True)
                subprocess.run([args.vvp, unit_test], check=True)
            if args.fixed_centers:
                ceiling_test = build / "tb_ceiling.vvp"
                subprocess.run([*common, "-s", "tb_pll", "-Ptb_pll.ON_CHIP_CAL=0",
                                "-Ptb_pll.MAX_COARSE_CODE=96", "-o", ceiling_test,
                                *RTL, ROOT / "tests" / "tb_pll.sv"], check=True)
                subprocess.run([args.vvp, ceiling_test, "+check_hard_ceiling"], check=True)
        if args.corner_grid:
            scenarios = {}
            ceilings = {}
            for corner, source, reference, start, retune, edge in corner_grid():
                table = build / f"{corner}.txt"
                if corner not in ceilings:
                    ceilings[corner] = spice_table(source, table)
                scenarios[f"{corner}_{reference}MHz"] = [
                    f"+spice_table={table}", f"+ref={reference}", f"+code_ceiling={ceilings[corner]}",
                    f"+start_n={start}", f"+retune_n={retune}", f"+edge={edge}",
                ]
        elif args.spice_data:
            table = build / "dco.txt"
            max_code = spice_table(args.spice_data, table, ideal_quarter_bins=args.ideal_quarter_bins,
                                   lut_point=args.phase_lut_point, phase_shape=args.phase_shape,
                                   coarse_only=args.coarse_phase)
            extra = [f"+spice_table={table}", f"+ref={args.ref}", f"+code_ceiling={max_code}"]
            if args.phase_lut_point:
                extra.append(f"+phase_lut={table.with_suffix('.lut')}")
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
            command = [args.vvp, output, *options, f"+startup_delay_ps={args.startup_delay_ps}",
                       f"+expected_calibration={parameter}", f"+expected_tracking_replicas={replicas}",
                       f"+expected_range_dco={range_dco}"]
            if args.tracking_gear is not None:
                command.append(f"+tracking_gear={args.tracking_gear}")
            if args.calibrate:
                command += ["+precalibrate", f"+cal_code={args.cal_code}"]
            if args.coarse_phase:
                command.append("+coarse_phase")
            if args.slow_phase_profile:
                command.append("+slow_phase_profile")
            if args.no_dither:
                command.append("+no_dither")
            if args.narrow_near_integer:
                command.append("+narrow_near_integer")
            if args.spectrum:
                command += [f"+spectrum_edges={args.spectrum_edges}", f"+spectrum_settle={args.spectrum_settle}"]
            if args.trace and label in ("nominal", "spice_interpolated"):
                command.append(f"+trace={args.trace.resolve()}")
            if args.report:
                result = subprocess.run(command, capture_output=True, text=True)
                print(result.stdout, end="")
                print(result.stderr, end="")
                results.append({"scenario": label, "passed": result.returncode == 0,
                                "output": result.stdout.splitlines()})
                args.report.write_text(json.dumps({"scenarios": results}, indent=2) + "\n")
                result.check_returncode()
            else:
                subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
