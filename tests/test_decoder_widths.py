#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise the coarse fallback observed in the extracted fast-corner waveform."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "spice"))
from dco_deck import TAP_COUNT, TAP_ORDER, decoded_widths


class DecoderWidthsTest(unittest.TestCase):
    def measure(self, reverse=False):
        cycle = [(float(i), tap, rising) for i, (tap, rising) in enumerate(TAP_ORDER)]
        events = []
        for start, tap, rising in cycle:
            base = 5 + 3 * tap
            # The far replica still shows the preceding transition in bin zero.
            word = 4 if start == 0 else 0
            raw = word ^ 5 ^ (0 if rising else 7)
            events.extend((start - 0.01, base + bit, (raw >> bit) & 1) for bit in range(3))
        events.extend([(0.25, 7, 1), (0.65, 5, 0)])
        if reverse:
            events.append((0.80, 5, 1))
        events.sort()
        histories = [[] for _ in range(TAP_COUNT)]
        for time, index, level in events:
            histories[index].append((time, level))
        return decoded_widths(cycle, events, 10.0, histories)

    def test_invalid_prefix_then_two_legal_subdivisions(self):
        slots = self.measure()
        self.assertAlmostEqual(sum(slots), 1)
        for index, expected in ((0, .025), (1, .04), (3, .035)):
            self.assertAlmostEqual(slots[index], expected)

    def test_reverse_legal_progression_is_rejected(self):
        self.assertIsNone(self.measure(reverse=True))


if __name__ == "__main__":
    unittest.main()
