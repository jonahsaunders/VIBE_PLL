#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check measured overlap at the upper target, including its dependence on settling."""
import csv
import unittest
from pathlib import Path

from qualify_pex import coverage


class ExtractedCoverageTest(unittest.TestCase):
    def test_slow_cold_upper_rails(self):
        path = Path(__file__).resolve().parents[1] / "results/range-dco/settled-ss-upper-rails.csv"
        with path.open(newline="") as file:
            rows = list(csv.DictReader(file))
        pairs = coverage(rows)["overlaps_at_300_mhz"]
        self.assertEqual([pair["codes"] for pair in pairs], [[158, 159]])
        self.assertGreater(pairs[0]["width_mhz"], 0)
        self.assertLess(pairs[0]["low_mhz"], 300)
        self.assertGreater(pairs[0]["high_mhz"], 300)

        # Removing the middle setting leaves no measured adjacent pair.
        skipped = [row for row in rows if row["code"] != "159"]
        self.assertEqual(coverage(skipped)["overlaps_at_300_mhz"], [])


if __name__ == "__main__":
    unittest.main()
