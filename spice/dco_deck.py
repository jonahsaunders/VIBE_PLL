#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate and characterize the Sky130A five-tap DCO schematic."""

import argparse
import csv
import os
from pathlib import Path
from statistics import mean
import subprocess
import sys
import tempfile


THERM_PINS = tuple(f"therm_{index}" for index in range(255))
TAP_PINS = tuple(f"tap_{index}" for index in range(5))
# Unit current grows gradually with code. Spend the finest increments where
# dF/dI is highest while retaining the slow-corner upper tuning authority.
DAC_GROUPS = ((80, 0.42, 4.0), (48, 0.42, 2.7), (32, 0.42, 1.6),
              (32, 0.42, 1.0), (32, 0.70, 1.0), (16, 1.05, 1.0), (15, 1.89, 1.0))
TAP_ORDER = ((0, 1), (1, 0), (2, 1), (3, 0), (4, 1),
             (0, 0), (1, 1), (2, 0), (3, 1), (4, 0))


def wrapped_line(prefix, nodes, suffix=""):
    tokens = [*nodes, *suffix.split()]
    return "\n".join([prefix + " " + " ".join(tokens[:10])] + [
        "+ " + " ".join(tokens[index:index + 10]) for index in range(10, len(tokens), 10)
    ])


def mos(name, pins, channel, width, length):
    area = width * 0.29
    perimeter = 2 * (width + 0.29)
    return (f"X{name} {' '.join(pins)} sky130_fd_pr__{channel}fet_01v8 "
            f"w={width:.4g} l={length:.4g} nf=1 ad={area:.4g} as={area:.4g} "
            f"pd={perimeter:.4g} ps={perimeter:.4g} nrd={0.29 / width:.4g} nrs={0.29 / width:.4g}")


def schematic():
    lines = [
        "* SPDX-License-Identifier: Apache-2.0",
        "* CPZ4 DCO. Geometry is in microns under the Sky130 SPICE library scale.",
        "* DCO pin order: vdd vss enable, therm_0..254, tap_0..4.",

        ".subckt cpz4_starved_stage a z bp bn vdd vss",
        mos("p_starve", ("up", "bp", "vdd", "vdd"), "p", 5.6, 0.50),
        mos("p_core", ("z", "a", "up", "vdd"), "p", 3.36, 0.15),
        mos("n_core", ("z", "a", "down", "vss"), "n", 1.68, 0.15),
        mos("n_starve", ("down", "bn", "vss", "vss"), "n", 2.8, 0.50),
        ".ends cpz4_starved_stage",
        ".subckt cpz4_tap_buffer a z vdd vss",
        mos("p_in", ("mid", "a", "vdd", "vdd"), "p", 0.84, 0.15),
        mos("n_in", ("mid", "a", "vss", "vss"), "n", 0.42, 0.15),
        mos("p_out", ("z", "mid", "vdd", "vdd"), "p", 3.36, 0.15),
        mos("n_out", ("z", "mid", "vss", "vss"), "n", 1.68, 0.15),
        ".ends cpz4_tap_buffer",
        wrapped_line(".subckt cpz4_dco", ("vdd", "vss", "enable", *THERM_PINS, *TAP_PINS)),
        "* Turn off the reference and force both starve mirrors off in standby.",
        mos("p_eninv", ("disable", "enable", "vdd", "vdd"), "p", 0.84, 0.15),
        mos("n_eninv", ("disable", "enable", "vss", "vss"), "n", 0.42, 0.15),
        mos("reference_switch", ("r_hi", "disable", "vdd", "vdd"), "p", 4.2, 0.30),
        "Xr_ref r_hi vref vss sky130_fd_pr__res_xhigh_po_0p35 l=8.40",
        mos("reference", ("vref", "vref", "vss", "vss"), "n", 4.2, 0.50),
        mos("reference_off", ("vref", "disable", "vss", "vss"), "n", 0.42, 0.15),
        mos("base", ("bp", "vref", "vss", "vss"), "n", 3.36, 1.0),
        mos("p_diode", ("bp", "bp", "vdd", "vdd"), "p", 4.2, 0.50),
        mos("p_replica", ("bn", "bp", "vdd", "vdd"), "p", 4.2, 0.50),
        mos("n_diode", ("bn", "bn", "vss", "vss"), "n", 2.1, 0.50),
        mos("p_off", ("bp", "enable", "vdd", "vdd"), "p", 0.84, 0.15),
        mos("n_off", ("bn", "disable", "vss", "vss"), "n", 0.42, 0.15),
        mos("seed", ("n0", "disable", "vss", "vss"), "n", 0.84, 0.15),
        "* Tapered thermometer bank. The control flops sit at the macro boundary.",
    ]
    index = 0
    for group, (count, _width, _length) in enumerate(DAC_GROUPS):
        for pin in THERM_PINS[index:index + count]:
            lines.append(f"Xu{index} bp vref {pin} vss cpz4_dac_unit_{group}")
            index += 1
    for index, tap in enumerate(TAP_PINS):
        lines += [
            f"Xs{index} n{(index - 1) % 5} n{index} bp bn vdd vss cpz4_starved_stage",
            f"Xload{index} n{index} vss sky130_fd_pr__cap_mim_m3_1 w=2.2 l=2.2",
            f"Xb{index} n{index} {tap} vdd vss cpz4_tap_buffer",
        ]
    lines.append(".ends cpz4_dco")
    for group, (_count, width, length) in enumerate(DAC_GROUPS):
        name = f"cpz4_dac_unit_{group}"
        lines += [
            f".subckt {name} bp bias select vss",
            mos("unit", ("bp", "bias", "src", "vss"), "n", width, length),
            mos("switch", ("src", "select", "vss", "vss"), "n", max(1.68, 2 * width), 0.15),
            f".ends {name}",
        ]
    lines.append("")
    return "\n".join(lines)


def make_deck(library, corner, volts, temperature, code):
    active_units = ["vdd" if index < code else "0" for index in range(255)]
    loads = ["Cload0 tap_0 0 20f"] + [f"Cload{i} tap_{i} 0 8f" for i in range(1, 5)]
    return "\n".join([
        f"CPZ4 DCO {corner} {volts} V {temperature} C code {code}",
        f'.lib "{library.as_posix()}" {corner}',
        '.include "cpz4_dco.spice"',
        f".temp {temperature}",
        ".options method=gear maxord=2 reltol=0.002",
        f"Vdd vdd 0 {volts}",
        f"Ven enable 0 PULSE(0 {volts} 10n 100p 100p 1u 2u)",
        wrapped_line("Xosc", ("vdd", "0", "enable", *active_units, *TAP_PINS), "cpz4_dco"),
        *loads,
        ".tran 65p 205n 0 65p",
        ".control",
        "run",
        "set wr_singlescale",
        "set wr_vecnames",
        "let supply_current = -i(Vdd)",
        "wrdata waveform.dat v(tap_0) v(tap_1) v(tap_2) v(tap_3) v(tap_4) supply_current",
        ".endc",
        ".end",
        "",
    ])


def crossings(rows, threshold):
    edges = []
    for first, second in zip(rows, rows[1:]):
        if second[0] < 10e-9:
            continue
        for index, (a, b) in enumerate(zip(first[1:6], second[1:6])):
            if (a >= threshold) != (b >= threshold):
                time = first[0] + (second[0] - first[0]) * (threshold - a) / (b - a)
                edges.append((time, index, int(b >= threshold)))
    return sorted(edges)


def characterize(path, volts):
    with path.open() as data:
        next(data)
        rows = [tuple(map(float, line.split())) for line in data if line.strip()]
    if len(rows) < 2 or len(rows[0]) != 7:
        raise ValueError("Expected time, five taps and supply current in waveform.dat")
    edges = crossings(rows, volts / 2)
    rises = [i for i, event in enumerate(edges) if event[1:] == (0, 1) and event[0] > 70e-9]
    if len(rises) < 6:
        raise ValueError("Fewer than five complete oscillator periods after 70 ns")
    rises = rises[-13:]
    cycles = [(edges[start:stop], edges[stop][0]) for start, stop in zip(rises, rises[1:])]
    periods, duty, min_bins, min_guards = [], [], [], []
    bin_widths = [[] for _ in TAP_ORDER]
    bad_sequences = 0
    for cycle, end in cycles:
        start = cycle[0][0]
        period = end - start
        periods.append(period)
        if tuple(edge[1:] for edge in cycle) != TAP_ORDER:
            bad_sequences += 1
            continue
        times = [edge[0] for edge in cycle] + [end]
        duty.append((times[5] - start) / period)
        widths = [(b - a) / period for a, b in zip(times, times[1:])]
        min_bins.append(min(widths))
        for widths_at_index, width in zip(bin_widths, widths):
            widths_at_index.append(width)
        min_guards.append(min(times[5] - times[3], times[7] - times[5],
                              times[3] - start, end - times[7]) / period)
    tail_start, tail_end = edges[rises[0]][0], edges[rises[-1]][0]
    tail = [row for row in rows if tail_start <= row[0] <= tail_end]
    avg_current = sum((b[0] - a[0]) * (a[-1] + b[-1]) / 2
                      for a, b in zip(tail, tail[1:])) / (tail[-1][0] - tail[0][0])
    return {
        "frequency_mhz": round(1e-6 / mean(periods), 4),
        "period_spread_pct": round(100 * (max(periods) - min(periods)) / mean(periods), 4),
        "duty_pct": round(100 * mean(duty), 3) if duty else "",
        "min_bin_ui": round(min(min_bins), 5) if min_bins else "",
        "min_cdc_guard_ui": round(min(min_guards), 5) if min_guards else "",
        "bad_tap_sequences": bad_sequences,
        "dco_power_mw": round(1e3 * avg_current * volts, 5),
        **{f"bin_{i}_ui": round(mean(widths), 8) if widths else "" for i, widths in enumerate(bin_widths)},
    }


def run_case(args, code):
    with tempfile.TemporaryDirectory(prefix="cpz4-spice-") as name:
        path = Path(name)
        (path / "cpz4_dco.spice").write_text(schematic(), encoding="ascii")
        (path / "bench.cir").write_text(make_deck(args.lib, args.corner, args.vdd, args.temp, code), encoding="ascii")
        command = [args.ngspice, "-n", "-b", "bench.cir"]
        if args.ngspice_dll:
            command = [sys.executable, str(Path(__file__).resolve()), "--dll-run", str(args.ngspice_dll)]
        run = subprocess.run(command, cwd=path, capture_output=True, text=True, errors="replace", timeout=180)
        waveform = path / "waveform.dat"
        # ngspice can return 1 for a control-only deck with no .plot/.print.
        if not waveform.exists() or "simulation(s) aborted" in (run.stdout + run.stderr).lower():
            raise RuntimeError(f"ngspice failed at code {code}:\n{(run.stdout + run.stderr)[-5000:]}")
        if args.keep_waveform:
            args.keep_waveform.mkdir(parents=True, exist_ok=True)
            (args.keep_waveform / f"{args.corner}-{args.vdd}-{args.temp}-{code}.dat").write_bytes(waveform.read_bytes())
        return {"corner": args.corner, "vdd": args.vdd, "temp_c": args.temp,
                "code": code, **characterize(waveform, args.vdd)}


def run_shared_library(path):
    import ctypes as c

    # Each sweep case is a subprocess, so the shared simulator starts clean.
    dll_dir = os.add_dll_directory(str(path.parent)) if os.name == "nt" else None
    try:
        spice = c.CDLL(str(path))
        text_cb = c.CFUNCTYPE(c.c_int, c.c_char_p, c.c_int, c.c_void_p)
        exit_cb = c.CFUNCTYPE(c.c_int, c.c_int, c.c_bool, c.c_bool, c.c_int, c.c_void_p)

        @text_cb
        def message(raw, _identifier, _userdata):
            print(raw.decode(errors="replace"))
            return 0

        @exit_cb
        def controlled_exit(_code, _immediate, _quit, _identifier, _userdata):
            return 0

        spice.ngSpice_Init.argtypes = [text_cb, text_cb, exit_cb, c.c_void_p,
                                      c.c_void_p, c.c_void_p, c.c_void_p]
        spice.ngSpice_Command.argtypes = [c.c_char_p]
        spice.ngSpice_Init(message, message, controlled_exit, None, None, None, None)
        return spice.ngSpice_Command(b"source bench.cir")
    finally:
        if dll_dir is not None:
            dll_dir.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit", type=Path, help="write the portable DCO subcircuit")
    parser.add_argument("--lib", type=Path, help="absolute or relative path to sky130.lib.spice")
    parser.add_argument("--ngspice", default="ngspice", help="ngspice executable, default ngspice on PATH")
    parser.add_argument("--ngspice-dll", type=Path, help="run each case using a shared ngspice library")
    parser.add_argument("--corner", default="tt", choices=("tt", "ff", "ss", "fs", "sf"))
    parser.add_argument("--vdd", default=1.8, type=float)
    parser.add_argument("--temp", default=25.0, type=float)
    parser.add_argument("--codes", default="0,32,64,96,128,160,192,224,255")
    parser.add_argument("--output", type=Path, help="write summary CSV to this path")
    parser.add_argument("--keep-waveform", type=Path, help="write waveform samples in this directory")
    parser.add_argument("--dll-run", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.dll_run:
        return run_shared_library(args.dll_run.resolve())
    if args.emit:
        args.emit.write_text(schematic(), encoding="ascii")
    if args.lib:
        args.lib = args.lib.resolve(strict=True)
        if args.ngspice_dll:
            args.ngspice_dll = args.ngspice_dll.resolve(strict=True)
        if not 0 < args.vdd <= 1.95:
            parser.error("the 1.8 V Sky130 MOS models are characterized to 1.95 V")
        codes = [int(code) for code in args.codes.split(",")]
        if not all(0 <= code <= 255 for code in codes):
            parser.error("thermometer codes must be 0..255")
        results = []
        for code in codes:
            result = run_case(args, code)
            results.append(result)
            print(result, flush=True)
        if args.output:
            with args.output.open("w", newline="", encoding="ascii") as file:
                writer = csv.DictWriter(file, fieldnames=list(results[0]))
                writer.writeheader()
                writer.writerows(results)
    elif not args.emit:
        parser.error("use --emit to generate the netlist or --lib to run a sweep")
    return 0


if __name__ == "__main__":
    sys.exit(main())
