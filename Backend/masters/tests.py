from django.test import SimpleTestCase


class AsmTargetsWorkbookTests(SimpleTestCase):
    """TD Target cells are lakhs; text targets are parsed, order-count targets skipped."""

    def test_lakhs(self):
        from decimal import Decimal

        from masters.asm_targets import lakhs, rule_for

        self.assertEqual(lakhs(42.0), Decimal("4200000"))
        self.assertEqual(lakhs("15L"), Decimal("1500000"))
        self.assertEqual(lakhs("110 orders 30L"), Decimal("3000000"))
        self.assertEqual(lakhs("2.5Cr"), Decimal("25000000"))
        self.assertIsNone(lakhs("130 orders"))
        self.assertIsNone(lakhs(0.0))
        self.assertEqual(rule_for("mumbai", "2026-06"), ("asm", "Suresh"))
        self.assertEqual(rule_for("mumbai", "2026-05")[0], "distributor")
