#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Rank interconnect loading at the five ring nodes in a Magic-extracted DCO."""
import argparse
import csv
from pathlib import Path
import re
import sys


def ring_loads(path):
    rows = [line.split() for line in path.read_text().splitlines() if line.strip()]
    nodes = {r[1] for r in rows if r[0].lower().startswith("x") and
             "sky130_fd_pr__cap_mim_m3_1" in r and r[2] == "vss"}
    if len(nodes) != 5:
        raise ValueError("Expected five explicit grounded ring MIM capacitors")
    loads = {n: [0.0, 0.0] for n in nodes}
    scales = {"": 1e15, "p": 1e3, "f": 1, "a": .001}
    for r in rows:
        if not r[0].lower().startswith("c"):
            continue
        for net, other in ((r[1], r[2]), (r[2], r[1])):
            if net in loads:
                m = re.fullmatch(r"([\d.+eE-]+)([pfa]?)", r[3], re.I)
                if not m:
                    raise ValueError(f"Unknown capacitance {r[3]}")
                index = 0 if other in ("0", "vss", "vdd") else 1
                loads[net][index] += float(m[1]) * scales[m[2].lower()]
    return sorted(((n, *v, sum(v)) for n, v in loads.items()), key=lambda row: -row[3])


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("netlist", type=Path)
    args = p.parse_args()
    writer = csv.writer(sys.stdout)
    writer.writerow(["net", "rail_cap_ff", "coupling_cap_ff", "incident_cap_ff"])
    writer.writerows(ring_loads(args.netlist))
