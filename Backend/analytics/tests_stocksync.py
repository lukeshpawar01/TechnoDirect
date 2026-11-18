"""Distributor stock sync: sheet import ("Inventory Updated"), 3-day rule, Stock sync filter."""
import csv
import datetime as dt
import os
import shutil
import tempfile

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from accounts.testing import jwt_login
from analytics.stocksync import bucket
from masters.distributor_sync import import_file
from warehouse.models import Distributor

from .tests import make_world


class StockSyncTests(TestCase):
    def setUp(self):
        cache.clear()
        self.w = make_world()  # d1 Heera Exports, d2 Anand Sports
        self.d3 = Distributor.objects.create(code="KUM01", name="Kumar Enterprises", state=self.w["ka"])
        today = dt.date.today()
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "dist.csv")
        with open(self.path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["Distributor", "Inventory Updated", "Status", "ref", "State", "Taken By", "Frequency"])
            w.writerow(["Heera Exports", (today - dt.timedelta(days=1)).strftime("%m/%d/%Y"), "Inventory Live", "Y",
                        "Karnataka", "Manually", "Daily"])
            w.writerow(["Anand Sports", (today - dt.timedelta(days=6)).strftime("%m/%d/%Y"), "Inventory Live", "",
                        "Odisha", "CK", "Twice a week"])
            w.writerow(["Kumar", "", "Inventory Pending", "", "Bihar", "CK", ""])  # prefix match, no date
            w.writerow(["Nobody Traders", "11/17/2026", "Inventory Live", "", "", "CK", "Daily"])
        self.rep = import_file(self.path)
        User.objects.create_superuser(email="k@test.local", password="x-Strong-pass1")
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION="Bearer " + jwt_login(self.c, "k@test.local", "x-Strong-pass1")["access"])

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_import_matches_names_and_dates(self):
        self.assertEqual(self.rep["unmatched"], ["Nobody Traders"])
        d1 = Distributor.objects.get(id=self.w["d1"].id)
        self.assertEqual(d1.stock_updated_on, dt.date.today() - dt.timedelta(days=1))
        self.assertEqual((d1.stock_upload_mode, d1.stock_update_frequency), ("Manually", "Daily"))
        k = Distributor.objects.get(id=self.d3.id)
        self.assertIn("Kumar", k.aliases)  # short sheet name kept as an alias
        self.assertEqual((k.stock_updated_on, k.inventory_status), (None, "Inventory Pending"))

    def test_three_day_rule(self):
        t = dt.date(2026, 11, 18)
        self.assertEqual(bucket(dt.date(2026, 11, 15), t), "fresh")
        self.assertEqual(bucket(dt.date(2026, 11, 14), t), "stale")
        self.assertEqual(bucket(None, t), "never")

    def test_stock_sync_filter(self):
        def ids(v):
            rows = self.c.get(f"/api/distributors/?preset=last_90d&stock_sync={v}").json()["data"]["rows"]
            return {r["id"] for r in rows}

        self.assertEqual(ids("fresh"), {self.w["d1"].id})
        self.assertEqual(ids("stale"), {self.w["d2"].id})
        self.assertIn(self.d3.id, ids("never"))
        row = next(r for r in self.c.get("/api/distributors/?preset=last_90d").json()["data"]["rows"]
                   if r["id"] == self.w["d1"].id)
        self.assertEqual((row["stock_sync_status"], row["stock_upload_mode"]), ("fresh", "Manually"))
