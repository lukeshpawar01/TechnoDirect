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
        self.assertEqual(set(d), {"status_counts", "ageing", "tat", "cancellation_rate", "payment", "order_payment_modes", "order_platforms",
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


class KycVerifiedFilterTests(TestCase):
    def setUp(self):
        cache.clear()
        self.w = make_world()
        self.admin = User.objects.create_superuser(email="kyc@test.local", password="x-Strong-pass1")
        self.c = APIClient()
        self.c.force_authenticate(self.admin)

    def test_kyc_verified_splits_retailers_and_funnel(self):
        from warehouse.models import Retailer

        total = self.c.get("/api/retailers/?preset=all_time").json()["count"]
        yes = self.c.get("/api/retailers/?preset=all_time&kyc_verified=true").json()["count"]
        no = self.c.get("/api/retailers/?preset=all_time&kyc_verified=false").json()["count"]
        self.assertEqual((yes, no), (Retailer.objects.filter(kyc_status="approved").count(),
                                     Retailer.objects.exclude(kyc_status="approved").count()))
        self.assertEqual(yes + no, total)
        stages = {s["key"]: s["count"] for s in self.c.get("/api/funnel/?preset=all_time&kyc_verified=false").json()["data"]["stages"]}
        self.assertEqual(stages["kyc_approved"], 0)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class GrowthJourneyTests(TestCase):
    """/growth/ and /distributors/insights/ (TD_DataDeck slides 28-63): the numbers must reconcile."""

    def setUp(self):
        cache.clear()
        reg = Region.objects.create(code="S", name="South")
        ka = State.objects.create(code="KA", name="Karnataka", region=reg)
        self.d1 = Distributor.objects.create(code="D1", name="Dist One", state=ka, region=reg)
        self.d2 = Distributor.objects.create(code="D2", name="Dist Two", state=ka, region=reg)
        rets = [Retailer.objects.create(name=f"R{i}", phone=f"98765000{i}0", pincode="560001", state=ka, region=reg,
                                        distributor=self.d1, kyc_status="approved") for i in range(3)]
        # r0: both years (like-for-like) and two distributors; r1: last year only (lapsed); r2: this year only (new)
        plan = [(rets[0], self.d1, D(2025, 11, 5), 100000, 10), (rets[0], self.d2, D(2026, 11, 5), 150000, 20),
                (rets[0], self.d1, D(2026, 10, 3), 50000, 5), (rets[1], self.d1, D(2025, 10, 7), 40000, 8),
                (rets[2], self.d2, D(2026, 9, 9), 60000, 12)]
        for n, (ret, dist, day, val, units) in enumerate(plan):
            placed = timezone.make_aware(dt.datetime.combine(day, dt.time(11)))
            Order.objects.create(source_id=f"g{n}", display_id=f"G{n}", split_group=f"gc{n}", retailer=ret,
                                 distributor=dist, state=ka, region=reg, status="delivered",
                                 payment_status="captured", medusa_payment_status="captured",
                                 gross_value=Decimal(val), units=units, placed_at=placed, placed_date=day,
                                 shipped_at=placed + dt.timedelta(hours=10))
        run_all_derivations()
        User.objects.create_superuser(email="g@test.local", password="x-Strong-pass1")
        self.c = APIClient()
        tok = jwt_login(self.c, "g@test.local", "x-Strong-pass1")["access"]
        self.c.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}")
        r = self.c.get("/api/growth/?preset=custom&date_from=2026-11-01&date_to=2026-11-14")
        self.assertEqual(r.status_code, 200, r.content)
        self.d = r.json()["data"]

    def test_rollups_match_monthly(self):
        total = sum(m["sales"] for m in self.d["monthly"])
        self.assertAlmostEqual(total, 400000)
        self.assertAlmostEqual(sum(q["sales"] for q in self.d["quarters"]), total)
        self.assertAlmostEqual(sum(y["sales"] for y in self.d["fy"]), total)
        self.assertAlmostEqual(self.d["monthly"][-1]["cum_sales"], total)
        self.assertEqual(self.d["headline"]["retailers"], 3)
        nov = next(m for m in self.d["monthly"] if m["month"] == "2026-11")
        self.assertAlmostEqual(nov["yoy_pct"], 50.0)  # 150K vs 100K same month last year

    def test_decomposition_multiplies_back_and_shares_sum_to_100(self):
        dec = self.d["decomposition"]
        self.assertTrue(dec["available"])
        f = {x["key"]: x for x in dec["factors"]}
        for side, sales in (("prev", 100000), ("cur", 150000)):
            prod = f["active_retailers"][side] * f["orders_per_retailer"][side] * f["aov"][side]
            self.assertAlmostEqual(prod, sales, delta=1)
        self.assertAlmostEqual(sum(x["share_pct"] for x in dec["factors"]), 100, delta=0.2)

    def test_bridge_reconciles(self):
        b = self.d["bridge"]  # Jun-Nov 2026 vs Jun-Nov 2025
        rebuilt = b["prev_total"] - b["lapsed"]["sales"] + b["like_for_like"]["change"] + b["new"]["sales"]
        self.assertAlmostEqual(rebuilt, b["cur_total"])
        self.assertEqual((b["like_for_like"]["retailers"], b["new"]["retailers"], b["lapsed"]["retailers"]), (1, 1, 1))

    def test_distributor_insights(self):
        r = self.c.get("/api/distributors/insights/?preset=custom&date_from=2026-09-01&date_to=2026-11-14")
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()["data"]
        self.assertEqual(d["multi_distributor"]["multi"], 1)  # r0 bought from both distributors
        self.assertEqual({x["name"] for x in d["trend"]["series"]}, {"Dist One", "Dist Two"})
        rows = self.c.get("/api/distributors/?preset=mtd").json()["data"]["rows"]
        self.assertIn("l3m_growth_pct", rows[0])


class RsmRollupTests(TestCase):
    """RSM = the ASM's RSM, else the RSM heading the region; filter, grouping and targets must agree."""

    def setUp(self):
        from warehouse.models import Asm, Rsm, Target

        cache.clear()
        south, east = Region.objects.create(code="S", name="South"), Region.objects.create(code="E", name="East")
        ka = State.objects.create(code="KA", name="Karnataka", region=south)
        od = State.objects.create(code="OD", name="Odisha", region=east)
        self.r_s = Rsm.objects.create(code="RS", name="Ravi South", region=south)
        self.r_e = Rsm.objects.create(code="RE", name="Esha East", region=east)
        a_s = Asm.objects.create(code="AS", name="Asha", region=south, rsm=self.r_s)
        # an ASM based in the South who reports to the East RSM: follows the reporting line, not the region
        a_x = Asm.objects.create(code="AX", name="Xavier", region=south, rsm=self.r_e)
        d1 = Distributor.objects.create(code="D1", name="D1", state=ka, region=south, asm=a_s)
        d2 = Distributor.objects.create(code="D2", name="D2", state=ka, region=south, asm=a_x)
        d3 = Distributor.objects.create(code="D3", name="D3", state=od, region=east)  # no ASM -> East RSM
        day = D(2026, 11, 5)
        for n, (dist, st, reg, asm, val) in enumerate([(d1, ka, south, a_s, 100), (d2, ka, south, a_x, 40),
                                                        (d3, od, east, None, 10)]):
            ret = Retailer.objects.create(name=f"R{n}", phone=f"9000000{n}00", state=st, region=reg, asm=asm,
                                          distributor=dist)
            placed = timezone.make_aware(dt.datetime.combine(day, dt.time(11)))
            Order.objects.create(source_id=f"o{n}", display_id=f"O{n}", split_group=f"c{n}", retailer=ret,
                                 distributor=dist, state=st, region=reg, asm=asm, status="delivered",
                                 payment_status="captured", gross_value=Decimal(val), units=1, placed_at=placed,
                                 placed_date=day)
        m = D(2026, 11, 1)
        for scope, sid, v in (("asm", a_s.id, 200), ("asm", a_x.id, 80), ("distributor", d3.id, 20)):
            Target.objects.create(month=m, scope_type=scope, scope_id=sid, value=v, effective_from=m)
        run_all_derivations()
        User.objects.create_superuser(email="r@test.local", password="x-Strong-pass1")
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION="Bearer " + jwt_login(self.c, "r@test.local", "x-Strong-pass1")["access"])
        self.q = "preset=custom&date_from=2026-11-01&date_to=2026-11-14"

    def test_grouping_targets_and_breakdown(self):
        d = self.c.get(f"/api/territory/?{self.q}&group_by=rsm").json()["data"]
        rows = {r["name"]: r for r in d["rows"]}
        self.assertEqual((rows["Ravi South"]["sales"], rows["Ravi South"]["target"]), (100, 200))
        # East = Xavier (reports to East) + the ASM-less East distributor
        self.assertEqual((rows["Esha East"]["sales"], rows["Esha East"]["target"]), (50, 100))
        self.assertEqual(rows["Esha East"]["asms"], 1)
        east = [b for b in d["breakdown"] if b["rsm_id"] == self.r_e.id]
        self.assertEqual({b["name"]: (b["sales"], b["target"]) for b in east},
                         {"Xavier": (40, 80), "Distributor-managed (no ASM)": (10, 20)})

    def test_filter_matches_grouping(self):
        k = self.c.get(f"/api/overview/?{self.q}&rsm={self.r_e.id}").json()["data"]["kpis"]["sales"]["value"]
        self.assertEqual(k, 50)
        t = self.c.get(f"/api/overview/?{self.q}&rsm={self.r_e.id}").json()["data"]["target"]["target"]
        self.assertEqual(t, 100)

    def test_achievement_counts_only_months_with_a_target(self):
        from warehouse.models import Asm

        a_s = Asm.objects.get(code="AS")
        ret = Retailer.objects.get(name="R0")
        day = D(2026, 10, 10)  # October has no target
        Order.objects.create(source_id="oct", display_id="OCT", split_group="coct", retailer=ret,
                             distributor=ret.distributor, state=ret.state, region=ret.region, asm=a_s,
                             status="delivered", payment_status="captured", gross_value=Decimal(1000), units=1,
                             placed_at=timezone.make_aware(dt.datetime.combine(day, dt.time(11))), placed_date=day)
        cache.clear()
        q = "preset=custom&date_from=2026-10-01&date_to=2026-11-14"
        rows = {r["name"]: r for r in self.c.get(f"/api/territory/?{q}&group_by=rsm").json()["data"]["rows"]}
        self.assertEqual(rows["Ravi South"]["sales"], 1100)
        self.assertEqual(rows["Ravi South"]["achievement_pct"], 50.0)  # Nov sales 100 / Nov target 200
        t = self.c.get(f"/api/overview/?{q}&rsm={self.r_s.id}").json()["data"]["target"]
        self.assertEqual((t["achieved"], t["target"], t["target_months"]), (100, 200, ["2026-11"]))


class AsmHandoverTests(TestCase):
    """A resignation / new joiner keeps history: orders stay with the ASM in charge on the order date."""

    def test_handover_splits_orders_by_date(self):
        from masters.services import assign_distributor_asm
        from warehouse.models import Asm

        from .derivations import attribute_orders_to_distributor_asm

        reg = Region.objects.create(code="S", name="South")
        old, new = Asm.objects.create(code="OLD", name="Imran"), Asm.objects.create(code="NEW", name="Valluru")
        d = Distributor.objects.create(code="V", name="Virat", region=reg, asm=old)
        for n, day in enumerate([D(2026, 9, 20), D(2026, 10, 9)]):
            Order.objects.create(source_id=f"h{n}", display_id=f"H{n}", split_group=f"h{n}", distributor=d, region=reg,
                                 status="delivered", payment_status="captured", gross_value=Decimal(100), units=1,
                                 placed_at=timezone.make_aware(dt.datetime.combine(day, dt.time(11))), placed_date=day)
        assign_distributor_asm(d, new, D(2026, 10, 1))
        attribute_orders_to_distributor_asm()
        d.refresh_from_db()
        self.assertEqual(d.asm_id, new.id)  # current ASM = whoever is in charge today
        self.assertEqual(Order.objects.get(source_id="h0").asm_id, old.id)  # September stays with the leaver
        self.assertEqual(Order.objects.get(source_id="h1").asm_id, new.id)
        self.assertEqual(attribute_orders_to_distributor_asm(), 0)  # idempotent


class DistributorNetworkTests(TestCase):
    """Distributors grouped by state with their period sales."""

    def test_network_by_state(self):
        cache.clear()
        reg = Region.objects.create(code="S", name="South")
        ka = State.objects.create(code="KA", name="Karnataka", region=reg)
        d = Distributor.objects.create(code="H", name="Heera", state=ka, region=reg)
        Distributor.objects.create(code="T", name="Never traded", state=ka, region=reg)
        day = D(2026, 11, 5)
        Order.objects.create(source_id="n1", display_id="N1", split_group="n1", distributor=d, state=ka, region=reg,
                             status="delivered", payment_status="captured", gross_value=Decimal(500), units=1,
                             placed_at=timezone.make_aware(dt.datetime.combine(day, dt.time(11))), placed_date=day)
        User.objects.create_superuser(email="n@test.local", password="x-Strong-pass1")
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Bearer " + jwt_login(c, "n@test.local", "x-Strong-pass1")["access"])
        data = c.get("/api/distributors/network/?preset=custom&date_from=2026-11-01&date_to=2026-11-14").json()["data"]
        self.assertEqual(data["summary"], {"states": 1, "distributors": 1, "selling": 1})
        self.assertEqual(data["states"][0]["distributors"][0]["sales"], 500)
