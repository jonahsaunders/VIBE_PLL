#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Characterize one extracted DCO corner and replay its measured tuning and phase data."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CORNERS = {"tt": (1.80, 25), "ss": (1.62, 0), "ff": (1.95, 0)}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def characterize(args):
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    table = out / "sweep.csv"
    record = out / "source.json"
    record.unlink(missing_ok=True)
    (out / "qualification.json").unlink(missing_ok=True)
    vdd, temp = CORNERS[args.corner]
    codes = sorted(set(range(0, args.ceiling + 1, args.stride)) | set(args.extra_codes) | {args.ceiling})
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        def probe(code):
            path = Path(tmp) / f"{code}.csv"
            subprocess.run([sys.executable, ROOT / "spice/dco_deck.py", "--lib", args.lib,
                            "--netlist", args.netlist, "--corner", args.corner, "--vdd", str(vdd),
                            "--temp", str(temp), "--codes", str(code), "--fine-codes", "0,64,128",
                            "--settle-ns", str(args.settle_ns), "--timeout", str(args.timeout),
                            "--output", path], check=True)
            with path.open(newline="") as f:
                return list(csv.DictReader(f))
        with ThreadPoolExecutor(args.jobs) as pool:
            rows = [row for group in pool.map(probe, codes) for row in group]
        staged = Path(tmp) / "sweep.csv"
        with staged.open("w", newline="") as f:
            writer = csv.DictWriter(f, rows[0])
            writer.writeheader()
            writer.writerows(rows)
        staged.replace(table)
    record.write_text(json.dumps({"corner": args.corner, "vdd": vdd, "temp_c": temp,
                                 "coarse_codes": codes, "fine_codes": [0, 64, 128], "settle_ns": args.settle_ns,
                                 "netlist_sha256": digest(args.netlist), "sweep_sha256": digest(table)},
                                 indent=2) + "\n")


def coverage(rows):
    rails = {}
    for r in rows:
        rails.setdefault(int(r["code"]), {})[int(r["fine_code"])] = float(r["frequency_mhz"])
    codes = sorted(rails)
    holes, unmeasured = [], []
    for a, b in zip(codes, codes[1:]):
        if rails[b][128] < 160 or rails[a][0] > 300:
            continue
        if b != a + 1:
            unmeasured.append([a, b])
        elif max(160, rails[a][128]) < min(300, rails[b][0]):
            holes.append([a, b, rails[b][0] - rails[a][128]])
    low, high = rails[codes[0]][0], rails[codes[-1]][128]
    return {"low_mhz": low, "high_mhz": high, "brackets_target": low <= 160 and high >= 300,
            "unmeasured_intervals": unmeasured, "gaps_mhz": holes}


def replay(args):
    import numpy as np
    sys.path.insert(0, str(ROOT / "analysis"))
    from spectrum import estimate

    out = args.output
    table = out / "sweep.csv"
    result_path = out / "qualification.json"
    result_path.unlink(missing_ok=True)
    source = json.loads((out / "source.json").read_text())
    if digest(table) != source["sweep_sha256"]:
        raise ValueError("Sweep does not match the extracted-netlist record")
    with table.open(newline="") as f:
        rows = list(csv.DictReader(f))
    bounds = coverage(rows)
    cases = []
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        for detector in ("fine", "coarse"):
            base = [sys.executable, ROOT / "tests/run_rtl.py", "--spice-data", table,
                    "--fixed-centers", "--tracking-replicas", "--range-dco"]
            if detector == "coarse":
                base.append("--coarse-phase")
            elif source["corner"] == "ss":
                base.append("--slow-phase-profile")
            # A separate lock/retune case also exercises loss and return of reference.
            for label, options in [("range", ["--ref", "20", "--start", "32768", "--retune", "61440"]),
                                   *((str(r), ["--ref", "25", "--start", str(r)])
                                     for r in (41984, 40959, 40961))]:
                edge_file = Path(tmp) / "edges.csv"
                edge_file.unlink(missing_ok=True)
                if label != "range":
                    options += ["--spectrum", edge_file, "--spectrum-edges", str(args.edges)]
                case = subprocess.run(base + options, capture_output=True, text=True)
                name = f"{detector}-{label}"
                (out / f"{name}.log").write_text(case.stdout + case.stderr)
                result = {"case": name, "passed": case.returncode == 0}
                if case.returncode == 0 and label != "range":
                    edges = np.loadtxt(edge_file, skiprows=1)
                    if len(edges) != args.edges:
                        raise ValueError("Incomplete edge record")
                    result["spectrum_1khz_10mhz"] = estimate(edges, 1000, 10e6)
                cases.append(result)
                print(name, result, flush=True)
    sampled_pass = bounds["brackets_target"] and not bounds["gaps_mhz"] and all(c["passed"] for c in cases)
    passed = sampled_pass and not bounds["unmeasured_intervals"]
    result_path.write_text(json.dumps({"passed": passed, "sampled_pass": sampled_pass,
                                      "source": source, "coverage": bounds,
                                      "cases": cases}, indent=2) + "\n")
    return 0 if (sampled_pass if args.sampled else passed) else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    subs = p.add_subparsers(dest="command", required=True)
    sweep = subs.add_parser("sweep")
    sweep.add_argument("--lib", required=True, type=Path)
    sweep.add_argument("--netlist", required=True, type=Path)
    sweep.add_argument("--corner", choices=CORNERS, required=True)
    sweep.add_argument("--ceiling", type=int, required=True)
    sweep.add_argument("--stride", type=int, default=1)
    sweep.add_argument("--extra-codes", type=int, nargs="*", default=[],
                       help="also measure these codes, e.g. adjacent settings around the nominal channel")
    sweep.add_argument("--jobs", type=int, default=1)
    sweep.add_argument("--settle-ns", type=float, default=900)
    sweep.add_argument("--timeout", type=int, default=1200)
    sweep.add_argument("--output", required=True, type=Path)
    check = subs.add_parser("replay")
    check.add_argument("--output", required=True, type=Path)
    check.add_argument("--edges", type=int, default=524288)
    check.add_argument("--sampled", action="store_true", help="check sampled channels without requiring every code")
    args = p.parse_args()
    if args.command == "sweep":
        if not (16 <= args.ceiling <= 255 and 1 <= args.stride <= args.ceiling and args.jobs > 0 and
                all(0 <= c <= args.ceiling for c in args.extra_codes)):
            p.error("Invalid ceiling, stride, or job count")
        return characterize(args)
    if args.edges < 2:
        p.error("At least two edges are required")
    return replay(args)


if __name__ == "__main__":
    raise SystemExit(main())
