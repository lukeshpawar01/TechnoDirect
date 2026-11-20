"""Mappings given by hand stay apart and close when proper data covers them (masters/manual_mappings.py)."""
import datetime as dt
from decimal import Decimal

from django.test import TestCase

from masters import manual_mappings as mm
from masters.models import ManualMapping
from warehouse.models import Asm, AsmAssignment, Distributor, Retailer, TargetSplit

D = dt.date


class ManualMappingTests(TestCase):
    def setUp(self):
        self.gaurav = Asm.objects.create(code="G", name="Gaurav")
        self.other = Asm.objects.create(code="O", name="Other")
        self.d = Distributor.objects.create(code="ARTI", name="Arti Hosiery", asm=self.gaurav, bo_only=True,
                                            aliases=["Arti", "Arti Hos"])
        self.r = Retailer.objects.create(name="R", distributor=self.d, asm=self.gaurav)
        self.e = ManualMapping.objects.create(kind="distributor_asm", distributor=self.d, asm=self.gaurav,
                                              value={"previous_asm_id": None}, given_on=D(2026, 11, 18), said="x")

    def test_proper_data_closes_it(self):
        self.assertEqual(mm.superseded(self.d, D(2026, 12, 1), self.gaurav, "ASM tracker Dec.csv"), 1)
        self.e.refresh_from_db()
        self.assertEqual(self.e.status, "confirmed")
        e2 = ManualMapping.objects.create(kind="distributor_asm", distributor=self.d, asm=self.gaurav,
                                          given_on=D(2026, 11, 18))
        mm.superseded(self.d, D(2026, 12, 1), self.other, "ASM tracker Dec.csv")
        e2.refresh_from_db()
        self.assertEqual(e2.status, "replaced")
        self.assertIn("Other", e2.closed_reason)

    def test_incentive_sheet_check(self):
        TargetSplit.objects.create(month=D(2026, 10, 1), distributor=self.d, role="asm", person="Other",
                                   asm=self.other, value=Decimal(1), source="Google Sheet")
        self.assertEqual(mm.check()["conflicts"], 1)  # disagreement is only flagged
        self.e.refresh_from_db()
        self.assertEqual(self.e.status, "active")
        self.assertIn("Other", self.e.conflict)
        TargetSplit.objects.create(month=D(2026, 11, 1), distributor=self.d, role="asm", person="Gaurav",
                                   asm=self.gaurav, value=Decimal(1), source="Google Sheet")
        self.assertEqual(mm.check()["confirmed"], 1)  # the latest sheet month agrees
        self.e.refresh_from_db()
        self.assertEqual(self.e.status, "confirmed")

    def test_remove_undoes(self):
        mm.remove(self.e)
        self.d.refresh_from_db()
        self.r.refresh_from_db()
        self.assertIsNone(self.d.asm_id)
        self.assertIsNone(self.r.asm_id)
        self.assertEqual(ManualMapping.objects.get(id=self.e.id).status, "removed")

    def test_remove_alias_and_handover(self):
        a = ManualMapping.objects.create(kind="distributor_alias", distributor=self.d, value={"alias": "arti hos"},
                                         given_on=D(2026, 11, 17))
        mm.remove(a)
        self.d.refresh_from_db()
        self.assertEqual(self.d.aliases, ["Arti"])
        AsmAssignment.objects.create(distributor=self.d, asm=self.gaurav, start=D(2023, 1, 1), end=D(2026, 9, 30))
        AsmAssignment.objects.create(distributor=self.d, asm=self.other, start=D(2026, 10, 1))
        h = ManualMapping.objects.create(kind="asm_handover", distributor=self.d, asm=self.other, start=D(2026, 10, 1),
                                         given_on=D(2026, 11, 16))
        self.assertEqual([x.id for x in mm._covering(self.d.id, D(2026, 9, 1))], [self.e.id])  # not before its start
        mm.remove(h)
        self.assertFalse(AsmAssignment.objects.filter(distributor=self.d, asm=self.other).exists())
