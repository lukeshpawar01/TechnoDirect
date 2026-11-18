"""Order flow & delays (/api/orders/flow/): lead times in days, late = past SLA or still waiting past it, measured
from the data date (latest day in the export), and every number lists exactly its orders."""
import datetime as dt
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from accounts.testing import jwt_login
from warehouse.models import Distributor, Order, Region, Retailer, State


def at(d, hour=12):
    return timezone.make_aware(dt.datetime.combine(d, dt.time(hour)))


class OrderFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        reg = Region.objects.create(code="S", name="South")
        ka = State.objects.create(code="KA", name="Karnataka", region=reg)
        self.slow = Distributor.objects.create(code="SL", name="Slow Dist", region=reg, state=ka)
        self.fast = Distributor.objects.create(code="FA", name="Fast Dist", region=reg, state=ka)
        r = Retailer.objects.create(source_id="r", name="Shop", distributor=self.fast, region=reg)
        # the export's last day is 3 days before today: the clock must not make its orders late
        self.as_of = timezone.localdate() - dt.timedelta(days=3)
        a = self.as_of
        rows = [  # (distributor, placed days before as_of, ship after days, deliver after days, status)
            (self.fast, 10, 0, 1, "delivered"),   # same-day dispatch, 1 day transit
            (self.fast, 10, 1, 2, "delivered"),
            (self.slow, 10, 5, 1, "delivered"),   # late dispatch
            (self.slow, 10, 1, 6, "delivered"),   # late transit
            (self.slow, 6, None, None, "received"),  # still not shipped 6 days later: late
            (self.fast, 1, None, None, "received"),  # placed yesterday (data date): not late yet
            (self.fast, 7, 1, None, "shipped"),   # in transit 6 days: late
            (self.fast, 5, None, None, "cancelled"),
        ]
        for i, (dist, ago, ship, dlv, st) in enumerate(rows):
            placed = a - dt.timedelta(days=ago)
            shipped = placed + dt.timedelta(days=ship) if ship is not None else None
            delivered = shipped + dt.timedelta(days=dlv) if shipped and dlv is not None else None
            Order.objects.create(
                source_id=f"o{i}", display_id=f"O{i}", split_group=f"o{i}", retailer=r, distributor=dist, region=reg,
                state=ka, status=st, payment_status="captured", payment_mode="UPI", platform="android",
                is_qualifying=st != "cancelled", gross_value=Decimal(1000), units=30, placed_at=at(placed),
                placed_date=placed, shipped_at=at(shipped, 23) if shipped else None,
                delivered_at=at(delivered, 23) if delivered else None)
        # the data date = the latest placed day
        Order.objects.create(source_id="last", display_id="LAST", split_group="last", retailer=r, distributor=self.fast,
                             region=reg, state=ka, status="delivered", payment_status="captured", is_qualifying=True,
                             gross_value=Decimal(1), units=1, placed_at=at(a), placed_date=a, shipped_at=at(a, 23),
                             delivered_at=at(a, 23))
        User.objects.create_superuser(email="fl@test.local", password="x-Strong-pass1")
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION="Bearer " + jwt_login(self.c, "fl@test.local", "x-Strong-pass1")["access"])
        self.span = f"preset=custom&date_from={a - dt.timedelta(days=20)}&date_to={timezone.localdate()}"

    def flow(self, q=""):
        r = self.c.get(f"/api/orders/flow/?{self.span}&{q}")
        self.assertEqual(r.status_code, 200, r.content[:300])
        return r.json()["data"]

    def count(self, q):
        return self.c.get(f"/api/orders/?{self.span}&page_size=1&{q}").json()["count"]

    def test_lead_times_and_late_orders(self):
        d = self.flow()
        self.assertEqual(d["as_of"], self.as_of.isoformat())
        self.assertEqual(d["orders"], 8)  # cancelled excluded
        disp = {b["key"]: b["orders"] for b in d["dispatch"]["buckets"]}
        self.assertEqual((disp["0"], disp["1"], disp["4_6"]), (2, 3, 1))  # incl. the data-date order
        self.assertEqual((d["dispatch"]["waiting"], d["dispatch"]["waiting_late"]), (2, 1))
        self.assertEqual((d["transit"]["waiting"], d["transit"]["waiting_late"]), (1, 1))
        # late: slow 5-day dispatch, slow 6-day transit, slow unshipped 6 days, fast in transit 6 days
        self.assertEqual(d["late_orders"], 4)
        by = {g["label"]: g for g in d["hotspots"]["rows"]}
        self.assertEqual((by["Slow Dist"]["late_orders"], by["Fast Dist"]["late_orders"]), (3, 1))
        self.assertEqual(d["hotspots"]["rows"][0]["label"], "Slow Dist")  # most late orders first
        self.assertTrue(any(i["params"] == {"delay": "dispatch", "waiting": "1"} for i in d["insights"]))

    def test_every_number_lists_its_orders(self):
        d = self.flow()
        for b in d["dispatch"]["buckets"]:
            self.assertEqual(self.count(f"lead=dispatch&lead_bucket={b['key']}"), b["orders"], b)
        for b in d["transit"]["buckets"]:
            self.assertEqual(self.count(f"lead=transit&lead_bucket={b['key']}"), b["orders"], b)
        self.assertEqual(self.count("delay=any"), d["late_orders"])
        self.assertEqual(self.count("delay=dispatch&waiting=1"), d["dispatch"]["waiting_late"])
        for g in d["hotspots"]["rows"]:
            self.assertEqual(self.count(f"delay=any&group_by=distributor&group={g['key']}"), g["late_orders"])
            self.assertEqual(self.count(f"group_by=distributor&group={g['key']}"), g["orders"])
        for p in d["flow"]["points"]:
            for ev in ("received", "shipped", "delivered"):
                if p[ev]:
                    self.assertEqual(self.count(f"flow_day={p['date']}&flow_event={ev}"), p[ev], (p, ev))
        # the retailer roll-up uses the same selection
        r = self.c.get(f"/api/orders/retailers/?{self.span}&delay=any").json()
        self.assertEqual(sum(x["orders"] for x in r["results"]), d["late_orders"])

    def test_other_dimensions_and_validation(self):
        for dim in ("state", "asm", "weekday", "size", "cart", "payment_mode", "platform"):
            d = self.flow(f"group_by={dim}")
            self.assertEqual(sum(g["orders"] for g in d["hotspots"]["rows"]), 8, dim)
        self.assertEqual(self.c.get(f"/api/orders/flow/?{self.span}&group_by=nope").status_code, 400)
        self.assertEqual(self.c.get(f"/api/orders/?{self.span}&lead=dispatch&lead_bucket=9").status_code, 400)

    def test_sla_breaches_count_from_the_data_date(self):
        # unshipped 6 days before the data date is a breach; placed the day before the data date is not, even
        # though the clock says 4 days
        s = self.c.get(f"/api/orders/summary/?{self.span}").json()["data"]
        self.assertEqual(s["sla_breaches"], 1)
