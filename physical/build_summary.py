#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Publish the observed physical limits, including incomplete and failed builds."""
import argparse
import csv
import json
from pathlib import Path


def load(path):
    return json.loads(path.read_text()) if path.is_file() else {}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("artifacts", type=Path)
    p.add_argument("--commit", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    route = a.artifacts / "sky130-standalone"
    osc = a.artifacts / "sky130-oscillator"
    area = load(route / "area.json")
    geometry = load(route / "physical-verification.json")
    timing = load(route / "timing-verification.json")
    probes = []
    for fname in ("pex-tt.csv", "pex-tt-max.csv", "pex-ss-max.csv"):
        path = osc / fname
        if path.is_file():
            with path.open(newline="") as f:
                probes.extend(csv.DictReader(f))
    a.output.mkdir(parents=True, exist_ok=True)
    data = {"commit": a.commit, "area": area, "physical": geometry, "timing": timing, "probes": probes}
    (a.output / "summary.json").write_text(json.dumps(data, indent=2) + "\n")
    def status(record):
        return {True: "pass", False: "fail", None: "unavailable"}[record.get("passed")]
    lines = [f"## Standalone PLL at `{a.commit[:10]}`", "",
             "| Check | Result |", "| --- | --- |",
             f"| Enabled geometry and device LVS | {status(geometry)} |",
             f"| Routed timing | {status(timing)} |",
             f"| Worst max / min slack (ns) | {timing.get('setup_wns_ns')} / {timing.get('hold_wns_ns')} |",
             f"| Die area (mm²) | {area.get('die_mm2', 'unavailable')} |",
             "", "| Corner | Coarse:fine | Extracted MHz | Missing fine bins | Bad coarse / fine cycles |",
             "| --- | --- | ---: | ---: | --- |"]
    for r in probes:
        lines.append(f"| {r['corner']} {r['vdd']} V {r['temp_c']} °C | {r['code']}:{r['fine_code']} "
                     f"| {r['frequency_mhz']} | {r['missing_fine_bins'] or 'unavailable'} "
                     f"| {r['bad_tap_sequences']} / {r['bad_fine_sequences']} |")
    if len(probes) != 3:
        lines.append("\nEndpoint characterization is incomplete.")
    (a.output / "summary.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
