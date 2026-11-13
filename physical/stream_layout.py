#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Merge a standalone routed DEF with Sky130 standard-cell and DCO geometry."""

import argparse
from pathlib import Path

import klayout.db as db


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--technology", type=Path, required=True)
    parser.add_argument("--def", dest="route_def", type=Path, required=True)
    parser.add_argument("--lef", type=Path, nargs="+", required=True)
    parser.add_argument("--gds", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tech = db.Technology()
    tech.load(str(args.technology))
    options = tech.load_layout_options
    lefdef = options.lefdef_config
    lefdef.lef_files = [str(path.resolve()) for path in args.lef]
    options.lefdef_config = lefdef
    layout = db.Layout()
    layout.read(str(args.route_def), options)
    top = layout.cell("cpz4_sky130")
    if top is None:
        raise ValueError("The routed DEF has no cpz4_sky130 top cell")
    for cell in layout.each_cell():
        if cell.cell_index() != top.cell_index() and not cell.name.startswith("VIA_"):
            cell.clear()
    for path in args.gds:
        layout.read(str(path))
    merged = db.Layout()
    merged.dbu = layout.dbu
    merged.create_cell(top.name).copy_tree(top)
    missing = [cell.name for cell in merged.each_cell() if cell.is_empty()]
    if missing:
        raise ValueError(f"Missing physical cell views: {', '.join(sorted(missing))}")
    merged.write(str(args.output))
    print(f"Merged standalone layout: {args.output}")


if __name__ == "__main__":
    main()
