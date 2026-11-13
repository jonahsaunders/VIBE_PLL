#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the Sky130 KLayout geometry and device-connectivity checks for the DCO."""

import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


def normalize_lvs(source, target):
    # The bundled deck uses a Linux-only memory logger and appends default
    # R/C parameters even when the reference netlist supplies those values.
    # KLayout's SPICE reader also uppercases model names and net labels.
    text = "\n".join(
        '  "#{msg}\\n"' if "Memory Usage" in line and "pmap" in line else line
        for line in source.read_text(encoding="utf-8").splitlines()
    )
    for line in ('super(s + " C=2e-16", element)', 'super(s + " R=0", element)'):
        text = text.replace(line, "super(s, element)")
    # The packaged deck recognizes N+ substrate diodes only inside a
    # closed local tap ring. Standard-cell antenna diodes instead use the
    # row's shared substrate taps. Use the physical substrate for the anode,
    # as in the newer upstream Sky130 deck, while keeping the independently
    # derived N+ diffusion and its connected cathode layer. No diode,
    # parameter, or connection is removed from comparison.
    ring_rule = "ndiode_terminal_p = ptap_conn.holes.interacting(ndiode_terminal_n)"
    if ring_rule in text:
        pattern = re.compile(
            r'^extract_devices\(diode\("(sky130_fd_pr__diode_pw2nd_[^"]+)", Diode\),.*$', re.M)
        def substrate_diode(match):
            cathode = re.search(r'"N"\s*=>\s*(ndiode_\w+)', match[0])
            if cathode is None:
                raise ValueError("Missing substrate-diode cathode region")
            return (f'extract_devices(diode("{match[1]}", Diode), '
                    '{ "P" => sub, "N" => ' + cathode[1]
                    + ', "tA" => sub, "tC" => ndiode_terminal_n})')
        text, count = pattern.subn(substrate_diode, text)
        if count != 4:
            raise ValueError(f"Expected four substrate-diode extractors, found {count}")
    comparison = "#=== COMPARE ===\ncompare"
    if comparison not in text:
        raise ValueError("Expected the open_pdks Sky130 comparison section")
    text = text.replace(comparison, """#=== COMPARE ===
schematic.each_device_class { |dc| dc.name = dc.name.downcase }
schematic.each_circuit do |c|
  c.name = c.name.downcase
  c.each_net { |n| n.name = n.name.downcase }
end
netlist.each_circuit do |c|
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
    pdk = args.pdk.resolve() / "libs.tech" / "klayout"
    layout = build / "cpz4_dco.gds"
    drc_report = build / "dco-drc.lyrdb"
    reference = build / "cpz4_dco_lvs.spice"
    result_path = build / "dco-verification.json"
    for stale in (drc_report, build / "dco-lvs.lvsdb", build / "dco-lvs.log", result_path):
        stale.unlink(missing_ok=True)
    result = {"top": "cpz4_dco", "passed": False, "enabled_drc_groups": ["feol", "beol", "offgrid"]}
    try:
        for label, path in (("layout", layout), ("reference", reference),
                            ("drc_deck", pdk / "drc/sky130A_mr.drc"),
                            ("lvs_deck", pdk / "lvs/sky130.lvs")):
            result[label + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        run(args.klayout, build, "dco-drc", pdk / "drc" / "sky130A_mr.drc",
            {"input": layout, "report": drc_report, "top_cell": "cpz4_dco",
             "feol": 1, "beol": 1, "offgrid": 1})
        violations = len(ET.parse(drc_report).findall("./items/item"))
        result["drc_markers"] = violations
        print(f"DCO geometry DRC markers: {violations}")
        deck = build / "sky130-portable.lvs"
        normalize_lvs(pdk / "lvs" / "sky130.lvs", deck)
        run(args.klayout, build, "dco-lvs", deck,
            {"input": layout, "schematic": reference,
             "report": build / "dco-lvs.lvsdb", "lvs_sub": "vss", "thr": 2})
        result["lvs_match"] = "Netlists match." in (build / "dco-lvs.log").read_text(encoding="utf-8")
        if not result["lvs_match"]:
            raise SystemExit("KLayout did not report a matching device netlist")
        print("DCO LVS match")
        result["passed"] = violations == 0
        return int(violations != 0)
    finally:
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
