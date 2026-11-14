import datetime as dt
from accounts.testing import jwt_login
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from warehouse.models import Distributor, Order, Region, Retailer, State

from .derivations import classify_months, run_all_derivations
from .filters import resolve_period

D = dt.date


class PresetDateMathTests(TestCase):
    today = D(2026, 11, 11)  # Wednesday

    def p(self, preset, today=None, **kw):
        return resolve_period(preset, today=today or self.today, **kw)

    def test_mtd_and_compare(self):
        p = self.p("mtd")
        self.assertEqual((p.start, p.end), (D(2026, 11, 1), D(2026, 11, 11)))
        self.assertEqual((p.cmp_start, p.cmp_end), (D(2026, 10, 1), D(2026, 10, 11)))

    def test_mtd_compare_clamps_short_month(self):
        p = self.p("mtd", today=D(2026, 3, 31))
        self.assertEqual((p.cmp_start, p.cmp_end), (D(2026, 2, 1), D(2026, 2, 28)))

    def test_qtd_uses_fy_quarters(self):
        p = self.p("qtd")
        self.assertEqual(p.start, D(2026, 10, 1))  # FY Q3 = Oct-Dec
        # same offset into the previous quarter
        self.assertEqual((p.cmp_start, p.cmp_end), (D(2026, 7, 1), D(2026, 8, 11)))
        self.assertIn("FY26-27 Q3", p.label)
        self.assertEqual(self.p("qtd", today=D(2027, 2, 5)).start, D(2027, 1, 1))  # Q4 = Jan-Mar

    def test_fytd_april_start(self):
        p = self.p("fytd")
        self.assertEqual((p.start, p.end), (D(2026, 4, 1), D(2026, 11, 11)))
        self.assertEqual((p.cmp_start, p.cmp_end), (D(2025, 4, 1), D(2025, 11, 11)))
        self.assertEqual(self.p("fytd", today=D(2027, 1, 15)).start, D(2026, 4, 1))
        self.assertEqual(self.p("fytd", today=D(2026, 3, 31)).start, D(2025, 4, 1))

    def test_prev_month_wtd_today_last12(self):
        p = self.p("prev_month")
        self.assertEqual((p.start, p.end, p.cmp_start, p.cmp_end),
                         (D(2026, 10, 1), D(2026, 10, 31), D(2026, 9, 1), D(2026, 9, 30)))
        w = self.p("wtd")
        self.assertEqual((w.start, w.cmp_start, w.cmp_end), (D(2026, 11, 9), D(2026, 11, 2), D(2026, 11, 4)))
        t = self.p("yesterday")
        self.assertEqual((t.start, t.cmp_start), (D(2026, 11, 10), D(2026, 11, 9)))
        l12 = self.p("last_12m")
        self.assertEqual((l12.start, l12.end, l12.cmp_start), (D(2025, 12, 1), self.today, D(2024, 12, 1)))

    def test_custom_and_prev_year(self):
        p = self.p("custom", date_from="2026-10-10", date_to="2026-10-19")
        self.assertEqual((p.cmp_start, p.cmp_end), (D(2026, 9, 30), D(2026, 10, 9)))
        y = self.p("mtd", compare="prev_year")
        self.assertEqual((y.cmp_start, y.cmp_end), (D(2025, 11, 1), D(2025, 11, 11)))
        self.assertIsNone(self.p("mtd", compare="none").cmp_start)


class NewPresetTests(TestCase):
    """Presets added for the grouped date menu (FY quarters, last week, rolling windows, all time)."""

    def p(self, preset, today):
        return resolve_period(preset, today=today)

    def test_last_week_is_previous_monday_to_sunday(self):
        for today in (dt.date(2026, 11, 14), dt.date(2026, 11, 16)):  # Saturday, Monday
            r = self.p("last_week", today)
            self.assertEqual(r.start.weekday(), 0)
            self.assertEqual((r.end - r.start).days, 6)
            self.assertLess(r.end, today - dt.timedelta(days=today.weekday()) + dt.timedelta(days=0))
            self.assertEqual(r.cmp_end, r.start - dt.timedelta(days=1))

    def test_running_quarter_compares_whole_previous_quarter(self):
        r = self.p("q3", dt.date(2026, 11, 14))
        self.assertEqual((r.start, r.end), (dt.date(2026, 10, 1), dt.date(2026, 11, 14)))
        self.assertEqual((r.cmp_start, r.cmp_end), (dt.date(2026, 7, 1), dt.date(2026, 9, 30)))

    def test_complete_quarter_compares_whole_previous_quarter(self):
        r = self.p("q2", dt.date(2026, 11, 14))
        self.assertEqual((r.start, r.end), (dt.date(2026, 7, 1), dt.date(2026, 9, 30)))
        self.assertEqual((r.cmp_start, r.cmp_end), (dt.date(2026, 4, 1), dt.date(2026, 6, 30)))

    def test_quarter_not_started_is_its_own_future_range(self):
        r = self.p("q4", dt.date(2026, 11, 14))  # FY26-27 Q4 = Jan-Mar 2027, not started: no fallback
        self.assertEqual((r.start, r.end), (dt.date(2027, 1, 1), dt.date(2027, 3, 31)))
        self.assertIn("not started", r.label)
        self.assertIsNone(r.cmp_start)

    def test_rolling_windows(self):
        for preset, n in (("last_7d", 7), ("last_30d", 30), ("last_90d", 90)):
            r = self.p(preset, dt.date(2026, 11, 14))
            self.assertEqual((r.end - r.start).days + 1, n)
            self.assertEqual((r.cmp_end - r.cmp_start).days + 1, n)
            self.assertEqual(r.cmp_end, r.start - dt.timedelta(days=1))

    def test_all_time_without_orders_uses_fallback_and_no_compare(self):
        r = self.p("all_time", dt.date(2026, 11, 14))
        self.assertEqual((r.start, r.end, r.cmp_start), (dt.date(2023, 9, 1), dt.date(2026, 11, 14), None))


class RetailerStatusTests(TestCase):
    def test_classification(self):
        months = [D(2025, 1, 1), D(2025, 2, 1), D(2025, 4, 1), D(2025, 5, 1)]
        got = classify_months(months, D(2025, 7, 1))
        self.assertEqual(got, [
            (D(2025, 1, 1), "new", True),
            (D(2025, 2, 1), "retained", True),
            (D(2025, 3, 1), "lost", False),
            (D(2025, 4, 1), "reactivated", True),
            (D(2025, 5, 1), "retained", True),
            (D(2025, 6, 1), "lost", False),
        ])  # July: inactive two months running -> no row

    def test_single_month_and_empty(self):
        self.assertEqual(classify_months([D(2025, 3, 1)], D(2025, 3, 1)), [(D(2025, 3, 1), "new", True)])
        self.assertEqual(classify_months([], D(2025, 3, 1)), [])


def make_world():
    """Two states, one distributor + retailer each, a few orders."""
    r1 = Region.objects.create(code="S", name="South")
    r2 = Region.objects.create(code="E", name="East")
    ka = State.objects.create(code="KA", name="Karnataka", region=r1)
    od = State.objects.create(code="OD", name="Odisha", region=r2)
    d1 = Distributor.objects.create(code="HEERA", name="Heera Exports", state=ka, region=r1)
    d2 = Distributor.objects.create(code="ANAND", name="Anand Sports", state=od, region=r2)
    ret1 = Retailer.objects.create(name="KA Shop", phone="9876543210", pincode="560001", state=ka, region=r1,
                                   distributor=d1, kyc_status="approved")
    ret2 = Retailer.objects.create(name="OD Shop", phone="9876500000", pincode="751001", state=od, region=r2,
                                   distributor=d2, kyc_status="approved")
    now = timezone.now()
    n = 0
    for ret, dist, days, val in ((ret1, d1, 2, 50000), (ret1, d1, 40, 30000), (ret2, d2, 3, 20000)):
        n += 1
        placed = now - dt.timedelta(days=days)
        Order.objects.create(source_id=f"o{n}", display_id=str(n), split_group=f"c{n}", retailer=ret,
                             distributor=dist, state=ret.state, region=ret.region, status="delivered",
                             payment_status="captured", medusa_payment_status="captured",
                             gross_value=Decimal(val), units=100,
                             placed_at=placed, placed_date=timezone.localtime(placed).date(),
                             shipped_at=placed + dt.timedelta(hours=30))
    run_all_derivations()
    return {"ka": ka, "od": od, "d1": d1, "d2": d2, "ret1": ret1, "ret2": ret2}


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class EndpointShapeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.w = make_world()
        self.admin = User.objects.create_superuser(email="admin@test.local", password="x-Strong-pass1")
        self.c = APIClient()
        tok = jwt_login(self.c, "admin@test.local", "x-Strong-pass1")["access"]
        self.c.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}")

    def test_new_presets_and_module_params_are_accepted(self):
        for preset in ("last_week", "q1", "q2", "q3", "q4", "last_7d", "last_30d", "last_90d", "all_time"):
            self.assertEqual(self.c.get(f"/api/overview/?preset={preset}").status_code, 200, preset)
        base = self.c.get("/api/orders/?preset=all_time").json()["count"]
        web = self.c.get("/api/orders/?preset=all_time&platform=web").json()["count"]
        self.assertLessEqual(web, base)
        for q in ("loyalty/?event_type=redeemed", "funnel/?has_account=true", "inventory/items/?size=XL",
                  "products/?cat_l1=men", "distributors/?stock_sync=never"):
            self.assertEqual(self.c.get(f"/api/{q}").status_code, 200, q)
        opts = self.c.get("/api/meta/filters/").json()
        for k in ("payment_modes", "platforms", "category_tree", "sizes"):
            self.assertIn(k, opts)

    def test_mom_trend_shape(self):
        r = self.c.get("/api/trends/mom/?months=6")
        self.assertEqual(r.status_code, 200, r.content)
        rows = r.json()["data"]["months"]
        self.assertEqual(len(rows), 6)
        for k in ("month", "sales", "pieces", "boxes", "sales_mom_pct", "pieces_mom_pct", "is_partial", "basis"):
            self.assertIn(k, rows[-1])
        self.assertEqual(sum(1 for x in rows if x["is_partial"]), 1 if rows[-1]["is_partial"] else 0)
        self.assertEqual(self.c.get("/api/trends/mom/?months=5").status_code, 400)

    def test_overview_shape(self):
        r = self.c.get("/api/overview/?preset=last_12m")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(set(body), {"data", "meta"})
        meta = body["meta"]
        for k in ("sales_basis", "as_of", "period", "freshness", "last_refresh_at", "next_refresh_at"):
            self.assertIn(k, meta)
        for k in ("from", "to", "label", "compare_from", "compare_to"):
            self.assertIn(k, meta["period"])
        d = body["data"]
        for k in ("kpis", "target", "daily_trend", "monthly", "order_funnel", "concentration",
                  "top_distributors", "top_states", "exceptions"):
            self.assertIn(k, d)
        for k in ("sales", "orders", "aov", "units_per_order", "realisation_per_unit", "active_retailers",
                  "new_retailers", "repeat_retailers", "active_distributors"):
            self.assertEqual(set(d["kpis"][k]), {"value", "compare", "delta_pct", "spark"})
            self.assertEqual(len(d["kpis"][k]["spark"]), 12)
        self.assertEqual(d["kpis"]["sales"]["value"], 100000.0)
        self.assertEqual(d["kpis"]["orders"]["value"], 3)
        self.assertEqual([s["status"] for s in d["order_funnel"]],
                         ["received", "confirmed", "shipped", "delivered", "cancelled"])

    def test_orders_summary_and_list_shapes(self):
        d = self.c.get("/api/orders/summary/?preset=last_12m").json()["data"]
        self.assertEqual(set(d), {"status_counts", "ageing", "tat", "cancellation_rate", "payment",
                                  "split_orders", "sla_breaches", "crm"})
        self.assertNotIn("refunds", d)
        lst = self.c.get("/api/orders/?preset=last_12m").json()
        self.assertEqual(set(lst), {"count", "next", "previous", "results"})
        self.assertEqual(lst["count"], 3)

    def test_detail_envelopes(self):
        d = self.c.get(f"/api/distributors/{self.w['d1'].id}/?preset=last_12m").json()
        self.assertEqual(set(d), {"data", "meta"})
        self.assertEqual(set(d["data"]["kpis"]["sales"]), {"value", "compare", "delta_pct", "spark"})
        self.assertEqual(d["data"]["kpis"]["sales"]["value"], 80000.0)
        oid = Order.objects.first().id
        o = self.c.get(f"/api/orders/{oid}/").json()
        self.assertEqual(set(o), {"data", "meta"})
        self.assertTrue({"at", "status", "note", "actor"} <= set(o["data"]["timeline"][0]))
        r = self.c.get(f"/api/retailers/{self.w['ret1'].id}/").json()
        self.assertEqual(set(r["data"]), {"profile", "monthly", "recent_orders"})

    def test_payment_block_null_without_payu(self):
        d = self.c.get("/api/orders/summary/").json()["data"]
        self.assertIsNone(d["payment"])

    def test_export_csv(self):
        r = self.c.get("/api/retailers/?export=csv&preset=last_12m")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r["Content-Type"])
