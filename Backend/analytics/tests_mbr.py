"""Monthly Business Review: scorecard (like-for-like windows, targets, projection), the path to the sales goal,
tech adherence, carry-forward and access."""
import datetime as dt
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User
from accounts.testing import jwt_login
from analytics.filters import system_filters
from analytics.mbr import default_goal_by, path_to_goal, scorecard
from masters.mbr import adherence, carry_forward, tech_summary
from masters.models import MbrItem, MbrReview
from warehouse.models import Distributor, Order, Region, Retailer, Target

D = dt.date


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
        p = path_to_goal(self.f, c, 110000, D(2027, 3, 1))
        # base = October (latest complete): 5,500 from 2 retailers; spend over Sep-Oct = 6,500 / 3 retailer-months
        self.assertEqual((p["base_month"], p["base_sales"], p["active_retailers"]), ("2026-10", 5500.0, 2))
        self.assertEqual(p["retailers_needed"], 51)          # ceil(110,000 / 2,166.67)
        self.assertEqual(p["months_left"], 5)
        self.assertAlmostEqual(p["monthly_growth_needed_pct"], round(((110000 / 5500) ** (1 / 5) - 1) * 100, 1))
        self.assertEqual(p["scenarios"][0]["extra_retailers"], 49)
        self.assertEqual(default_goal_by(D(2026, 11, 25)), D(2027, 3, 1))


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
