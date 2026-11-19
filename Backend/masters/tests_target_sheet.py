"""Live targets sheet (TD_ASM_Executive_Incentive_Tracker) and the CRM sheet: parsing, matching, month-only writes."""
import datetime as dt
from decimal import Decimal

from django.test import TestCase

from analytics.metrics import target_values
from masters import name_match, target_sheet
from warehouse.models import Asm, Distributor, FieldStaff, Region, State, Target, TargetSplit

OCT = dt.date(2026, 10, 1)
SHEET = [
    ["TechnoDirect - ASM & Executive Individual Incentive Tracker"],
    ["Enter the yellow cells."],
    ["Month", "Region", "State", "Distributor", "Role", "Employee Name", "Base Incentive", "TD Target (₹)"],
    ["Oct", "South", "Karnataka", "Heera Exports", "ASM", "Gururaj", "", "₹8,000,000"],
    ["", "South", "", "", "Executive", "Srinivas", "", "₹3,000,000"],
    ["", "South", "Andhra Pradesh", "Virat Sports", "ASM", "Imran", "", "₹3,000,000"],
    ["", "South", "", "", "ASM", "Anil Kumar", "", "₹1,000,000"],
    ["", "South", "Tamil Nadu", "Tirupati Entps", "ASM", "Vacant", "", "₹800,000"],
    ["", "", "", "", "", "", "", "₹0"],
]


class TargetSheetTests(TestCase):
    def setUp(self):
        south = Region.objects.create(code="S", name="South")
        ka = State.objects.create(code="KA", name="Karnataka", region=south)
        self.gururaj = Asm.objects.create(code="A1", name="Gururaj", region=south)
        self.anil = Asm.objects.create(code="A2", name="Anil", region=south)
        self.imran = Asm.objects.create(code="A3", name="Imran", region=south)
        self.heera = Distributor.objects.create(code="HE", name="Heera Exports Inc", region=south, state=ka, asm=self.gururaj)
        self.virat = Distributor.objects.create(code="VI", name="Virat Sports Wear", region=south, state=ka, asm=self.anil)
        self.tiru = Distributor.objects.create(code="TI", name="Tirupati Enterprises", region=south, state=ka)
        FieldStaff.objects.create(emp_id="E1", name="Srinivasa N")
        # September and an old October target that the sheet replaces
        Target.objects.create(month=dt.date(2026, 9, 1), scope_type="distributor", scope_id=self.heera.id, value=5, effective_from=dt.date(2026, 9, 1))
        Target.objects.create(month=OCT, scope_type="distributor", scope_id=self.tiru.id, value=99, effective_from=OCT)

    def test_month_label(self):
        today = dt.date(2026, 11, 19)
        self.assertEqual(target_sheet.resolve_month("Oct", today), OCT)
        self.assertEqual(target_sheet.resolve_month("Dec", today), dt.date(2025, 12, 1))  # no year: latest past one
        self.assertEqual(target_sheet.resolve_month("Oct 25", today), dt.date(2025, 10, 1))
        self.assertEqual(target_sheet.resolve_month("2027-01", today), dt.date(2027, 1, 1))

    def test_apply_october_only(self):
        rows = target_sheet.parse(SHEET, dt.date(2026, 11, 19))
        self.assertEqual(len(rows), 5)
        target_sheet.apply(target_sheet.plan(rows))
        dist = {k[0]: v for k, v in target_values("distributor", None, [OCT]).items()}
        self.assertEqual(dist[self.heera.id], Decimal("11000000"))  # ASM + executive
        self.assertEqual(dist[self.virat.id], Decimal("4000000"))
        self.assertEqual(dist[self.tiru.id], Decimal("800000"))  # abbreviation matched, old 99 replaced
        asm = {k[0]: v for k, v in target_values("asm", None, [OCT]).items()}
        self.assertEqual(asm[self.gururaj.id], Decimal("11000000"))
        self.assertEqual((asm[self.imran.id], asm[self.anil.id]), (Decimal("3000000"), Decimal("1000000")))
        self.assertEqual(target_values("overall", None, [OCT])[(None, OCT)], Decimal("15800000"))
        self.assertEqual(target_values("distributor", None, [dt.date(2026, 9, 1)])[(self.heera.id, dt.date(2026, 9, 1))], 5)
        sp = TargetSplit.objects.get(month=OCT, person="Srinivas")
        self.assertEqual((sp.role, sp.field_staff.name, sp.value), ("executive", "Srinivasa N", Decimal("3000000")))
        self.assertTrue(target_sheet.sheet_managed(OCT))
        self.assertFalse(target_sheet.sheet_managed(dt.date(2026, 9, 1)))

    def test_executive_performance(self):
        from django.utils import timezone

        from accounts.models import User
        from warehouse.models import Order, Retailer

        solo = Distributor.objects.create(code="RM", name="RM Readymades", region=self.heera.region)
        sheet = SHEET[:-1] + [["", "South", "", "RM Readymades", "Executive", "Jwahar", "", "₹300,000"]]
        target_sheet.apply(target_sheet.plan(target_sheet.parse(sheet, dt.date(2026, 11, 19))))
        r = Retailer.objects.create(name="Shop")
        at = timezone.make_aware(dt.datetime(2026, 10, 10, 12))
        for n, (d, v) in enumerate([(self.heera, 1100000), (solo, 150000)]):
            Order.objects.create(source_id=f"x{n}", display_id=str(n), split_group=f"g{n}", retailer=r, distributor=d,
                                 status="delivered", payment_status="captured", gross_value=v, units=1,
                                 placed_at=at, placed_date=at.date(), is_qualifying=True)
        admin = User.objects.create_superuser(email="a@test.local", password="x-Strong-pass1")
        ex = {e["person"]: e for e in target_sheet.executive_performance(OCT, admin)["executives"]}
        self.assertEqual(set(ex), {"Srinivas", "Jwahar"})  # executives only, not ASMs
        self.assertEqual((ex["Srinivas"]["basis"], ex["Srinivas"]["sales"]), ("allocated", 300000.0))  # 30/110 of Heera
        self.assertEqual((ex["Jwahar"]["basis"], ex["Jwahar"]["sales"], ex["Jwahar"]["achieved_pct"]), ("exact", 150000.0, 50.0))

    def test_unknown_distributor_fails_without_writing(self):
        rows = target_sheet.parse(SHEET + [["Oct", "North", "UP", "Nowhere Traders", "ASM", "X", "", "₹100"]],
                                  dt.date(2026, 11, 19))
        with self.assertRaises(target_sheet.TargetSheetError):
            target_sheet.plan(rows)
        self.assertEqual(Target.objects.filter(month=OCT).count(), 1)

    def test_name_match(self):
        dists = list(Distributor.objects.all())
        self.assertEqual(name_match.distributor("Tirupati Entps", dists), self.tiru)
        self.assertEqual(name_match.person("Anil Kumar", list(Asm.objects.all())), self.anil)
        self.assertIsNone(name_match.distributor("Unknown Shop", dists))


class CrmSheetTests(TestCase):
    def test_load_records(self):
        from django.utils import timezone

        from ingestion.connectors.google_sheets import GoogleSheetsConnector
        from warehouse.models import CrmTicket, Order, Retailer

        south = Region.objects.create(code="S", name="South")
        d = Distributor.objects.create(code="HE", name="Heera Exports Inc", region=south, aliases=["HEERA"])
        r = Retailer.objects.create(name="Shop")
        now = timezone.now()
        o = Order.objects.create(source_id="o1", display_id="16904", split_group="c1", retailer=r, distributor=d,
                                 status="delivered", payment_status="captured", gross_value=1, units=1,
                                 placed_at=now, placed_date=now.date())
        recs = [
            {"DATE": "4-Dec-2025", "ORDER ID": "# 16904.", "CUSTOMER NAME": "Shop", "DISTRIBUTOR": "HEERA",
             "ISSUES TYPE": "DISPATCH DELAY", "STATUS": "CLOSED", "CRM _REMARKS": "late", "REFUND": "₹6,495.00"},
            {"DATE": "4-Dec-2026", "ORDER ID": "", "CUSTOMER NAME": "Other", "DISTRIBUTOR": "HEERA",
             "ISSUES TYPE": "ISSUES TYPE ", "STATUS": "", "CRM _REMARKS": ""},
        ]
        con = GoogleSheetsConnector()
        self.assertEqual(con.load_records(recs, today=dt.date(2026, 11, 19)), 2)
        t1 = CrmTicket.objects.get(order=o)
        self.assertEqual((t1.ticket_type, t1.status, t1.retailer, t1.raw["refund_amount"]), ("Dispatch Delay", "closed", r, 6495.0))
        t2 = CrmTicket.objects.exclude(order=o).get()
        self.assertEqual((t2.ticket_type, t2.status, t2.distributor, t2.opened_at.year), ("Not specified", "open", d, 2025))
        con.load_records(recs[:1], today=dt.date(2026, 11, 19))  # a deleted sheet row disappears
        self.assertEqual(CrmTicket.objects.count(), 1)
