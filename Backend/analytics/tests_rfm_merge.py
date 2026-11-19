"""RFM segment merge (2026-11-19): fewer labels, same scoring; At Risk keeps a value priority."""
from django.test import SimpleTestCase

from analytics import rfm


class RfmMergeTests(SimpleTestCase):
    def test_grid_uses_only_the_merged_segments(self):
        cells = {seg for row in rfm.GRID.values() for seg in row}
        self.assertEqual(cells, {"champions", "loyal", "potential_loyalists", "needs_attention", "at_risk"})
        self.assertTrue(all(k in rfm.SEGMENTS for k in rfm.SCORED))

    def test_priority_follows_value(self):
        self.assertEqual([rfm.priority_for(fm) for fm in (1, 2, 3, 4, 5)], ["low", "low", "medium", "high", "high"])
        # the old "Can't Lose Them" cells (R1-2, FM4-5) are exactly At Risk / high
        for r in (1, 2):
            for fm in (4, 5):
                self.assertEqual((rfm.GRID[r][fm - 1], rfm.priority_for(fm)), ("at_risk", "high"))

    def test_labels(self):
        self.assertEqual(rfm.label({"segment": "at_risk", "priority": "high"}), "At Risk (high value)")
        self.assertEqual(rfm.label({"segment": "champions"}), "Champions")
        self.assertEqual(rfm.label(None), "Prospect")
        d = rfm.describe({"segment": "at_risk", "priority": "low", "fm": 1})
        self.assertEqual((d["label"], d["action"]), ("At Risk (low value)", "Automated reorder reminders."))
