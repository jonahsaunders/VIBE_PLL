#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check the final routed timing report and write an independent release result."""
import argparse
import json
import math
from pathlib import Path
import re


def evaluate(log, extracted):
    numbers = {}
    for key, label in (("setup_wns_ns", "worst slack max"), ("hold_wns_ns", "worst slack min"),
                       ("setup_tns_ns", "tns max")):
        matches = re.findall(r"^" + label + r"\s+(\S+)\s*$", log, re.MULTILINE)
        numbers[key] = float(matches[-1]) if matches else None
    warnings = [line for line in log.splitlines() if re.search(r"\[WARNING STA-(1648|1650)\]", line)]
    # OpenSTA may warn about -from on a black-box pin. Verify every actual
    # routed capture report contains its constrained path and achieved slack.
    expected = {f"controller.sampler.{name}[{i}]" for name, count in
                (("neg_meta", 12), ("pos_meta", 12), ("tap_meta", 5), ("fine_meta", 15))
                for i in range(count)}
    capture = {}
    routed = log.partition("Loaded routed SPEF")[2]
    for name, section in re.findall(r"^(?:Gray|Phase) capture (\S+)\n(.*?)(?=^(?:Gray|Phase) capture |\Z)",
                                    routed, re.MULTILINE | re.DOTALL):
        slack = re.findall(r"^\s*([-+.\d]+)\s+slack \((?:MET|VIOLATED)\)", section, re.MULTILINE)
        if ("Path Group: path delay" in section and
                re.search(r"^\s+1\.0+\s+1\.0+\s+max_delay\s*$", section, re.MULTILINE) and slack):
            capture[name] = min(map(float, slack))
    missing = sorted(expected - capture.keys())
    minimum = min(capture.values(), default=None)
    passed = (extracted and not warnings and not missing and minimum is not None and minimum >= 0 and
              all(v is not None and math.isfinite(v) and v >= 0 for v in numbers.values()))
    return {"passed": passed, "routed_spef_loaded": extracted, **numbers,
            "capture_endpoints_checked": len(capture), "missing_capture_endpoints": missing,
            "minimum_capture_slack_ns": minimum,
            "unresolved_spef_names": len(warnings), "annotation_warnings": warnings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path)
    args = parser.parse_args()
    report = args.build / "timing-verification.json"
    report.unlink(missing_ok=True)
    log = (args.build / "openroad.log").read_text(errors="replace")
    spef = args.build / "routed.spef"
    result = evaluate(log, spef.is_file() and spef.stat().st_size > 0 and "Loaded routed SPEF" in log)
    report.write_text(json.dumps(result, indent=2) + "\n")
    print(report.read_text())
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
