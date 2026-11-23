"""Alerts (analytics/alerts.py) and the daily MIS email (analytics/daily_mis.py)."""
import datetime as dt
from decimal import Decimal

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from analytics import alerts, daily_mis
from analytics.filters import system_filters
from warehouse.models import Distributor, DistributorSettlement, Order, Region, Retailer, Target

D = dt.date
TODAY = D(2026, 11, 21)  # 20 days of November gone


class AlertTests(TestCase):
    def setUp(self):
        self.reg = Region.objects.create(code="S", name="South")
        self.d1 = Distributor.objects.create(code="A", name="Ahead", region=self.reg)
        self.d2 = Distributor.objects.create(code="B", name="Behind", region=self.reg)
        r = Retailer.objects.create(name="R", distributor=self.d1)
        for i, (d, v) in enumerate([(self.d1, 70000), (self.d2, 10000)]):
            at = timezone.make_aware(dt.datetime(2026, 11, 10, 12))
            Order.objects.create(source_id=f"o{i}", display_id=str(i), split_group=f"c{i}", retailer=r, distributor=d,
                                 status="delivered", payment_status="captured", is_qualifying=True,
                                 gross_value=Decimal(v), units=1, placed_at=at, placed_date=D(2026, 11, 10))
        for d in (self.d1, self.d2):  # 1.5 L target each: by the 20th ~1 L is expected
            Target.objects.create(month=D(2026, 11, 1), scope_type="distributor", scope_id=d.id, metric="sales",
                                  value=Decimal(150000), effective_from=D(2026, 11, 1))
        DistributorSettlement.objects.create(order_ref="X1", order_date=D(2026, 11, 1), distributor=self.d1,
                                             order_value=Decimal(1000), customer_refund=Decimal(250),
                                             settlement_status="settled")

    def test_behind_target_and_refunds(self):
        f = system_filters("mtd", today=TODAY)
        behind = alerts.behind_target(f, "distributor")
        self.assertEqual([b["name"] for b in behind], ["Behind"])  # 10k of ~1 L expected; Ahead has 70k (70% pace)
        self.assertEqual(alerts.refunds_pending(f).count(), 1)
        codes = {e["code"] for e in alerts.extra_exceptions(f)}
        self.assertIn("distributors_behind_target", codes)
        self.assertIn("refunds_pending", codes)

    @override_settings(MIS_RECIPIENTS="", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_mis_off_without_recipients(self):
        self.assertEqual(daily_mis.send(today=TODAY), [])
        self.assertFalse(daily_mis.due(TODAY))
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(MIS_RECIPIENTS="ops@technosport.in", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_mis_sends_once(self):
        self.assertTrue(daily_mis.due(TODAY))
        self.assertEqual(daily_mis.send(today=TODAY), ["ops@technosport.in"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("TechnoDirect MIS", mail.outbox[0].subject)
        self.assertIn("Behind", mail.outbox[0].alternatives[0][0])
        self.assertFalse(daily_mis.due(TODAY))  # already sent today
