"""Internal distributors (Distributor.is_internal): their orders never count as sales; hidden from lists."""
import datetime as dt
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from analytics.derivations import run_all_derivations
from warehouse.models import Distributor, Order, Retailer


class InternalDistributorTests(TestCase):
    def test_orders_of_internal_distributors_do_not_count(self):
        real = Distributor.objects.create(code="R", name="Real")
        internal = Distributor.objects.create(code="I", name="Internal", is_internal=True)
        ret = Retailer.objects.create(name="Shop", phone="9876500000", distributor=real)
        day = dt.date(2026, 11, 5)
        for i, d in enumerate((real, internal)):
            Order.objects.create(source_id=f"o{i}", display_id=f"O{i}", split_group=f"c{i}", retailer=ret, distributor=d,
                                 status="delivered", payment_status="captured", gross_value=Decimal(100), units=1,
                                 placed_at=timezone.make_aware(dt.datetime.combine(day, dt.time(11))), placed_date=day)
        self.assertEqual(Order.objects.filter(is_qualifying=True).count(), 2)
        run_all_derivations()
        self.assertEqual(list(Order.objects.filter(is_qualifying=True).values_list("distributor__name", flat=True)), ["Real"])
        ret.refresh_from_db()
        self.assertEqual(ret.orders_count, 1)  # the internal order is not counted for the retailer either
