"""Orders-page drill-downs: /orders/ and /orders/retailers/ select exactly what each chart mark counts."""
import datetime as dt
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from accounts.testing import jwt_login
from warehouse.models import Distributor, Order, Region, Retailer


class OrdersDrillTests(TestCase):
    def setUp(self):
        cache.clear()
        reg = Region.objects.create(code="S", name="South")
        d = Distributor.objects.create(code="H", name="Heera", region=reg)
        self.r1 = Retailer.objects.create(source_id="a", name="Shop A", distributor=d, region=reg)
        self.r2 = Retailer.objects.create(source_id="b", name="Shop B", distributor=d, region=reg)
        now = timezone.now()
        rows = [  # (retailer, hours ago, status, mode, platform, value)
            (self.r1, 10, "received", "UPI", "android", 1000),
            (self.r1, 30, "confirmed", "CC", "web", 2000),
            (self.r2, 30, "confirmed", "", "android", 3000),
            (self.r2, 200, "shipped", "UPI", "ios", 4000),
            (self.r2, 20, "cancelled", "UPI", "android", 5000),
        ]
        for i, (r, h, st, mode, plat, v) in enumerate(rows):
            at = now - dt.timedelta(hours=h)
            Order.objects.create(source_id=f"o{i}", display_id=f"O{i}", split_group=f"o{i}", retailer=r, distributor=d,
                                 region=reg, status=st, payment_status="captured", payment_mode=mode, platform=plat,
                                 is_qualifying=st != "cancelled", gross_value=Decimal(v), units=1, placed_at=at,
                                 placed_date=timezone.localtime(at).date())
        User.objects.create_superuser(email="dr@test.local", password="x-Strong-pass1")
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION="Bearer " + jwt_login(self.c, "dr@test.local", "x-Strong-pass1")["access"])

    def get(self, path, q):
        today = timezone.localdate()
        span = f"preset=custom&date_from={today - dt.timedelta(days=30)}&date_to={today}"
        return self.c.get(f"/api/{path}?{span}&{q}").json()

    def test_ageing_cell(self):
        self.assertEqual(self.get("orders/", "order_status=confirmed&age_bucket=1-2d")["count"], 2)
        self.assertEqual(self.get("orders/", "order_status=shipped&age_bucket=7d%2B")["count"], 1)
        self.assertEqual(self.get("orders/", "order_status=received&age_bucket=7d%2B")["count"], 0)
        self.assertEqual(self.c.get("/api/orders/?age_bucket=9d").status_code, 400)

    def test_payment_mode_and_platform_are_paid_orders_only(self):
        self.assertEqual(self.get("orders/", "paid=1&mode=UPI")["count"], 2)  # the cancelled UPI order is excluded
        self.assertEqual(self.get("orders/", "paid=1&mode=Unknown")["count"], 1)  # blank mode
        self.assertEqual(self.get("orders/", "paid=1&platform=android")["count"], 2)

    def test_retailer_rollup_matches_orders(self):
        data = self.get("orders/retailers/", "order_status=confirmed&age_bucket=1-2d")
        self.assertEqual(data["count"], 2)
        by = {r["retailer"]: r for r in data["results"]}
        self.assertEqual(by["Shop A"]["orders"], 1)
        self.assertEqual(by["Shop B"]["value"], 3000)
        self.assertEqual(data["results"][0]["retailer"], "Shop B")  # highest value first
        self.assertIn("rfm_label", data["results"][0])
        csv = self.c.get("/api/orders/retailers/?order_status=confirmed&age_bucket=1-2d&export=csv")
        self.assertEqual(csv.status_code, 200)
        self.assertEqual(len(csv.content.decode("utf-8-sig").strip().splitlines()), 3)
