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


def read_cells(paths, cdl_paths=()):
    # The foundry CDL identifies tie-cell poly straps as `short`. SPICE
    # models these conductors with parasitic resistance; geometry LVS must
    # retain their connectivity, using the independent CDL declaration.
    shorts = {}
    for path in cdl_paths:
        logical = re.sub(r"\r?\n\+\s*", " ", path.read_text())
        for match in re.finditer(r"(?ims)^\.subckt\s+(\S+)[ \t]+([^\n]*)\n(.*?)^\.ends[^\n]*", logical):
            name, ports, body = match.groups()
            pairs = re.findall(r"(?im)^r\S+\s+(\S+)\s+(\S+)\s+short\s*$", body)
            # Internal CDL node names need not survive SPICE compilation;
            # only port-to-port straps require boundary equivalence here.
            pairs = [pair for pair in pairs if all(n in ports.split() for n in pair)]
            if pairs:
                shorts[name] = {frozenset(pair) for pair in pairs}
    cells = {}
    for path in paths:
        logical = re.sub(r"\r?\n\+\s*", " ", path.read_text())
        for match in re.finditer(r"(?ims)^\.subckt\s+(\S+)[ \t]+([^\n]*)\n(.*?)^\.ends[^\n]*", logical):
            name, ports, body = match.groups()
            lines = [f".subckt {name} {ports}"]
            aliases = {}
            seen_shorts = set()
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
                elif model == "sky130_fd_pr__res_generic_po" and len(nets) == 2:
                    pair = frozenset(nets)
                    if pair in shorts.get(name, set()):
                        aliases[nets[1]] = nets[0]
                        seen_shorts.add(pair)
                        continue
                    width, length = (dimension(params[p]) for p in ("w", "l"))
                    if width <= 0 or length <= 0:
                        raise ValueError(f"Invalid resistor geometry in {path}: {line}")
                    resistance = 48.2 * length / width
                    lines.append(f"R{words[0]} {' '.join(nets)} {model} R={resistance:g} W={width:g}u L={length:g}u")
                elif words[0].upper().startswith("X") and model.startswith("sky130_fd_sc_hd__") and not params:
                    lines.append(line)
                else:
                    raise ValueError(f"Unsupported cell device in {path}: {line}")
            if seen_shorts != shorts.get(name, set()):
                raise ValueError(f"SPICE and CDL disagree on conductor shorts in {name}")
            if aliases:
                # Duplicate formal nodes express real pin equivalence. On
                # flattening, KLayout joins the corresponding parent nets.
                lines[0] = f".subckt {name} " + " ".join(aliases.get(p, p) for p in ports.split())
            lines.append(f".ends {name}")
            value = (ports.split(), "\n".join(lines))
            if name in cells and value != cells[name]:
                raise ValueError(f"Conflicting PDK definitions for {name}")
            cells[name] = value
    for name, (ports, body) in cells.items():
        for line in body.splitlines():
            if line.lstrip().upper().startswith("X"):
                words = line.split()
                if words[-1] not in cells or len(words[1:-1]) != len(cells[words[-1]][0]):
                    raise ValueError(f"Unknown cell or incorrect pin count in {name}: {line}")
    return cells


def main():
    import odb
    build = Path(os.environ["OUT_DIR"])
    pdk = Path(os.environ["SKY130A"])
    cell_root = pdk / "libs.ref/sky130_fd_sc_hd"
    cells = read_cells(sorted((cell_root / "spice").glob("*.spice")),
                       sorted((cell_root / "cdl").glob("*.cdl")))
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
    pending = list(used)
    while pending:
        name = pending.pop()
        for line in cells[name][1].splitlines():
            if line.lstrip().upper().startswith("X"):
                child = line.split()[-1]
                if child not in used:
                    used.add(child)
                    pending.append(child)
    lines += [cells[name][1] for name in sorted(used)]
    (build / "cpz4_sky130_lvs.spice").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
