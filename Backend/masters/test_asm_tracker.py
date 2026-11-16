"""ASM tracker: read / Excel export / on-screen save / upload round trip."""
import io

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Role, User
from analytics.tests import make_world
from warehouse.models import Asm, Distributor, Target


class AsmTrackerTests(TestCase):
    def setUp(self):
        cache.clear()
        self.w = make_world()
        self.admin = User.objects.create_superuser(email="admin@test.local", password="x-Strong-pass1")
        self.c = APIClient()
        self.c.force_authenticate(self.admin)
        self.d1, self.d2 = list(Distributor.objects.order_by("id")[:2])

    def save(self, rows, month="2026-11"):
        return self.c.post("/api/masters/asm-tracker/", {"month": month, "rows": rows}, format="json")

    def test_save_creates_asm_and_targets_then_blank_removes_them(self):
        r = self.save([{"distributor_id": self.d1.id, "region": "South", "asm": "Gururaj", "target": 1000000},
                       {"distributor_id": self.d2.id, "region": "East", "asm": "Gururaj", "target": ""}])
        self.assertEqual(r.status_code, 200, r.content)
        asm = Asm.objects.get(name="Gururaj")
        self.d1.refresh_from_db()
        self.assertEqual((self.d1.asm_id, self.d1.region.name), (asm.id, "South"))
        t = Target.objects.filter(month="2026-11-01", metric="sales")
        self.assertEqual(float(t.get(scope_type="distributor", scope_id=self.d1.id).value), 1000000)
        self.assertEqual(float(t.get(scope_type="asm", scope_id=asm.id).value), 1000000)
        self.assertFalse(t.filter(scope_type="distributor", scope_id=self.d2.id).exists())

        data = self.c.get("/api/masters/asm-tracker/?month=2026-11").json()
        row = next(x for x in data["rows"] if x["distributor_id"] == self.d1.id)
        self.assertEqual((row["asm"], row["target"]), ("Gururaj", 1000000.0))
        self.assertEqual(data["asm_summary"][0]["asm"], "Gururaj")

        # clearing the target removes the distributor, ASM and region targets for that month
        self.save([{"distributor_id": self.d1.id, "region": "South", "asm": "Gururaj", "target": ""},
                   {"distributor_id": self.d2.id, "region": "East", "asm": "Gururaj", "target": ""}])
        self.assertFalse(Target.objects.filter(month="2026-11-01", scope_type__in=["distributor", "asm"]).exists())

    def test_export_xlsx_and_upload_round_trip(self):
        self.save([{"distributor_id": self.d1.id, "region": "South", "asm": "Anil", "target": 500000},
                   {"distributor_id": self.d2.id, "region": "East", "asm": "", "target": ""}])
        r = self.c.get("/api/masters/asm-tracker/?month=2026-11&download=xlsx")
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r["Content-Type"])
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(r.content))
        ws = wb.worksheets[0]
        header = [c.value for c in ws[1]]
        self.assertEqual(header[:3], ["Distributor", "Region", "ASM"])
        # edit the sheet: new ASM + new target on the second distributor, then upload it back
        tcol = header.index("Total Target") + 1
        for row in ws.iter_rows(min_row=2):
            if row[0].value == self.d2.name:
                row[2].value = "Supriya"
                ws.cell(row[0].row, tcol).value = 250000
        buf = io.BytesIO()
        wb.save(buf)
        up = SimpleUploadedFile("tracker.xlsx", buf.getvalue())
        r = self.c.post("/api/masters/asm-tracker/upload/", {"file": up, "month": "2026-11"}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.d2.refresh_from_db()
        self.assertEqual(self.d2.asm.name, "Supriya")
        self.assertEqual(float(Target.objects.get(month="2026-11-01", scope_type="distributor",
                                                  scope_id=self.d2.id).value), 250000)

    def test_permissions(self):
        viewer = User.objects.create_user(email="v@test.local", password="Strong-pass-1",
                                          role=Role.objects.create(name="Viewer", permissions=["view_territory"]))
        c = APIClient()
        c.force_authenticate(viewer)
        self.assertEqual(c.get("/api/masters/asm-tracker/").status_code, 200)
        self.assertEqual(c.get("/api/masters/asm-tracker/?download=xlsx").status_code, 403)  # no export_data
        self.assertEqual(c.post("/api/masters/asm-tracker/", {"rows": []}, format="json").status_code, 403)

    def test_bad_target_rejected(self):
        r = self.save([{"distributor_id": self.d1.id, "region": "South", "asm": "X", "target": "abc"}])
        self.assertEqual(r.status_code, 400)


class BulkRemapTests(TestCase):
    def test_remap_updates_changed_rows_and_keeps_distributor_asm_on_orders(self):
        from warehouse.models import Order, Pincode, Retailer
        from masters.services import remap_retailers_for_pincodes

        w = make_world()
        r = Retailer.objects.exclude(pincode="").first()
        pin, _ = Pincode.objects.get_or_create(pincode=r.pincode, defaults={"state_id": r.state_id})
        a1, a2 = Asm.objects.create(code="A1", name="One"), Asm.objects.create(code="A2", name="Two")
        pin.asm = a1
        pin.save()
        self.assertGreater(remap_retailers_for_pincodes([pin.pincode]), 0)
        r.refresh_from_db()
        self.assertEqual(r.asm_id, a1.id)
        self.assertEqual(remap_retailers_for_pincodes([pin.pincode]), 0)  # nothing changed -> nothing written
        # the order's distributor has its own ASM: orders keep that one after the re-map
        o = Order.objects.filter(retailer=r).first()
        if o and o.distributor_id:
            Distributor.objects.filter(id=o.distributor_id).update(asm=a2)
            pin.asm = None
            pin.save()
            remap_retailers_for_pincodes([pin.pincode])
            r.refresh_from_db()
            o.refresh_from_db()
            self.assertIsNone(r.asm_id)  # NULL handled
            self.assertEqual(o.asm_id, a2.id)
        self.assertIsNotNone(w)


class LivePropagationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.w = make_world()
        self.admin = User.objects.create_superuser(email="admin2@test.local", password="x-Strong-pass1")
        self.c = APIClient()
        self.c.force_authenticate(self.admin)

    def test_save_sets_state_targets_and_bumps_data_version(self):
        d1, d2 = list(Distributor.objects.order_by("id")[:2])
        v0 = self.c.get("/api/meta/data-version/").json()["version"]
        r = self.c.post("/api/masters/asm-tracker/", {"month": "2026-11", "rows": [
            {"distributor_id": d1.id, "region": "South", "asm": "A", "target": 300},
            {"distributor_id": d2.id, "region": "East", "asm": "B", "target": 200}]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertGreater(self.c.get("/api/meta/data-version/").json()["version"], v0)
        st = {t.scope_id: float(t.value) for t in Target.objects.filter(month="2026-11-01", scope_type="state")}
        expected = {}
        for d, v in ((d1, 300), (d2, 200)):
            if d.state_id:
                expected[d.state_id] = expected.get(d.state_id, 0) + v
        self.assertEqual(st, expected)
        # clearing all targets removes the state targets too
        self.c.post("/api/masters/asm-tracker/", {"month": "2026-11", "rows": [
            {"distributor_id": d1.id, "region": "South", "asm": "A", "target": ""},
            {"distributor_id": d2.id, "region": "East", "asm": "B", "target": ""}]}, format="json")
        self.assertFalse(Target.objects.filter(month="2026-11-01", scope_type="state").exists())

    def test_remap_moves_loyalty_events_with_the_retailer(self):
        import datetime as dt

        from masters.services import remap_retailers_for_pincodes
        from warehouse.models import LoyaltyEvent, Pincode, Retailer

        r = Retailer.objects.exclude(pincode="").first()
        ev = LoyaltyEvent.objects.create(source_id="ev1", customer_source_id="c", retailer=r, event_type="earned",
                                         points=10, event_date=dt.date(2026, 11, 1), asm=None)
        asm = Asm.objects.create(code="AX", name="Mover")
        pin, _ = Pincode.objects.get_or_create(pincode=r.pincode, defaults={"state_id": r.state_id})
        pin.asm = asm
        pin.save()
        remap_retailers_for_pincodes([pin.pincode])
        ev.refresh_from_db()
        self.assertEqual(ev.asm_id, asm.id)


class AsmLevelTargetTests(TestCase):
    """Months whose targets are set per ASM (monthly ASM workbook) must survive an on-screen save."""

    def setUp(self):
        cache.clear()
        make_world()
        self.c = APIClient()
        self.c.force_authenticate(User.objects.create_superuser(email="a@test.local", password="x-Strong-pass1"))
        self.d1, self.d2 = list(Distributor.objects.order_by("id")[:2])
        self.asm = Asm.objects.create(code="ASM-T", name="Tara", is_active=True)
        self.left = Asm.objects.create(code="ASM-L", name="Leela", is_active=False)
        self.d1.asm, self.d2.asm = self.asm, self.left
        self.d1.save(), self.d2.save()
        Target.objects.create(month="2026-02-01", scope_type="asm", scope_id=self.asm.id, value=900000,
                              effective_from="2026-02-01", notes="ASM targets workbook (Feb 26, TD Target in lakhs)")

    def test_save_keeps_asm_targets_and_edits_them(self):
        rows = [{"distributor_id": self.d1.id, "region": "", "asm": "Tara", "target": ""},
                {"distributor_id": self.d2.id, "region": "", "asm": "Leela", "target": ""}]
        data = self.c.get("/api/masters/asm-tracker/?month=2026-02").json()
        tara = next(a for a in data["asm_summary"] if a["asm"] == "Tara")
        self.assertEqual((tara["target"], tara["target_from"]), (900000.0, "asm"))

        r = self.c.post("/api/masters/asm-tracker/", {"month": "2026-02", "rows": rows}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        t = Target.objects.filter(month="2026-02-01", scope_type="asm", scope_id=self.asm.id)
        self.assertEqual(float(t.latest("version").value), 900000)  # not wiped by blank distributor targets

        r = self.c.post("/api/masters/asm-tracker/", {"month": "2026-02", "rows": rows,
                                                     "asm_targets": [{"asm": "Tara", "target": 1200000}]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        cache.clear()
        data = self.c.get("/api/masters/asm-tracker/?month=2026-02").json()
        self.assertEqual(next(a for a in data["asm_summary"] if a["asm"] == "Tara")["target"], 1200000.0)
        self.assertEqual(data["totals"]["target"], 1200000.0)  # company total = ASM targets
        self.left.refresh_from_db()
        self.assertFalse(self.left.is_active)  # a past month's save does not bring a leaver back


class AddAsmAndDistributorTests(TestCase):
    """Add ASM / Add distributor from the Edit ASM & targets window."""

    def setUp(self):
        from warehouse.models import Region, Rsm, State

        cache.clear()
        self.south = Region.objects.create(code="S", name="South")
        self.ka = State.objects.create(code="KA", name="Karnataka", region=self.south)
        self.rsm = Rsm.objects.create(code="R1", name="Prabhakar", region=self.south)
        self.c = APIClient()
        self.c.force_authenticate(User.objects.create_superuser(email="m@test.local", password="x-Strong-pass1"))

    def test_add_asm_then_distributor_appears_in_tracker(self):
        r = self.c.post("/api/masters/asm-tracker/asm/", {"name": "Ravi", "full_name": "Ravi Kumar", "region": "South",
                                                         "joined_on": "2026-11-10"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        asm = Asm.objects.get(name="Ravi")
        self.assertEqual((asm.rsm_id, asm.region_id, str(asm.joined_on)), (self.rsm.id, self.south.id, "2026-11-10"))
        self.assertEqual(self.c.post("/api/masters/asm-tracker/asm/", {"name": "ravi", "region": "South"},
                                     format="json").status_code, 400)  # duplicate

        r = self.c.post("/api/masters/asm-tracker/distributor/", {"name": "NEW SPORTS", "state_id": self.ka.id,
                                                                 "city": "mysuru", "asm": "Ravi"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        d = Distributor.objects.get(id=r.json()["id"])
        self.assertEqual((d.name, d.region_id, d.asm_id, d.city), ("New Sports", self.south.id, asm.id, "Mysuru"))
        self.assertEqual(self.c.post("/api/masters/asm-tracker/distributor/", {"name": "New  Sports",
                         "state_id": self.ka.id}, format="json").status_code, 400)  # same name
        data = self.c.get("/api/masters/asm-tracker/?month=2026-11").json()
        self.assertIn("New Sports", [x["distributor"] for x in data["rows"]])
        self.assertEqual(data["rsms"][0]["name"], "Prabhakar")

    def test_needs_manage_mappings(self):
        role = Role.objects.create(name="Viewer", permissions=["view_territory"])
        u = User.objects.create_user(email="v@test.local", password="x-Strong-pass1", role=role)
        c = APIClient()
        c.force_authenticate(u)
        self.assertEqual(c.post("/api/masters/asm-tracker/asm/", {"name": "X", "region": "South"}, format="json")
                         .status_code, 403)


class TargetForecasterTests(TestCase):
    """TD Target Forecaster: uses only what was known on the as-of day, and suggests sensible targets."""

    def setUp(self):
        import datetime as dt
        from decimal import Decimal

        from django.utils import timezone

        from warehouse.models import Order, Region

        reg = Region.objects.create(code="S", name="South")
        self.asm = Asm.objects.create(code="ASM-A", name="Asha", region=reg)
        self.d = Distributor.objects.create(code="D1", name="Dist", region=reg, asm=self.asm)
        n = 0
        # Rs 10 L a month spread over the month, Jan..Oct 2026; a huge order AFTER the as-of day (must be ignored)
        for mo in range(1, 11):
            for day in (5, 15, 25):
                d = dt.date(2026, mo, day)
                n += 1
                Order.objects.create(source_id=f"f{n}", display_id=f"F{n}", split_group=f"f{n}", distributor=self.d,
                                     asm=self.asm, region=reg, status="delivered", payment_status="captured",
                                     gross_value=Decimal(1000000) / 3, units=1, placed_date=d,
                                     placed_at=timezone.make_aware(dt.datetime.combine(d, dt.time(11))))
        later = dt.date(2026, 10, 30)
        Order.objects.create(source_id="late", display_id="LATE", split_group="late", distributor=self.d, asm=self.asm,
                             region=reg, status="delivered", payment_status="captured", gross_value=Decimal(50000000),
                             units=1, placed_date=later, placed_at=timezone.make_aware(dt.datetime.combine(later, dt.time(11))))
        for mo in range(1, 11):
            Target.objects.create(month=dt.date(2026, mo, 1), scope_type="asm", scope_id=self.asm.id,
                                  value=1200000, effective_from=dt.date(2026, mo, 1))

    def test_no_leakage_and_sensible_value(self):
        import datetime as dt

        from masters.target_forecast import History, forecast, run
        from warehouse.models import TargetForecast

        h = History()
        fc = forecast(h, dt.date(2026, 11, 1), dt.date(2026, 10, 27), alpha=0.5, phi=0.5)
        r = fc["asm"][self.asm.id]
        self.assertAlmostEqual(r["sales_forecast"], 1000000, delta=150000)  # the Rs 5 Cr order on 30 Oct is unseen
        self.assertEqual(r["value"] % 50000, 0)  # rounded to Rs 0.5 L
        self.assertTrue(1000000 <= r["value"] <= 1400000)  # anchored on the 12 L target, stretch ~1.2 on ~10 L sales
        res = run(month=dt.date(2026, 11, 1), as_of=dt.date(2026, 10, 27), h=h)
        self.assertEqual(res["asms"], 1)
        self.assertTrue(TargetForecast.objects.filter(month="2026-11-01", scope_type="distributor",
                                                      scope_id=self.d.id).exists())
        data = self.c_get("2026-11")
        self.assertEqual(data["forecast"]["as_of"], "2026-10-27")
        stored = TargetForecast.objects.get(month="2026-11-01", scope_type="asm", scope_id=self.asm.id)
        self.assertEqual(data["rows"][0]["suggested"], float(stored.value))  # one distributor = the whole ASM

    def c_get(self, month):
        c = APIClient()
        c.force_authenticate(User.objects.create_superuser(email="f@test.local", password="x-Strong-pass1"))
        return c.get(f"/api/masters/asm-tracker/?month={month}").json()


class StaleEditorSaveTests(TestCase):
    """Saving a page loaded before a handover must not undo it; only edited ASM cells change the mapping."""

    def setUp(self):
        cache.clear()
        make_world()
        self.c = APIClient()
        self.c.force_authenticate(User.objects.create_superuser(email="s@test.local", password="x-Strong-pass1"))
        self.d = Distributor.objects.order_by("id").first()
        self.old = Asm.objects.create(code="ASM-OLD", name="Valluru")
        self.new = Asm.objects.create(code="ASM-NEW", name="Anil")
        self.d.asm = self.old
        self.d.save()

    def test_untouched_stale_asm_keeps_newer_handover(self):
        import datetime as dt

        from masters.services import assign_distributor_asm

        # page loaded showing Valluru; meanwhile Anil takes over from Oct
        assign_distributor_asm(self.d, self.new, dt.date(2026, 10, 1))
        row = {"distributor_id": self.d.id, "region": "", "region_orig": "", "asm": "Valluru", "asm_orig": "Valluru",
               "target": 6000000}
        r = self.c.post("/api/masters/asm-tracker/", {"month": "2026-11", "rows": [row]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.d.refresh_from_db()
        self.assertEqual(self.d.asm_id, self.new.id)
        self.assertFalse(self.d.asm_history.filter(start="2026-11-01").exists())
        t = Target.objects.get(month="2026-11-01", scope_type="asm")
        self.assertEqual(t.scope_id, self.new.id)  # the month's target follows the ASM in charge

        # an ASM the user really changed is still a handover from that month
        row.update({"asm": "Valluru", "asm_orig": "Anil"})
        self.c.post("/api/masters/asm-tracker/", {"month": "2026-12", "rows": [row]}, format="json")
        self.assertTrue(self.d.asm_history.filter(start="2026-12-01", asm=self.old).exists())
