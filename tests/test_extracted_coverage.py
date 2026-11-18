#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check measured overlap at the upper target, including its dependence on settling."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from qualify_pex import coverage


ROOT = Path(__file__).resolve().parents[1]


class ExtractedCoverageTest(unittest.TestCase):
    def setUp(self):
        path = ROOT / "results/range-dco/settled-ss-upper-rails.csv"
        with path.open(newline="") as file:
            self.rows = list(csv.DictReader(file))

    def test_slow_cold_upper_rails(self):
        pairs = coverage(self.rows)["overlaps_at_300_mhz"]
        self.assertEqual([pair["codes"] for pair in pairs], [[158, 159]])
        self.assertGreater(pairs[0]["width_mhz"], 0)
        self.assertLess(pairs[0]["low_mhz"], 300)
        self.assertGreater(pairs[0]["high_mhz"], 300)

        # Removing the middle setting leaves no measured adjacent pair.
        skipped = [row for row in self.rows if row["code"] != "159"]
        self.assertEqual(coverage(skipped)["overlaps_at_300_mhz"], [])

    def test_summary_writes_confirmed_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory)
            replay = artifacts / "replay-ss"
            replay.mkdir()
            (replay / "qualification.json").write_text(json.dumps({"coverage": coverage(self.rows)}))
            output = artifacts / "summary"
            subprocess.run(
                [sys.executable, ROOT / "physical/build_summary.py", artifacts,
                 "--commit", "coverage-test", "--output", output],
                check=True,
            )
            markdown = (output / "summary.md").read_text(encoding="utf-8")
            self.assertIn("158 and 159 overlap across 300 MHz", markdown)
            self.assertIn("299.2621 to 302.2498 MHz (2.9877 MHz)", markdown)


if __name__ == "__main__":
    unittest.main()
