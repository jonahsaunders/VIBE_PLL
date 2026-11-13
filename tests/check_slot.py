#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Map VIBE_PLL to Sky130 HD and check a preliminary slot floorplan."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
TOP = "cpz4_sky130"
SITE_WIDTH = 0.46
ROW_HEIGHT = 2.72
BLOCK = "cpz4_dco"


def lef_cells(path):
    cells = {}
    name = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if match := re.match(r"MACRO\s+(\S+)", line):
            name = match[1]
        elif name and (match := re.match(r"\s+SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", line)):
            cells[name] = tuple(map(float, match.groups()))
            name = None
    return cells


def map_cells(yosys, liberty, on_chip_cal, mapped_netlist=None):
    executable = shutil.which(yosys)
    if executable is None:
        raise FileNotFoundError(f"Cannot find Yosys executable: {yosys}")
    executable = str(Path(executable).resolve())
    with tempfile.TemporaryDirectory(prefix="vibe-area-") as work:
        directory = Path(work)
        shutil.copyfile(liberty, directory / "cells.lib")
        rtl = sorted((ROOT / "rtl").glob("*.sv"))
        for path in rtl:
            shutil.copyfile(path, directory / path.name)
        script = [
            "read_verilog -sv " + " ".join(path.name for path in rtl),
            f"chparam -set ON_CHIP_CAL {int(on_chip_cal)} {TOP}",
            f"synth -top {TOP} -flatten -noabc",
            "dfflibmap -liberty cells.lib",
            "abc -liberty cells.lib -dont_use sky130_fd_sc_hd__lpflow* -dont_use sky130_fd_sc_hd__probe*",
            "clean",
            "write_json mapped.json",
        ]
        if mapped_netlist is not None:
            script.append("write_verilog -noattr -noexpr mapped.v")
        subprocess.run([executable, "-Q", "-q", "-p", "; ".join(script)], cwd=directory, check=True)
        design = json.loads((directory / "mapped.json").read_text(encoding="utf-8"))
        if mapped_netlist is not None:
            shutil.copyfile(directory / "mapped.v", mapped_netlist)
    return Counter(cell["type"] for cell in design["modules"][TOP]["cells"].values()
                   if cell["type"] != "$scopeinfo")


def pack_rows(widths, row_widths):
    """Return a largest-first row-packing result in integer placement sites."""
    remaining = sorted(row_widths)
    for width in sorted(widths, reverse=True):
        slot = next((i for i, free in enumerate(remaining) if free >= width), None)
        if slot is None:
            return False
        remaining[slot] -= width
        remaining.sort()
    return True


def positive_pair(parser, label, pair):
    if any(not math.isfinite(value) or value <= 0 for value in pair):
        parser.error(f"{label} requires two finite positive values")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yosys", default="yosys", help="Yosys 0.66 or compatible executable")
    parser.add_argument("--liberty", required=True, type=Path, help="Sky130 HD TT Liberty")
    parser.add_argument("--lef", required=True, type=Path, help="Sky130 HD standard-cell LEF")
    parser.add_argument("--slot", required=True, type=float, nargs=2, metavar=("WIDTH", "HEIGHT"))
    parser.add_argument("--dco-reserve", required=True, type=float, nargs=2, metavar=("WIDTH", "HEIGHT"),
                        help="oscillator block including its halo, in micrometers")
    parser.add_argument("--edge-reserve", required=True, type=float, metavar="UM",
                        help="per-edge space for wrapper access and the power grid")
    parser.add_argument("--utilization", required=True, type=float,
                        help="maximum standard-cell utilization of remaining rows")
    parser.add_argument("--on-chip-cal", action="store_true", help="include the calibration histogram")
    parser.add_argument("--mapped-netlist", type=Path, help="export mapped Verilog for physical design")
    args = parser.parse_args()
    positive_pair(parser, "--slot", args.slot)
    positive_pair(parser, "--dco-reserve", args.dco_reserve)
    if not math.isfinite(args.edge_reserve) or args.edge_reserve < 0:
        parser.error("--edge-reserve must be finite and nonnegative")
    if not 0 < args.utilization <= 1:
        parser.error("--utilization must be a fraction in (0, 1]")

    inner_width, inner_height = (x - 2 * args.edge_reserve for x in args.slot)
    dco_width, dco_height = args.dco_reserve
    sites = math.floor(inner_width / SITE_WIDTH + 1e-8)
    rows = math.floor(inner_height / ROW_HEIGHT + 1e-8)
    blocked_sites = math.ceil(dco_width / SITE_WIDTH - 1e-8)
    blocked_rows = math.ceil(dco_height / ROW_HEIGHT - 1e-8)
    if blocked_sites > sites or blocked_rows > rows:
        parser.error("DCO reservation extends outside the grid-aligned core")

    mapped = map_cells(args.yosys, args.liberty, args.on_chip_cal, args.mapped_netlist)
    if mapped.pop(BLOCK, 0) != 1:
        parser.error("expected one DCO hard-macro instance")
    cells = lef_cells(args.lef)
    widths = []
    for name, count in mapped.items():
        if name not in cells:
            parser.error(f"missing LEF for mapped cell {name}")
        width, height = cells[name]
        n = round(width / SITE_WIDTH)
        if not math.isclose(height, ROW_HEIGHT) or not math.isclose(width, n * SITE_WIDTH):
            parser.error(f"{name} does not fit a single Sky130 HD row")
        widths.extend([n] * count)
    row_widths = [sites - blocked_sites] * blocked_rows + [sites] * (rows - blocked_rows)
    available = sum(row_widths)
    occupied = sum(widths)
    site_area = SITE_WIDTH * ROW_HEIGHT
    allowance = math.floor(available * args.utilization)
    fits = occupied <= allowance and pack_rows(widths, row_widths)
    print(f"Slot {args.slot[0]:.2f} x {args.slot[1]:.2f} um; DCO reservation {dco_width:.2f} x {dco_height:.2f} um")
    print(f"Sky130 HD cells: {len(widths)}, area: {occupied*site_area:.2f} um^2")
    print(f"Available digital rows: {available*site_area:.2f} um^2, utilized: {100*occupied/available:.2f}%"
          if available else "Available digital rows: 0 um^2")
    print(f"Digital area headroom at {100*args.utilization:.1f}% utilization: "
          f"{(allowance-occupied)*site_area:.2f} um^2")
    print("Planning fit PASS" if fits else "Planning fit FAIL")
    return 0 if fits else 1


if __name__ == "__main__":
    raise SystemExit(main())
