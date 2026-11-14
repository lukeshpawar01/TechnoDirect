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
