#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Summarize actual KLayout LVS mismatches without changing verification."""
import argparse
from collections import Counter
from pathlib import Path
import klayout.db as db


def value(obj, name):
    field = getattr(obj, name)
    return field() if callable(field) else field


def describe(obj):
    if obj is None:
        return None
    if hasattr(obj, "to_s"):
        return obj.to_s()
    if hasattr(obj, "expanded_name"):
        return value(obj, "expanded_name")
    return str(obj)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("report")
    args = p.parse_args()
    layout_path = Path(args.report).parent / "cpz4_sky130-review.gds"
    if layout_path.exists():
        layout = db.Layout()
        layout.read(str(layout_path))
        for cell in layout.each_cell():
            if "diode" not in cell.name:
                continue
            print("PHYSICAL DIODE CELL", cell.name, str(cell.bbox()), "dbu", layout.dbu)
            for layer in layout.layer_indexes():
                count = cell.shapes(layer).size()
                if count:
                    print("  LAYER", str(layout.get_info(layer)), "shapes", count,
                          "area_um2", db.Region(cell.shapes(layer)).area() * layout.dbu ** 2)
            diff = db.Region(cell.shapes(layout.layer(65, 20)))
            nsdm = db.Region(cell.shapes(layout.layer(93, 44)))
            marker = db.Region(cell.shapes(layout.layer(81, 23)))
            print("  MARKED NDIFF AREA", ((diff & nsdm) & marker).area() * layout.dbu ** 2)
    lvs = db.LayoutVsSchematic()
    lvs.read(args.report)
    for label, netlist in (("LAYOUT", value(lvs, "netlist")), ("REFERENCE", value(lvs, "reference"))):
        classes = Counter()
        for circuit in netlist.each_circuit():
            for device in circuit.each_device():
                classes[value(value(device, "device_class"), "name")] += 1
        print(label, "DEVICE CLASSES", dict(classes))
    xref = value(lvs, "xref")
    for circuit in xref.each_circuit_pair():
        print("CIRCUIT", value(value(circuit, "first"), "name") if value(circuit, "first") else None,
              value(value(circuit, "second"), "name") if value(circuit, "second") else None,
              str(value(circuit, "status")))
        for kind in ("pin", "device", "net", "subcircuit"):
            pairs = list(getattr(xref, "each_" + kind + "_pair")(circuit))
            print(kind, dict(Counter(str(value(pair, "status")) for pair in pairs)))
            bad = [pair for pair in pairs if value(pair, "status") != db.NetlistCrossReference.Match]
            for pair in bad[:80]:
                print("MISMATCH", kind, str(value(pair, "status")),
                      describe(value(pair, "first")), "<=>",
                      describe(value(pair, "second")))
                if kind == "device":
                    for side in ("first", "second"):
                        device = value(pair, side)
                        if device is not None:
                            cls = value(device, "device_class")
                            print("  DEVICE DETAIL", side, value(cls, "name"),
                                  {value(p, "name"): device.parameter(value(p, "id"))
                                   for p in cls.parameter_definitions()},
                                  {value(t, "name"): describe(device.net_for_terminal(value(t, "id")))
                                   for t in cls.terminal_definitions()})
                if kind == "net":
                    terminals = list(xref.each_net_terminal_pair(pair))
                    for terminal in terminals[:12]:
                        print("  TERMINAL", describe(value(terminal, "first")), "<=>",
                              describe(value(terminal, "second")))
                    print("  TOTAL TERMINAL PAIRS", len(terminals))


if __name__ == "__main__":
    main()
