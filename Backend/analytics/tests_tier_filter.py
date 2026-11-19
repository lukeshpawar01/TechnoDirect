"""Tier filter (Executive Overview): orders of retailers in the chosen BlueOrigin tier(s); "None" = not in BlueOrigin."""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from analytics.filters import parse_filters
from warehouse.models import Order, Retailer


class TierFilterTests(TestCase):
    def setUp(self):
        from django.utils import timezone

        from accounts.models import User

        self.user = User.objects.create_superuser(email="admin@test.local", password="x-Strong-pass1")
        now = timezone.now()
        for i, tier in enumerate(["Gold", "Platinum", ""]):
            r = Retailer.objects.create(name=f"R{i}", tier=tier)
            Order.objects.create(source_id=f"o{i}", display_id=str(i), split_group=f"c{i}", retailer=r,
                                 status="delivered", payment_status="captured", gross_value=Decimal(100 * (i + 1)),
                                 units=1, placed_at=now, placed_date=timezone.localtime(now).date())

    def orders(self, tier):
        from rest_framework.request import Request

        req = Request(APIRequestFactory().get("/api/overview/", {"tier": tier}))
        req.user = self.user
        return sorted(o.retailer.name for o in parse_filters(req).orders(qualifying=False))

    def test_tiers(self):
        self.assertEqual(self.orders("Gold"), ["R0"])
        self.assertEqual(self.orders("gold,platinum"), ["R0", "R1"])
        self.assertEqual(self.orders("None"), ["R2"])
        self.assertEqual(self.orders(""), ["R0", "R1", "R2"])


class TerritoryNarrowFilterTests(TestCase):
    """A filter finer than the grouping (one distributor while grouped by region) scopes the target too."""

    def test_narrower(self):
        from types import SimpleNamespace as NS

        from analytics.views.distributors import TerritoryView as T

        f = lambda **k: NS(**{"regions": [], "rsms": [], "states": [], "asms": [], "distributors": [], "retailers": [], **k})  # noqa: E731
        self.assertTrue(T.narrower_filter(f(distributors=[1]), "region"))
        self.assertTrue(T.narrower_filter(f(asms=[1]), "state"))
        self.assertFalse(T.narrower_filter(f(regions=[1]), "region"))  # same level: the region's own target
        self.assertFalse(T.narrower_filter(f(regions=[1]), "asm"))  # wider filter: ASM targets as they are
        self.assertFalse(T.narrower_filter(f(), "region"))
