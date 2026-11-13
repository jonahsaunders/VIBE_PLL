#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Export the routed database's intended connectivity as a device-level LVS reference.

Run with OpenROAD's Python interpreter. Real standard-cell device definitions
come from open_pdks; unknown cells, unsupported devices and unconnected pins fail.
"""
import os
from pathlib import Path
import re

NUMBER = re.compile(r"([+-]?[\d.]+(?:e[+-]?\d+)?)([a-z]*)$", re.I)
SCALE = {"": 1, "u": 1e-6, "n": 1e-9, "p": 1e-12, "m": 1e-3}


def dimension(value):
    match = NUMBER.fullmatch(value)
    if not match or match[2].lower() not in SCALE:
        raise ValueError(f"Unsupported PDK geometry {value}")
    return float(match[1]) * SCALE[match[2].lower()]


def read_cells(paths):
    cells = {}
    for path in paths:
        logical = re.sub(r"\r?\n\+\s*", " ", path.read_text())
        for match in re.finditer(r"(?ims)^\.subckt\s+(\S+)[ \t]+([^\n]*)\n(.*?)^\.ends[^\n]*", logical):
            name, ports, body = match.groups()
            lines = [f".subckt {name} {ports}"]
            for line in body.splitlines():
                words = line.split()
                if not words or words[0].startswith("*"):
                    continue
                first_param = next((i for i, w in enumerate(words) if "=" in w), len(words))
                model = words[first_param - 1]
                nets = words[1:first_param - 1]
                params = dict(w.lower().split("=", 1) for w in words[first_param:])
                if "fet_" in model and len(nets) == 4:
                    if any(float(params.get(p, "1")) != 1 for p in ("m", "mult", "nf")):
                        raise ValueError(f"Unsupported MOS multiplicity in {path}: {line}")
                    width, length = (dimension(params[p]) for p in ("w", "l"))
                    if not (0.1 <= width <= 1000 and 0.1 <= length <= 100):
                        raise ValueError(f"Unexpected micron geometry in {path}: {line}")
                    lines.append(f"M{words[0]} {' '.join(nets)} {model} W={width:g}u L={length:g}u")
                elif "diode_" in model and len(nets) == 2:
                    area = dimension(params.get("area", params.get("a", "")))
                    perimeter = dimension(params.get("pj", params.get("p", "")))
                    lines.append(f"D{words[0]} {' '.join(nets)} {model} A={area:g}p P={perimeter:g}u")
                else:
                    raise ValueError(f"Unsupported cell device in {path}: {line}")
            lines.append(f".ends {name}")
            value = (ports.split(), "\n".join(lines))
            if name in cells and value != cells[name]:
                raise ValueError(f"Conflicting PDK definitions for {name}")
            cells[name] = value
    return cells


def main():
    import odb
    build = Path(os.environ["OUT_DIR"])
    pdk = Path(os.environ["SKY130A"])
    cells = read_cells(sorted((pdk / "libs.ref/sky130_fd_sc_hd/spice").glob("*.spice")))
    if not cells:
        raise ValueError("No standard-cell SPICE definitions in the selected PDK")
    macro = (build / "cpz4_dco_lvs.spice").read_text()
    macro_ports = re.search(r"(?im)^\.subckt cpz4_dco (.*)$", macro)[1].split()
    database = odb.dbDatabase.create()
    odb.read_db(database, str(build / "routed.odb"))
    block = database.getChip().getBlock()
    ports = sorted(term.getName() for term in block.getBTerms())
    lines = ["* Intended post-route connectivity, independent of GDS extraction.",
             ".subckt cpz4_sky130 " + " ".join(ports)]
    used = set()
    for index, inst in enumerate(sorted(block.getInsts(), key=lambda i: i.getName())):
        master = inst.getMaster().getName()
        if master == "cpz4_dco":
            pins = macro_ports
        elif master in cells:
            pins = cells[master][0]
            used.add(master)
        else:
            raise ValueError(f"No transistor-level reference for {master}")
        nets = []
        for pin in pins:
            physical_pin = re.sub(r"_(\d+)$", r"[\1]", pin) if master == "cpz4_dco" else pin
            iterm = inst.findITerm(physical_pin)
            if iterm is not None and iterm.getNet() is None and iterm.getMTerm().getIoType() == "OUTPUT":
                nets.append(f"unused_output_{index}_{physical_pin}")
                continue
            if iterm is None or iterm.getNet() is None:
                raise ValueError(f"Unconnected reference terminal {inst.getName()}/{physical_pin}")
            nets.append(iterm.getNet().getName())
        lines.append(f"X{index} {' '.join(nets)} {master}")
    lines += [".ends cpz4_sky130", macro]
    lines += [cells[name][1] for name in sorted(used)]
    (build / "cpz4_sky130_lvs.spice").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
