"""Incentive tracker (masters/incentives.py): BO conversions (offline first, new to TD) credited to the BlueOrigin
distributor / ASM, KYC conversions, shared-distributor split, payout slabs."""
import datetime as dt
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from masters import incentives as inc
from warehouse.models import (Asm, BoRetailer, BoRetailerMonth, BoRetailerQuarter, Distributor, FieldStaff, Order,
                              Retailer, TargetSplit)

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
        # BO retailer whose BO distributor is not in the incentive sheet: counts for no one (not even its BO ASM)
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
            # the tier that counts is the one in the last BO quarter before the month (Q2 FY27 for October)
            BoRetailerQuarter.objects.create(bo_retailer=b, quarter=D(2026, 7, 1), label="Q2 FY27", tier=tier or "Untiered")
        return r

    def test_counts_credit_and_split(self):
        t = inc.tracker(OCT)
        self.assertEqual(t["totals"], {"new": 1, "gps": 1, "kyc": 2})  # credited only: bo-gold; KYC td-only, bo-new-oct
        self.assertEqual(t["uncredited"]["new"], 1)  # bo-noble: its BO distributor is not in the sheet
        g = next(p for p in t["people"] if p["person"] == "Gururaj")
        s = next(p for p in t["people"] if p["person"] == "Srinivas")
        # bo-gold -> Heera (its BO distributor), split 20:10 for New and 10:5 for G/P/S
        self.assertAlmostEqual(g["new_actual"], round(2 / 3, 1))
        self.assertAlmostEqual(s["new_actual"], round(1 / 3, 1))
        self.assertEqual(g["via_bo_asm"], {"new": 0, "gps": 0})
        self.assertAlmostEqual(g["gps_actual"] + s["gps_actual"], 1.0, places=1)
        # KYC before Oct among first TD orders in Oct, credited to the first-order distributor (Heera): bo-gold's first
        # order went through "Other dist" (not in the sheet) -> not credited
        self.assertEqual(t["uncredited"]["kyc"], 1)
        self.assertEqual(g["payout_pct"], sum(g[f"{k}_payable"] for k in ("td", "new", "gps", "kyc")))

    def test_payout_factors(self):
        """TD_Incentive_Policy: per KPI, <70 -> 0, 70-<90 -> 0.90, 90+ -> 1.00; no target -> 0."""
        self.assertEqual([inc.payout_factor(x) for x in (None, 69.9, 70, 89.9, 90, 99.9, 100, 180)],
                         [0, 0, 0.9, 0.9, 1.0, 1.0, 1.0, 1.0])
        # the policy's example: TD 71%, New 99%, G/P/S 89%, KYC 100% -> 4,650 of 5,000 = 93%
        r = inc.score({"td_pct": 71, "new_pct": 99, "gps_pct": 89, "kyc_pct": 100})
        self.assertAlmostEqual(r["payout_pct"], 93.0)
        self.assertEqual([r[f"{k}_payable"] for k in ("td", "new", "gps", "kyc")], [45.0, 20.0, 18.0, 10.0])

    def test_retailer_list(self):
        rows = {r["retailer"]: r for r in inc.retailer_list(OCT, kpi="new")}
        self.assertEqual(set(rows), {"bo-gold", "bo-noble"})
        self.assertEqual(rows["bo-gold"]["bo_distributor"], "Heera")
        self.assertEqual(rows["bo-gold"]["td_distributor"], "Other dist")
        self.assertEqual(rows["bo-noble"]["credited_to"], "No one in the sheet")
        self.assertEqual([r["retailer"] for r in inc.retailer_list(OCT, kpi="gps", tiers=["Gold"])], ["bo-gold"])
        mine = inc.retailer_list(OCT, kpi="new", distributor_ids=[self.heera.id], asm_id=self.gururaj.id)
        self.assertEqual([m["retailer"] for m in mine], ["bo-gold"])


class IncentiveSheetTests(IncentiveTests):
    """The sheet-shaped table: one row per sheet line, own score per row, falls back to the latest sheet month."""

    def test_sheet_rows_and_fallback(self):
        t = inc.sheet_table(D(2026, 11, 1))  # no November rows: shows October
        self.assertTrue(t["fallback"])
        self.assertEqual(t["month"], "2026-10")
        self.assertEqual([r["employee"] for r in t["rows"]], ["Gururaj", "Srinivas"])  # sheet order
        g, s = t["rows"]
        self.assertAlmostEqual(g["td_actual"] + s["td_actual"], 300.0)  # Heera's 3 October orders of 100 (bo-gold went via another distributor)
        self.assertEqual(g["td_target"], 80.0)
        self.assertEqual(g["payout_pct"], round(sum(g[f"{k}_payable"] for k in ("td", "new", "gps", "kyc")), 1))
        self.assertFalse(inc.sheet_table(OCT)["fallback"])


class IncentiveSheetEditTests(IncentiveTests):
    """Editing the sheet month by month in the dashboard (target_sheet.editor / save_month)."""

    def test_new_month_starts_as_copy_and_saves(self):
        from masters import target_sheet as ts
        from warehouse.models import Target

        nov = D(2026, 11, 1)
        e = ts.editor(nov)
        self.assertEqual(e["copied_from"], "2026-10")
        self.assertEqual([r["person"] for r in e["rows"]], ["Gururaj", "Srinivas"])
        rows = e["rows"]
        rows[0]["td_target"], rows[0]["new_target"] = 120, 4
        rows.append({"distributor_id": self.other.id, "role": "executive", "person": "Vacant", "td_target": 50})
        ts.save_month(nov, rows, "a@b.c")
        saved = list(TargetSplit.objects.filter(month=nov).order_by("id"))
        self.assertEqual([(s.person, float(s.value), s.new_retailer_target) for s in saved],
                         [("Gururaj", 120.0, 4), ("Srinivas", float(rows[1]["td_target"]), rows[1]["new_target"]), ("Vacant", 50.0, None)])
        self.assertTrue(saved[0].source.startswith(ts.EDIT_PREFIX))
        self.assertEqual(float(Target.objects.get(month=nov, metric="sales", scope_type="overall").value),
                         120 + rows[1]["td_target"] + 50)
        self.assertEqual(ts.editor(nov)["owner"], "dashboard")
        self.assertEqual(ts.edited_months(), {nov})
        self.assertEqual(TargetSplit.objects.filter(month=OCT).count(), 2)  # October untouched

    def test_validation(self):
        from masters import target_sheet as ts

        with self.assertRaises(ts.TargetSheetError):
            ts.save_month(OCT, [{"distributor_id": self.heera.id, "role": "asm", "person": "Gururaj", "td_target": 0}], "x")
        with self.assertRaises(ts.TargetSheetError):
            ts.save_month(OCT, [{"role": "asm", "person": "Gururaj", "td_target": 10}], "x")
        with self.assertRaises(ts.TargetSheetError):
            ts.save_month(OCT, [], "x")
        self.assertEqual(TargetSplit.objects.filter(month=OCT).count(), 2)  # nothing changed

    def test_payment_from_eligible_amount(self):
        from masters import target_sheet as ts

        rows = ts.editor(OCT)["rows"]
        rows[0]["eligible"] = "5,000"
        ts.save_month(OCT, rows, "a@b.c")
        g, s = inc.sheet_table(OCT)["rows"]
        self.assertEqual(g["eligible"], 5000.0)
        self.assertEqual(s["eligible"], inc.ELIGIBLE_DEFAULT)  # no amount of its own -> the policy's ₹5,000
        self.assertAlmostEqual(s["payment"], 5000 * s["payout_pct"] / 100)
        self.assertAlmostEqual(g["payment"], sum(g[f"{k}_amount"] for k in ("td", "new", "gps", "kyc")))
        self.assertAlmostEqual(g["payment"], 5000 * g["payout_pct"] / 100, places=1)
        self.assertAlmostEqual(g["td_amount"], 5000 * 0.5 * g["td_factor"])
        with self.assertRaises(ts.TargetSheetError):
            rows[0]["eligible"] = "five thousand"
            ts.save_month(OCT, rows, "a@b.c")
