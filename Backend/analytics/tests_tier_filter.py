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


class GlobalTierFilterTests(TierFilterTests):
    """The tier filter is global: every retailer-level queryset built through dims_q follows it."""

    def filters(self, tier):
        from rest_framework.request import Request

        req = Request(APIRequestFactory().get("/api/funnel/", {"tier": tier}))
        req.user = self.user
        return parse_filters(req)

    def test_retailer_and_line_querysets(self):
        from accounts.scope import RETAILER_DIMS

        f = self.filters("Platinum")
        self.assertEqual(list(Retailer.objects.filter(f.dims_q(RETAILER_DIMS, retailer_field="id")).values_list("name", flat=True)), ["R1"])
        self.assertEqual([o.retailer.name for o in Order.objects.filter(f.dims_q(retailer_field="retailer_id"))], ["R1"])
        self.assertFalse(f.targets_comparable)
        self.assertTrue(self.filters("").targets_comparable)
        # distributor-level querysets (no retailer field) are not touched by the tier
        self.assertEqual(len(f.dims_q(retailer_field=None)), 0)


class ExpectedTdTests(TestCase):
    """Expected TD = BO purchase x tier benchmark, never below actual; offline-only distributors carry none."""

    def row(self, dist, tier, purchase, app, td=1):
        return {"distributor_id": dist, "tier": tier, "purchase": purchase, "app_sales": app, "td_retailer_id": td}

    def test_expected_and_gap(self):
        from analytics import blueorigin as bo

        bench = {t: {"share": 0.10, "cells": 5, "basis": "tier"} for t in bo.TIERS}
        rows = [self.row(1, "Gold", 1000, 20),   # below benchmark: expected 100, gap 80
                self.row(2, "Gold", 1000, 300),  # above: keeps its 300, no gap
                self.row(9, "Gold", 5000, 0)]    # offline-only distributor: no expected TD
        e = bo._expected(rows, bench, 1, off={9})
        self.assertEqual(e["td_actual"], 320)
        self.assertEqual(e["td_expected"], 400)
        self.assertEqual(e["gap"], 80)
        self.assertEqual(e["offline_only_bo"], 5000)

    def test_percentile(self):
        from analytics.blueorigin import _percentile

        self.assertEqual(_percentile([0, 0, 0.04, 0.08, 0.2], 0.75), 0.08)
        self.assertIsNone(_percentile([], 0.75))
