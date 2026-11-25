"""Way Forward deck extensions: retailer-to-distributor proximity (slide 10) and TD inside the TechnoSport base (slide 12)."""
import datetime as dt
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from analytics.filters import system_filters
from analytics.views.distributors import proximity, proximity_band
from analytics.views.funnel import retailer_base, techno_base
from warehouse.models import BoRetailer, BoRetailerMonth, Distributor, Order, Retailer

D = dt.date


class ProximityBandTests(SimpleTestCase):
    def test_bands(self):
        self.assertEqual(proximity_band("560001", "560001"), "same_pincode")
        self.assertEqual(proximity_band("560068", "560001"), "same_district")
        self.assertEqual(proximity_band("561203", "560001"), "same_circle")
        self.assertEqual(proximity_band("590001", "560001"), "same_zone")
        self.assertEqual(proximity_band("110001", "560001"), "other_zone")
        self.assertIsNone(proximity_band("", "560001"))
        self.assertIsNone(proximity_band("5600", "560001"))


class DeckExtensionTests(TestCase):
    def setUp(self):
        self.d = Distributor.objects.create(code="D", name="D", pincode="560001")
        self.n = 0
        # TD-first: first TD order Jan-26, first offline purchase Apr-26
        self.a = self._r("a", "560068", "approved", D(2026, 1, 10), 1)
        # BO-first: offline since Oct-25, TD from Jan-26
        self.b = self._r("b", "110001", "approved", D(2026, 1, 12), 1)
        # not in BO, 2 orders (TD acquired); not in BO, 1 order (too soon)
        self._r("c", "", "approved", D(2026, 2, 1), 2)
        self._r("e", "560001", "approved", D(2026, 3, 1), 1)
        # KYC done, never ordered, in BO
        self.f = Retailer.objects.create(name="f", kyc_status="approved", distributor=self.d,
                                         signed_up_at=timezone.make_aware(dt.datetime(2025, 5, 1)))
        for bo_id, td, months in (("B1", self.a, [D(2026, 4, 1)]), ("B2", self.b, [D(2025, 10, 1)]),
                                  ("B3", self.f, [D(2025, 11, 1)]), ("B4", None, [D(2025, 12, 1)])):
            bo = BoRetailer.objects.create(bo_id=bo_id, name=bo_id, distributor=self.d, td_retailer=td)
            for m in months:
                BoRetailerMonth.objects.create(bo_retailer=bo, month=m, value=Decimal(1000), distributor=self.d)

    def _r(self, name, pin, kyc, first, n):
        r = Retailer.objects.create(name=name, pincode=pin, kyc_status=kyc, distributor=self.d, first_order_date=first,
                                    orders_count=n, signed_up_at=timezone.make_aware(dt.datetime(2025, 5, 1)))
        for i in range(n):
            self.n += 1
            day = first + dt.timedelta(days=i * 20)
            Order.objects.create(source_id=f"o{self.n}", display_id=str(self.n), split_group=f"c{self.n}", retailer=r,
                                 distributor=self.d, status="delivered", payment_status="captured", is_qualifying=True,
                                 gross_value=Decimal(100), units=1, placed_date=day,
                                 placed_at=timezone.make_aware(dt.datetime.combine(day, dt.time(12))))
        return r

    def test_proximity(self):
        p = proximity(Order.objects.all())
        rows = {r["band"]: r for r in p["rows"]}
        self.assertEqual((rows["same_pincode"]["retailers"], rows["same_district"]["retailers"],
                          rows["other_zone"]["retailers"]), (1, 1, 1))
        self.assertEqual(p["unknown_orders"], 2)  # retailer c has no pincode
        self.assertAlmostEqual(p["outside_district_pct"], 33.33, places=1)

    def test_techno_base(self):
        f = system_filters(today=D(2026, 11, 20))
        f.period.start, f.period.end = D(2026, 11, 1), D(2026, 11, 20)
        t = techno_base(f, retailer_base(f))
        self.assertEqual(t["universe"], 4)
        self.assertEqual((t["bo_on_td"], t["bo_transacting"], t["bo_never_transacted"]), (3, 2, 2))
        self.assertEqual((t["kyc"], t["kyc_in_bo"], t["kyc_new"]), (5, 3, 2))
        self.assertEqual((t["ants"], t["ants_in_bo"]), (1, 1))
        self.assertEqual(t["attribution"], {"td_first": 1, "not_in_bo_established": 1, "same_quarter": 0,
                                            "bo_first": 1, "not_in_bo_new": 1})
        self.assertEqual((t["acquired_by_td"], t["acquired_by_td_pct"]), (2, 50.0))

