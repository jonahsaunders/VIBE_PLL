#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify the complete streamed PLL against real device-level references."""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from check_dco import normalize_lvs, run


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build", type=Path, required=True)
    p.add_argument("--pdk", type=Path, required=True)
    p.add_argument("--klayout", default="klayout")
    p.add_argument("--route-exit-code", type=int, default=0)
    p.add_argument("--geometry-mode", choices=("flat", "deep"), default="flat")
    a = p.parse_args()
    build = a.build.resolve(strict=True)
    decks = a.pdk.resolve() / "libs.tech/klayout"
    layout = build / "cpz4_sky130-review.gds"
    reference = build / "cpz4_sky130_lvs.spice"
    summary = {"top": "cpz4_sky130", "route_exit_code": a.route_exit_code,
               "enabled_drc_groups": ["feol", "beol", "offgrid"],
               "lvs_geometry_mode": a.geometry_mode, "passed": False}
    result = build / "physical-verification.json"
    report = build / "pll-drc.lyrdb"
    for stale in (result, report, build / "pll-lvs.lvsdb", build / "pll-lvs.log",
                  build / "cpz4_sky130.gds"):
        stale.unlink(missing_ok=True)
    try:
        for label, path in (("layout", layout), ("reference", reference),
                            ("drc_deck", decks / "drc/sky130A_mr.drc"),
                            ("lvs_deck", decks / "lvs/sky130.lvs")):
            summary[label + "_sha256"] = sha(path)
        run(a.klayout, build, "pll-drc", decks / "drc/sky130A_mr.drc",
            {"input": layout, "report": report, "top_cell": "cpz4_sky130",
             "feol": 1, "beol": 1, "offgrid": 1})
        summary["drc_markers"] = len(ET.parse(report).findall("./items/item"))
        deck = build / "sky130-portable.lvs"
        normalize_lvs(decks / "lvs/sky130.lvs", deck)
        # Extract the full physical geometry flat so substrate junctions
        # and shared standard-cell wells are evaluated in their real
        # top-level surroundings. This also avoids hierarchy-dependent
        # diode omissions in older KLayout releases. No device is waived.
        text = deck.read_text()
        section = "#=== FLATTEN CELLS ===\nalign"
        if section not in text:
            raise ValueError("Expected the Sky130 hierarchy alignment section")
        text = text.replace(section, "#=== FLATTEN CELLS ===\nnetlist.make_top_level_pins\nnetlist.flatten\nschematic.flatten\nalign", 1)
        # Preserve the actual top-level interface. Calling simplify after
        # flatten would turn internal cell labels into new external pins.
        for graph in ("netlist", "schematic"):
            text = text.replace(graph + ".simplify", graph + ".purge\n" +
                                graph + ".combine_devices\n" + graph + ".purge_nets")
        # Include physical-junction diagnostics without changing extraction.
        junction = 'logger.info("Starting DIODE EXTRACTION")'
        if junction not in text:
            raise ValueError("Expected the Sky130 diode extraction section")
        text = text.replace(junction, junction + """
logger.info("JUNCTION GEOMETRY ncomp=#{ncomp.area} marker=#{areaid_de.area} ndiode=#{ndiode_5v0_terminal_n.area} sub=#{sub.area} overlap=#{(ndiode_5v0_terminal_n & sub).area}")
""", 1)
        before_flatten = "netlist.make_top_level_pins"
        counts = """
junction_counts = Hash.new(0)
netlist.each_circuit { |c| c.each_device { |d| junction_counts[d.device_class.name] += 1 } }
logger.info("JUNCTION RAW DEVICES #{junction_counts.inspect}")
"""
        text = text.replace(before_flatten, counts + before_flatten, 1)
        text = text.replace("netlist.flatten", "netlist.flatten" + counts.replace("RAW", "FLATTENED"), 1)
        deck.write_text(text)
        run(a.klayout, build, "pll-lvs", deck,
            {"input": layout, "schematic": reference, "report": build / "pll-lvs.lvsdb",
             "target_netlist": build / "pll-extracted.spice", "lvs_sub": "vss",
             "schematic_simplify": "true", "run_mode": a.geometry_mode, "thr": 4})
        summary["lvs_match"] = "Netlists match." in (build / "pll-lvs.log").read_text()
        route_drc = int((build / "route-violations.txt").read_text().strip())
        route_checks = (build / "route-checks.txt").read_text()
        summary["route_drc"] = route_drc
        summary["route_checks"] = route_checks
        checks = dict(line.split(": ", 1) for line in route_checks.splitlines())
        summary["passed"] = (summary["drc_markers"] == 0 and summary["lvs_match"] and
                             route_drc == 0 and a.route_exit_code == 0 and
                             checks.get("All signal nets routed") == "1" and
                             checks.get("Antenna-violating nets") == "0" and
                             checks.get("Power grids connected") == "1")
        if summary["passed"]:
            (build / "cpz4_sky130.gds").write_bytes(layout.read_bytes())
        return 0 if summary["passed"] else 1
    finally:
        result.write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
