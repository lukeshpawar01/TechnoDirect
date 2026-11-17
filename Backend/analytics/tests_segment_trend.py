"""Segment trends (analytics/segment_trend.py)."""
import datetime as dt
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from accounts.testing import jwt_login

from . import segment_trend as st
from .tests import make_world

D = dt.date


class BucketTests(TestCase):
    def test_fy_quarters_and_weeks(self):
        self.assertEqual(st.bucket_start(D(2026, 11, 17), "quarter"), D(2026, 10, 1))
        self.assertEqual(st.bucket_start(D(2026, 2, 3), "quarter"), D(2026, 1, 1))
        self.assertEqual(st.bucket_start(D(2026, 5, 9), "quarter"), D(2026, 4, 1))
        self.assertEqual(st.bucket_start(D(2026, 11, 17), "week"), D(2026, 11, 16))  # Monday
        self.assertEqual(st.label(D(2026, 10, 1), "quarter"), "Q3 FY27")

    def test_buckets_end_at_period_end_and_mark_partial(self):
        b = st.buckets(D(2026, 11, 17), "month", 3)
        self.assertEqual([x[0] for x in b], [D(2026, 9, 1), D(2026, 10, 1), D(2026, 11, 1)])
        self.assertEqual(b[-1][1], D(2026, 11, 17))
        self.assertTrue(b[-1][2])
        self.assertFalse(b[0][2])

    def test_lifecycle_flows(self):
        o = [(1, D(2026, 9, 5), "a", Decimal(1)), (1, D(2026, 10, 5), "b", Decimal(1)),   # new Sep, retained Oct
             (2, D(2026, 8, 5), "c", Decimal(1)), (2, D(2026, 10, 9), "d", Decimal(1)),   # reactivated Oct
             (3, D(2026, 9, 9), "e", Decimal(1))]                                          # lost in Oct
        b = st.buckets(D(2026, 10, 31), "month", 2)
        out = st.lifecycle(o, b, "month", signup_scope=None)
        self.assertEqual(out["new"], [2, 0])  # retailers 1 and 3 both first ordered in September
        self.assertEqual(out["retained"][1], 1)
        self.assertEqual(out["reactivated"][1], 1)
        self.assertEqual(out["lost"][1], 1)
        self.assertEqual(out["repeat"][1], 2)
        self.assertEqual(out["one_time"][1], 1)


class SegmentTrendEndpointTests(TestCase):
    def test_endpoint_matches_retention_monthly_movement(self):
        cache.clear()
        make_world()
        User.objects.create_superuser(email="t@test.local", password="x-Strong-pass1")
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Bearer " + jwt_login(c, "t@test.local", "x-Strong-pass1")["access"])
        for kind in ("rfm", "lifecycle"):
            for grain in ("day", "week", "month", "quarter"):
                r = c.get(f"/api/retailers/segment-trend/?kind={kind}&grain={grain}")
                self.assertEqual(r.status_code, 200, (kind, grain))
                d = r.json()["data"]
                self.assertEqual(len(d["buckets"]), st.DEFAULT_COUNT[grain])
                self.assertTrue(all(len(v) == len(d["buckets"]) for v in d["series"].values()))
        life = c.get("/api/retailers/segment-trend/?kind=lifecycle&grain=month").json()["data"]
        ret = c.get("/api/retention/?preset=mtd").json()["data"]["movement"]
        by_month = {m["month"][:7]: m for m in ret}
        for i, b in enumerate(life["buckets"][:-1]):  # completed months match the Retention page exactly
            m = by_month.get(b["start"][:7])
            if m:
                for k in ("new", "retained", "reactivated", "lost", "active"):
                    self.assertEqual(life["series"][k][i], m[k], (b["start"], k))
