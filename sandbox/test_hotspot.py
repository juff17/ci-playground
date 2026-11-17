import unittest
from pathlib import Path

HOTSPOT = Path(__file__).with_name("hotspot.txt")


class HotspotTest(unittest.TestCase):
    """A conflict left half-resolved fails CI here instead of reaching main."""

    def test_no_conflict_markers(self):
        text = HOTSPOT.read_text()
        for marker in ("<<<<<<<", "=======", ">>>>>>>"):
            self.assertNotIn(marker, text)

    def test_one_line_per_slot(self):
        slots = [line.split(":", 1)[0] for line in HOTSPOT.read_text().splitlines() if line.startswith("slot-")]
        self.assertEqual(slots, [f"slot-{i:02d}" for i in range(1, 25)])
