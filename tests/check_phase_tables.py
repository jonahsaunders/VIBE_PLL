#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check that the fixed hardware tables use the centers of the recorded PEX bins."""
import argparse
import csv
import math
from pathlib import Path
import re

from run_rtl import ROOT, phase_centers


def packed_centers(path, corner):
    with path.open(newline="") as file:
        rows = list(csv.DictReader(file))
    if len(rows) != 1 or rows[0]["corner"] != corner:
        raise ValueError(f"Expected one {corner} phase profile in {path}")
    row = rows[0]
    widths = [float(row[f"fine_bin_{i}_ui"]) for i in range(40)]
    if (int(row["bad_tap_sequences"]) or int(row["bad_fine_sequences"])
            or not all(math.isfinite(w) and w >= 0 for w in widths)
            or not math.isclose(sum(widths), 1, abs_tol=1e-5)):
        raise ValueError(f"Invalid phase measurement in {path}")
    return "".join(f"{center:03x}" for center in reversed(phase_centers(widths)))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for corner in ("tt", "ss"):
        p.add_argument("--" + corner, type=Path, required=True)
    args = p.parse_args()
    rtl = (ROOT / "rtl/cpz4_pll.sv").read_text()
    for corner, path in vars(args).items():
        table = "RANGE_" + corner.upper()
        expected = packed_centers(path, corner)
        body = re.search(r"\b" + table + r"\s*=\s*\{([^}]+)\}", rtl)
        actual = "".join(re.findall(r"120'h([a-fA-F0-9]{30})\b", body[1])).lower() if body else ""
        if actual != expected:
            raise SystemExit(f"{table} disagrees with {path}\nExpected packed centers: {expected}")
        print(f"{table} matches {path}")
