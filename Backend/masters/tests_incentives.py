"""Incentive tracker (masters/incentives.py): BO conversions (offline first, new to TD) credited to the BlueOrigin
distributor / ASM, KYC conversions, shared-distributor split, payout slabs."""
import datetime as dt
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from masters import incentives as inc
from warehouse.models import (Asm, BoRetailer, BoRetailerMonth, Distributor, FieldStaff, Order, Retailer,
                              TargetSplit)

D = dt.date
OCT = D(2026, 10, 1)


class IncentiveTests(TestCase):
    def setUp(self):
        self.heera = Distributor.objects.create(code="H", name="Heera")
        self.other = Distributor.objects.create(code="X", name="Other dist")  # fulfils TD orders, not in the sheet
        self.offline = Distributor.objects.create(code="N", name="Noble", bo_only=True)  # BO only, not in the sheet
        self.gururaj = Asm.objects.create(code="G", name="Gururaj")
        ex = FieldStaff.objects.create(emp_id="E1", name="Srinivas")
        TargetSplit.objects.create(month=OCT, distributor=self.heera, role="asm", person="Gururaj", asm=self.gururaj,
                                   value=Decimal(80), new_retailer_target=20, bo_gps_target=10, kyc_target=20)
        TargetSplit.objects.create(month=OCT, distributor=self.heera, role="executive", person="Srinivas",
                                   field_staff=ex, value=Decimal(30), new_retailer_target=10, bo_gps_target=5,
                                   kyc_target=5)
        self.n = 0
        # BO retailer of Heera (offline since May), first TD order in Oct through ANOTHER distributor: new + G/P/S
        self._r("bo-gold", "Gold", D(2026, 5, 1), D(2026, 10, 5), self.other, bo=(self.heera, None, D(2026, 6, 1)))
        # BO retailer whose BO distributor is not in the sheet: credited to its BlueOrigin ASM (Gururaj)
        self._r("bo-noble", "Yellow", D(2026, 10, 2), D(2026, 10, 9), self.heera, bo=(self.offline, self.gururaj, D(2026, 7, 1)))
        # not in BlueOrigin: KYC conversion only (KYC before Oct)
        self._r("td-only", "", D(2026, 1, 1), D(2026, 10, 20), self.heera)
        # in BO only from October (not "existing first"): not a BO conversion
        self._r("bo-new-oct", "Silver", D(2026, 9, 1), D(2026, 10, 21), self.heera, bo=(self.heera, None, OCT))
        # first TD order in August: not new in October
        self._r("repeat", "Gold", D(2025, 1, 1), D(2026, 8, 1), self.heera, bo=(self.heera, None, D(2025, 1, 1)))

    def _order(self, r, day, dist, value=100):
        self.n += 1
        at = timezone.make_aware(dt.datetime.combine(day, dt.time(12)))
        Order.objects.create(source_id=f"o{self.n}", display_id=str(self.n), split_group=f"c{self.n}", retailer=r,
                             distributor=dist, status="delivered", payment_status="captured", is_qualifying=True,
                             gross_value=Decimal(value), units=1, placed_at=at, placed_date=day)

    def _r(self, name, tier, signed, first, dist, bo=None):
        r = Retailer.objects.create(name=name, tier=tier, kyc_status="approved", distributor=dist,
                                    signed_up_at=timezone.make_aware(dt.datetime.combine(signed, dt.time(10))))
        self._order(r, first, dist)
        if bo:
            b = BoRetailer.objects.create(bo_id=f"B-{name}", name=name, distributor=bo[0], asm=bo[1], td_retailer=r,
                                          tier=tier)
            BoRetailerMonth.objects.create(bo_retailer=b, month=bo[2], value=Decimal(5000))
        return r

    def test_counts_credit_and_split(self):
        t = inc.tracker(OCT)
        self.assertEqual(t["totals"], {"new": 2, "gps": 1, "kyc": 2})  # credited only (td-only, bo-new-oct)
        g = next(p for p in t["people"] if p["person"] == "Gururaj")
        s = next(p for p in t["people"] if p["person"] == "Srinivas")
        # bo-gold -> Heera (its BO distributor), split 20:10 for New and 10:5 for G/P/S; bo-noble -> Gururaj via BO ASM
        self.assertAlmostEqual(g["new_actual"], round(2 / 3 + 1, 1))
        self.assertAlmostEqual(s["new_actual"], round(1 / 3, 1))
        self.assertEqual(g["via_bo_asm"], {"new": 1, "gps": 0})
        self.assertAlmostEqual(g["gps_actual"] + s["gps_actual"], 1.0, places=1)
        # KYC before Oct among first TD orders in Oct, credited to the first-order distributor (Heera): bo-gold's first
        # order went through "Other dist" (not in the sheet) -> not credited
        self.assertEqual(t["uncredited"]["kyc"], 1)
        self.assertEqual(g["payout_pct"], inc.payout_pct(g["score_pct"]))

    def test_payout_slabs(self):
        self.assertEqual([inc.payout_pct(x) for x in (74.9, 75, 89.9, 90, 99.9, 100, 149.9, 150)],
                         [0, 90, 90, 100, 100, 200, 200, 300])

    def test_retailer_list(self):
        rows = {r["retailer"]: r for r in inc.retailer_list(OCT, kpi="new")}
        self.assertEqual(set(rows), {"bo-gold", "bo-noble"})
        self.assertEqual(rows["bo-gold"]["bo_distributor"], "Heera")
        self.assertEqual(rows["bo-gold"]["td_distributor"], "Other dist")
        self.assertIn("BlueOrigin ASM", rows["bo-noble"]["credited_to"])
        self.assertEqual([r["retailer"] for r in inc.retailer_list(OCT, kpi="gps", tiers=["Gold"])], ["bo-gold"])
        mine = inc.retailer_list(OCT, kpi="new", distributor_ids=[self.heera.id], asm_id=self.gururaj.id)
        self.assertEqual(len(mine), 2)
