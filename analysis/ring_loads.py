#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Identify and measure interconnect loading at each extracted ring stage."""
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
    # The seed transistor pulls n0 to VSS. Each ring NMOS identifies
    # the next stage even if the extractor interchanged source and drain.
    successors, seeds = {}, []
    for r in rows:
        if "sky130_fd_pr__nfet_01v8" in r:
            for terminal, other in ((r[1], r[3]), (r[3], r[1])):
                if terminal in nodes:
                    if other == "vss":
                        seeds.append(terminal)
                    if r[2] in nodes:
                        successors[r[2]] = terminal
    if len(seeds) != 1 or set(successors) != nodes:
        raise ValueError("Cannot identify the seed and five ring stages")
    ordered = [seeds[0]]
    for _ in range(4):
        ordered.append(successors[ordered[-1]])
    if set(ordered) != nodes or successors[ordered[-1]] != ordered[0]:
        raise ValueError("Ring stages do not form a five-node loop")
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
    return [(f"n{i}", n, *loads[n], sum(loads[n])) for i, n in enumerate(ordered)]


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("netlist", type=Path)
    args = p.parse_args()
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(["stage", "extracted_net", "rail_cap_ff", "coupling_cap_ff", "incident_cap_ff"])
    writer.writerows(ring_loads(args.netlist))
