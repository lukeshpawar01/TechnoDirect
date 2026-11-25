"""TD wallet share of BlueOrigin spend (analytics/blueorigin.py): by tier and by quarter, Way Forward deck measure."""
import datetime as dt
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from analytics import blueorigin as bo
from analytics.filters import system_filters
from warehouse.models import BoRetailer, BoRetailerMonth, BoRetailerQuarter, Distributor, Order, Retailer

D = dt.date


class WalletShareTests(TestCase):
    def setUp(self):
        self.d = Distributor.objects.create(code="D1", name="D1")
        self.n = 0
        # matched: ordered on TD; BO 1,000 in Q2 FY27 (Jul+Aug) and 400 in Q1 FY27, TD 300 in Q2 FY27 only
        gold = self._retailer("gold", D(2026, 7, 10), [(D(2026, 7, 10), 300)])
        b = self._bo("B1", gold, "Gold", {D(2026, 4, 1): 400, D(2026, 7, 1): 600, D(2026, 8, 1): 400})
        # linked to an app retailer that never ordered: not matched
        never = Retailer.objects.create(name="never", distributor=self.d)
        self._bo("B2", never, "Gold", {D(2026, 7, 1): 5000})
        # not linked at all
        self._bo("B3", None, "Silver", {D(2026, 7, 1): 7000})
        self.b = b

    def _retailer(self, name, first, orders):
        r = Retailer.objects.create(name=name, distributor=self.d, first_order_date=first)
        for day, v in orders:
            self.n += 1
            Order.objects.create(source_id=f"o{self.n}", display_id=str(self.n), split_group=f"c{self.n}", retailer=r,
                                 distributor=self.d, status="delivered", payment_status="captured", is_qualifying=True,
                                 gross_value=Decimal(v), units=1, placed_date=day,
                                 placed_at=timezone.make_aware(dt.datetime.combine(day, dt.time(12))))
        return r

    def _bo(self, bo_id, td, tier, months):
        b = BoRetailer.objects.create(bo_id=bo_id, name=bo_id, distributor=self.d, td_retailer=td, tier=tier)
        for m, v in months.items():
            BoRetailerMonth.objects.create(bo_retailer=b, month=m, value=Decimal(v), distributor=self.d)
        for q in {D(m.year, (m.month - 1) // 3 * 3 + 1, 1) for m in months}:
            BoRetailerQuarter.objects.create(bo_retailer=b, quarter=q, label="q", tier=tier, distributor=self.d,
                                             purchase=sum(Decimal(v) for mm, v in months.items()
                                                          if D(mm.year, (mm.month - 1) // 3 * 3 + 1, 1) == q))
        return b

    def test_by_tier_and_by_quarter(self):
        f = system_filters(today=D(2026, 11, 20))
        f.period.start, f.period.end = D(2026, 7, 1), D(2026, 9, 30)
        d = bo.potential(f)
        gold = next(t for t in d["by_tier"] if t["tier"] == "Gold")
        # only the matched retailer counts: TD 300 of its BO 1,000 in the window (Jul-Sep)
        self.assertEqual((gold["wallet_retailers"], gold["wallet_td"], gold["wallet_bo"], gold["wallet_gap"]),
                         (1, 300.0, 1000.0, 700.0))
        self.assertEqual(gold["wallet_pct"], 30.0)
        self.assertEqual(next(t for t in d["by_tier"] if t["tier"] == "Silver")["wallet_retailers"], 0)
        q = {x["quarter"]: x for x in d["wallet_by_quarter"]}
        # Q1 FY27: BO 400 and no TD yet -> 0%; Q2 FY27: 300 / 1,000
        self.assertEqual([x["quarter"] for x in d["wallet_by_quarter"]], sorted(q, key=lambda k: q[k]["start"]))
        q2 = next(x for x in d["wallet_by_quarter"] if x["start"] == "2026-07-01")
        self.assertEqual((q2["retailers"], q2["td"], q2["bo"], q2["wallet_pct"]), (1, 300.0, 1000.0, 30.0))
