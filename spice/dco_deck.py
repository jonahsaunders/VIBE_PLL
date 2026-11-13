#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate and characterize the Sky130A coarse/fine DCO and delay taps."""

import argparse
import csv
import math
import os
from pathlib import Path
import re
from statistics import mean
import subprocess
import sys
import tempfile


THERM_PINS = tuple(f"therm_{index}" for index in range(255))
FINE_THERM_PINS = tuple(f"fine_therm_{index}" for index in range(128))
TAP_PINS = tuple(f"tap_{index}" for index in range(5))
FINE_TAP_PINS = tuple(f"fine_tap_{index}" for index in range(15))
TAP_COUNT = len(TAP_PINS) + len(FINE_TAP_PINS)
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


def schematic(replica_strength=1.0):
    lines = [
        "* SPDX-License-Identifier: Apache-2.0",
        "* CPZ4 DCO. Geometry is in microns under the Sky130 SPICE library scale.",
        "* Pins: vdd vss enable, therm_0..254, fine_therm_0..127, tap_0..4, fine_tap_0..14.",

        ".subckt cpz4_starved_stage a z bp bn vdd vss",
        mos("p_starve", ("up", "bp", "vdd", "vdd"), "p", 5.6, 0.50),
        mos("p_core", ("z", "a", "up", "vdd"), "p", 3.36, 0.15),
        mos("n_core", ("z", "a", "down", "vss"), "n", 1.68, 0.15),
        mos("n_starve", ("down", "bn", "vss", "vss"), "n", 2.8, 0.50),
        ".ends cpz4_starved_stage",
        ".subckt cpz4_fine_delay a z vdd vss",
        mos("p_delay", ("z", "a", "vdd", "vdd"), "p", 1.68 * replica_strength, 0.15),
        mos("n_delay", ("z", "a", "vss", "vss"), "n", 0.84 * replica_strength, 0.15),
        ".ends cpz4_fine_delay",
        ".subckt cpz4_tap_buffer a z vdd vss",
        mos("p_in", ("mid", "a", "vdd", "vdd"), "p", 0.84, 0.15),
        mos("n_in", ("mid", "a", "vss", "vss"), "n", 0.42, 0.15),
        mos("p_out", ("z", "mid", "vdd", "vdd"), "p", 3.36, 0.15),
        mos("n_out", ("z", "mid", "vss", "vss"), "n", 1.68, 0.15),
        ".ends cpz4_tap_buffer",
        wrapped_line(".subckt cpz4_dco", ("vdd", "vss", "enable", *THERM_PINS,
                                           *FINE_THERM_PINS, *TAP_PINS, *FINE_TAP_PINS)),
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
        "* Fine slices use the lowest-weight coarse unit and a nominal 20:1 mirror.",
        mos("fine_p_diode", ("fine_bp", "fine_bp", "vdd", "vdd"), "p", 8.4, 0.50),
        mos("fine_p_mirror", ("fine_bn", "fine_bp", "vdd", "vdd"), "p", 0.42, 0.50),
        mos("fine_n_diode", ("fine_bn", "fine_bn", "vss", "vss"), "n", 0.84, 0.50),
        mos("fine_n_mirror", ("bp", "fine_bn", "vss", "vss"), "n", 0.84, 0.50),
        mos("fine_p_off", ("fine_bp", "enable", "vdd", "vdd"), "p", 0.84, 0.15),
        mos("fine_n_off", ("fine_bn", "disable", "vss", "vss"), "n", 0.42, 0.15),
        "* Tapered thermometer bank. The control flops sit at the macro boundary.",
    ]
    index = 0
    for group, (count, _width, _length) in enumerate(DAC_GROUPS):
        for pin in THERM_PINS[index:index + count]:
            lines.append(f"Xu{index} bp vref {pin} vss cpz4_dac_unit_{group}")
            index += 1
    for index, pin in enumerate(FINE_THERM_PINS):
        lines.append(f"Xfine_unit{index} fine_bp vref {pin} vss cpz4_dac_unit_0")
    for index, tap in enumerate(TAP_PINS):
        lines += [
            f"Xs{index} n{(index - 1) % 5} n{index} bp bn vdd vss cpz4_starved_stage",
            f"Xload{index} n{index} vss sky130_fd_pr__cap_mim_m3_1 w=2.2 l=2.2",
            f"Xb{index} n{index} {tap} vdd vss cpz4_tap_buffer",
        ]
        # Start from the buffered ring tap to isolate the ring. Replicas
        # alternate polarity, with the final inverter replicating the load.
        source = tap
        for substep in range(3):
            fine_index = 3 * index + substep
            node = FINE_TAP_PINS[fine_index]
            lines.append(f"Xdelay{fine_index} {source} {node} vdd vss cpz4_fine_delay")
            source = node
        lines.append(f"Xdelay_load{index} {source} fine_dummy_{index} vdd vss cpz4_fine_delay")
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


def make_deck(library, corner, volts, temperature, code, fine_code, aggregate=False,
              added_tap_load_ff=0, ripple_mv=0, ripple_mhz=10):
    high_select = "control_high" if ripple_mv else "vdd"
    active_units = [high_select if index < code else "0" for index in range(len(THERM_PINS))]
    fine_units = [high_select if index < fine_code else "0" for index in range(len(FINE_THERM_PINS))]
    loads = [f"Cload{i} {tap} 0 {(20 if i == 0 else 8) + added_tap_load_ff:g}f"
             for i, tap in enumerate(TAP_PINS)]
    loads += [f"Cfine_load{i} {tap} 0 {8 + added_tap_load_ff:g}f"
              for i, tap in enumerate(FINE_TAP_PINS)]
    probes = " ".join(f"v({tap})" for tap in (*TAP_PINS, *FINE_TAP_PINS))
    if aggregate:
        control = " control_high" if ripple_mv else ""
        instance = f"Xosc vdd 0 enable{control} " + " ".join((*TAP_PINS, *FINE_TAP_PINS)) + " cpz4_dco"
    else:
        instance = wrapped_line("Xosc", ("vdd", "0", "enable", *active_units, *fine_units,
                                        *TAP_PINS, *FINE_TAP_PINS), "cpz4_dco")
    supply = [f"Vdd vdd 0 {volts}"]
    duration = "280n"
    if ripple_mv:
        supply = [f"Vdd vdd 0 SIN({volts} {ripple_mv / 1000:g} {ripple_mhz:g}meg 200n)",
                  f"Vcontrol control_high 0 {volts}"]
        duration = f"{0.2 + 4 / ripple_mhz:.8g}u"
    return "\n".join([
        f"CPZ4 DCO {corner} {volts} V {temperature} C coarse {code} fine {fine_code}",
        f'.lib "{library.as_posix()}" {corner}',
        '.include "cpz4_dco.spice"',
        f".temp {temperature}",
        ".options method=gear maxord=2 reltol=0.002",
        *supply,
        f"Ven enable 0 PWL(0 0 10n 0 10.1n {volts})" if ripple_mv else
        f"Ven enable 0 PULSE(0 {volts} 10n 100p 100p 1u 2u)",
        instance,
        *loads,
        f".tran 22p {duration} 0 22p",
        ".control",
        "run",
        "set wr_singlescale",
        "set wr_vecnames",
        "let supply_current = -i(Vdd)",
        f"wrdata waveform.dat {probes} supply_current",
        ".endc",
        ".end",
        "",
    ])


def crossings(rows, threshold):
    edges = []
    for first, second in zip(rows, rows[1:]):
        if second[0] < 10e-9:
            continue
        for index, (a, b) in enumerate(zip(first[1:1 + TAP_COUNT], second[1:1 + TAP_COUNT])):
            if (a >= threshold) != (b >= threshold):
                time = first[0] + (second[0] - first[0]) * (threshold - a) / (b - a)
                edges.append((time, index, int(b >= threshold)))
    return sorted(edges)


def characterize(path, volts):
    with path.open() as data:
        next(data)
        rows = [tuple(map(float, line.split())) for line in data if line.strip()]
    if len(rows) < 2 or len(rows[0]) != TAP_COUNT + 2:
        raise ValueError("Expected time, coarse and fine taps, and supply current in waveform.dat")
    edges = crossings(rows, volts / 2)
    rises = [i for i, event in enumerate(edges) if event[1:] == (0, 1) and event[0] > 110e-9]
    if len(rises) < 5:
        raise ValueError("Fewer than four complete oscillator periods after 110 ns")
    rises = rises[-9:]
    cycles = [(edges[start:stop], edges[stop][0]) for start, stop in zip(rises, rises[1:])]
    periods, duty, min_bins, min_guards = [], [], [], []
    bin_widths = [[] for _ in TAP_ORDER]
    fine_widths = [[] for _ in range(40)]
    bad_sequences = 0
    bad_fine_sequences = 0
    for all_events, end in cycles:
        cycle = [event for event in all_events if event[1] < len(TAP_PINS)]
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
        subdivisions = []
        fine_codes = []
        for coarse_bin, (edge_time, tap, rising) in enumerate(cycle):
            finish = times[coarse_bin + 1]
            base = len(TAP_PINS) + 3 * tap
            interval = [(t, i, r) for t, i, r in all_events
                        if edge_time < t < finish and base <= i < base + 3]
            expected = [(base + k, rising ^ int(k % 2 == 0)) for k in range(3)]
            if [(i, r) for _, i, r in interval] != expected[:len(interval)]:
                break
            boundaries = [edge_time, *(t for t, _, _ in interval), finish]
            subdivisions.extend((b - a) / period for a, b in zip(boundaries, boundaries[1:]))
            fine_codes.extend(4 * coarse_bin + i for i in range(len(boundaries) - 1))
        if len(fine_codes) < 10 or fine_codes[-1] // 4 != 9:
            bad_fine_sequences += 1
        else:
            per_cycle = dict(zip(fine_codes, subdivisions))
            for i, samples in enumerate(fine_widths):
                samples.append(per_cycle.get(i, 0.0))
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
        "bad_fine_sequences": bad_fine_sequences,
        "missing_fine_bins": sum(not any(samples) for samples in fine_widths) if fine_widths[0] else "",
        "min_fine_bin_ui": round(min(w for samples in fine_widths for w in samples if w > 0), 5)
        if any(any(samples) for samples in fine_widths) else "",
        "dco_power_mw": round(1e3 * avg_current * volts, 5),
        **{f"bin_{i}_ui": round(mean(widths), 8) if widths else "" for i, widths in enumerate(bin_widths)},
        **{f"fine_bin_{i}_ui": round(mean(widths), 8) if widths else "" for i, widths in enumerate(fine_widths)},
    }


def supply_pushing(path, volts, ripple_mv, ripple_mhz):
    with path.open() as file:
        next(file)
        samples = ((float(fields[0]), float(fields[1])) for line in file if (fields := line.split()))
        first = next(samples)
        rising = []
        for second in samples:
            if first[1] < volts / 2 <= second[1]:
                edge = first[0] + (second[0] - first[0]) * (volts / 2 - first[1]) / (second[1] - first[1])
                if edge >= 200e-9 + 1e-6 / ripple_mhz:
                    rising.append(edge)
            first = second
    # Least-squares fit of instantaneous frequency to DC, sine and cosine.
    # Using both quadratures includes the phase lag of the oscillator bias.
    normal = [[0.0] * 4 for _ in range(3)]
    for a, b in zip(rising, rising[1:]):
        phase = 2 * math.pi * ripple_mhz * 1e6 * ((a + b) / 2 - 200e-9)
        vector = (1.0, math.sin(phase), math.cos(phase))
        for row, lhs in zip(normal, vector):
            for index, rhs in enumerate(vector):
                row[index] += lhs * rhs
            row[3] += lhs * 1e-6 / (b - a)
    if len(rising) < 8:
        raise ValueError("Insufficient DCO edges after supply injection")
    for index, row in enumerate(normal):
        scale = row[index]
        row[:] = [value / scale for value in row]
        for other in normal:
            if other is not row:
                coefficient = other[index]
                other[:] = [value - coefficient * pivot for value, pivot in zip(other, row)]
    return 1000 * math.hypot(normal[1][3], normal[2][3]) / ripple_mv


def aggregate_dac(netlist, code, fine_code, library, corner, independent_supply=False):
    """Compress parallel devices in a static code sweep. Keep the production netlist intact."""
    corner_file = library.parent / "corners" / f"{corner}.spice"
    include = next(line.split('"')[1] for line in corner_file.read_text().splitlines()
                   if re.search(r"sky130_fd_pr__nfet_01v8__(tt|ss|ff|sf|fs)\.pm3\.spice", line))
    model_file = (corner_file.parent / include).resolve()
    model = model_file.read_text()
    start = model.index(".model sky130_fd_pr__nfet_01v8__model.")
    end = re.search(r"^\.ends", model[start:], re.MULTILINE).start() + start
    models = re.sub(r"^\.model sky130_fd_pr__nfet_01v8__model\.",
                    ".model cpz4_static_nmos.", model[start:end], flags=re.MULTILINE)
    models = re.sub(r"\s*\+\s*mc_mm_switch\s*\*\s*agauss\(0,1\.0,1\)\s*\*\s*\([^{}]*\)(?=\})",
                    "", models, flags=re.IGNORECASE)
    if "mc_mm_switch" in models.lower():
        raise ValueError("Unsupported mismatch expression in the compact DAC model")
    lines = netlist.splitlines()
    high_select = "control_high" if independent_supply else "vdd"
    result = []
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if line.startswith(".subckt cpz4_dco "):
            control = " control_high" if independent_supply else ""
            result.append(f".subckt cpz4_dco vdd vss enable{control} " + " ".join((*TAP_PINS, *FINE_TAP_PINS)))
            while lines[index].startswith("+"):
                index += 1
        elif line.startswith(("Xu", "Xfine_unit")):
            continue
        elif line == ".ends cpz4_dco":
            remaining = code
            for group, (count, _, _) in enumerate(DAC_GROUPS):
                active = min(remaining, count)
                remaining -= active
                for select, devices in ((high_select, active), ("vss", count - active)):
                    if devices:
                        result.append(f"Xgroup{group}_{select} bp vref {select} vss cpz4_dac_unit_{group} cells={devices}")
            for select, devices in ((high_select, fine_code), ("vss", len(FINE_THERM_PINS) - fine_code)):
                if devices:
                    result.append(f"Xfine_{select} fine_bp vref {select} vss cpz4_dac_unit_0 cells={devices}")
            result.append(line)
        elif line.startswith(".subckt cpz4_dac_unit_"):
            result.append(line + " params: cells=1")
            for _ in range(2):
                raw = lines[index]
                index += 1
                name, drain, gate, source, bulk, _model, *parameters = raw.split()
                pins = (drain, gate, source, bulk)
                geometry = " ".join(parameters)
                result.append("M" + name[1:] + " " + " ".join(pins) +
                              " cpz4_static_nmos " + geometry + " m={cells}")
        else:
            result.append(line)
    return "\n".join(result) + "\n" + models


def run_case(args, code, fine_code):
    with tempfile.TemporaryDirectory(prefix="cpz4-spice-") as name:
        path = Path(name)
        source = schematic(args.replica_strength)
        if args.aggregate_dac:
            source = aggregate_dac(source, code, fine_code, args.lib, args.corner, bool(args.supply_ripple_mv))
        (path / "cpz4_dco.spice").write_text(source, encoding="ascii")
        deck = make_deck(args.lib, args.corner, args.vdd, args.temp, code, fine_code, args.aggregate_dac,
                         args.added_tap_load_ff, args.supply_ripple_mv, args.supply_ripple_mhz)
        (path / "bench.cir").write_text(deck, encoding="ascii")
        command = [args.ngspice, "-n", "-b", "bench.cir"]
        if args.ngspice_dll:
            command = [sys.executable, str(Path(__file__).resolve()), "--dll-run", str(args.ngspice_dll)]
        run = subprocess.run(command, cwd=path, capture_output=True, text=True, errors="replace",
                             timeout=args.timeout)
        waveform = path / "waveform.dat"
        # ngspice can return 1 for a control-only deck with no .plot/.print.
        if not waveform.exists() or "simulation(s) aborted" in (run.stdout + run.stderr).lower():
            raise RuntimeError(f"ngspice failed at {code}:{fine_code}:\n{(run.stdout + run.stderr)[-5000:]}")
        if args.keep_waveform:
            args.keep_waveform.mkdir(parents=True, exist_ok=True)
            name = f"{args.corner}-{args.vdd}-{args.temp}-{code}-{fine_code}.dat"
            (args.keep_waveform / name).write_bytes(waveform.read_bytes())
        operating_point = {"corner": args.corner, "vdd": args.vdd, "temp_c": args.temp,
                           "code": code, "fine_code": fine_code}
        if args.supply_ripple_mv:
            pushing = supply_pushing(waveform, args.vdd, args.supply_ripple_mv, args.supply_ripple_mhz)
            return {**operating_point, "ripple_mv_peak": args.supply_ripple_mv,
                    "ripple_mhz": args.supply_ripple_mhz, "added_tap_load_ff": args.added_tap_load_ff,
                    "supply_pushing_mhz_per_v": round(pushing, 3)}
        return {**operating_point, **characterize(waveform, args.vdd)}


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
    parser.add_argument("--fine-codes", default="64", help="comma-separated fine codes (0 through 128)")
    parser.add_argument("--aggregate-dac", action="store_true",
                        help="use parallel multiplicity for static DAC codes, with mismatch disabled")
    parser.add_argument("--timeout", type=int, default=480, help="seconds per SPICE case")
    parser.add_argument("--output", type=Path, help="write summary CSV to this path")
    parser.add_argument("--keep-waveform", type=Path, help="write waveform samples in this directory")
    parser.add_argument("--added-tap-load-ff", type=float, default=0,
                        help="additional capacitance on each sampled tap in fF")
    parser.add_argument("--replica-strength", type=float, default=1.0,
                        help="scale both replica inverter device widths for a sensitivity sweep")
    parser.add_argument("--supply-ripple-mv", type=float, default=0,
                        help="peak sine amplitude injected on the DCO supply in mV")
    parser.add_argument("--supply-ripple-mhz", type=float, default=10, help="frequency of injected supply ripple")
    parser.add_argument("--dll-run", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.dll_run:
        return run_shared_library(args.dll_run.resolve())
    if not math.isfinite(args.replica_strength) or args.replica_strength < 1:
        parser.error("replica strength must be finite and at least one")
    if args.emit:
        args.emit.write_text(schematic(args.replica_strength), encoding="ascii", newline="\n")
    if args.lib:
        args.lib = args.lib.resolve(strict=True)
        if args.ngspice_dll:
            args.ngspice_dll = args.ngspice_dll.resolve(strict=True)
        if args.timeout <= 0:
            parser.error("the per-case timeout must be positive")
        if not 0 < args.vdd <= 1.95:
            parser.error("the 1.8 V Sky130 MOS models are characterized to 1.95 V")
        if not math.isfinite(args.added_tap_load_ff) or args.added_tap_load_ff < 0:
            parser.error("added tap load must be finite and nonnegative")
        if not 0 <= args.supply_ripple_mv < 1000 * args.vdd or args.vdd + args.supply_ripple_mv / 1000 > 1.95:
            parser.error("ripple must be nonnegative and keep the supply in (0, 1.95] V")
        if not math.isfinite(args.supply_ripple_mhz) or args.supply_ripple_mhz <= 0:
            parser.error("ripple frequency must be finite and positive")
        codes = [int(code) for code in args.codes.split(",")]
        fine_codes = [int(code) for code in args.fine_codes.split(",")]
        if not all(0 <= code <= 255 for code in codes):
            parser.error("thermometer codes must be 0..255")
        if not all(0 <= code <= 128 for code in fine_codes):
            parser.error("fine thermometer codes must be 0..128")
        results = []
        for code in codes:
            for fine_code in fine_codes:
                result = run_case(args, code, fine_code)
                results.append(result)
                summary = {k: v for k, v in result.items() if not k.startswith(("bin_", "fine_bin_"))}
                print(summary, flush=True)
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
