"""Regression: every column a table shows must come back from the API (bugs found in the Nov-2026 sweep)."""
import datetime as dt

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from accounts.testing import jwt_login
from warehouse.models import InventorySnapshot, Product

from .tests import make_world


class TableFieldTests(TestCase):
    def setUp(self):
        cache.clear()
        self.w = make_world()
        User.objects.create_superuser(email="f@test.local", password="x-Strong-pass1")
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION="Bearer " + jwt_login(self.c, "f@test.local", "x-Strong-pass1")["access"])

    def test_inventory_items_carry_quantity_status_and_category(self):
        prod = Product.objects.create(style="OR89", name="OR89 Trackpant", category_l1="men", category_l3="trackpants")
        now = timezone.now()
        for sku, q in (("OR89-L", 0), ("OR89-XL", 40)):
            InventorySnapshot.objects.create(distributor=self.w["d1"], product=prod, sku=sku, style="OR89", size=sku[-2:],
                                             snapshot_date=timezone.localdate(), quantity=q, synced_at=now)
        rows = {r["sku"]: r for r in self.c.get("/api/inventory/items/?ordering=quantity").json()["results"]}
        self.assertEqual(rows["OR89-L"]["quantity"], 0)
        self.assertEqual(rows["OR89-L"]["stock_status"], "oos")  # was shown as "in stock" when the page read `qty`
        self.assertEqual(rows["OR89-XL"]["stock_status"], "in_stock")
        self.assertEqual(rows["OR89-XL"]["category"], "men · trackpants")

    def test_distributor_detail_tables(self):
        d = self.c.get(f"/api/distributors/{self.w['d1'].id}/?preset=all_time").json()["data"]
        r = d["retailers"][0]
        for k in ("state", "segment", "rfm_label", "days_since_last_order", "last_order_date"):
            self.assertIn(k, r)
        self.assertEqual(r["state"], "Karnataka")
        self.assertGreaterEqual(r["days_since_last_order"], 0)

    def test_funnel_warm_unknown_without_ledger(self):
        n = self.c.get("/api/funnel/?preset=all_time").json()["data"]["never_ordered"]
        self.assertFalse(n["warm_available"])
        self.assertIsNone(n["warm"])
        self.assertIsNone(n["cold"])
