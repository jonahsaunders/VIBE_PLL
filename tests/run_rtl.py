#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the PLL testbench with abstract plants or an interpolated SPICE sweep."""

import argparse
import csv
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


def spice_table(source, destination):
    with source.open(newline="", encoding="ascii") as file:
        rows = sorted(csv.DictReader(file), key=lambda row: int(row["code"]))
    pvt = {(row["corner"], row["vdd"], row["temp_c"]) for row in rows}
    codes = [int(row["code"]) for row in rows]
    if not codes or codes[0] != 0 or codes[-1] != 255 or len(set(codes)) != len(codes) or len(pvt) != 1:
        raise ValueError("Provide one PVT condition, with distinct DCO codes including 0 and 255")
    data = []
    for row in rows:
        if int(row["bad_tap_sequences"]):
            raise ValueError(f"Illegal tap order at code {row['code']}")
        data.append([float(row["frequency_mhz"])] +
                    [float(row[f"bin_{i}_ui"]) for i in range(10)])
    if any(b[0] <= a[0] for a, b in zip(data, data[1:])):
        raise ValueError("The measured sweep is nonmonotonic")
    with destination.open("w", encoding="ascii") as file:
        interval = 0
        for code in range(256):
            if code > codes[interval + 1]:
                interval += 1
            fraction = (code - codes[interval]) / (codes[interval + 1] - codes[interval])
            values = [a + fraction * (b - a) for a, b in zip(data[interval], data[interval + 1])]
            width_sum = sum(values[1:])
            values[1:] = [width / width_sum for width in values[1:]]
            file.write(" ".join(f"{value:.10f}" for value in values) + "\n")


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
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="cpz4-rtl-") as temp:
        build = Path(temp)
        output = build / "tb_pll.vvp"
        common = [args.iverilog, "-g2012", "-Wall", "-Wno-timescale"]
        subprocess.run([*common, "-s", "cpz4_sky130", "-t", "null", *RTL], check=True)
        subprocess.run([*common, "-s", "tb_pll", "-o", output, *RTL, ROOT / "tests" / "tb_pll.sv"], check=True)
        if args.spice_data:
            table = build / "dco.txt"
            spice_table(args.spice_data, table)
            extra = [f"+spice_table={table}", f"+ref={args.ref}"]
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
            scenarios = SCENARIOS
        for label, options in scenarios.items():
            print(f"CASE {label}", flush=True)
            command = [args.vvp, output, *options]
            if args.trace and label in ("nominal", "spice_interpolated"):
                command.append(f"+trace={args.trace.resolve()}")
            subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
