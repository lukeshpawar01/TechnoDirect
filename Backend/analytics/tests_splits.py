"""Split (multi-distributor) carts: detection from consecutive orders, finance tracker override, cart-level counts."""
import datetime as dt
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from masters.splits import mark_split_carts
from warehouse.models import DistributorSettlement, Order

from .tests import make_world


class SplitCartTests(TestCase):
    def setUp(self):
        self.w = make_world()  # orders 1, 2 (ret1/Heera, different days), 3 (ret2/Anand)
        self.day = dt.date.today() - dt.timedelta(days=5)
        placed = timezone.make_aware(dt.datetime.combine(self.day, dt.time(6, 30)))

        def order(n, dist, ret=None):
            return Order.objects.create(
                source_id=f"s{n}", display_id=str(n), split_group=f"s{n}", retailer=ret or self.w["ret1"],
                distributor=dist, status="delivered", payment_status="captured", gross_value=Decimal(1000),
                placed_at=placed, placed_date=self.day)

        # one cart split between Heera and Anand (consecutive ids, same retailer, same day)
        self.a, self.b = order(500, self.w["d1"]), order(501, self.w["d2"])
        # same retailer, same day, consecutive, but SAME distributor -> two separate orders
        order(600, self.w["d1"])
        order(601, self.w["d1"])
        # consecutive ids of different retailers -> not a cart
        order(700, self.w["d1"])
        order(701, self.w["d2"], ret=self.w["ret2"])

    def test_rule_marks_only_true_carts(self):
        rep = mark_split_carts()
        self.assertEqual((rep["carts"], rep["orders"]), (1, 2))
        a, b = Order.objects.get(id=self.a.id), Order.objects.get(id=self.b.id)
        self.assertTrue(a.is_split and b.is_split)
        self.assertEqual(a.split_group, b.split_group)
        self.assertEqual(a.split_group, "cart:500")
        self.assertFalse(Order.objects.get(display_id="600").is_split)
        self.assertFalse(Order.objects.get(display_id="700").is_split)
        # cart-level: the split cart is one retailer order
        self.assertEqual(Order.objects.filter(display_id__in=["500", "501"]).values("split_group").distinct().count(), 1)

    def test_finance_tracker_overrules_the_rule(self):
        def srow(ref, multi):
            o = Order.objects.get(display_id=ref)
            DistributorSettlement.objects.create(order_ref=ref, order=o, distributor=o.distributor, order_date=self.day,
                                                 order_value=1000, payable=1000, multi_distributor=multi)

        # finance says 500/501 are NOT a split cart; 600/601 ARE (one part reassigned to the same distributor)
        srow("500", False)
        srow("501", False)
        srow("600", True)
        srow("601", True)
        mark_split_carts()
        self.assertFalse(Order.objects.get(display_id="500").is_split)
        self.assertEqual(Order.objects.get(display_id="500").split_group, "s500")  # reset to its own order
        self.assertTrue(Order.objects.get(display_id="600").is_split)
        self.assertEqual(Order.objects.get(display_id="601").split_group, "cart:600")
