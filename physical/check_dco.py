#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the Sky130 KLayout geometry and device-connectivity checks for the DCO."""

import argparse
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


def normalize_lvs(source, target):
    # The bundled deck uses a Linux-only memory logger and appends default
    # R/C parameters even when the reference netlist supplies those values.
    # KLayout's SPICE reader also uppercases model names and net labels.
    text = "\n".join(
        "  msg" if "Memory Usage" in line and "pmap" in line else line
        for line in source.read_text(encoding="utf-8").splitlines()
    )
    for line in ('super(s + " C=2e-16", element)', 'super(s + " R=0", element)'):
        text = text.replace(line, "super(s, element)")
    comparison = "#=== COMPARE ===\ncompare"
    if comparison not in text:
        raise ValueError("Expected the open_pdks Sky130 comparison section")
    text = text.replace(comparison, """#=== COMPARE ===
schematic.each_device_class { |dc| dc.name = dc.name.downcase }
schematic.each_circuit do |c|
  c.name = c.name.downcase
  c.each_net { |n| n.name = n.name.downcase }
end
compare""", 1)
    target.write_text(text + "\n", encoding="utf-8", newline="\n")


def run(klayout, build, tag, deck, settings):
    command = [klayout, "-b"]
    for key, value in settings.items():
        command += ["-rd", f"{key}={value}"]
    command += ["-r", str(deck)]
    log = build / f"{tag}.log"
    with log.open("w", encoding="utf-8") as output:
        result = subprocess.run(command, cwd=build, stdout=output, stderr=subprocess.STDOUT)
    if result.returncode:
        raise SystemExit(f"{tag} exited with {result.returncode}. See {log}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--klayout", default="klayout")
    parser.add_argument("--pdk", type=Path, required=True, help="Sky130A open_pdks root")
    parser.add_argument("--build", type=Path, required=True)
    args = parser.parse_args()
    build = args.build.resolve(strict=True)
    pdk = args.pdk.resolve(strict=True) / "libs.tech" / "klayout"
    layout = build / "cpz4_dco.gds"
    drc_report = build / "dco-drc.lyrdb"
    run(args.klayout, build, "dco-drc", pdk / "drc" / "sky130A_mr.drc",
        {"input": layout, "report": drc_report, "top_cell": "cpz4_dco",
         "feol": 1, "beol": 1, "offgrid": 1})
    violations = len(ET.parse(drc_report).findall("./items/item"))
    print(f"DCO geometry DRC markers: {violations}")
    deck = build / "sky130-portable.lvs"
    normalize_lvs(pdk / "lvs" / "sky130.lvs", deck)
    run(args.klayout, build, "dco-lvs", deck,
        {"input": layout, "schematic": build / "cpz4_dco_lvs.spice",
         "report": build / "dco-lvs.lvsdb", "lvs_sub": "vss", "thr": 2})
    if "Netlists match." not in (build / "dco-lvs.log").read_text(encoding="utf-8"):
        raise SystemExit("KLayout did not report a matching device netlist")
    print("DCO LVS match")
    return int(violations != 0)


if __name__ == "__main__":
    raise SystemExit(main())
