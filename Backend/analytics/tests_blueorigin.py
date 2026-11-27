"""BlueOrigin (offline) import + endpoints: distributor mapping, tiers, phone match, hierarchy totals, filters."""
import csv
import os
import shutil
import tempfile

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from accounts.models import User
from accounts.testing import jwt_login
from masters.blueorigin import import_folder, month_of_column, phone10, quarter_of_file
from warehouse.models import Asm, BoRetailer, Distributor, Retailer

from .tests import make_world

HEAD = ["Retailer Name", "Deliverables", "Phone", "Address", "Pincode", "District", "State", "Year", "{m1}", "{m2}",
        "{m3}", "Last 3 Months", "New Tier", "Old Tier", "Shop Board", "Distributor", "Quarter", "Phone_Alt",
        "Code name", "Retailer_ID"]


def sheet(folder, name, months, rows):
    head = [h.format(m1=months[0], m2=months[1], m3=months[2]) for h in HEAD]
    with open(os.path.join(folder, name), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(head)
        for r in rows:
            w.writerow(r)


def row(name, phone, pin, state, vals, tier, dist, rid, alt=""):
    return [name, "Yes", phone, "addr", pin, "", state, "2026", *vals, sum(vals), tier, "", "No", dist, "", alt,
            f"{name}-{dist}", rid]


class ParseTests(SimpleTestCase):
    def test_helpers(self):
        self.assertEqual(quarter_of_file("FY27_qtr2.csv")[1], "Q2 FY27")
        self.assertEqual(str(quarter_of_file("FY27_qtr4.csv")[0]), "2027-01-01")
        self.assertEqual(str(quarter_of_file("FY25_qtr3.csv")[0]), "2024-10-01")
        self.assertEqual(str(month_of_column("Sept_24")), "2024-09-01")
        self.assertEqual(str(month_of_column("July_26")), "2026-07-01")
        self.assertIsNone(month_of_column("Last 3 Months"))
        self.assertEqual(phone10("+91 98765 43210"), "9876543210")
        self.assertEqual(phone10("9876543210.0"), "9876543210")
        self.assertEqual(phone10("1111111111"), "")  # junk
        self.assertEqual(phone10("0123456789"), "")


class BlueOriginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.w = make_world()
        d1 = self.w["d1"]
        d1.aliases = ["Heera"]
        self.asm = Asm.objects.create(code="GURU", name="Gururaj", region=d1.region)
        d1.asm = self.asm
        d1.save()
        self.dir = tempfile.mkdtemp()
        q1 = ("Apr_26", "May_26", "Jun_26")
        q2 = ("July_26", "Aug_26", "Sept_26")
        sheet(self.dir, "FY27_qtr1.csv", q1, [
            row("Big Shop", "9876543210", "560001", "KARNATAKA", [400000, 400000, 300000], "Platinum", "Heera", "HEE-1"),
            row("Small Shop", "", "560002", "", [10000, 0, 5000], "", "Heera", "HEE-2"),
        ])
        sheet(self.dir, "FY27_qtr2.csv", q2, [
            # KA Shop on the app (same phone): Gold now, was Platinum -> downgrade
            row("Big Shop", "9876543210", "560001", "KARNATAKA", [300000, 200000, 100000], "Gold", "Heera", "HEE-1"),
            row("Small Shop", "", "560002", "", [20000, 0, 0], "", "Heera", "HEE-2"),
            # unknown distributor -> created offline-only, state from the row's pincode (Odisha)
            row("Puri Store", "9000000001", "752001", "", [60000, 0, 0], "Yellow", "Noble Traders", "NOB-1"),
        ])

        User.objects.create_superuser(email="b@test.local", password="x-Strong-pass1")
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION="Bearer " + jwt_login(self.c, "b@test.local", "x-Strong-pass1")["access"])
        self.rep = import_folder(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_import_maps_hierarchy_and_tags_app_retailers(self):
        self.assertEqual(self.rep["retailers"], 3)
        self.assertEqual(self.rep["tiers"]["Q2 FY27"], {"Gold": 1, "Untiered": 1, "Yellow": 1})
        big = BoRetailer.objects.get(bo_id="HEE-1")
        self.assertEqual(big.distributor, self.w["d1"])  # alias "Heera"
        self.assertEqual(big.asm, self.asm)  # distributor's ASM
        self.assertEqual(big.state.name, "Karnataka")
        self.assertEqual(big.td_retailer, self.w["ret1"])
        noble = Distributor.objects.get(name="Noble Traders")
        self.assertTrue(noble.bo_only)
        self.assertIsNone(noble.asm)
        self.assertEqual(BoRetailer.objects.get(bo_id="NOB-1").state.name, "Odisha")
        ret1 = Retailer.objects.get(id=self.w["ret1"].id)
        self.assertEqual((ret1.tier, ret1.warm_match), ("Gold", True))
        self.assertEqual(Retailer.objects.get(id=self.w["ret2"].id).tier, "")  # not in BlueOrigin

    def test_reimport_is_a_rebuild(self):
        import_folder(self.dir)
        self.assertEqual(BoRetailer.objects.count(), 3)
        self.assertEqual(Distributor.objects.filter(name="Noble Traders").count(), 1)

    def test_summary_hierarchy_and_filters(self):
        p = "preset=custom&date_from=2026-07-01&date_to=2026-09-30"
        s = self.c.get(f"/api/blueorigin/summary/?{p}").json()["data"]
        self.assertEqual(s["kpis"]["purchase"], 680000)
        self.assertEqual(s["kpis"]["prev_purchase"], 1115000)
        self.assertEqual(s["kpis"]["tiers"]["Gold"], 1)
        self.assertEqual(s["movement"]["downgraded"], 1)  # Platinum -> Gold
        self.assertEqual(s["movement"]["new"], 1)  # Puri Store not in the Q1 sheet
        for g in ("region", "rsm", "asm", "state", "distributor"):
            h = self.c.get(f"/api/blueorigin/hierarchy/?{p}&group_by={g}").json()["data"]
            self.assertEqual(round(sum(r["purchase"] for r in h["rows"])), 680000, g)
        h = self.c.get(f"/api/blueorigin/hierarchy/?{p}&group_by=asm").json()["data"]
        self.assertIn("Unassigned", [r["name"] for r in h["rows"]])
        a = self.c.get(f"/api/blueorigin/summary/?{p}&asm={self.asm.id}").json()["data"]["kpis"]
        self.assertEqual(a["purchase"], 620000)
        t = self.c.get(f"/api/blueorigin/summary/?{p}&tier=Yellow").json()["data"]["kpis"]
        self.assertEqual((t["retailers"], t["purchase"]), (1, 60000))

    def test_window_after_bo_data_shows_latest_quarter(self):
        s = self.c.get("/api/blueorigin/summary/?preset=custom&date_from=2026-11-01&date_to=2026-11-15").json()["data"]
        self.assertTrue(s["window"]["shifted"])
        self.assertEqual(s["window"]["from"], "2026-07-01")

    def test_retailer_list_and_td_tier_filter(self):
        rows = self.c.get("/api/blueorigin/retailers/?preset=custom&date_from=2026-07-01&date_to=2026-09-30").json()
        self.assertEqual(rows["count"], 3)
        self.assertEqual(rows["results"][0]["bo_id"], "HEE-1")  # biggest purchase first
        self.assertNotIn("on_app", rows["results"][0])  # BlueOrigin page = sheet data only
        td = self.c.get("/api/retailers/?preset=all_time&tier=Gold").json()
        self.assertEqual([r["id"] for r in td["results"]], [self.w["ret1"].id])
        d = self.c.get(f"/api/retailers/{self.w['ret1'].id}/?preset=all_time").json()["data"]
        self.assertEqual(d["blueorigin"][0]["bo_id"], "HEE-1")
        self.assertEqual(len(d["blueorigin"][0]["quarters"]), 2)


class CompactFileTests(TestCase):
    """The BO_data notebook's TD_BO_dashboard.csv.gz (one file, only the dashboard's columns) imports to exactly the
    same tables as the quarter files it is made from."""

    def _import(self, write):
        from warehouse.models import BoRetailerMonth, BoRetailerQuarter

        d = tempfile.mkdtemp()
        try:
            write(d)
            rep = import_folder(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        snap = (sorted(BoRetailer.objects.values_list("bo_id", "name", "phone", "pincode", "tier")),
                sorted((q.bo_retailer.bo_id, str(q.quarter), q.label, q.purchase, q.tier, q.deliverables)
                       for q in BoRetailerQuarter.objects.select_related("bo_retailer")),
                sorted((m.bo_retailer.bo_id, str(m.month), m.value)
                       for m in BoRetailerMonth.objects.select_related("bo_retailer")))
        return rep, snap

    def test_compact_file_matches_quarter_files(self):
        import gzip

        make_world()
        q1 = [("Big Shop", "9876543210", "560001", "KARNATAKA", [400000, 400000, 300000], "Platinum", "Heera", "HEE-1"),
              ("Small Shop", "", "560002", "", [10000, 0, 5000], "", "Heera", "HEE-2")]
        q2 = [("Big Shop", "9876543210", "560001", "KARNATAKA", [300000, 200000, 100000], "Gold", "Heera", "HEE-1"),
              ("Puri Store", "9000000001", "752001", "", [60000, 0, 0], "Yellow", "Noble Traders", "NOB-1")]

        def quarters(d):
            sheet(d, "FY27_qtr1.csv", ("Apr_26", "May_26", "Jun_26"), [row(*r) for r in q1])
            sheet(d, "FY27_qtr2.csv", ("July_26", "Aug_26", "Sept_26"), [row(*r) for r in q2])

        def compact(d):
            months = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
            head = ["Quarter_Start", "Quarter_Label", "Retailer_ID", "Retailer Name", "Distributor", "State", "District",
                    "Pincode", "Phone", "Phone_Alt", "New Tier", "Old Tier", "Deliverables", "Last 3 Months", *months]
            with gzip.open(os.path.join(d, "TD_BO_dashboard.csv.gz"), "wt", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(head)
                for start, label, rows, at in (("2026-04-01", "Q1 FY27", q1, 0), ("2026-07-01", "Q2 FY27", q2, 3)):
                    for name, ph, pin, st, vals, tier, dist, rid in rows:
                        mv = [""] * 6
                        mv[at:at + 3] = vals
                        w.writerow([start, label, rid, name, dist, st, "", pin, ph, "", tier, "", "Yes", sum(vals), *mv])

        rep_q, snap_q = self._import(quarters)
        rep_c, snap_c = self._import(compact)
        self.assertEqual(snap_c, snap_q)
        self.assertEqual(rep_c["tiers"], rep_q["tiers"])
        self.assertEqual((rep_c["retailers"], rep_c["month_rows"]), (rep_q["retailers"], rep_q["month_rows"]))
