import csv
import datetime as dt
import io
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from ingestion.connectors import supabase_queries as Q


class SupabaseTablesTests(SimpleTestCase):
    """The Supabase tables are read with the expected columns; the login gets exactly those tables."""

    def test_columns_match_the_sample(self):
        heads = {k: next(csv.reader(io.StringIO(body))) for k, body in (
            ("distributor", TD_SAMPLE["Distributor_Data.csv"]),
            ("customer", TD_SAMPLE["Customer_Data.csv"]),
            ("product", TD_SAMPLE["Product_Data.csv"]),
            ("order", TD_SAMPLE["Order_Data.csv"]),
            ("sales", TD_SAMPLE["Sales_Data.csv"]),
            ("inventory", TD_SAMPLE["Inventory_Data.csv"]),
            ("loyalty", TD_SAMPLE["Loyality_Data.csv"]))}
        for kind, cols in heads.items():
            self.assertEqual(Q.TABLES[kind][1], cols, kind)

    def test_grant_sql(self):
        from ingestion.management.commands.supabase_check import grant_sql

        sql = grant_sql()
        for t in ("orders", "sales", "customers", "distributors", "products", "inventory_snapshot", "loyalty_ledger",
                  "etl_watermark"):
            self.assertIn(f'grant select on "public"."{t}" to td_dashboard_ro;', sql)
        self.assertIn("default_transaction_read_only = on", sql)
        self.assertNotIn("grant insert", sql.lower())

    def test_values_as_text(self):
        from ingestion.connectors.supabase import as_text

        self.assertEqual(as_text(True), "true")
        self.assertEqual(as_text(None), "")
        self.assertEqual(as_text(Decimal("20.0000000000000000")), "20.0000000000000000")
        self.assertEqual(as_text(Decimal("1E+2")), "100")
        self.assertEqual(as_text(dt.date(2026, 11, 10)), "2026-11-10")
        ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
        self.assertEqual(as_text(dt.datetime(2026, 11, 13, 13, 30, tzinfo=ist)), "2026-11-13T08:00:00.000000Z")
        self.assertEqual(as_text(500), "500")


class MergeDistributorTests(TestCase):
    def test_merge_moves_references_targets_and_aliases(self):
        import datetime as dt
        from decimal import Decimal

        from django.utils import timezone

        from masters.management.commands.merge_distributors import merge
        from warehouse.models import Distributor, Order, Target

        keep = Distributor.objects.create(code="HEERA", name="Heera Exports Inc", aliases=["Heera"])
        dup = Distributor.objects.create(code="HEERAMAIN", name="Heera Main")
        now = timezone.now()
        Order.objects.create(source_id="o1", display_id="1", split_group="c1", distributor=dup, placed_at=now,
                             placed_date=now.date())
        m = dt.date(2026, 11, 1)
        Target.objects.create(month=m, scope_type="distributor", scope_id=keep.id, value=100, effective_from=m)
        Target.objects.create(month=m, scope_type="distributor", scope_id=dup.id, value=50, effective_from=m)
        merge(keep, dup)
        self.assertFalse(Distributor.objects.filter(id=dup.id).exists())
        self.assertEqual(Order.objects.get(source_id="o1").distributor_id, keep.id)
        self.assertEqual(Target.objects.get(scope_type="distributor").value, Decimal("150"))
        keep.refresh_from_db()
        self.assertIn("Heera Main", keep.aliases)


# A tiny TD dataset: the Supabase tables' rows in text form, one CSV string per table.
TD_SAMPLE = {
    "Distributor_Data.csv": (
        "distributor_id,distributor_name,gst_number,city,state,pincode,is_active,created_at,deleted_at\n"
        "9,HEERA EXPORTS INC,,BANGALORE,Karnataka,560053,true,2024-11-14T11:35:22.155866Z,\n"
        "6,Ankit Jain,,DELHI,Delhi,110001,true,2025-01-01T00:00:00Z,\n"
        "32,Ankit Jain,,DELHI,Delhi,110001,true,2025-02-01T00:00:00Z,\n"),
    "Customer_Data.csv": (
        "customer_id,email,first_name,last_name,business_name,phone,has_account,kyc,gst_number,udyam_number,"
        "ts_pincode,city,province,distributor_name,is_test,created_at,updated_at,deleted_at\n"
        "cus_1,,Ravi,K,RAVI SPORTS,9000000001,true,true,,,560064,Bengaluru,Karnataka,HEERA EXPORTS INC,false,"
        "2025-03-01T10:00:00.000000Z,,\n"
        "cus_t,,Test,,TEST,9000000009,true,true,,,888888,Bengaluru,Karnataka,HEERA EXPORTS INC,true,"
        "2023-09-25T14:29:47.417162Z,,\n"),
    "Product_Data.csv": (
        "variant_id,product_id,sku,style,product_title,size,price,pcs_per_unit,category_level_1,category_level_2,"
        "category_level_3,fabric,gsm,usp1,usp2,usp3,usp4,usp5,usp6,product_status,is_deleted,launch_date\n"
        "var_1,prod_1,SKU-OR67-M,OR67,OR67 Tee,M,3594,6,men,topwear,t-shirts,,0,,,,,,,published,false,"
        "2025-09-23T09:20:20.58316Z\n"),
    "Order_Data.csv": (
        "order_id,display_id,customer_id,distributor_id,ts_order_status,settlement_status,order_date,"
        "dispatch_date,delivered_date,units,line_total,payu_amount,points_redeemed,total_amount,pg_charges,mode,"
        "platform,city,province,updated_at\n"
        "order_A,500,cus_1,9,delivered,pending,2026-11-10,2026-11-11,2026-11-13,2,4312.00,3000.00,1312.00,"
        "4312.00,0,UPI,android,bengaluru,Karnataka,2026-11-13T08:00:00Z\n"
        "order_B,501,cus_1,9,packed,pending,2026-11-12,,,1,2156.00,2156.00,0,2156.00,0,CC,web,,,"
        "2026-11-12T08:00:00Z\n"
        "order_P,4,cus_1,9,delivered,pending,2023-11-27,,,1,20.00,0.00,0.00,0.00,0,,android,,,"
        "2023-11-29T10:26:40Z\n"),
    "Sales_Data.csv": (
        "sales_id,order_key,order_id,order_date,customer_id,distributor_id,ts_order_status,variant_id,product_id,"
        "size,quantity,pieces,unit_price,line_amount\n"
        "item_1,order_A,500,2026-11-10,cus_1,9,delivered,var_1,prod_1,M,2,12,2156,4312\n"
        "item_2,order_B,501,2026-11-12,cus_1,9,packed,var_1,prod_1,M,1,6,2156,2156\n"
        "item_3,order_P,4,2023-11-27,cus_1,9,delivered,var_1,prod_1,M,1,6,20,20\n"),
    "Inventory_Data.csv": (
        "inventory_pk,snapshot_date,variant_id,location_id,stock_location,distributor_id,stock,reserved,available\n"
        "k1,2026-11-17,var_1,sloc_1,heera-exports-inc,9,10,2,8\n"
        "k2,2026-11-17,var_1,sloc_2,heera-exports-incc,,4,0,4\n"),
    "Loyality_Data.csv": (
        "ledger_id,customer_id,order_id,event,total_points,signed_points,discount_value,event_date\n"
        "lpoint_1,cus_1,,New Customer,100,100,0,2026-01-01\n"
        "lpoint_2,cus_1,500,Points Redeemed,1312,-1312,0,2026-11-10\n"),
}


def typed(kind, value):
    """CSV text -> the Python value Postgres would return for that column (to simulate Supabase)."""
    if value == "":
        return None
    if value in ("true", "false"):
        return value == "true"
    if kind == "date":
        return dt.date.fromisoformat(value)
    if kind == "ts":
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    try:
        return Decimal(value)
    except ArithmeticError:
        return value


class SupabaseImportTests(TestCase):
    """The TD sample served as Supabase rows (typed Postgres values) maps into the warehouse correctly."""

    TEXT = {"order_id", "customer_id", "variant_id", "product_id", "sku", "style", "size", "order_key", "sales_id",
            "ledger_id", "inventory_pk", "location_id", "stock_location", "phone", "pincode", "ts_pincode",
            "gst_number", "udyam_number", "display_id"}

    def rows(self):
        kinds = {"Distributor_Data.csv": "distributor", "Customer_Data.csv": "customer", "Product_Data.csv": "product",
                 "Order_Data.csv": "order", "Sales_Data.csv": "sales", "Inventory_Data.csv": "inventory",
                 "Loyality_Data.csv": "loyalty"}
        out = {}
        for name, body in TD_SAMPLE.items():
            table = Q.TABLES[kinds[name]][0]
            recs = list(csv.DictReader(io.StringIO(body)))
            cols = list(recs[0])
            def conv(c, v):
                if c in self.TEXT:
                    return v or None
                if c.endswith("_date") and c != "launch_date":
                    return typed("date", v)
                if c.endswith("_at") or c == "launch_date":
                    return typed("ts", v)
                return typed("num", v)
            out[table] = (cols, [tuple(conv(c, r[c]) for c in cols) for r in recs])
        return out

    def test_import(self):
        from ingestion.connectors.supabase import SupabaseConnector, SupabaseTdImporter
        from ingestion.models import SyncRun
        from warehouse.models import Distributor, InventorySnapshot, LoyaltyEvent, Order, Retailer

        tables = self.rows()

        def fetch(sql):
            if "etl_watermark" in sql:
                return ["max", "min", "count"], [(dt.datetime(2026, 11, 19, 4, tzinfo=dt.timezone.utc),
                                                  dt.datetime(2026, 11, 19, 3, tzinfo=dt.timezone.utc), 7)]
            table = sql.split(" FROM ")[1].split()[0].strip('"')
            return tables[table]

        SupabaseTdImporter(fetch).run()
        heera = Distributor.objects.get(source_id="td:9")
        a = Order.objects.get(source_id="order_A")
        self.assertEqual((a.display_id, a.status, a.is_qualifying, a.gross_value, a.units),
                         ("500", "delivered", True, Decimal("4312"), 12))
        self.assertEqual((a.distributor_id, a.platform, a.payment_mode), (heera.id, "android", "UPI"))
        self.assertTrue(a.placed_at <= a.shipped_at <= a.delivered_at)
        self.assertEqual(Order.objects.get(source_id="order_B").status, "confirmed")
        self.assertFalse(Order.objects.get(source_id="order_P").is_qualifying)
        self.assertFalse(Retailer.objects.filter(source_id="cus_t").exists())
        self.assertEqual(InventorySnapshot.objects.get(distributor=heera).quantity, 12)
        self.assertEqual(dict(LoyaltyEvent.objects.values_list("event_type", "points")),
                         {"new_customer": 100, "redeemed": -1312})
        self.assertEqual(LoyaltyEvent.objects.get(event_type="redeemed").order_id, a.id)
        self.assertEqual(Distributor.objects.filter(name="Ankit Jain").count(), 2)  # same name, two ids
        self.assertEqual(Order.objects.get(source_id="order_B").ts_order_status, "packed")

        SupabaseTdImporter(fetch).run()  # re-import is idempotent
        self.assertEqual((Order.objects.count(), a.lines.count(), LoyaltyEvent.objects.count()), (3, 1, 2))

        # the connector imports, then skips while Supabase's etl_watermark is unchanged
        conn = SupabaseConnector()
        run = SyncRun.objects.create(source="supabase")
        self.assertEqual(conn.sync(run, fetch), 4)  # 3 orders + 1 retailer
        run2 = SyncRun.objects.create(source="supabase")
        self.assertEqual(conn.sync(run2, fetch), 0)
        self.assertTrue(run2.details["unchanged"])


class ImportLockTests(SimpleTestCase):
    """Only one import at a time across processes: a second taker is told to skip; the lock is released after."""

    def test_second_import_skips(self):
        import tempfile
        from unittest import mock

        from ingestion import locks

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(locks, "lock_path", return_value=__import__("pathlib").Path(d, "x.lock")):
            with locks.import_lock() as first:
                self.assertTrue(first)
                with locks.import_lock() as second:
                    self.assertFalse(second)
            with locks.import_lock() as again:
                self.assertTrue(again)


class AutoRefreshSchedulerTests(TestCase):
    """The server's built-in schedule: refresh after each SYNC_TIMES slot once (catching up if the server was off),
    never twice for one slot, and the target forecast from the 27th."""

    def setUp(self):
        from ingestion import scheduler

        scheduler._last_attempt.clear()

    def at(self, y, mo, d, h, mi=0):
        from django.utils import timezone

        return timezone.make_aware(dt.datetime(y, mo, d, h, mi))

    def test_refresh_due_after_a_slot_until_one_runs(self):
        from django.test import override_settings

        from ingestion.models import SyncRun
        from ingestion.scheduler import refresh_due
        from ingestion.schedule import REFRESH_SOURCE

        with override_settings(SYNC_TIMES=[(10, 0), (18, 0)]):
            self.assertEqual(refresh_due(self.at(2026, 11, 19, 10, 5)), self.at(2026, 11, 19, 10))
            # server off all morning: still due at 14:00 (catch-up), for the 10:00 slot
            self.assertEqual(refresh_due(self.at(2026, 11, 19, 14)), self.at(2026, 11, 19, 10))
            SyncRun.objects.create(source=REFRESH_SOURCE, status="failed", started_at=self.at(2026, 11, 19, 10, 1))
            self.assertIsNone(refresh_due(self.at(2026, 11, 19, 14)))  # ran (even if it failed): not again
            self.assertEqual(refresh_due(self.at(2026, 11, 19, 18, 1)), self.at(2026, 11, 19, 18))
            # a Supabase-only import does not count as the full refresh
            SyncRun.objects.create(source=REFRESH_SOURCE, status="success", started_at=self.at(2026, 11, 19, 18, 2),
                                   details={"via": "supabase_live"})
            self.assertEqual(refresh_due(self.at(2026, 11, 19, 18, 5)), self.at(2026, 11, 19, 18))

    def test_tick_runs_the_refresh_once(self):
        from unittest import mock

        from django.test import override_settings

        from ingestion import scheduler
        from ingestion.models import SyncRun
        from ingestion.schedule import REFRESH_SOURCE

        def fake_refresh(*a, **k):
            SyncRun.objects.create(source=REFRESH_SOURCE, status="success", started_at=now)

        now = self.at(2026, 11, 19, 10, 1)
        with override_settings(SYNC_TIMES=[(10, 0), (18, 0)]), \
                mock.patch("django.core.management.call_command", side_effect=fake_refresh) as cc, \
                mock.patch.object(scheduler, "forecast_due", return_value=None):
            self.assertEqual(scheduler.tick(now), ["refresh"])
            self.assertEqual(scheduler.tick(now + dt.timedelta(minutes=1)), [])  # already ran for 10:00
            self.assertEqual(cc.call_count, 1)

    def test_forecast_due_from_the_27th(self):
        from warehouse.models import TargetForecast
        from ingestion.scheduler import forecast_due

        self.assertIsNone(forecast_due(self.at(2026, 11, 26, 23)))
        self.assertIsNone(forecast_due(self.at(2026, 11, 27, 10)))
        self.assertEqual(forecast_due(self.at(2026, 11, 27, 11)), dt.date(2026, 12, 1))
        self.assertEqual(forecast_due(self.at(2026, 11, 30, 9)), dt.date(2026, 12, 1))  # catch-up
        TargetForecast.objects.create(month=dt.date(2026, 12, 1), scope_type="overall", value=1,
                                      as_of=dt.date(2026, 11, 27))
        self.assertIsNone(forecast_due(self.at(2026, 11, 28, 12)))
