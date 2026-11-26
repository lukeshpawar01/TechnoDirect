"""P&L module: the workbook's formulas reproduced exactly, quarter handling, data checks, and access limited to the
Business Head role and the master admin."""
import datetime as dt
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Role, User
from accounts.testing import jwt_login
from masters.models import PnlQuarter
from masters.pnl import compute, growth, next_quarter, quarter_label, statement

# Cached values of TD_P&L_QoQ_Rev.xlsx (what Excel computed), per quarter: B / C / E / G columns
EXCEL = {
    "2025-07-01": {"net_revenue": 37954219, "cogs": 26567953.3, "gross_profit": 11386265.7, "gross_margin": 0.3,
                   "payment_gateway": 382154.15, "loyalty": 95538.5375, "cm1": 10908573.0125,
                   "cm1_pct": 0.2874139766253655, "cm2": 9508573.0125, "ebitda": 9408573.0125,
                   "op_margin": 0.2461983734181613},
    "2025-10-01": {"net_revenue": 52263486, "cogs": 36584440.2, "gross_profit": 15679045.8,
                   "payment_gateway": 526966.5, "loyalty": 131741.625, "cm1": 15020337.675, "cm2": 13620337.675,
                   "ebitda": 13449337.675, "op_margin": 0.25522187226322746},
    "2026-01-01": {"net_revenue": 63929080.6, "cogs": 44750356.42, "gross_profit": 19178724.18,
                   "payment_gateway": 643172.41, "loyalty": 160793.1025, "cm1": 18374758.6675,
                   "cm2": 16974758.6675, "ebitda": 16874758.6675, "op_margin": 0.26236757679795375},
    "2026-04-01": {"net_revenue": 73469129, "cogs": 51428390.3, "gross_profit": 22040738.7,
                   "payment_gateway": 746169.28, "loyalty": 186542.32, "cm1": 21108027.1, "cm1_pct": 0.28730471406568603,
                   "cm2": 19708027.1, "ebitda": 19608027.1, "op_margin": 0.2627825565265834},
}
# the sheet's QoQ growth columns (D / F / H) for value lines
EXCEL_GROWTH = {"2025-10-01": {"gross_revenue": 0.3789370074876853, "ebitda": 0.42947688848580323,
                               "returns": 0.6583868053109542},
                "2026-04-01": {"cm1": 0.1487512561095247, "ebitda": 0.16197377908367655}}


class PnlFormulaTests(TestCase):
    """The seed migration loaded the workbook's four quarters."""

    def test_every_line_matches_the_workbook(self):
        for start, expected in EXCEL.items():
            vals = compute(PnlQuarter.objects.get(quarter_start=start))
            for key, want in expected.items():
                self.assertAlmostEqual(float(vals[key]), want, places=4, msg=f"{start} {key}")

    def test_growth_like_the_sheet_with_its_two_fixes(self):
        data = {q["start"]: q for q in statement(today=dt.date(2026, 11, 19))["quarters"]}
        for start, expected in EXCEL_GROWTH.items():
            for key, want in expected.items():
                self.assertAlmostEqual(data[start]["growth"][key], want, places=9, msg=f"{start} {key}")
        # fix 1: loyalty growth is calculated (the sheet had a hard-coded 0 in D11)
        self.assertAlmostEqual(data["2025-10-01"]["growth"]["loyalty"], 0.3789370074876853, places=9)
        # fix 2: margins change in percentage points, not as a % of a %
        q1 = data["2026-04-01"]
        self.assertAlmostEqual(q1["growth"]["op_margin"], 0.2627825565265834 - 0.26236757679795375, places=12)
        self.assertIsNone(data["2025-07-01"]["growth"]["gross_revenue"])  # first quarter: nothing to compare with

    def test_quarters(self):
        self.assertEqual(quarter_label(dt.date(2025, 7, 1)), "Q2 (FY 25-26)")
        self.assertEqual(quarter_label(dt.date(2026, 1, 1)), "Q4 (FY 25-26)")
        self.assertEqual(quarter_label(dt.date(2026, 4, 1)), "Q1 (FY 26-27)")
        self.assertEqual(next_quarter(dt.date(2025, 10, 1)), dt.date(2026, 1, 1))
        self.assertEqual(next_quarter(dt.date(2026, 4, 1)), dt.date(2026, 7, 1))

    def test_missing_inputs_leave_dependent_lines_empty(self):
        q = PnlQuarter(quarter_start=dt.date(2026, 7, 1), tech_platform_cost=Decimal(800000))
        vals = compute(q)
        self.assertIsNone(vals["net_revenue"])
        self.assertIsNone(vals["ebitda"])
        q.gross_revenue, q.returns = Decimal(100), Decimal(0)
        self.assertEqual(compute(q)["gross_profit"], Decimal("30.00"))
        self.assertIsNone(compute(q)["cm2"])  # manpower not entered yet


class PnlApiTests(TestCase):
    def setUp(self):
        self.bh = Role.objects.get_or_create(name="Business Head")[0]
        self.bh.permissions = sorted(set(self.bh.permissions or []) | {"view_pnl", "manage_pnl", "view_overview"})
        self.bh.save()
        self.rm = Role.objects.get_or_create(name="Regional Manager", defaults={"permissions": ["view_overview"]})[0]
        User.objects.create_user(email="bh@test.local", password="x-Strong-pass1", role=self.bh)
        User.objects.create_user(email="rm@test.local", password="x-Strong-pass1", role=self.rm)
        User.objects.create_superuser(email="admin@test.local", password="x-Strong-pass1")

    def client_for(self, email):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Bearer " + jwt_login(c, email, "x-Strong-pass1")["access"])
        return c

    def test_only_business_head_and_admin(self):
        self.assertEqual(self.client_for("rm@test.local").get("/api/masters/pnl/").status_code, 403)
        for email in ("bh@test.local", "admin@test.local"):
            r = self.client_for(email).get("/api/masters/pnl/")
            self.assertEqual(r.status_code, 200, email)
            self.assertEqual(len(r.json()["quarters"]), 4)
            self.assertTrue(r.json()["can_edit"])
        # the codes cannot be given to any other role
        admin = self.client_for("admin@test.local")
        r = admin.patch(f"/api/admin/roles/{self.rm.pk}/", {"permissions": ["view_overview", "view_pnl"]}, format="json")
        self.assertEqual(r.status_code, 400)
        # and even if they were put there directly, the P&L still refuses
        self.rm.permissions = ["view_overview", "view_pnl"]
        self.rm.save()
        self.assertEqual(self.client_for("rm@test.local").get("/api/masters/pnl/").status_code, 403)

    def test_add_next_quarter_edit_and_undo(self):
        c = self.client_for("bh@test.local")
        r = c.post("/api/masters/pnl/quarters/", {}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["label"], "Q2 (FY 26-27)")
        q = PnlQuarter.objects.get(quarter_start="2026-07-01")
        # costs and % carried forward from the previous quarter; revenue and returns left to enter
        self.assertEqual((q.tech_platform_cost, q.misc_expense, q.cogs_pct), (Decimal(800000), Decimal(100000), 70))
        self.assertIsNone(q.gross_revenue)
        # amounts as typed: Indian digit grouping is fine
        r = c.patch("/api/masters/pnl/quarters/2026-07-01/", {"gross_revenue": "9,09,98,000", "returns": 1021000},
                    format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(PnlQuarter.objects.get(quarter_start="2026-07-01").gross_revenue, Decimal(90998000))
        self.assertEqual(c.patch("/api/masters/pnl/quarters/2026-07-01/", {"returns": "-5"}, format="json").status_code,
                         400)
        self.assertEqual(c.patch("/api/masters/pnl/quarters/2026-07-01/", {"cogs_pct": 120}, format="json").status_code,
                         400)
        data = c.get("/api/masters/pnl/").json()
        last = data["quarters"][-1]
        self.assertAlmostEqual(last["values"]["net_revenue"], 89977000)
        self.assertEqual(last["missing"], [])
        self.assertIsNotNone(last["growth"]["ebitda"])
        self.assertEqual(c.delete("/api/masters/pnl/quarters/2026-04-01/").status_code, 400)  # not the latest
        self.assertEqual(c.delete("/api/masters/pnl/quarters/2026-07-01/").status_code, 204)
        from accounts.models import AuditLog

        self.assertTrue(AuditLog.objects.filter(object_type__icontains="pnl").exists())

    def test_export_like_the_sheet(self):
        r = self.client_for("bh@test.local").get("/api/masters/pnl/?export=csv")
        self.assertEqual(r.status_code, 200)
        text = r.content.decode("utf-8-sig")
        self.assertIn("P&L Particular", text.splitlines()[0])
        self.assertIn("Operating Profit / EBITDA", text)
        self.assertEqual(self.client_for("rm@test.local").get("/api/masters/pnl/?export=csv").status_code, 403)


class PnlDataCheckTests(TestCase):
    def test_quarter_totals_from_orders(self):
        from masters.models import PnlDataCheck
        from masters.pnl import rebuild_data_checks

        rows = [
            {"order_date": "2026-07-03", "mode": "UPI", "total_amount": "1000", "line_total": "990",
             "points_redeemed": "10", "ts_order_status": "delivered"},
            {"order_date": "2026-08-10", "mode": "", "payu_amount": "500", "total_amount": "500", "line_total": "500",
             "points_redeemed": "0", "ts_order_status": "cancelled"},
            {"order_date": "2026-08-11", "mode": "", "payu_amount": "0", "total_amount": "300", "line_total": "300",
             "ts_order_status": "delivered"},  # unpaid pilot order: not revenue
        ]
        self.assertEqual(rebuild_data_checks(rows), 1)
        dc = PnlDataCheck.objects.get(quarter_start="2026-07-01")
        self.assertEqual((dc.orders, dc.order_value, dc.cancelled_value, dc.points_redeemed),
                         (2, Decimal(1500), Decimal(500), Decimal(10)))

    def test_internal_distributor_orders_are_not_revenue(self):
        from masters.models import PnlDataCheck
        from masters.pnl import rebuild_data_checks
        from warehouse.models import Distributor

        Distributor.objects.create(code="TS", name="Techno Sportswear Private Limited", source_id="td:3", is_internal=True)
        rows = [{"order_date": "2026-07-03", "mode": "UPI", "total_amount": "1000", "line_total": "1000",
                 "points_redeemed": "0", "ts_order_status": "delivered", "distributor_id": "7"},
                {"order_date": "2026-07-04", "mode": "UPI", "total_amount": "400", "line_total": "400",
                 "points_redeemed": "0", "ts_order_status": "delivered", "distributor_id": "3"}]
        rebuild_data_checks(rows)
        dc = PnlDataCheck.objects.get(quarter_start="2026-07-01")
        self.assertEqual((dc.orders, dc.order_value), (1, Decimal(1000)))


class PnlMonthlyTests(PnlApiTests):
    """Monthly P&L: months fill in from the data and their quarter; three months add up to the quarter; edits
    override one figure of one month; the range is limited."""

    def setUp(self):
        super().setUp()
        from masters.models import PnlMonthData

        # Q1 FY 26-27 (seeded): Gross 7,46,16,928; split over its three months
        for m, v in (("2026-04-01", "24771000"), ("2026-05-01", "22540000"), ("2026-06-01", "27305928")):
            PnlMonthData.objects.create(month=dt.date.fromisoformat(m), orders=10, order_value=Decimal(v))

    def test_months_add_up_to_the_quarter(self):
        from masters.pnl import monthly_statement

        d = monthly_statement(dt.date(2026, 4, 1), dt.date(2026, 6, 1), today=dt.date(2026, 11, 26))
        ms = d["months"]
        self.assertEqual([m["label"] for m in ms], ["Apr 2026", "May 2026", "Jun 2026"])
        q = statement()["quarters"][-1]["values"]
        gross = sum(m["values"]["gross_revenue"] for m in ms)
        self.assertAlmostEqual(gross, q["gross_revenue"], places=2)
        # no finance tracker rows in the test: returns are the quarter's, in proportion to revenue
        self.assertAlmostEqual(sum(m["values"]["returns"] for m in ms), q["returns"], places=2)
        self.assertAlmostEqual(sum(m["values"]["ebitda"] for m in ms), q["ebitda"], places=2)
        self.assertEqual(ms[0]["sources"]["tech_platform_cost"], "Q1 (FY 26-27) / 3")
        self.assertIsNone(ms[0]["growth"]["gross_revenue"])  # no March data
        self.assertAlmostEqual(ms[1]["growth"]["gross_revenue"], 22540000 / 24771000 - 1, places=9)

    def test_month_in_progress_counts_costs_for_the_days_so_far(self):
        from masters.pnl import monthly_statement

        m = monthly_statement(dt.date(2026, 6, 1), dt.date(2026, 6, 1), today=dt.date(2026, 6, 15))["months"][0]
        self.assertEqual(m["status"], "in_progress")
        self.assertAlmostEqual(m["values"]["tech"], 800000 / 3 * 15 / 30, places=2)
        self.assertIn("15/30 days", m["sources"]["tech_platform_cost"])

    def test_edit_a_month_and_go_back_to_automatic(self):
        c = self.client_for("bh@test.local")
        r = c.patch("/api/masters/pnl/months/2026-05/", {"tech_platform_cost": "300,000", "notes": "new server"}, format="json")
        self.assertEqual(r.status_code, 200)
        m = c.get("/api/masters/pnl/months/?from=2026-05&to=2026-05").json()["months"][0]
        self.assertEqual(m["values"]["tech"], 300000.0)
        self.assertEqual(m["sources"]["tech_platform_cost"], "entered")
        c.patch("/api/masters/pnl/months/2026-05/", {"tech_platform_cost": ""}, format="json")
        m = c.get("/api/masters/pnl/months/?from=2026-05&to=2026-05").json()["months"][0]
        self.assertAlmostEqual(m["values"]["tech"], 800000 / 3, places=2)
        self.assertEqual(m["inputs"]["notes"], "new server")

    def test_range_rules_and_access(self):
        self.assertEqual(self.client_for("rm@test.local").get("/api/masters/pnl/months/").status_code, 403)
        c = self.client_for("admin@test.local")
        self.assertEqual(len(c.get("/api/masters/pnl/months/").json()["months"]), 3)  # this month and the two before
        self.assertEqual(c.get("/api/masters/pnl/months/?from=2025-01&to=2026-06").status_code, 400)  # > 12 months
        self.assertEqual(c.get("/api/masters/pnl/months/?from=2026-06&to=2026-04").status_code, 400)
        self.assertEqual(c.get("/api/masters/pnl/months/?from=2030-01&to=2030-01").status_code, 400)
        r = c.get("/api/masters/pnl/months/?from=2026-04&to=2026-06&export=csv")
        self.assertEqual(r.status_code, 200)
