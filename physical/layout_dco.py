#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate the Sky130A oscillator layout and its matching LEF and LVS input."""

import argparse
from dataclasses import dataclass
from pathlib import Path
import re

import klayout.db as db


TOP = "cpz4_dco"
SCHEMATIC = Path(__file__).resolve().parents[1] / "spice" / f"{TOP}.spice"
NMOS = "sky130_fd_pr__nfet_01v8"
PMOS = "sky130_fd_pr__pfet_01v8"
RESISTOR = "sky130_fd_pr__res_xhigh_po_0p35"
CAPACITOR = "sky130_fd_pr__cap_mim_m3_1"
LAYERS = {
    "nwell": (64, 20), "diff": (65, 20), "tap": (65, 44),
    "poly": (66, 20), "poly_res": (66, 13), "licon": (66, 44),
    "li": (67, 20), "mcon": (67, 44),
    "met1": (68, 20), "via1": (68, 44), "met2": (69, 20), "via2": (69, 44),
    "met3": (70, 20), "via3": (70, 44), "met4": (71, 20), "via4": (71, 44),
    "met5": (72, 20), "urpm": (79, 20), "capm": (89, 44),
    "nsdm": (93, 44), "psdm": (94, 20), "npc": (95, 20), "boundary": (235, 4),
}
WIDTH, HEIGHT = 130_000, 105_000
LEFT = 4_800
RIGHT = 126_800
VSS_X = 1_050
VREF_X = 2_700
BP_X = 3_700
FINE_BP_X = 127_350
VDD_X = 128_900


@dataclass(frozen=True)
class Device:
    name: str
    model: str
    nets: tuple[str, ...]
    params: dict[str, str]

    def dimension(self, key):
        return round(float(self.params[key]) * 1000)


def schematic_devices(path):
    definitions = {}
    for line in re.sub(r"\r?\n\+\s*", " ", path.read_text(encoding="utf-8")).splitlines():
        words = line.split()
        if not words or line.startswith("*"):
            continue
        if words[0] == ".subckt":
            name = words[1]
            definitions[name] = (words[2:], [])
        elif words[0][0].upper() == "X":
            first_param = next((i for i, word in enumerate(words) if "=" in word), len(words))
            definitions[name][1].append(Device(words[0][1:], words[first_param - 1],
                                               tuple(words[1:first_param - 1]),
                                               dict(word.split("=", 1) for word in words[first_param:])))
        elif words[0] != ".ends":
            raise ValueError(f"Unsupported schematic line {line}")

    def expand(cell, prefix, nets):
        for device in definitions[cell][1]:
            nodes = tuple(nets.get(net, f"{prefix}{net}") for net in device.nets)
            if device.model in definitions:
                ports = definitions[device.model][0]
                yield from expand(device.model, f"{prefix}{device.name}_", dict(zip(ports, nodes, strict=True)))
            elif device.model in (NMOS, PMOS, RESISTOR, CAPACITOR):
                yield Device(f"{prefix}{device.name}", device.model, nodes, device.params)
            else:
                raise ValueError(f"Unsupported device {device.model}")

    ports = definitions[TOP][0]
    return ports, {device.name: device for device in expand(TOP, "", {port: port for port in ports})}


def round_grid(value):
    return round(value / 5) * 5


def lef_name(name):
    return re.sub(r"_(\d+)$", r"[\1]", name)


class Layout:
    def __init__(self):
        self.layout = db.Layout()
        self.layout.dbu = 0.001
        self.cell = self.layout.create_cell(TOP)
        self.layers = {name: self.layout.layer(*pair) for name, pair in LAYERS.items()}
        self.pins = {}

    def rect(self, layer, x1, y1, x2, y2):
        self.cell.shapes(self.layers[layer]).insert(db.Box(x1, y1, x2, y2))

    def landing(self, layer, x, y, width, height=None):
        height = width if height is None else height
        self.rect(layer, x - width // 2, y - height // 2, x + width // 2, y + height // 2)

    def wire(self, layer, first, last, width):
        x, y = first
        u, v = last
        if x != u and y != v:
            raise ValueError(f"Non-Manhattan wire {first} to {last}")
        half = width // 2
        self.rect(layer, min(x, u) - half, min(y, v) - half, max(x, u) + half, max(y, v) + half)

    def via(self, lower, x, y):
        if lower == 1:
            cut, width1, width2 = 150, 320, 320
        elif lower == 2:
            cut, width1, width2 = 200, 370, 340
        elif lower == 3:
            cut, width1, width2 = 200, 380, 340
        elif lower == 4:
            cut, width1, width2 = 800, 1180, 1420
        else:
            raise ValueError(lower)
        self.landing(f"via{lower}", x, y, cut)
        self.landing(f"met{lower}", x, y, width1)
        self.landing(f"met{lower + 1}", x, y, width2)

    def stack(self, lower, upper, point):
        for layer in range(lower, upper):
            self.via(layer, *point)

    def contact(self, x, y, poly=False, metal=True):
        self.landing("licon", x, y, 170)
        self.landing("li", x, y, 330)
        if metal:
            self.landing("mcon", x, y, 170)
            self.landing("met1", x, y, 300)
        if poly:
            self.landing("npc", x, y, 420)

    def pin(self, name, metal, x, y, w, h):
        if name in self.pins:
            raise ValueError(f"Duplicate pin {name}")
        self.port_shape(name, metal, x, y, w, h)

    def port_shape(self, name, metal, x, y, w, h, label=True):
        layer = LAYERS[metal][0]
        for purpose in ((5, 16) if label else (16,)):
            self.cell.shapes(self.layout.layer(layer, purpose)).insert(db.Text(name, x, y))
        box = (x - w // 2, y - h // 2, x + w // 2, y + h // 2)
        self.cell.shapes(self.layout.layer(layer, 16)).insert(db.Box(*box))
        self.pins.setdefault(name, []).append((metal, box))

    def transistor(self, device, x, y, gate_up=True, diffusion=None, contacts=None,
                   implant=True, gate_y=None, on_li=False, gate_contact_x=None):
        """Draw a single-finger MOSFET with drain on the left."""
        length = device.dimension("l")
        width = device.dimension("w")
        upper = y + width
        pmos = device.model == PMOS
        left, right = diffusion or (x - 440, x + length + 440)
        self.rect("diff", left, y, right, upper)
        if implant:
            self.rect("psdm" if pmos else "nsdm", left - 130, y - 130, right + 130, upper + 130)
        gate_x = round_grid(x + length / 2)
        if gate_y is None:
            gate_y = upper + 410 if gate_up else y - 410
        self.rect("poly", x, min(y - 145, gate_y), x + length, max(upper + 145, gate_y))
        if gate_contact_x is not None:
            self.wire("poly", (gate_x, gate_y), (gate_contact_x, gate_y), 150)
            gate_x = gate_contact_x
        self.landing("poly", gate_x, gate_y, 330)
        self.contact(gate_x, gate_y, poly=True, metal=not on_li)
        mid = round_grid(y + width / 2)
        drain_x, source_x = contacts or (x - 245, x + length + 245)
        for contact_x in (drain_x, source_x):
            if contact_x is not None:
                self.contact(contact_x, mid, metal=not on_li)
        return (drain_x, mid), (gate_x, gate_y), (source_x, mid)

    def body_tap(self, x, y, pmos):
        self.landing("tap", x, y, 420)
        self.landing("nsdm" if pmos else "psdm", x, y, 680)
        self.contact(x, y)

    def capacitor(self, device, x, y):
        width, length = (device.dimension(p) for p in ("w", "l"))
        self.rect("capm", x, y, x + width, y + length)
        self.rect("met3", x - 180, y - 180, x + width + 860, y + length + 180)
        top = (x + width // 2, y + length // 2)
        bottom = (x + width + 590, top[1])
        self.via(3, *top)
        self.via(2, *bottom)
        return (4, *top), (2, *bottom)

    def resistor(self, x, y, length):
        right = x + length + 4_320
        self.rect("poly", x, y, right, y + 350)
        self.rect("poly_res", x + 2_160, y, right - 2_160, y + 350)
        self.rect("urpm", x - 200, y - 460, right + 200, y + 810)
        self.rect("psdm", x - 110, y - 110, right + 110, y + 460)
        self.rect("npc", x - 95, y - 95, right + 95, y + 445)
        center = y + 175
        for left in (x, right - 2_160):
            self.rect("licon", left + 80, y + 90, left + 2_080, y + 260)
            self.rect("li", left, y, left + 2_160, y + 350)
            self.rect("met1", left, y, left + 2_160, y + 350)
            for offset in (400, 800, 1_200, 1_600):
                self.landing("mcon", left + offset, center, 170)
        return (x + 1_080, center), (right - 1_080, center)

    def write(self, output, ports):
        if set(ports) != set(self.pins):
            raise ValueError(f"Pin mismatch, missing {set(ports) - set(self.pins)}, extra {set(self.pins) - set(ports)}")
        self.rect("boundary", 0, 0, WIDTH, HEIGHT)
        if self.cell.bbox() != db.Box(0, 0, WIDTH, HEIGHT):
            raise ValueError(f"DCO shapes exceed the declared boundary: {self.cell.bbox()}")
        options = db.SaveLayoutOptions()
        options.set_format_from_filename(f"{TOP}.gds")
        options.gds2_write_timestamps = False
        self.layout.write(str(output / f"{TOP}.gds"), options)
        lines = ['VERSION 5.7 ;', 'BUSBITCHARS "[]" ;', 'DIVIDERCHAR "/" ;',
                 f"MACRO {TOP}", "  CLASS BLOCK ;", "  ORIGIN 0 0 ;",
                 f"  SIZE {WIDTH / 1000:g} BY {HEIGHT / 1000:g} ;"]
        for name in ports:
            direction = "OUTPUT" if name.startswith(("tap_", "fine_tap_")) else "INPUT"
            use = {"vdd": "POWER", "vss": "GROUND"}.get(name, "SIGNAL")
            lines += [f"  PIN {lef_name(name)}", f"    DIRECTION {direction} ;",
                      f"    USE {use} ;", "    PORT"]
            for metal, box in self.pins[name]:
                lines += [f"      LAYER {metal} ;", "        RECT " +
                          " ".join(f"{value / 1000:g}" for value in box) + " ;"]
            lines += ["    END", f"  END {lef_name(name)}"]
        lines += ["  OBS", "    LAYER li1 ;", f"      RECT 0 0 {WIDTH / 1000:g} {HEIGHT / 1000:g} ;"]
        for metal in ("met1", "met2", "met3", "met4", "met5"):
            metal_region = db.Region(self.cell.shapes(self.layers[metal]))
            pins = [db.Box(*box) for shapes in self.pins.values() for layer, box in shapes if layer == metal]
            if pins:
                metal_region -= db.Region(pins)
            if metal_region.is_empty():
                continue
            lines.append(f"    LAYER {metal} ;")
            for polygon in metal_region.decompose_trapezoids_to_region().each():
                box = polygon.bbox()
                lines.append(f"      RECT {box.left / 1000:g} {box.bottom / 1000:g} "
                             f"{box.right / 1000:g} {box.top / 1000:g} ;")
        lines += ["  END", f"END {TOP}", "END LIBRARY", ""]
        (output / f"{TOP}.lef").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def dac_rows(devices, bank):
    prefix, count = ("u", 255) if bank == "coarse" else ("fine_unit", 128)
    row, cursor = [], LEFT
    for index in range(count):
        unit = devices.pop(f"{prefix}{index}_unit")
        switch = devices.pop(f"{prefix}{index}_switch")
        pitch = unit.dimension("l") + 1_810
        if cursor + pitch > RIGHT:
            yield row
            row, cursor = [], LEFT
        row.append((cursor + 540, unit, switch))
        cursor += pitch
    yield row


def draw_dac(layout, devices):
    y = 2_350
    rail_start = {}
    for bank in ("coarse", "fine"):
        for row in dac_rows(devices, bank):
            height = max(switch.dimension("w") for _, _, switch in row)
            bias_y, drain_y, ground_y = y - 840, y - 340, y + height + 155
            drain_x = BP_X if bank == "coarse" else FINE_BP_X
            last_gate, last_unit, last_switch = row[-1]
            layout.wire("met2", (VREF_X, bias_y), (last_gate + last_unit.dimension("l") // 2, bias_y), 300)
            drain_end = row[-1][0] - 245 if bank == "coarse" else row[0][0] - 245
            layout.wire("met2", (drain_x, drain_y), (drain_end, drain_y), 300)
            last_source = last_gate + last_unit.dimension("l") + 450 + last_switch.dimension("l") + 330
            layout.wire("met2", (VSS_X, ground_y), (last_source, ground_y), 340)
            layout.rect("nsdm", row[0][0] - 505, y - 130, last_source + 360, y + height + 130)
            layout.via(2, VREF_X, bias_y)
            layout.via(2, drain_x, drain_y)
            layout.via(2, VSS_X, ground_y)
            for rail_x, rail_y in ((VREF_X, bias_y), (drain_x, drain_y), (VSS_X, ground_y)):
                rail_start.setdefault(rail_x, rail_y)
            # Strap the p-substrate at both ends and at regular interior gaps.
            tap_y = ground_y + 490
            tap_locations = [LEFT - 650, RIGHT + 440] + [gate_x - 390 for gate_x, _, _ in row[1::4]]
            for tx in tap_locations:
                layout.body_tap(tx, tap_y, False)
                layout.wire("met1", (tx, tap_y), (tx, ground_y), 240)
                layout.wire("met2", (VSS_X, ground_y), (tx, ground_y), 360)
                layout.via(1, tx, ground_y)
            for gate_x, unit, switch in row:
                if unit.nets[1:] != ("vref", switch.nets[0], "vss") or switch.nets[2:] != ("vss", "vss"):
                    raise ValueError(f"Unexpected connections in {unit.name}")
                switch_y = round_grid(y + (height - switch.dimension("w")) / 2)
                unit_y = round_grid(switch_y + (switch.dimension("w") - unit.dimension("w")) / 2)
                unit_right = gate_x + unit.dimension("l")
                switch_x = unit_right + 450
                switch_right = switch_x + switch.dimension("l")
                join_x = unit_right + 175
                d, g, _ = layout.transistor(unit, gate_x, unit_y, gate_up=False, implant=False,
                                             diffusion=(gate_x - 375, join_x),
                                             contacts=(gate_x - 245, None), gate_y=bias_y)
                _, gs, ss = layout.transistor(switch, switch_x, switch_y,
                                               diffusion=(join_x, switch_right + 470),
                                               contacts=(None, switch_right + 330),
                                               implant=False, gate_y=ground_y + 900)
                layout.wire("met1", d, (d[0], drain_y), 320)
                layout.via(1, d[0], drain_y)
                layout.wire("met1", g, (g[0], bias_y), 320)
                layout.via(1, g[0], bias_y)
                layout.wire("met1", ss, (ss[0], ground_y), 320)
                layout.via(1, ss[0], ground_y)
                pin_x, pin_y = gs
                layout.stack(1, 3, gs)
                layout.pin(switch.nets[1], "met3", pin_x, pin_y, 340, 340)
            y += height + 2_750
    for x, bottom in rail_start.items():
        layout.wire("met3", (x, bottom), (x, y), 480 if x == VSS_X else 360)
    return y


def stage_row(stage):
    return [f"s{stage}_{part}" for part in ("p_starve", "p_core", "n_core", "n_starve")] + [
        f"b{stage}_{side}_{part}" for part in ("in", "out") for side in ("p", "n")
    ] + [
        f"{name}_{side}_delay"
        for name in (f"delay{3*stage}", f"delay{3*stage+1}", f"delay{3*stage+2}", f"delay_load{stage}")
        for side in ("p", "n")
    ]


def draw_core(layout, devices, start_y):
    points = {}
    p_top, n_top = HEIGHT - 2_000, 82_750
    ring_pitch = 19_600
    p_landing, n_landing = p_top - 10_200, n_top - 4_950
    layout.rect("nwell", 3_450, p_top - 8_850, 126_200, HEIGHT - 220)
    layout.rect("psdm", 4_150, p_top - 8_540, 123_000, p_top + 130)
    layout.rect("nsdm", 4_150, n_top - 4_350, 123_000, n_top + 130)

    def append(net, metal, point):
        points.setdefault(net, []).append((metal, *point))

    def place(device, column, top, landing):
        y = top - device.dimension("w")
        length = device.dimension("l")
        x = column + (550 if length > 300 else 600)
        tracks = (column, column + 700, column + 2_100) if length > 500 else (
            column, column + 700, column + 1_400)
        points_for_device = layout.transistor(device, x, y, gate_up=False, implant=False,
                                              on_li=True, gate_contact_x=tracks[1])
        for net, point, track in zip(device.nets[:3], points_for_device, tracks, strict=True):
            # Lift each terminal locally. The longer drops use perpendicular
            # routing layers above the active and gate contacts.
            if point == points_for_device[1]:
                escape = point
            else:
                escape = (track, point[1])
                layout.rect("li", min(point[0], track) - 90, point[1] - 165,
                            max(point[0], track) + 90, point[1] + 165)
            layout.landing("li", *escape, 330)
            layout.landing("mcon", *escape, 170)
            layout.via(1, *escape)
            if device.model == PMOS:
                endpoint = (track, landing)
                layout.wire("met2", escape, endpoint, 300)
                layout.stack(2, 4, endpoint)
                append(net, 4, endpoint)
            else:
                append(net, 2, escape)
        return column + (2_800 if length > 500 else 2_100)

    bias_names = [name for name, device in devices.items()
                  if not re.match(r"^(s\d|b\d|delay|load)", name) and device.model in (NMOS, PMOS)]
    for model, top, landing in ((PMOS, p_top, p_landing), (NMOS, n_top, n_landing)):
        column = 4_900
        names = [name for name in bias_names if name in devices and devices[name].model == model]
        for name in names:
            column = place(devices.pop(name), column, top, landing)
        if column > 26_600:
            raise ValueError("The bias transistors overrun the first ring stage")

    for i in range(5):
        x = 26_600 + i * ring_pitch
        names = stage_row(i)
        for model, top, landing in ((PMOS, p_top, p_landing), (NMOS, n_top, n_landing)):
            group = [name for name in names if name in devices and devices[name].model == model]
            column = x
            for name in group:
                column = place(devices.pop(name), column, top, landing)
        cap = devices.pop(f"load{i}")
        a, b = layout.capacitor(cap, x + 15_900, HEIGHT - 4_200)
        points.setdefault(cap.nets[0], []).append(a)
        points.setdefault(cap.nets[1], []).append(b)

    resistor = devices.pop("r_ref")
    p_tap_y, n_tap_y = HEIGHT - 850, n_top + 780
    for body_x in (4_250, 24_500, 45_300, 68_000, 90_900, 122_100):
        layout.body_tap(body_x, p_tap_y, True)
        layout.body_tap(body_x, n_tap_y, False)
    layout.wire("met1", (4_250, p_tap_y), (VDD_X, p_tap_y), 480)
    layout.wire("met1", (VSS_X, n_tap_y), (122_100, n_tap_y), 480)
    layout.stack(1, 4, (VDD_X, p_tap_y))
    layout.stack(1, 4, (VSS_X, n_tap_y))
    append("vdd", 4, (VDD_X, p_tap_y))
    append("vss", 4, (VSS_X, n_tap_y))
    a, b = layout.resistor(114_950, 85_100, resistor.dimension("l"))
    for net, contact in zip(resistor.nets[:2], (a, b), strict=True):
        append(net, 1, contact)
    if devices:
        raise ValueError(f"Unplaced devices {sorted(devices)}")
    for net, x in (("vss", VSS_X), ("vref", VREF_X), ("bp", BP_X), ("fine_bp", FINE_BP_X)):
        append(net, 3, (x, start_y - 280))
    return points, n_landing, p_landing


def route_core(layout, points, ports, n_landing, p_landing):
    # Metal2 approaches from the NMOS row and metal4 from the PMOS row.
    rows = list(range(n_landing + 700, p_landing - 650, 700))
    tracks = [[] for _ in rows]
    locations = {"vdd": VDD_X, "vss": VSS_X}
    channels = {}
    for net, terminals in sorted(points.items(), key=lambda item: min(p[1] for p in item[1])):
        left, right = min(p[1] for p in terminals), max(p[1] for p in terminals)
        index = next((i for i, spans in enumerate(tracks)
                      if all(right + 700 < a or left - 700 > b for a, b in spans)), None)
        if index is None:
            raise ValueError(f"Insufficient routing tracks for {net} at {left / 1000:g}..{right / 1000:g} um")
        tracks[index].append((left, right))
        channels[net] = rows[index]
    for net, terminals in points.items():
        y = channels[net]
        lo, hi = min(x for _, x, _ in terminals), max(x for _, x, _ in terminals)
        layout.wire("met3", (lo, y), (hi, y), 340)
        for metal, x, point_y in terminals:
            if metal == 4:
                layout.wire("met4", (x, point_y), (x, y), 340)
                layout.via(3, x, y)
            else:
                if metal == 1:
                    layout.via(1, x, point_y)
                elif metal == 3:
                    layout.via(2, x, point_y)
                layout.wire("met2", (x, point_y), (x, y), 300)
                layout.via(2, x, y)
        if net in ports:
            x = locations.get(net, (lo + hi) // 10 * 5)
            layout.pin(net, "met3", x, y, 340, 340)


def write_lvs_reference(path, ports, devices):
    lines = [f".subckt {TOP} " + " ".join(ports)]
    for device in devices:
        nodes = " ".join(device.nets)
        if device.model in (NMOS, PMOS):
            lines.append(f"M{device.name} {nodes} {device.model} W={device.params['w']}u L={device.params['l']}u")
        elif device.model == CAPACITOR:
            width, length = (device.dimension(p) / 1000 for p in ("w", "l"))
            capacitance = 2e-15 * width * length
            lines.append(f"C{device.name} {nodes} sky130_fd_pr__model__cap_mim C={capacitance:.7g} "
                         f"A={width * length:g}p P={2 * (width + length):g}u")
        else:
            resistance = 2000 * float(device.params["l"]) / 0.35
            lines.append(f"R{device.name} {nodes} {device.model} R={resistance:g} W=0.35u L={device.params['l']}u")
    lines += [f".ends {TOP}", ""]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schematic", type=Path, default=SCHEMATIC)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    ports, devices = schematic_devices(args.schematic)
    layout = Layout()
    todo = devices.copy()
    dac_top = draw_dac(layout, todo)
    core, n_landing, p_landing = draw_core(layout, todo, dac_top)
    route_core(layout, core, ports, n_landing, p_landing)
    # Independent metal5 supply landings give the top level an unobstructed
    # vertical connection at the right and left edges of the analog block.
    for net, x, y in (("vdd", VDD_X, HEIGHT - 850), ("vss", VSS_X, 83_530)):
        layout.via(4, x, y)
        pin_x = min(WIDTH - 1_350, max(1_350, x))
        layout.landing("met5", pin_x, y, 2_600, 1_600)
        layout.port_shape(net, "met5", pin_x, y, 2_600, 1_600, label=False)
    layout.write(args.output, ports)
    write_lvs_reference(args.output / "cpz4_dco_lvs.spice", ports, devices.values())
    print(f"DAC occupies the lower {dac_top / 1000:g} um")
    print(f"{TOP} schematic contains {len(ports)} pins and {len(devices)} primitive devices")


if __name__ == "__main__":
    main()
