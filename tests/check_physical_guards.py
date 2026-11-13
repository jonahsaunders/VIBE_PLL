#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prove that the real PDK checker rejects a device mismatch and a geometry defect."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import klayout.db as db

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build", type=Path, required=True)
    p.add_argument("--pdk", type=Path, required=True)
    p.add_argument("--klayout", default="klayout")
    p.add_argument("--python", default=sys.executable)
    a = p.parse_args()
    source = a.build.resolve(strict=True)
    checker = ROOT / "physical/check_dco.py"
    with tempfile.TemporaryDirectory(prefix="negative-checks-", dir=source) as temp:
        for kind in ("lvs", "drc"):
            target = Path(temp) / kind
            target.mkdir()
            for name in ("cpz4_dco.gds", "cpz4_dco_lvs.spice"):
                shutil.copyfile(source / name, target / name)
            if kind == "lvs":
                reference = target / "cpz4_dco_lvs.spice"
                lines = reference.read_text().splitlines()
                index = next(i for i, line in enumerate(lines) if line.startswith("M"))
                words = lines[index].split()
                # Physically leave the device intact, but request a different gate net.
                words[2] = "deliberately_disconnected_gate"
                lines[index] = " ".join(words)
                reference.write_text("\n".join(lines) + "\n")
            else:
                layout = db.Layout()
                layout.read(str(target / "cpz4_dco.gds"))
                top = layout.top_cell()
                x = top.bbox().right + round(1.0 / layout.dbu)
                width = round(0.05 / layout.dbu)
                top.shapes(layout.layer(68, 20)).insert(db.Box(x, 0, x + width, width))
                layout.write(str(target / "cpz4_dco.gds"))
            # A prior passing report must never survive a failed check.
            (target / "dco-verification.json").write_text('{"passed": true}')
            env = {key: value for key, value in os.environ.items()
                   if key not in ("PYTHONHOME", "PYTHONPATH")}
            proc = subprocess.run([a.python, str(checker), "--build", str(target),
                                   "--pdk", str(a.pdk.resolve()), "--klayout", a.klayout],
                                  capture_output=True, text=True, env=env)
            report = json.loads((target / "dco-verification.json").read_text())
            if proc.returncode == 0 or report["passed"]:
                raise AssertionError(f"{kind} defect was incorrectly accepted: exit={proc.returncode}; "
                                     f"command={proc.args}; {proc.stdout}; {proc.stderr}")
            if kind == "drc" and report.get("drc_markers", 0) == 0:
                raise AssertionError("Geometry defect did not create a DRC marker")
            print(f"PASS: {kind.upper()} defect rejected; stale success cleared")


if __name__ == "__main__":
    main()
