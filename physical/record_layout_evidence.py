#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Record the actual checked layout, image, regressions, and remaining limits."""
import argparse
import csv
import gzip
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-commit", required=True)
    p.add_argument("--run-id", type=int, required=True)
    a = p.parse_args()
    route = ROOT / "build/evidence/route"
    osc = ROOT / "build/evidence/oscillator"
    results = ROOT / "results"
    ci = json.loads((ROOT / "build/evidence/ci-verification.json").read_text())
    full = json.loads((route / "physical-verification.json").read_text())
    macro = json.loads((osc / "dco-verification.json").read_text())
    for result in (ci, full, macro):
        require(result.get("passed") is True and result.get("drc_markers") == 0
                and result.get("lvs_match") is True, "Verification did not pass")
    for result in (ci, full):
        require(result.get("route_exit_code") == 0 and result.get("route_drc") == 0,
                "Routing did not pass")
        checks = dict(line.split(": ", 1) for line in result["route_checks"].splitlines())
        require(checks == {"All signal nets routed": "1", "Antenna-violating nets": "0",
                           "Power grids connected": "1"}, "Incomplete route checks")
    for key, name in (("layout_sha256", "cpz4_sky130.gds"),
                      ("reference_sha256", "cpz4_sky130_lvs.spice")):
        require(ci[key] == full[key] == sha(route / name), "Verified input changed: " + name)
    require(macro["layout_sha256"] == sha(osc / "cpz4_dco.gds")
            == sha(route / "cpz4_dco.gds"), "Oscillator artifacts disagree")
    require("DCO Magic DRC markers: 0" in (osc / "magic-pex.log").read_text(),
            "Missing Magic DRC result")
    for name in ("rev4-pll-layout.png", "rev4-dco-layout.png"):
        require((ROOT / "docs" / name).read_bytes().startswith(b"\x89PNG\r\n\x1a\n"),
                "Missing rendered image")
    for source, dest in ((ROOT / "build/evidence/ci-verification.json", "rev4-pll-ci-verification.json"),
                         (route / "physical-verification.json", "rev4-pll-verification.json"),
                         (osc / "dco-verification.json", "rev4-dco-ci-verification.json")):
        shutil.copyfile(source, results / dest)
    diode_guard = json.loads((route / "diode-guard.json").read_text())
    require(diode_guard.get("passed") is True
            and diode_guard["base_layout_sha256"] == full["layout_sha256"]
            and diode_guard["layout_diodes_after_parallel_combination"] > 0
            and diode_guard["layout_diodes_after_parallel_combination"]
                == diode_guard["reference_diodes_after_parallel_combination"]
            and diode_guard["negative_verification"]["passed"] is False,
            "Missing physical antenna-diode negative regression")
    shutil.copyfile(route / "diode-guard.json", results / "rev4-diode-guard.json")
    measurements = []
    for name, condition in (("tt", "TT, 1.8 V, 25 C"), ("tt-max", "TT, 1.8 V, 25 C"),
                            ("ss-max", "SS, 1.62 V, 0 C")):
        source = osc / ("pex-" + name + ".csv")
        rows = list(csv.DictReader(source.open()))
        require(len(rows) == 1, "Expected one measured endpoint")
        row = rows[0]
        measurements.append(f"| {condition} | {row['code']}:{row['fine_code']} | "
                            f"{float(row['frequency_mhz']):.4f} MHz | {row['missing_fine_bins']} |")
        shutil.copyfile(source, results / ("rev4-pex-" + name + ".csv"))
    url = f"https://github.com/jonahsaunders/VIBE_PLL/actions/runs/{a.run_id}"
    passes = []
    for mode, count in (("fixed", 4), ("corners", 12), ("calibration", 4), ("tracking", 1)):
        path = ROOT / "build/evidence/rtl" / (mode + ".json")
        cases = json.loads(path.read_text())["scenarios"]
        require(len(cases) == count and len({c["scenario"] for c in cases}) == count
                and all(c["passed"] is True for c in cases), f"Incomplete {mode} regression")
        passes.extend(f"{mode}/{c['scenario']} {line}" for c in cases for line in c["output"]
                      if line.startswith("PASS ref="))
    require(len(passes) == 21, "Expected 21 passing PLL scenarios")
    (results / "rev4-rtl-regression.txt").write_text(
        f"Source commit: {a.source_commit}\nWorkflow: {url}\n"
        "Modeled/schematic replay; not extracted PLL qualification.\n\n" + "\n".join(passes) + "\n")
    log = (route / "openroad.log").read_text()
    def metric(name):
        values = re.findall(name + r"\s+([-+0-9.]+)", log)
        require(bool(values), "Missing timing metric: " + name)
        return float(values[-1])
    setup, hold, tns = metric("worst slack max"), metric("worst slack min"), metric("tns max")
    provenance = {"design_commit": a.source_commit, "workflow_url": url,
                  "pdk": "sky130-fa87f8f4bbcc7255b6f0c0fb506960f531ae2392",
                  "orfs_image": "openroad/orfs@sha256:73275384ed91270ea0e5f47710b3c2ff1b91708440c0744208ff226b751f88a0",
                  "recheck_klayout": subprocess.check_output(["klayout", "-v"], text=True).strip(),
                  "layout_sha256": full["layout_sha256"], "reference_sha256": full["reference_sha256"],
                  "image_sha256": sha(ROOT / "docs/rev4-pll-layout.png"),
                  "setup_slack_ns": setup, "hold_slack_ns": hold, "setup_tns_ns": tns,
                  "tracking_replicas": 1, "on_chip_cal": 0, "max_coarse_code": 255}
    (results / "rev4-build-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    layout = ROOT / "layout"
    layout.mkdir(exist_ok=True)
    for name in ("cpz4_sky130.gds", "cpz4_sky130_lvs.spice"):
        (layout / (name + ".gz")).write_bytes(gzip.compress((route / name).read_bytes(), mtime=0))
    (layout / "README.md").write_text(f"""# Checked Rev. 4 layout

[Standalone GDS](cpz4_sky130.gds.gz) and
[intended device-level LVS reference](cpz4_sky130_lvs.spice.gz) are gzip-compressed
copies of [verified run {a.run_id}]({url}), source commit `{a.source_commit}`.

GDS SHA-256: `{full['layout_sha256']}`

Reference SHA-256: `{full['reference_sha256']}`

Decompress with standard gzip tools. See [verification and physical limits](../results/rev4-layout.md)
and [reproduction commands](../physical/README.md). These are geometrically and
electrically matched artifacts; timing and analog qualification remain open.
""")
    old = (results / "rev4-layout.md").read_text(encoding="utf-8")
    prefix = re.split(r"^## Full-PLL (?:status|result)", old, maxsplit=1, flags=re.M)[0]
    prefix = prefix.replace("[Tracking check record](rev4-dco-verification.json)",
                            "[Tracking CI check record](rev4-dco-ci-verification.json)")
    prefix = prefix.replace("The local checks used", "The historical local checks used")
    prefix = re.sub(r"https://github.com/jonahsaunders/VIBE_PLL/actions/runs/\d+/job/\d+", url, prefix)
    tail = f"""## Full-PLL result

The complete standalone PLL passes the enabled Sky130 geometry checks and
full-device LVS. These artifacts were built from `{a.source_commit}` in
[run {a.run_id}]({url}), then rechecked before being recorded.

![Verified standalone PLL GDS](../docs/rev4-pll-layout.png)

| Check | Result |
| --- | --- |
| KLayout FEOL, BEOL, and manufacturing-grid DRC | 0 markers |
| Transistor-level LVS, including standard cells and DCO | Match |
| Detailed-router DRC | 0 violations |
| Signal nets routed | All |
| Power grids connected | All three |
| OpenROAD antenna check using available LEF data | 0 violating nets |

[CI result](rev4-pll-ci-verification.json), [artifact recheck](rev4-pll-verification.json),
[build provenance](rev4-build-provenance.json), and [checked GDS/reference](../layout/README.md)
bind the actual layout to the input hashes. The reference comes from intended
OpenDB connectivity and real PDK device definitions, including the documented
tie-cell conductor shorts.

The floorplan is **600 x 400 micrometers**, larger than the original 400 x 250
planning target. This build enables tracking replicas and fixed-center tables,
with a coarse ceiling of 255. On-chip calibration and the other original
build-time modes remain available and require their own physical builds.
Both source-branch histories are retained in main.

The [captured RTL regression](rev4-rtl-regression.txt) records 21 passing PLL
scenarios. The [negative-check log](rev4-checker-guards.txt) shows that wrong
connectivity, undersized metal, and missing inputs are rejected; stale success
records and clean-layout output are invalidated. The
[antenna-diode regression](rev4-diode-guard.json) separately confirms that real
junction devices match and removing their physical diffusion fails full-chip LVS.

The extraction wrapper derives the N+ diode body outside physical wells and
emits its anode onto the PDK's shared substrate terminal layer. This supports
standard-cell antenna diodes without a local closed tap ring; junction
dimensions and connectivity remain part of the comparison.

## Remaining physical qualification

The enabled checks do not establish harness, seal-ring, density, complete
analog antenna, jitter, or full PVT/CDC sign-off. The routed TT timing report
gives worst setup slack **{setup:.2f} ns**, worst hold slack **{hold:.2f} ns**,
and setup TNS **{tns:.2f} ns**. Timing closure remains open.

Magic-extracted oscillator measurements from the same build are:

| Condition | Coarse:fine code | Frequency | Missing fine bins |
| --- | --- | --- | --- |
{chr(10).join(measurements)}

The extracted slow corner does not cover the full 160-300 MHz target, and
missing fine bins require phase-detector characterization and tuning. Original
circuitry and RTL modes are retained, but their post-layout performance has not
been established by the schematic regressions or by DRC/LVS.
Raw measurements: [nominal](rev4-pex-tt.csv), [TT upper code](rev4-pex-tt-max.csv),
and [slow-cold upper code](rev4-pex-ss-max.csv).

See [commands and configuration](../physical/README.md).
"""
    (results / "rev4-layout.md").write_text(prefix + tail, encoding="utf-8")
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    text = text.replace("![Rev. 4 tracking-replica oscillator layout](docs/rev4-dco-layout.png)",
                        "![Rev. 4 routed PLL layout](docs/rev4-pll-layout.png)")
    text = text.replace("The tracking-replica oscillator layout passes the enabled geometry DRC checks and device-level LVS. [Layout verification and full-PLL status](results/rev4-layout.md).",
                        "The complete standalone PLL passes enabled geometry DRC and full-device LVS. [Verified layout, records, and physical performance limits](results/rev4-layout.md). Timing and extracted analog qualification remain open.")
    readme.write_text(text, encoding="utf-8")
    print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    main()
