#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Ensure real antenna diodes are compared and absent diffusion fails full LVS."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import klayout.db as db

ROOT = Path(__file__).resolve().parents[1]


def require(ok, message):
    if not ok:
        raise AssertionError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def diode_count(netlist):
    return sum(1 for circuit in netlist.each_circuit() for device in circuit.each_device()
               if device.device_class().name == "sky130_fd_pr__diode_pw2nd_05v5")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build", type=Path, required=True)
    p.add_argument("--pdk", type=Path, required=True)
    p.add_argument("--klayout", default="klayout")
    a = p.parse_args()
    build = a.build.resolve(strict=True)
    record = build / "diode-guard.json"
    record.unlink(missing_ok=True)
    positive = json.loads((build / "physical-verification.json").read_text())
    require(positive.get("passed") is True, "Start with a fully verified layout")
    layout_path = build / "cpz4_sky130-review.gds"
    original_hash = digest(layout_path)
    require(original_hash == positive["layout_sha256"], "Verified layout changed")
    lvs = db.LayoutVsSchematic()
    lvs.read(str(build / "pll-lvs.lvsdb"))
    actual, expected = diode_count(lvs.netlist()), diode_count(lvs.reference)
    require(actual > 0 and actual == expected, "Antenna diodes were not compared")
    with tempfile.TemporaryDirectory(prefix="diode-guard-", dir=build) as temp:
        negative = Path(temp)
        for name in ("cpz4_sky130_lvs.spice", "route-checks.txt", "route-violations.txt"):
            shutil.copyfile(build / name, negative / name)
        layout = db.Layout()
        layout.read(str(layout_path))
        cell = layout.cell("sky130_fd_sc_hd__diode_2")
        require(cell is not None, "No physical antenna-diode cell")
        diffusion = cell.shapes(layout.layer(65, 20))
        require(diffusion.size() > 0, "No physical diode diffusion")
        diffusion.clear()
        layout.write(str(negative / "cpz4_sky130-review.gds"))
        command = [sys.executable, str(ROOT / "physical/check_layout.py"),
                   "--build", str(negative), "--pdk", str(a.pdk.resolve()),
                   "--klayout", a.klayout, "--geometry-mode", positive["lvs_geometry_mode"]]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        bad = json.loads((negative / "physical-verification.json").read_text())
        log = (negative / "pll-lvs.log").read_text()
        require(result.returncode != 0 and bad.get("passed") is False,
                "Missing diode diffusion was accepted")
        require("Netlists don't match" in log and "Netlists match." not in log,
                "Negative case did not fail specifically in LVS")
        require(not (negative / "cpz4_sky130.gds").exists(),
                "Negative case produced a clean-layout artifact")
        (build / "diode-guard.log").write_text(result.stdout + "\n" + log)
    require(digest(layout_path) == original_hash, "Positive geometry was modified")
    proof = {"passed": True, "base_layout_sha256": original_hash,
             "layout_diodes_after_parallel_combination": actual,
             "reference_diodes_after_parallel_combination": expected,
             "negative_case": "Remove N+ diffusion from the antenna-diode cell",
             "negative_verification": bad}
    record.write_text(json.dumps(proof, indent=2) + "\n")
    print("PASS antenna-diode LVS guard: present devices match; removed diffusion fails")


if __name__ == "__main__":
    main()
