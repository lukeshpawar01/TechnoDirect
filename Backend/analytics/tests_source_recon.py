"""Dashboard vs sources (analytics/source_recon.py): month totals vs the finance sheet, carts, merged rows,
cancellations taken from the sheet."""
import datetime as dt
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from warehouse.models import Distributor, DistributorSettlement, Order, Retailer

from . import source_recon as R

D = dt.date


class SourceReconTests(TestCase):
    def setUp(self):
        self.d = Distributor.objects.create(code="H", name="Heera")
        self.r = Retailer.objects.create(name="Shop", phone="9000000000", distributor=self.d)
        self.n = 0

    def order(self, disp, day, v, status="delivered", group=None):
        at = timezone.make_aware(dt.datetime.combine(day, dt.time(12)))
        return Order.objects.create(source_id=f"o{disp}", display_id=disp, split_group=group or f"g{disp}",
                                    retailer=self.r, distributor=self.d, status=status, payment_status="captured",
                                    gross_value=Decimal(v), units=1, placed_at=at, placed_date=day)

    def sheet(self, ref, day, v, fulfilment="delivered", order=None):
        return DistributorSettlement.objects.create(order_ref=ref, order=order, order_date=day, order_value=Decimal(v),
                                                    distributor=self.d, fulfilment=fulfilment)

    def test_months_carts_merged_rows_and_cancellations(self):
        day = D(2026, 10, 5)
        a = self.order("1", day, 1000)
        self.sheet("1", day, 1000, order=a)                       # matches
        b1, b2 = self.order("2", day, 600, group="cart"), self.order("3", day, 400, group="cart")
        self.sheet("2", day, 700, order=b1)                       # split cart: 700 + 300 = 1000 = 600 + 400
        self.sheet("3", day, 300, order=b2)
        m1, m2 = self.order("4", day, 500), self.order("5", day, 200)
        self.sheet("4", day, 700, order=m1)                       # finance merged #4 and #5 into one row
        c = self.order("6", day, 50, status="received")
        self.sheet("6", day, 50, fulfilment="cancelled", order=c)  # TD status stale, the sheet records the cancel
        res = R.tracker(D(2026, 11, 26))
        oct_ = next(m for m in res["months"] if m["month"] == "2026-10")
        self.assertTrue(oct_["ok"])
        self.assertEqual((oct_["sheet"], oct_["dashboard"]), (2750.0, 2750.0))
        self.assertEqual(res["value_diff"], [])                   # the split cart adds up
        self.assertEqual(res["only_td"], [])                      # #5 is explained by the merged row
        self.assertEqual(res["merged_in_sheet"][0]["merged_order"], "5")
        self.assertEqual(len(res["status_diff"]), 1)
        self.assertEqual(R.apply_sheet_cancellations(), 1)
        c.refresh_from_db()
        self.assertEqual(c.status, "cancelled")
        self.assertTrue(c.is_qualifying)                          # tracker basis: still counted, like the sheet

    def test_a_real_difference_is_reported(self):
        day = D(2026, 2, 2)
        o = self.order("14569", day, 88815)
        self.sheet("14569", day, 0, order=o)                      # blank value in the sheet
        res = R.tracker(D(2026, 11, 26))
        self.assertFalse(res["months"][0]["ok"])
        self.assertEqual(res["value_diff"][0]["diff"], 88815.0)
        codes = {c for c, *_ in R.issues({"tracker": res})}
        self.assertEqual(codes, {"sales_vs_sheet_month", "order_value_vs_sheet"})
