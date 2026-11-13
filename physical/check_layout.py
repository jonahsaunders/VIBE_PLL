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
    a = p.parse_args()
    build = a.build.resolve(strict=True)
    decks = a.pdk.resolve(strict=True) / "libs.tech/klayout"
    layout = build / "cpz4_sky130-review.gds"
    reference = build / "cpz4_sky130_lvs.spice"
    summary = {"top": "cpz4_sky130", "layout_sha256": sha(layout),
               "reference_sha256": sha(reference), "passed": False}
    result = build / "physical-verification.json"
    report = build / "pll-drc.lyrdb"
    for stale in (result, report, build / "pll-lvs.lvsdb", build / "cpz4_sky130.gds"):
        stale.unlink(missing_ok=True)
    try:
        run(a.klayout, build, "pll-drc", decks / "drc/sky130A_mr.drc",
            {"input": layout, "report": report, "top_cell": "cpz4_sky130",
             "feol": 1, "beol": 1, "offgrid": 1})
        summary["drc_markers"] = len(ET.parse(report).findall("./items/item"))
        deck = build / "sky130-portable.lvs"
        normalize_lvs(decks / "lvs/sky130.lvs", deck)
        run(a.klayout, build, "pll-lvs", deck,
            {"input": layout, "schematic": reference, "report": build / "pll-lvs.lvsdb",
             "target_netlist": build / "pll-extracted.spice", "lvs_sub": "vss", "thr": 4})
        summary["lvs_match"] = "Netlists match." in (build / "pll-lvs.log").read_text()
        route_drc = int((build / "route-violations.txt").read_text().strip())
        route_checks = (build / "route-checks.txt").read_text()
        summary["route_drc"] = route_drc
        summary["route_checks"] = route_checks
        summary["passed"] = (summary["drc_markers"] == 0 and summary["lvs_match"] and
                             route_drc == 0 and "All signal nets routed: 1" in route_checks and
                             "Antenna-violating nets: 0" in route_checks)
        if summary["passed"]:
            (build / "cpz4_sky130.gds").write_bytes(layout.read_bytes())
        return 0 if summary["passed"] else 1
    finally:
        result.write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
