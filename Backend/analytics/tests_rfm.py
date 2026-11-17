"""RFM segmentation (analytics/rfm.py) - rules from "RFM Segmentation Logic" (TD, Nov-2026)."""
import datetime as dt
from decimal import Decimal

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from accounts.testing import jwt_login
from warehouse.models import Asm, Distributor, Order, Region, Retailer

from . import rfm

D = dt.date
AS_OF = D(2026, 11, 10)


def orders_every(rid, first, gap_days, count, value=10000):
    return [(rid, first + dt.timedelta(days=i * gap_days), f"{rid}-{i}", Decimal(value)) for i in range(count)]


class RfmMathTests(SimpleTestCase):
    def test_percentile_matches_postgres_percentile_cont(self):
        for got, want in zip(rfm.cutoffs([1, 2, 3, 4, 5]), [1.8, 2.6, 3.4, 4.2]):
            self.assertAlmostEqual(got, want)
        self.assertAlmostEqual(rfm.percentile(list(range(1, 11)), 0.9), 9.1)

    def test_strict_comparison_keeps_ties_at_the_lower_score(self):
        c = [1.0, 1.0, 2.0, 3.0]  # P20 == P40 (a big tie)
        self.assertEqual(rfm.score_high(1.0, c), 1)
        self.assertEqual(rfm.score_high(1.5, c), 3)
        self.assertEqual(rfm.score_low(0.5, c), 5)  # recency: lower ratio is better
        self.assertEqual(rfm.score_low(3.0, c), 1)

    def test_fm_rounds_half_up(self):
        self.assertEqual(rfm.round_half_up(2.5), 3)
        self.assertEqual(rfm.round_half_up(1.5), 2)
        self.assertEqual(rfm.round_half_up(4.0), 4)


class RfmLifecycleTests(SimpleTestCase):
    def build(self):
        o = []
        o += orders_every(1, D(2026, 1, 1), 7, 44)        # weekly buyer, last order 2026-11-05: on rhythm
        o += orders_every(2, D(2025, 1, 1), 7, 40)        # weekly buyer silent since Oct-2025: churned
        o += orders_every(3, D(2026, 1, 1), 60, 5)        # slow buyer (every 60 days), last 2026-09-28
        o += [(4, D(2026, 11, 1), "4-0", Decimal(5000))]  # first order 9 days ago: New Customer
        o += orders_every(5, D(2026, 2, 1), 7, 30, 500)   # weekly but tiny, silent ~2 months
        o += [(6, D(2026, 6, 1), "6-0", Decimal(0))]      # zero-value order only: not a buyer
        for rid in range(10, 30):                         # a population of regular monthly buyers
            o += orders_every(rid, D(2025, 12, 1) + dt.timedelta(days=rid), 30, 11, 20000 + rid * 1000)
        return o

    def test_lifecycle_and_segments(self):
        res = rfm.compute(as_of=AS_OF, orders=self.build())
        rows = res["rows"]
        self.assertNotIn(6, rows)  # Prospect: never scored
        self.assertEqual(rows[2]["lifecycle"], "churned")
        self.assertEqual(rows[2]["segment"], "churned")
        self.assertEqual(rows[1]["lifecycle"], "active")
        self.assertEqual(rows[4]["segment"], "new_customers")
        # the slow buyer is not churned after one quiet month - judged against their own rhythm
        self.assertEqual(rows[3]["lifecycle"], "active")
        self.assertLess(rows[3]["recency_ratio"], rows[5]["recency_ratio"])
        # one-time buyer's expected gap = the population median gap
        self.assertEqual(rows[4]["expected_gap"], res["population"]["median_gap"])
        # every active row is scored and mapped through the grid
        for r in rows.values():
            if r["lifecycle"] == "active" and r["segment"] != "new_customers":
                self.assertEqual(r["segment"], rfm.GRID[r["r_score"]][r["fm"] - 1])

    def test_as_of_never_later_than_the_latest_order(self):
        res = rfm.compute(as_of=D(2027, 6, 1), orders=self.build())
        self.assertEqual(res["as_of"], D(2026, 11, 1))  # latest valid order in the sample

    def test_tenure_floor_stops_one_order_looking_like_a_high_rate(self):
        res = rfm.compute(as_of=AS_OF, orders=self.build())
        self.assertEqual(res["rows"][4]["tenure_months"], rfm.MIN_TENURE_M)
        self.assertAlmostEqual(res["rows"][4]["f"], 1 / 3, places=3)


class RfmEndpointTests(TestCase):
    def test_rfm_summary_segment_filter_and_detail(self):
        cache.clear()
        reg = Region.objects.create(code="S", name="South")
        d = Distributor.objects.create(code="H", name="Heera", region=reg)
        rs = [Retailer.objects.create(source_id=f"r{i}", name=f"R{i}", distributor=d, region=reg) for i in range(6)]
        Retailer.objects.create(source_id="p", name="Prospect shop", distributor=d, region=reg)
        n = 0
        for i, r in enumerate(rs):
            for k in range(i + 1):
                day = D(2026, 11, 5) - dt.timedelta(days=20 * k + i)
                n += 1
                Order.objects.create(source_id=f"o{n}", display_id=f"O{n}", split_group=f"o{n}", retailer=r, distributor=d,
                                     region=reg, status="delivered", payment_status="captured", is_qualifying=True,
                                     gross_value=Decimal(1000 * (i + 1)), units=1, placed_date=day,
                                     placed_at=timezone.make_aware(dt.datetime.combine(day, dt.time(11))))
        User.objects.create_superuser(email="rfm@test.local", password="x-Strong-pass1")
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Bearer " + jwt_login(c, "rfm@test.local", "x-Strong-pass1")["access"])
        q = "preset=custom&date_from=2026-11-01&date_to=2026-11-10"
        data = c.get(f"/api/retailers/rfm/?{q}").json()["data"]
        self.assertEqual(data["summary"]["buyers"], 6)
        segs = {s["segment"]: s for s in data["segments"]}
        self.assertEqual(segs["prospect"]["retailers"], 1)
        self.assertEqual(sum(s["retailers"] for k, s in segs.items() if k != "prospect"), 6)
        self.assertEqual(len(data["grid"]), 25)
        # the segment filter lists exactly the retailers counted in that segment
        for key, s in segs.items():
            if s["retailers"]:
                got = c.get(f"/api/retailers/?{q}&segment={key}").json()
                self.assertEqual(got["count"], s["retailers"], key)
                self.assertTrue(all(r["rfm_segment"] == key for r in got["results"]))
        detail = c.get(f"/api/retailers/{rs[-1].id}/?{q}").json()["data"]
        self.assertIn(detail["rfm"]["segment"], rfm.SEGMENTS)
        self.assertTrue(detail["rfm"]["action"])


class RetailerAsmSyncTests(TestCase):
    def test_retailers_follow_their_distributors_asm(self):
        from masters.services import assign_distributor_asm

        from .derivations import sync_retailer_asms

        reg = Region.objects.create(code="S", name="South")
        old, new = Asm.objects.create(code="A1", name="Imran"), Asm.objects.create(code="A2", name="Anil")
        d = Distributor.objects.create(code="V", name="Virat", region=reg, asm=old)
        r = Retailer.objects.create(source_id="x", name="Shop", distributor=d, region=reg, asm=old)
        stray = Retailer.objects.create(source_id="y", name="Blank ASM", distributor=d, region=reg)
        assign_distributor_asm(d, new, D(2026, 10, 1))
        r.refresh_from_db()
        self.assertEqual(r.asm_id, new.id)  # handover moves the retailers immediately
        self.assertEqual(sync_retailer_asms(), 0 if Retailer.objects.get(id=stray.id).asm_id == new.id else 1)
        stray.refresh_from_db()
        self.assertEqual(stray.asm_id, new.id)
        self.assertEqual(sync_retailer_asms(), 0)  # idempotent
