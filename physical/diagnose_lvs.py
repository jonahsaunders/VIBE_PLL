#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Summarize actual KLayout LVS mismatches without changing verification."""
import argparse
from collections import Counter
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
                if kind == "net":
                    terminals = list(xref.each_net_terminal_pair(pair))
                    for terminal in terminals[:12]:
                        print("  TERMINAL", describe(value(terminal, "first")), "<=>",
                              describe(value(terminal, "second")))
                    print("  TOTAL TERMINAL PAIRS", len(terminals))


if __name__ == "__main__":
    main()
