"""Region & ASM scorecard: New (TD) vs BO -> TD conversions grouped by the BlueOrigin territory (analytics/conversions)."""
import datetime as dt
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from analytics import conversions as cv
from analytics.filters import system_filters
from warehouse.models import Asm, BoRetailer, BoRetailerMonth, BoRetailerQuarter, Distributor, Order, Retailer

D = dt.date


class ConversionTests(TestCase):
    def setUp(self):
        self.a1 = Asm.objects.create(code="A1", name="One")
        self.a2 = Asm.objects.create(code="A2", name="Two")
        self.d1 = Distributor.objects.create(code="D1", name="D1", asm=self.a1)
        self.d2 = Distributor.objects.create(code="D2", name="D2", asm=self.a2)
        self.n = 0
        # BO retailer of ASM Two (offline since June), first TD order in Oct through D1 (ASM One)
        r = self._r("bo-gold", "Gold", D(2026, 10, 5), self.d1)
        b = BoRetailer.objects.create(bo_id="B1", name="x", distributor=self.d2, asm=self.a2, td_retailer=r)
        BoRetailerMonth.objects.create(bo_retailer=b, month=D(2026, 6, 1), value=Decimal(900))
        BoRetailerQuarter.objects.create(bo_retailer=b, quarter=D(2026, 7, 1), label="Q2 FY27", tier="Gold")
        # a later quarter (would include the TD orders themselves) must not be used for an October conversion
        BoRetailerQuarter.objects.create(bo_retailer=b, quarter=D(2026, 10, 1), label="Q3 FY27", tier="Yellow")
        # in BO only from October: not a conversion
        r2 = self._r("bo-late", "Silver", D(2026, 10, 7), self.d1)
        b2 = BoRetailer.objects.create(bo_id="B2", name="y", distributor=self.d1, asm=self.a1, td_retailer=r2)
        BoRetailerMonth.objects.create(bo_retailer=b2, month=D(2026, 10, 1), value=Decimal(900))
        self._r("td-only", "", D(2026, 10, 9), self.d1)

    def _r(self, name, tier, first, dist):
        self.n += 1
        r = Retailer.objects.create(name=name, tier=tier, first_order_date=first, distributor=dist, asm=dist.asm)
        at = timezone.make_aware(dt.datetime.combine(first, dt.time(12)))
        Order.objects.create(source_id=f"o{self.n}", display_id=str(self.n), split_group=f"c{self.n}", retailer=r,
                             distributor=dist, asm=dist.asm, status="delivered", payment_status="captured",
                             is_qualifying=True, gross_value=Decimal(100), units=1, placed_at=at, placed_date=first)
        return r

    def test_counts_by_bo_territory(self):
        f = system_filters(today=D(2026, 11, 20))
        f.period.start, f.period.end = D(2026, 10, 1), D(2026, 10, 31)
        c = cv.counts(f, "asm")
        self.assertEqual(c[self.a1.id], {"new": 3, "bo": 0, "gps": 0})  # all first TD orders went through D1
        self.assertEqual(c[self.a2.id], {"new": 0, "bo": 1, "gps": 1})  # the conversion counts under its BO ASM
        rows = cv.retailers(f, "asm", self.a2.id, "gps")
        self.assertEqual([r["retailer"] for r in rows], ["bo-gold"])
        self.assertEqual((rows[0]["bo_asm"], rows[0]["td_distributor"]), ("Two", "D1"))
