#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Characterize one extracted DCO corner and replay its measured tuning and phase data."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CORNERS = {"tt": (1.80, 25), "ss": (1.62, 0), "ff": (1.95, 0)}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(out):
    out.mkdir(parents=True, exist_ok=True)
    (out / "source.json").unlink(missing_ok=True)
    (out / "qualification.json").unlink(missing_ok=True)


def save_sweep(out, rows, source):
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        staged = Path(tmp) / "sweep.csv"
        with staged.open("w", newline="") as f:
            writer = csv.DictWriter(f, rows[0])
            writer.writeheader()
            writer.writerows(rows)
        source = {**source, "sweep_sha256": digest(staged)}
        manifest = Path(tmp) / "source.json"
        manifest.write_text(json.dumps(source, indent=2) + "\n")
        staged.replace(out / "sweep.csv")
        manifest.replace(out / "source.json")


def characterize(args):
    out = args.output
    prepare(out)
    vdd, temp = CORNERS[args.corner]
    requested = sorted(set(range(0, args.ceiling + 1, args.stride)) | set(args.extra_codes) | {args.ceiling})
    index, count = args.partition
    if not 0 <= index < count <= len(requested):
        raise ValueError("Partition must select at least one requested coarse code")
    codes = requested[index::count]
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        def probe(code):
            path = Path(tmp) / f"{code}.csv"
            settle_ns = max(args.zero_settle_ns, args.settle_ns) if code == 0 else args.settle_ns
            subprocess.run([sys.executable, ROOT / "spice/dco_deck.py", "--lib", args.lib,
                            "--netlist", args.netlist, "--corner", args.corner, "--vdd", str(vdd),
                            "--temp", str(temp), "--codes", str(code), "--fine-codes", "0,64,128",
                            "--measure-decoder", "--settle-ns", str(settle_ns), "--timeout", str(args.timeout),
                            "--output", path], check=True)
            with path.open(newline="") as f:
                return list(csv.DictReader(f))
        with ThreadPoolExecutor(args.jobs) as pool:
            rows = [row for group in pool.map(probe, codes) for row in group]
    save_sweep(out, rows, {"corner": args.corner, "vdd": vdd, "temp_c": temp, "coarse_codes": codes,
                           "requested_codes": requested, "fine_codes": [0, 64, 128], "settle_ns": args.settle_ns,
                           "zero_settle_ns": max(args.settle_ns, args.zero_settle_ns),
                           "netlist_sha256": digest(args.netlist), "model_library_sha256": digest(args.lib),
                           "characterizer_sha256": digest(ROOT / "spice/dco_deck.py")})


def combine(args):
    if any(path.resolve() == args.output.resolve() for path in args.inputs):
        raise ValueError("Choose a separate output directory for the combined sweep")
    prepare(args.output)
    source, entries = None, {}
    for part in args.inputs:
        info = json.loads((part / "source.json").read_text())
        codes = info.pop("coarse_codes")
        table = part / "sweep.csv"
        if info.pop("sweep_sha256") != digest(table) or (source is not None and info != source):
            raise ValueError(f"Mismatched sweep provenance in {part}")
        source = info
        with table.open(newline="") as f:
            rows = list(csv.DictReader(f))
        points = {(int(r["code"]), int(r["fine_code"])): r for r in rows}
        if (len(points) != len(rows) or entries.keys() & points.keys()
                or set(points) != {(c, f) for c in codes for f in info["fine_codes"]}
                or any((r["corner"], float(r["vdd"]), float(r["temp_c"])) !=
                       (info["corner"], info["vdd"], info["temp_c"]) for r in rows)):
            raise ValueError(f"Incomplete, duplicate, or wrong-corner measurements in {part}")
        entries.update(points)
    if set(entries) != {(c, f) for c in source["requested_codes"] for f in source["fine_codes"]}:
        raise ValueError("Combined sweep is missing requested code pairs")
    save_sweep(args.output, [entries[key] for key in sorted(entries)],
               {**source, "coarse_codes": source["requested_codes"]})


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
    # Identify the target sub-bands that still depend on coarse interpolation.
    # Overlapping measured rails can cover a sub-band even with codes skipped.
    reached, uncovered = 160.0, []
    for first, last in sorted((r[0], r[128]) for r in rails.values()):
        if last < reached or first > 300:
            continue
        if first > reached:
            uncovered.append([reached, first])
        reached = max(reached, min(300.0, last))
    if reached < 300:
        uncovered.append([reached, 300.0])
    return {"low_mhz": low, "high_mhz": high, "brackets_target": low <= 160 and high >= 300,
            "within_400mhz_guard": max(freq for fine in rails.values() for freq in fine.values()) <= 400,
            "max_measured_fallback_ui": max((float(r["coarse_fallback_ui"]) for r in rows
                                             if r.get("coarse_fallback_ui")), default=None),
            "unmeasured_intervals": unmeasured, "gaps_mhz": holes,
            "uncovered_by_measured_rails_mhz": uncovered}


def replay(args):
    import numpy as np
    sys.path.insert(0, str(ROOT / "analysis"))
    from spectrum import estimate

    out = args.output
    table = out / "sweep.csv"
    result_path = out / "qualification.json"
    result_path.unlink(missing_ok=True)
    source = json.loads((out / "source.json").read_text())
    if source.get("requested_codes", source["coarse_codes"]) != source["coarse_codes"]:
        raise ValueError("Combine all partitions before replaying the sweep")
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
            channels = [("range" if ref == 20 else f"range-{ref}",
                         ["--ref", str(ref), "--start", str(160 * 4096 // ref),
                          "--retune", str(300 * 4096 // ref)]) for ref in (16, 20, 32)]
            channels += [(str(r), ["--ref", "25", "--start", str(r)]) for r in (41984, 40959, 40961)]
            if detector == "fine":
                channels += [(f"narrow-{r}", ["--ref", "25", "--start", str(r), "--narrow-near-integer"])
                             for r in (40959, 40961)]
            for label, options in channels:
                edge_file = Path(tmp) / "edges.csv"
                edge_file.unlink(missing_ok=True)
                if not label.startswith("range"):
                    options += ["--spectrum", edge_file, "--spectrum-edges", str(args.edges)]
                case = subprocess.run(base + options, capture_output=True, text=True)
                name = f"{detector}-{label}"
                (out / f"{name}.log").write_text(case.stdout + case.stderr)
                result = {"case": name, "passed": case.returncode == 0}
                result["locks_us"] = {label: float(us) for label, us in re.findall(
                    r"^LOCK (\S+) us=([\d.]+)", case.stdout, re.MULTILINE)}
                result["mean_frequency"] = [
                    {"target_mhz": float(target), "measured_mhz": float(actual), "error_ppm": float(error)}
                    for target, actual, error in re.findall(
                        r"^FREQ target_MHz=([\d.]+) measured_MHz=([\d.]+) error_ppm=([+-]?[\d.]+)",
                        case.stdout, re.MULTILINE)]
                watchdog = re.search(r"^WATCHDOG us=([\d.]+)", case.stdout, re.MULTILINE)
                if watchdog:
                    result["reference_loss_us"] = float(watchdog[1])
                activity = re.search(r"^DETECTOR samples=(\d+) coarse_fallback=(\d+)", case.stdout, re.MULTILINE)
                if activity:
                    result["detector_samples"], result["fallback_samples"] = map(int, activity.groups())
                if case.returncode == 0 and not label.startswith("range"):
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
    sweep.add_argument("--partition", nargs=2, type=int, default=(0, 1), metavar=("INDEX", "COUNT"),
                       help="measure a disjoint subset for parallel runners, indexed from zero")
    sweep.add_argument("--settle-ns", type=float, default=200, help="static settling window before measuring")
    sweep.add_argument("--zero-settle-ns", type=float, default=900,
                       help="minimum settling time at coarse zero, where oscillator startup is slower")
    sweep.add_argument("--timeout", type=int, default=1200)
    sweep.add_argument("--output", required=True, type=Path)
    union = subs.add_parser("combine", help="verify and join partitions of the same extracted sweep")
    union.add_argument("inputs", nargs="+", type=Path)
    union.add_argument("--output", required=True, type=Path)
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
    if args.command == "combine":
        return combine(args)
    if args.edges < 2:
        p.error("At least two edges are required")
    return replay(args)


if __name__ == "__main__":
    raise SystemExit(main())
