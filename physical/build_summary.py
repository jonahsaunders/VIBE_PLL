#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Publish the observed physical limits, including incomplete and failed builds."""
import argparse
import csv
import hashlib
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
    replays = {c: load(a.artifacts / f"replay-{c}" / "qualification.json") for c in ("tt", "ss", "ff")}
    pex = osc / "cpz4_dco_pex.spice"
    pex_sha = hashlib.sha256(pex.read_bytes()).hexdigest() if pex.is_file() else None
    same_extraction = bool(pex_sha) and all(
        (r.get("source", {}).get("corner"), r.get("source", {}).get("netlist_sha256")) == (c, pex_sha)
        for c, r in replays.items())
    data = {"commit": a.commit, "area": area, "physical": geometry, "timing": timing,
            "probes": probes, "extracted_replays": replays, "oscillator_pex_sha256": pex_sha,
            "replays_match_extraction": same_extraction}
    (a.output / "summary.json").write_text(json.dumps(data, indent=2) + "\n")
    def status(record):
        return {True: "pass", False: "fail", None: "unavailable"}[record.get("passed")]
    lines = [f"## Standalone PLL at `{a.commit[:10]}`", "",
             "| Check | Result |", "| --- | --- |",
             f"| Enabled geometry and device LVS | {status(geometry)} |",
             f"| Routed timing | {status(timing)} |",
             f"| All replay inputs match this build's oscillator extraction | {same_extraction} |",
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
    lines.extend(["", "| Extracted corner | Sampled replays | Continuous range |",
                  "| --- | --- | --- |"])
    for corner, result in replays.items():
        sampled = status({"passed": result.get("sampled_pass")})
        bounds = result.get("coverage", {})
        if not result:
            continuous = "unavailable"
        elif not bounds.get("brackets_target") or bounds.get("gaps_mhz"):
            continuous = "measured range gap"
        elif bounds.get("unmeasured_intervals"):
            continuous = "unverified between samples"
        else:
            continuous = "covered by measured rails"
        lines.append(f"| {corner.upper()} | {sampled} | {continuous} |")
    lines.extend(["", "| Corner | Case | 1 kHz–10 MHz TIE (ps RMS) | Strongest line (dBc) |",
                  "| --- | --- | ---: | ---: |"])
    for corner, result in replays.items():
        for case in result.get("cases", []):
            if spec := case.get("spectrum_1khz_10mhz"):
                lines.append(f"| {corner.upper()} | {case['case']} | {spec['band_tie_ps']:.2f} "
                             f"| {spec['strongest_line_dbc']:.2f} |")
    (a.output / "summary.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
