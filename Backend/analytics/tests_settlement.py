"""Distributor settlement: tracker import (parsing, payee mapping), buckets and endpoints."""
import csv
import datetime as dt
import os
import shutil
import tempfile
from decimal import Decimal

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from accounts.models import User
from accounts.testing import jwt_login
from masters.settlement import import_file, parse_date, parse_money
from warehouse.models import Distributor, DistributorSettlement

from .tests import make_world

HEAD = ["ORDER ID", "CUSTOMER NAME", " Distributor", "ORDER DATE", "DISPATCH DATE", "Month", "DESTINATION PLACE",
        "DESTINATION STATE", "PINCODE", "AWB NUMBER", "Multi Dist.Courier Amt", "DELIVERED DATE",
        "Multi Distributor Order", "Status", "ORDER VALUE", "Check Value from PayU", "Remark", "Customer Refund",
        "Refund Date", "Customer Settlement", "Settlement Date", "Loyalty Points", "Distributor Settlememnt",
        "Payment mode", "Transaction ID", "Payment Status", "Settlement status", "Distributor Settlement Date",
        "Received amount"]


def long(d):
    return d.strftime("%A, %B %d, %Y")


def row(oid, dist, ordered, delivered, status, value, refund, payable, pay, settle, paid_on=""):
    return {"ORDER ID": f"#{oid}", "CUSTOMER NAME": "Shop", " Distributor": dist, "ORDER DATE": long(ordered),
            "DISPATCH DATE": ordered.strftime("%d-%b-%Y"), "DESTINATION PLACE": "Town", "DESTINATION STATE": "Karnataka",
            "DELIVERED DATE": delivered.strftime("%d-%b-%Y") if delivered else "", "Status": status,
            "ORDER VALUE": f"₹{value:,.2f}", "Check Value from PayU": f"₹{value:,.2f}", "Customer Refund": refund,
            "Customer Settlement": f"₹{value * 0.98:,.2f}", "Distributor Settlememnt": payable, "Payment mode": "UPI",
            "Transaction ID": f"T{oid}", "Payment Status": pay, "Settlement status": settle,
            "Distributor Settlement Date": paid_on}


class ParseTests(SimpleTestCase):
    def test_dates(self):
        for raw, want in [("Sunday, February 01, 2026", "2026-02-01"), ("18 Sept 2026", "2026-09-18"),
                          ("Oct 8,2026", "2026-10-08"), ("23-July-2026", "2026-07-23"), ("15Jun-2026", "2026-06-15"),
                          ("30-jun_2026", "2026-06-30"), ("May 30.2026", "2026-05-30"),
                          ("june 12,2026 - june 13,2026", "2026-06-13"), ("4/24/2026", "2026-04-24")]:
            self.assertEqual(str(parse_date(raw)), want, raw)
        self.assertIsNone(parse_date("."))

    def test_money(self):
        self.assertEqual(parse_money("₹63,740.00"), Decimal("63740.00"))
        self.assertEqual(parse_money("₹150 & ₹4769", multi=True), Decimal(4919))
        self.assertEqual(parse_money("310, 132", multi=True), Decimal(442))
        self.assertEqual(parse_money("₹1,915. &₹2048", multi=True), Decimal(3963))
        self.assertIsNone(parse_money("#VALUE!"))
        self.assertIsNone(parse_money("15 Feb 1918"))


class SettlementTests(TestCase):
    def setUp(self):
        cache.clear()
        self.w = make_world()  # orders 1, 2 (Heera), 3 (Anand)
        today = dt.date.today()
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "tracker.csv")
        rows = [
            # settled, refund deducted from the payout
            row(1, "HEERA", today - dt.timedelta(days=20), today - dt.timedelta(days=17), "DELIVERED", 50000,
                "₹1,000.00", "₹49,000.00", "Approved", "Settled", (today - dt.timedelta(days=8)).strftime("%B %d, %Y")),
            # unknown sheet name -> mapped via its app order (Heera) and saved as alias; overdue (delivered 30 days ago)
            row(2, "HEERA MAIN", today - dt.timedelta(days=33), today - dt.timedelta(days=30), "DELIVERED", 30000,
                "₹0.00", "#VALUE!", "Not Approved", "Not Settled"),
            # in transit, not reviewed yet -> not yet due
            row(3, "Anand Sports", today - dt.timedelta(days=2), None, "IN TRANSIT", 20000, "₹0.00", "₹20,000.00", "", ""),
            # cancelled, unknown order
            row(99, "Anand Sports", today - dt.timedelta(days=3), None, "CANCELLED", 5000, "₹5,000.00", "₹0.00",
                "Cancelled", "Cancelled"),
        ]
        with open(self.path, "w", newline="", encoding="utf-8") as fh:
            wr = csv.DictWriter(fh, fieldnames=HEAD)
            wr.writeheader()
            wr.writerows(rows)
        self.rep = import_file(self.path)
        User.objects.create_superuser(email="s@test.local", password="x-Strong-pass1")
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION="Bearer " + jwt_login(self.c, "s@test.local", "x-Strong-pass1")["access"])

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_import(self):
        self.assertEqual(self.rep["rows"], 4)
        self.assertEqual(self.rep["orders_matched"], 3)
        s1 = DistributorSettlement.objects.get(order_ref="1")
        self.assertEqual((s1.distributor, s1.payable, s1.settlement_status), (self.w["d1"], Decimal(49000), "settled"))
        s2 = DistributorSettlement.objects.get(order_ref="2")
        self.assertEqual(s2.distributor, self.w["d1"])
        self.assertIn("HEERA MAIN", Distributor.objects.get(id=self.w["d1"].id).aliases)
        self.assertTrue(s2.payable_derived)
        self.assertEqual(s2.payable, Decimal(30000))
        self.assertEqual(DistributorSettlement.objects.get(order_ref="3").settlement_status, "pending")
        self.assertEqual(DistributorSettlement.objects.get(order_ref="99").payable, 0)
        import_file(self.path)  # rebuild, no duplicates
        self.assertEqual(DistributorSettlement.objects.count(), 4)

    def test_summary_buckets_and_filters(self):
        p = "preset=last_90d"
        k = self.c.get(f"/api/settlements/summary/?{p}").json()["data"]["kpis"]
        self.assertEqual((k["settled"], k["due"], k["overdue"], k["not_yet_due"]), (49000, 30000, 30000, 20000))
        self.assertEqual(k["payable"], 99000)
        self.assertEqual(k["refunds"], 6000)
        d = self.c.get(f"/api/settlements/distributors/?{p}").json()["data"]
        self.assertEqual(round(sum(r["payable"] for r in d["rows"])), 99000)
        heera = next(r for r in d["rows"] if r["id"] == self.w["d1"].id)
        self.assertEqual((heera["overdue_orders"], heera["settled"]), (1, 49000))
        k = self.c.get(f"/api/settlements/summary/?{p}&settlement_status=not_settled").json()["data"]["kpis"]
        self.assertEqual(k["orders"], 1)
        k = self.c.get(f"/api/settlements/summary/?{p}&pay_status=approved").json()["data"]["kpis"]
        self.assertEqual(k["settled"], 49000)
        k = self.c.get(f"/api/settlements/summary/?{p}&distributor={self.w['d2'].id}").json()["data"]["kpis"]
        self.assertEqual(k["orders"], 2)

    def test_payout_batches_are_whole_with_order_date_basis(self):
        # order 1 was placed 20 days ago and paid 8 days ago: a period of the last 10 days (order date basis) does not
        # contain its order, but its payout batch is in the period and must show in full
        t = dt.date.today()
        q = f"preset=custom&date_from={(t - dt.timedelta(days=10)).isoformat()}&date_to={t.isoformat()}"
        d = self.c.get(f"/api/settlements/summary/?{q}").json()["data"]
        self.assertEqual(d["kpis"]["settled"], 0)  # no order of the period is settled ...
        self.assertEqual([(p["date"], p["amount"]) for p in d["payouts"]],
                         [((t - dt.timedelta(days=8)).isoformat(), 49000)])  # ... but the batch paid in it is whole
        # clicking the batch (payout_date filter) lists all its orders, also the one ordered before the period
        k = self.c.get(f"/api/settlements/summary/?{q}&payout_date={(t - dt.timedelta(days=8)).isoformat()}").json()["data"]["kpis"]
        self.assertEqual((k["orders"], k["settled"]), (1, 49000))

    def test_payout_basis_and_order_list(self):
        paid = (dt.date.today() - dt.timedelta(days=8)).isoformat()
        k = self.c.get(f"/api/settlements/summary/?preset=last_30d&date_basis=payout").json()["data"]["kpis"]
        self.assertEqual((k["orders"], k["settled"]), (1, 49000))
        r = self.c.get(f"/api/settlements/orders/?preset=last_90d&payout_date={paid}").json()
        self.assertEqual([x["order_ref"] for x in r["results"]], ["1"])
        r = self.c.get("/api/settlements/orders/?preset=last_90d&view=overdue").json()
        self.assertEqual([x["order_ref"] for x in r["results"]], ["2"])
        self.assertTrue(r["results"][0]["overdue"])

    def test_distributor_statement_reconciles(self):
        d = self.c.get(f"/api/settlements/distributors/{self.w['d1'].id}/?preset=last_90d").json()["data"]
        b = d["bridge"]
        self.assertEqual(d["distributor"]["id"], self.w["d1"].id)
        self.assertEqual(round(b["order_value"] - b["cancelled"] - b["refunds"] + b["adjustments"]), round(b["payable"]))
        self.assertEqual(round(b["settled"] + b["remaining"]), round(b["payable"]))
        self.assertEqual((b["settled"], b["due"]), (49000, 30000))
        self.assertEqual([o["order_ref"] for o in d["open_orders"]], ["2"])
        self.assertTrue(d["open_orders"][0]["overdue"])
        self.assertEqual(d["payouts"][0]["cumulative"], 49000)
