"""Monthly Business Review: scorecard (like-for-like windows, targets, projection), the path to the sales goal,
tech adherence, carry-forward and access."""
import datetime as dt
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User
from accounts.testing import jwt_login
from analytics.filters import system_filters
from analytics.mbr import path_to_goal, scorecard
from masters.mbr import adherence, carry_forward, tech_summary
from masters.models import MbrItem, MbrReview
from warehouse.models import Distributor, Order, Region, Retailer, Target

D = dt.date


@override_settings(SALES_BASIS="net")
class MbrScorecardTests(TestCase):
    def setUp(self):
        self.region = Region.objects.create(code="S", name="South")
        self.d = Distributor.objects.create(code="D", name="Dist", region=self.region)
        self.n = 0
        # a: ordered Sep + Oct + Nov; b: new in Oct; c: KYC in Oct, never ordered
        self.a = self._ret("a", D(2026, 9, 5))
        self.b = self._ret("b", D(2026, 10, 3))
        self.c = self._ret("c", None, signed=D(2026, 10, 2))
        self._order(self.a, D(2026, 9, 5), 1000)
        self._order(self.a, D(2026, 10, 2), 2000)
        self._order(self.b, D(2026, 10, 3), 3000)
        self._order(self.b, D(2026, 10, 20), 500)   # after day 10: outside the like-for-like window
        self._order(self.a, D(2026, 11, 4), 4000)
        self._order(self.a, D(2026, 11, 8), 1000)
        self._order(self.b, D(2026, 11, 9), 600, status="cancelled", qualifying=False)
        for scope, sid in (("overall", None), ("region", self.region.id)):
            Target.objects.create(month=D(2026, 11, 1), scope_type=scope, scope_id=sid, metric="sales",
                                  value=Decimal(15000), effective_from=D(2026, 10, 25))
        self.f = system_filters(today=D(2026, 11, 10))

    def _ret(self, name, first, signed=D(2026, 8, 1)):
        return Retailer.objects.create(name=name, kyc_status="approved", distributor=self.d, first_order_date=first,
                                       signed_up_at=timezone.make_aware(dt.datetime.combine(signed, dt.time(10))))

    def _order(self, r, day, v, status="delivered", qualifying=True):
        self.n += 1
        at = timezone.make_aware(dt.datetime.combine(day, dt.time(12)))
        Order.objects.create(source_id=f"o{self.n}", display_id=str(self.n), split_group=f"c{self.n}", retailer=r,
                             distributor=self.d, region=self.region, status=status, payment_status="captured",
                             is_qualifying=qualifying, gross_value=Decimal(v), units=2, placed_date=day, placed_at=at,
                             delivered_at=at + dt.timedelta(days=2) if status == "delivered" else None)

    def test_month_in_progress_is_like_for_like(self):
        c = scorecard(self.f, D(2026, 11, 1))
        self.assertTrue(c["partial"])
        self.assertEqual(c["compare"]["prev"], "1–10 Oct 2026")
        rows = {r["key"]: r for r in c["rows"]}
        self.assertEqual((rows["sales"]["value"], rows["sales"]["prev"]), (5000.0, 5000.0))  # Oct 20 order excluded
        self.assertEqual(rows["sales"]["mom_pct"], 0.0)
        # target 15,000; 5,000 in 10 of 30 days -> projected 15,000 = 100%
        self.assertEqual((rows["sales"]["target"], rows["sales"]["achievement_pct"]), (15000.0, 33.33))
        self.assertEqual((rows["sales"]["projected"], rows["sales"]["projected_pct"]), (15000.0, 100.0))
        self.assertEqual(rows["sales"]["status"], "good")
        self.assertEqual(rows["active_retailers"]["value"], 1)
        self.assertEqual(rows["retention_pct"]["value"], 50.0)  # a of {a, b} active in October
        self.assertAlmostEqual(rows["cancel_pct"]["value"], 10.71, places=1)  # 600 / 5,600
        self.assertEqual(rows["delivery_days"]["value"], 2.0)
        self.assertEqual(len(rows["sales"]["trend"]), 12)
        self.assertEqual(c["territory"]["region"][0]["achievement_pct"], 33.33)

    def test_finished_month_and_product_metrics(self):
        c = scorecard(self.f, D(2026, 10, 1))
        self.assertFalse(c["partial"])
        rows = {r["key"]: r for r in c["rows"]}
        self.assertEqual((rows["sales"]["value"], rows["sales"]["prev"]), (5500.0, 1000.0))
        self.assertEqual((rows["new_retailers"]["value"], rows["repeat_retailers"]["value"]), (1, 1))
        self.assertEqual(rows["kyc_new"]["value"], 1)          # c signed up in October
        self.assertEqual(rows["kyc_to_order_pct"]["value"], 0.0)
        self.assertAlmostEqual(rows["adoption_pct"]["value"], 66.67, places=1)  # 2 of 3 KYC
        self.assertEqual(rows["ants"]["value"], 1)
        self.assertAlmostEqual(rows["adoption_pct"]["mom_pct"], 66.67 - 50.0, places=1)  # percentage points
        self.assertEqual(c["movers"]["up"][0]["change"], 4500.0)

    def test_path_to_goal(self):
        c = scorecard(self.f, D(2026, 11, 1))
        p = path_to_goal(self.f, c, 110000)
        # base = October (latest complete): 5,500 from 2 retailers; spend over Sep-Oct = 6,500 / 3 retailer-months
        self.assertEqual((p["base_month"], p["base_sales"], p["active_retailers"]), ("2026-10", 5500.0, 2))
        self.assertEqual(p["retailers_needed"], 51)          # ceil(110,000 / 2,166.67)
        # the goal applies to every month: October needs 20x its sales, with no deadline
        self.assertAlmostEqual(p["growth_needed_pct"], round((110000 / 5500 - 1) * 100, 1))
        octo = next(x for x in p["months"] if x["month"] == "2026-10")
        self.assertEqual((octo["goal_pct"], octo["short"]), (5.0, 104500.0))
        self.assertEqual(p["months_at_goal"], 0)
        self.assertEqual(p["scenarios"][0]["extra_retailers"], 49)


class MbrTechTests(TestCase):
    def test_adherence_states(self):
        today = D(2026, 11, 20)

        def mk(**k):
            return MbrItem(month=D(2026, 11, 1), section="tech", kind="feature", title="t", **k)

        self.assertEqual(adherence(mk(planned_date=D(2026, 11, 10), status="done", done_date=D(2026, 11, 9)), today),
                         {"state": "on_time", "slip_days": 0})
        self.assertEqual(adherence(mk(planned_date=D(2026, 11, 10), status="done", done_date=D(2026, 11, 15)), today),
                         {"state": "late", "slip_days": 5})
        self.assertEqual(adherence(mk(planned_date=D(2026, 11, 10), status="in_progress"), today),
                         {"state": "overdue", "slip_days": 10})
        self.assertEqual(adherence(mk(planned_date=D(2026, 11, 25), revised_date=D(2026, 12, 5), status="in_progress"),
                                   today), {"state": "slipping", "slip_days": 10})
        items = [mk(planned_date=D(2026, 11, 10), status="done", done_date=D(2026, 11, 9)),
                 mk(planned_date=D(2026, 11, 10), status="in_progress"),
                 mk(planned_date=D(2026, 12, 10), status="planned")]   # due next month: not measured yet
        s = tech_summary(items, D(2026, 11, 1), today)
        self.assertEqual((s["on_time"], s["overdue"], s["adherence_pct"]), (1, 1, 50.0))

    def test_carry_forward_once(self):
        oct_, nov = D(2026, 10, 1), D(2026, 11, 1)
        MbrItem.objects.create(month=oct_, section="growth", kind="action", title="open", status="in_progress")
        MbrItem.objects.create(month=oct_, section="growth", kind="action", title="done", status="done")
        MbrItem.objects.create(month=oct_, section="other", kind="win", title="note", status="planned")
        MbrReview.objects.create(month=oct_, goal_monthly_sales=Decimal(120000000))
        self.assertEqual(carry_forward(nov, "x"), 1)
        self.assertEqual(carry_forward(nov, "x"), 0)
        self.assertEqual(MbrItem.objects.get(month=nov).title, "open")
        self.assertEqual(MbrReview.objects.get(month=nov).goal_monthly_sales, Decimal(120000000))


class MbrApiTests(TestCase):
    def setUp(self):
        roles = {"Business Head": ["view_mbr", "manage_mbr"], "Regional Manager": ["view_mbr"], "ASM": ["view_overview"]}
        for (name, perms), email in zip(roles.items(), ("bh@test.local", "rm@test.local", "asm@test.local")):
            role = Role.objects.get_or_create(name=name)[0]
            role.permissions = perms
            role.save()
            User.objects.create_user(email=email, password="x-Strong-pass1", role=role, scope_all=True)

    def client_for(self, email):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Bearer " + jwt_login(c, email, "x-Strong-pass1")["access"])
        return c

    def test_access_and_edit(self):
        self.assertEqual(self.client_for("asm@test.local").get("/api/masters/mbr/").status_code, 403)
        rm = self.client_for("rm@test.local")
        r = rm.get("/api/masters/mbr/?month=2026-10")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["can_edit"])
        self.assertEqual(rm.post("/api/masters/mbr/items/?month=2026-10", {"section": "growth", "title": "x"},
                                 format="json").status_code, 403)
        bh = self.client_for("bh@test.local")
        r = bh.post("/api/masters/mbr/items/?month=2026-10", {"section": "growth", "kind": "bottleneck",
                                                              "title": "Credit", "team": "finance", "status": "blocked"},
                    format="json")
        self.assertEqual(r.status_code, 201, r.content)
        iid = r.json()["id"]
        self.assertEqual(bh.post("/api/masters/mbr/items/?month=2026-10", {"section": "growth", "title": "x",
                                                                           "team": "nope"}, format="json").status_code, 400)
        r = bh.patch(f"/api/masters/mbr/items/{iid}/", {"status": "done"}, format="json")
        self.assertEqual(r.json()["status"], "done")
        self.assertIsNotNone(r.json()["done_date"])
        r = bh.put("/api/masters/mbr/?month=2026-10", {"went_well": "East beat target",
                                                      "goal_monthly_sales": "10,00,00,000", "goal_by": "2027-03"},
                   format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["review"]["goal_by"], "2027-03")
        self.assertEqual(r.json()["review"]["goal_monthly_sales"], 100000000.0)
        self.assertEqual(bh.put("/api/masters/mbr/?month=2099-01", {}, format="json").status_code, 400)
        self.assertEqual(bh.delete(f"/api/masters/mbr/items/{iid}/").status_code, 204)
        self.assertEqual(rm.get("/api/mbr/?month=2026-10").status_code, 200)


class ProductDecisionTests(TestCase):
    """The MBR product calls: scale / defend / fix / watch and the decision cards."""

    def _cat(self, name, sales, prev, share, prev_share, role, oos=None):
        from .metrics import delta_pct
        return {"key": name.lower(), "name": name, "sales": sales, "prev_sales": prev, "change": sales - prev,
                "share_pct": share, "prev_share_pct": prev_share, "share_change_pp": round(share - prev_share, 1),
                "mom_pct": delta_pct(sales, prev), "top_style": "X1", "role": role, "oos_value": oos}

    def test_calls_and_decisions(self):
        from .mbr_products import _call, _decisions
        # TD 100 -> 130 (+30%); A grows slower and loses share with lots of demand at zero stock; B grows fast
        a = self._cat("A", 90, 80, 69.2, 80.0, "defend", oos=20)
        b = self._cat("B", 40, 20, 30.8, 20.0, "rising", oos=1)
        for c in (a, b):
            c["call"] = _call(c)
        self.assertEqual((a["call"], b["call"]), ("fix", "scale"))  # 20/90 = 22% >= 15% and losing share
        a2 = dict(a, oos_value=5)
        self.assertEqual(_call(a2), "defend")  # stock-outs too small to blame
        self.assertEqual(_call(dict(b, oos_value=30)), "scale")  # growing: never "fix"

        pulse = {"new_launch_share_pct": 12.0, "new_launch_sales": 15.6, "new_launches_selling": 3, "new_launches": 4}
        tail = {"styles": 3, "of_styles": 20, "sales": 13.0, "share_pct": 10.0}
        stock = {"lines": 4, "units": 50, "top_styles": [{"style": "X1", "units": 30}]}
        d = {x["kind"]: x for x in _decisions([a, b], pulse, tail, stock, 21.0, 30.0, 130, 50)}
        self.assertEqual(d["scale"]["title"], "Scale B")
        self.assertEqual(d["scale"]["value"], 20)
        self.assertEqual(d["fix"]["value"], 21.0)
        self.assertIn("80.0% to 69.2%", d["defend"]["reason"])
        self.assertAlmostEqual(d["defend"]["value"], (80.0 - 69.2) / 100 * 130, places=1)
        self.assertNotIn("watch", d)  # fewer than 10 tail styles: no card
        self.assertTrue(d["launch"]["good"])


class ExecutiveSummaryTests(TestCase):
    def test_bridge_adds_up(self):
        from .mbr_summary import bridge
        rows = {"sales": {"value": 130.0, "prev": 100.0}, "active_retailers": {"value": 12, "prev": 10},
                "new_retailers": {"value": 4}}
        b = bridge(rows)
        steps = {s["key"]: s["value"] for s in b["steps"]}
        self.assertEqual(steps["new"], 40.0)    # 4 new x last month's 10 per retailer
        self.assertEqual(steps["base"], -20.0)  # 8 repeat vs 10 last month
        self.assertAlmostEqual(sum(steps.values()), b["change"])
        self.assertEqual(b["change"], 30.0)

    def test_summary_on_a_scorecard(self):
        from .mbr_summary import executive_summary
        S = MbrScorecardTests("test_month_in_progress_is_like_for_like")
        S.setUp()
        from .mbr import path_to_goal
        card = scorecard(S.f, D(2026, 11, 1))
        card["path"] = path_to_goal(S.f, card, 100000)
        out = executive_summary(card)
        self.assertEqual(out["insights"][0]["area"], "sales")
        self.assertAlmostEqual(sum(s["value"] for s in out["bridge"]["steps"]), out["bridge"]["change"], places=2)
        self.assertTrue(any(d["area"] == "adoption" for d in out["decisions"]))

    def test_leaders_windows(self):
        S = MbrScorecardTests("test_month_in_progress_is_like_for_like")
        S.setUp()
        L = scorecard(S.f, D(2026, 11, 1))["products"]["leaders"]
        self.assertEqual(L["windows"], [30, 60])
        self.assertEqual((L["30"]["from"], L["30"]["to"]), ("2026-10-12", "2026-11-10"))  # 30 days to as-of (today 10 Nov)
        self.assertEqual(L["30"]["prev_to"], "2026-10-11")
        self.assertEqual(L["60"]["from"], "2026-09-12")


class SalesAsksTests(TestCase):
    def test_placeholder_asm_and_asks_run(self):
        from warehouse.models import Asm
        from .mbr import path_to_goal
        from .mbr_sales import _placeholder, sales_asks
        self.assertTrue(_placeholder(Asm(name="Zealous", emp_id=""), "Zealous Ventures"))
        self.assertFalse(_placeholder(Asm(name="Gururaj", emp_id="E1"), "Heera Exports Inc"))
        S = MbrScorecardTests("test_month_in_progress_is_like_for_like")
        S.setUp()
        card = scorecard(S.f, D(2026, 11, 1))
        path = path_to_goal(S.f, card, 100000)
        out = sales_asks(S.f, card, path)
        kinds = {a["kind"] for a in out["asks"]}
        self.assertIn("stretch", kinds)      # the region's biggest distributor gets a next-month target
        self.assertNotIn("no_asm", kinds)    # no ASM, but under ₹20k/month and <20 never-ordered: too small to flag
        st = next(a for a in out["asks"] if a["kind"] == "stretch")
        self.assertGreater(st["value"], 0)   # target is above today's pace


class FinanceAsksTests(TestCase):
    def test_finance_asks_without_settlement_or_incentive_data(self):
        from .mbr_finance import finance_asks
        S = MbrScorecardTests("test_month_in_progress_is_like_for_like")
        S.setUp()
        card = scorecard(S.f, D(2026, 11, 1))
        out = finance_asks(S.f, card)["asks"]
        self.assertEqual([a["kind"] for a in out], ["incentives"])  # no settlement rows: only the incentive ask
        self.assertIn("Approve", out[0]["title"])


class MarketingAsksTests(TestCase):
    def test_campaigns_are_sized(self):
        from .mbr import path_to_goal
        from .mbr_marketing import marketing_asks
        S = MbrScorecardTests("test_month_in_progress_is_like_for_like")
        S.setUp()
        card = scorecard(S.f, D(2026, 11, 1))
        card["path"] = path_to_goal(S.f, card, 100000)
        out = marketing_asks(S.f, card)["asks"]
        kinds = {a["kind"] for a in out}
        self.assertIn("kyc_never", kinds)   # retailer c: KYC done, never ordered, not warm
        a = next(x for x in out if x["kind"] == "kyc_never")
        self.assertEqual((a["audience"], a["rate_pct"]), (1, 2))


@override_settings(SALES_BASIS="net")
class GrowthDriversTests(TestCase):
    def test_tiers_add_up_to_td(self):
        from .mbr_growth import TIERS, growth_drivers
        S = MbrScorecardTests("test_month_in_progress_is_like_for_like")
        S.setUp()
        g = growth_drivers(S.f, scorecard(S.f, D(2026, 11, 1)))
        self.assertEqual([t["tier"] for t in g["tiers"]], TIERS)
        self.assertAlmostEqual(sum(t["sales"] for t in g["tiers"]), g["total"], places=2)
        self.assertEqual(g["total"], 5000.0)  # like for like: 1-10 Nov (the fixture's in-progress window)
        self.assertEqual(g["tiers"][-1]["tier"], "Not in BlueOrigin")  # fixture retailers have no BlueOrigin tier
        self.assertEqual(g["tiers"][-1]["retailers"], 1)
