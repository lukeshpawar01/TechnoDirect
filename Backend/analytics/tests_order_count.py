"""Order counts follow the finance Order Tracking sheet: every TD order once, so a cart split across two distributors
is two orders on the tracker basis (user, 2026-11-27) and one cart on the net basis."""
import datetime as dt
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from warehouse.models import Distributor, Order


class OrderCountTests(TestCase):
    def setUp(self):
        a = Distributor.objects.create(code="A", name="A")
        b = Distributor.objects.create(code="B", name="B")
        day = dt.date(2026, 10, 10)
        at = timezone.make_aware(dt.datetime.combine(day, dt.time(11)))
        # one cart split across two distributors (two TD orders, two sheet rows) + one ordinary order
        for sid, d, grp in (("o1", a, "cart1"), ("o2", b, "cart1"), ("o3", a, "o3")):
            Order.objects.create(source_id=sid, display_id=sid.upper(), split_group=grp, distributor=d, status="delivered",
                                 payment_status="captured", gross_value=Decimal(1000), units=1, placed_date=day, placed_at=at)

    def count(self):
        from analytics.metrics import agg_orders

        return agg_orders(Order.objects.all())["orders"]

    @override_settings(SALES_BASIS="tracker")
    def test_tracker_basis_counts_each_td_order_like_the_sheet(self):
        self.assertEqual(self.count(), 3)

    @override_settings(SALES_BASIS="net")
    def test_net_basis_counts_carts(self):
        self.assertEqual(self.count(), 2)
