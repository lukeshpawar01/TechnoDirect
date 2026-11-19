"""Live Google Sheets (settlement tracker, TechnoD Distributors) and fixed sheets kept in Supabase (schema reference)."""
import datetime as dt
import os
import tempfile
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from ingestion import gsheets
from ingestion import reference_sheets as R


class LinkTests(SimpleTestCase):
    def test_parse_link(self):
        sid = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcd"
        self.assertEqual(gsheets.parse_link(f"https://docs.google.com/spreadsheets/d/{sid}/edit#gid=123"), (sid, 123))
        self.assertEqual(gsheets.parse_link(f"https://docs.google.com/spreadsheets/d/{sid}/edit?usp=sharing"), (sid, None))
        self.assertEqual(gsheets.parse_link(sid), (sid, None))
        with self.assertRaises(gsheets.SheetError):
            gsheets.parse_link("https://example.com/not-a-sheet")

    def test_read_table_like_csv(self):
        values = [["ORDER ID", " Distributor", "ORDER VALUE"], ["#101", "Heera", "1,000"], ["", "", ""], ["#102", "Ravi"]]
        with mock.patch.object(gsheets, "read_values", return_value=values):
            rows = gsheets.read_table("x")
        self.assertEqual(rows, [{"ORDER ID": "#101", " Distributor": "Heera", "ORDER VALUE": "1,000"},
                                {"ORDER ID": "#102", " Distributor": "Ravi", "ORDER VALUE": ""}])
        self.assertNotEqual(gsheets.signature(rows), gsheets.signature(rows[:1]))


class LiveSheetRefreshTests(TestCase):
    def test_distributor_sync_reads_the_google_sheet(self):
        from ingestion.models import SyncRun
        from masters import distributor_sync
        from warehouse.models import Distributor, Region, State

        reg = Region.objects.create(code="S", name="South")
        Distributor.objects.create(code="HE", name="Heera Exports", region=reg,
                                   state=State.objects.create(code="KA", name="Karnataka", region=reg))
        rows = [{"Distributor": "Heera Exports", "Inventory Updated": "17/11/2026", "Status": "Active",
                 "Taken By": "Excel", "Frequency": "Daily"}]
        with override_settings(DISTRIBUTOR_SYNC_SHEET_URL="https://docs.google.com/spreadsheets/d/" + "a" * 30),  \
                mock.patch.object(gsheets, "configured", return_value=True), \
                mock.patch.object(gsheets, "read_table", return_value=rows):
            step = distributor_sync.refresh_if_changed()
            self.assertEqual(step["status"], "success")
            self.assertEqual(SyncRun.objects.get(pk=step["run_id"]).details["via"], "google_sheet")
            self.assertEqual(Distributor.objects.get(code="HE").stock_updated_on, dt.date(2026, 11, 17))
            self.assertEqual(distributor_sync.refresh_if_changed()["status"], "skipped")  # unchanged sheet
        with override_settings(DISTRIBUTOR_SYNC_SHEET_URL="https://docs.google.com/spreadsheets/d/" + "a" * 30), \
                mock.patch.object(gsheets, "configured", return_value=True), \
                mock.patch.object(gsheets, "read_table", side_effect=gsheets.SheetError("share the sheet")):
            step = distributor_sync.refresh_if_changed()
        self.assertEqual(step["status"], "failed")
        self.assertIn("share the sheet", SyncRun.objects.get(pk=step["run_id"]).error)


class FakeReference:
    def __init__(self):
        self.entries, self.data = [], {}

    def replace(self, name, source_file, parts):
        self.entries = [e for e in self.entries if e["name"] != name]
        for pos, (tab, kind, headers, rows) in enumerate(parts):
            table = name if kind == "table" else f"{name}__{R._slug(tab)}"
            self.entries.append({"name": name, "tab": tab, "position": pos, "table_name": table, "kind": kind,
                                 "source_file": source_file, "headers": headers, "rows": len(rows)})
            first = 2 if kind == "table" else 1
            self.data[table] = [(first + i, *r) for i, r in enumerate(rows)]
        return parts

    def catalog(self, name=None):
        return [e for e in self.entries if name is None or e["name"] == name]

    def grid(self, entry):
        return entry["headers"], self.data[entry["table_name"]]


class ReferenceSheetTests(SimpleTestCase):
    def test_csv_round_trip(self):
        d = tempfile.mkdtemp()
        src = os.path.join(d, "team.csv")
        with open(src, "w", encoding="utf-8", newline="") as fh:
            fh.write("Emp ID,Name,Designation,Designation\nE1,Ravi,ASM,Sales\n,,,\nE2,Asha,RSM,\n")
        store = FakeReference()
        R.upload("sales_team", src, store=store)
        self.assertEqual(R._columns(["Emp ID", "Name", "Designation", "Designation", ""]),
                         ["Emp ID", "Name", "Designation", "Designation_2", "column_5"])
        back = R.to_local_file("sales_team", store=store)
        with open(back, encoding="utf-8") as fh:
            self.assertEqual(fh.read().splitlines(), ["Emp ID,Name,Designation,Designation", "E1,Ravi,ASM,Sales", "E2,Asha,RSM,"])
        self.assertEqual(R.resolve_file("data/x.csv"), "data/x.csv")  # a plain path is left alone
        # personal details left out: only the listed columns are stored (a repeated header keeps both copies)
        R.upload("hr", src, store=store, columns=["Emp ID", "Designation"])
        hr = store.catalog("hr")[0]
        self.assertEqual(hr["headers"], ["Emp ID", "Designation", "Designation"])
        self.assertEqual(store.data["hr"][0], (2, "E1", "ASM", "Sales"))
        with self.assertRaises(R.ReferenceError):
            R.upload("hr", src, store=store, columns=["Phone"])

    def test_workbook_round_trip_keeps_cells_in_place(self):
        import openpyxl

        d = tempfile.mkdtemp()
        src = os.path.join(d, "targets.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Nov 26"
        ws["A1"], ws["C3"], ws["B4"], ws["D2"] = "TD Target", 42.0, "15L", dt.datetime(2026, 11, 1)
        wb.create_sheet("Dec 26")["B2"] = 7
        wb.save(src)
        store = FakeReference()
        R.upload("asm_targets", src, store=store)
        out = openpyxl.load_workbook(R.to_local_file("asm_targets", store=store), data_only=True)
        self.assertEqual(out.sheetnames, ["Nov 26", "Dec 26"])
        w = out["Nov 26"]
        self.assertEqual((w["A1"].value, w["C3"].value, w["B4"].value, w["D2"].value),
                         ("TD Target", 42.0, "15L", dt.datetime(2026, 11, 1)))
        self.assertEqual(out["Dec 26"]["B2"].value, 7)

    def test_workbook_formulas_kept_as_text(self):
        import openpyxl

        d = tempfile.mkdtemp()
        src = os.path.join(d, "pnl.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "P&L QoQ"
        ws["B4"], ws["B5"], ws["B6"] = 100, 10, "=B4-B5"
        wb.save(src)
        store = FakeReference()
        R.upload("pnl_qoq_formulas", src, store=store, formulas=True)
        self.assertIn((6, None, "=B4-B5"), store.data["pnl_qoq_formulas__p_l_qoq"])
        out = openpyxl.load_workbook(R.to_local_file("pnl_qoq_formulas", store=store))
        self.assertEqual(out["P&L QoQ"]["B6"].value, "=B4-B5")  # rebuilt as a working formula

    def test_names(self):
        with self.assertRaises(R.ReferenceError):
            R.upload("Bad Name!", __file__, store=FakeReference())


class SupabaseSheetRefreshTests(TestCase):
    """Without a Google link, the two sheets come from their copy in Supabase - no file on the PC."""

    def test_distributor_sync_from_supabase(self):
        from ingestion.models import SyncRun
        from masters import distributor_sync
        from warehouse.models import Distributor, Region

        reg = Region.objects.create(code="S", name="South")
        Distributor.objects.create(code="HE", name="Heera Exports", region=reg)
        rows = [{"Distributor": "Heera Exports", "Inventory Updated": "18/11/2026", "Status": "Active",
                 "Taken By": "Excel", "Frequency": "Daily"}]
        with override_settings(DISTRIBUTOR_SYNC_SHEET_URL="", DISTRIBUTOR_SYNC_REFERENCE_SHEET="distributor_sync"), \
                mock.patch.object(R, "configured", return_value=True), \
                mock.patch.object(R, "table_rows", return_value=rows) as tr:
            step = distributor_sync.refresh_if_changed()
            self.assertEqual(step["status"], "success")
            tr.assert_called_once_with("distributor_sync")
            self.assertEqual(SyncRun.objects.get(pk=step["run_id"]).details["via"], "supabase:distributor_sync")
            self.assertEqual(Distributor.objects.get(code="HE").stock_updated_on, dt.date(2026, 11, 18))
            self.assertEqual(distributor_sync.refresh_if_changed()["status"], "skipped")  # unchanged copy
            self.assertEqual(distributor_sync.refresh_if_changed(force=True)["status"], "success")
        with override_settings(DISTRIBUTOR_SYNC_SHEET_URL="", DISTRIBUTOR_SYNC_REFERENCE_SHEET="distributor_sync"), \
                mock.patch.object(R, "configured", return_value=True), \
                mock.patch.object(R, "table_rows", return_value=None):
            self.assertEqual(distributor_sync.refresh_if_changed()["status"], "not_configured")  # not uploaded

    def test_table_rows(self):
        store = FakeReference()
        d = tempfile.mkdtemp()
        src = os.path.join(d, "s.csv")
        with open(src, "w", encoding="utf-8", newline="") as fh:
            fh.write("ORDER ID, Distributor\n#1,Heera\n")
        R.upload("settlement_tracker", src, store=store)
        self.assertEqual(R.table_rows("settlement_tracker", store=store), [{"ORDER ID": "#1", " Distributor": "Heera"}])
        self.assertIsNone(R.table_rows("nothing", store=store))
