import datetime as dt
import re

from django.test import SimpleTestCase, TestCase

from ingestion.connectors import medusa_queries as Q
from ingestion.connectors.medusa import STATE_TO_REGION, clean_state, map_order_status

NOW = dt.datetime(2026, 11, 12, tzinfo=dt.timezone.utc)


class OrderStatusMappingTests(SimpleTestCase):
    def test_cancelled_wins(self):
        self.assertEqual(map_order_status("canceled", "not_fulfilled", None, None, None), "cancelled")
        self.assertEqual(map_order_status("pending", "shipped", NOW, None, None, "CANCELLED"), "cancelled")

    def test_delivered_and_shipped(self):
        self.assertEqual(map_order_status("completed", "shipped", NOW, NOW, NOW), "delivered")
        self.assertEqual(map_order_status("pending", "not_fulfilled", None, None, None, "delivered"), "delivered")
        self.assertEqual(map_order_status("pending", "not_fulfilled", NOW, None, None), "shipped")
        self.assertEqual(map_order_status("pending", "not_fulfilled", None, None, None, "dispatched"), "shipped")

    def test_confirmed_and_received(self):
        self.assertEqual(map_order_status("pending", "fulfilled", None, None, None), "confirmed")
        self.assertEqual(map_order_status("pending", "not_fulfilled", None, None, None, "packed"), "confirmed")
        self.assertEqual(map_order_status("pending", "not_fulfilled", None, None, None, "placed"), "received")


class GeographyTests(SimpleTestCase):
    def test_state_cleaning(self):
        self.assertEqual(clean_state("  KARNATAKA "), "Karnataka")
        self.assertEqual(clean_state("ORISSA"), "Odisha")
        self.assertEqual(clean_state("Jammu & Kashmir"), "Jammu And Kashmir")
        self.assertEqual(clean_state(None), "")

    def test_default_regions(self):
        self.assertEqual(STATE_TO_REGION["karnataka"], "South")
        self.assertEqual(STATE_TO_REGION["odisha"], "East & North-East")


class MedusaSqlTests(SimpleTestCase):
    """Static checks: the queries run with psycopg pyformat params, so every literal % must be doubled."""

    QUERIES = {n: getattr(Q, n) for n in dir(Q) if n.endswith("_SQL")}

    def test_placeholders_are_known(self):
        allowed = {"since", "div", "naive_tz"}
        for name, sql in self.QUERIES.items():
            used = set(re.findall(r"%\((\w+)\)s", sql))
            self.assertTrue(used <= allowed, f"{name} uses unknown params {used - allowed}")

    def test_no_bare_percent(self):
        for name, sql in self.QUERIES.items():
            stripped = re.sub(r"%\(\w+\)s|%%", "", sql)
            self.assertNotIn("%", stripped, f"{name} has an unescaped % sign")

    def test_no_select_star(self):
        """The read-only role has column-level grants on some tables, so `*` would be rejected."""
        for name, sql in self.QUERIES.items():
            self.assertIsNone(re.search(r"(\w+\.)?\*\s+FROM|SELECT\s+\*", sql, re.I), f"{name} uses SELECT *")

    def test_never_selects_secrets(self):
        secret = re.compile(r"password_hash|tc_api_token|\bsalt\b|merchant_id|razorpay_id|\"user\"", re.I)
        for name, sql in self.QUERIES.items():
            code = "\n".join(line.split("--")[0] for line in sql.splitlines())
            self.assertIsNone(secret.search(code), f"{name} references a secret column")


class CsvImportTests(TestCase):
    """End-to-end import of tiny versions of the five TD_*.csv exports."""

    FILES = {
        "TD_Customer_Data.csv": (
            "id,email,first_name,last_name,phone,has_account,created_at,updated_at,deleted_at,gst_number,"
            "business_name,ts_pincode,ts_preferred,kyc,udyam_number,distributor_name\n"
            "cus_1,a@x.in,Ravi,K,9000000001,TRUE,09/25/2023 14:29:34,09/24/2026 06:23:58,,29ABCDE1234F1Z5,"
            "RAVI SPORTS,560064,FALSE,TRUE,,\"HEERA EXPORTS INC, Zealous Ventures\"\n"
            "cus_2,,,,9000000002,FALSE,10/10/2023 09:05:26,10/11/2023 05:11:03,,,,888888,FALSE,FALSE,,\n"),
        "TD_product data.csv": (
            "product_id,style,product_title,launch_date,variant_id,size,price,category_level_1,category_level_2,"
            "category_level_3\n"
            "prod_1,OR67,OR67 Tee,09/23/2023 09:20:20,var_1,M,3594,men,topwear,t-shirts\n"
            "prod_2,OR67,OR67 Tee relaunch,09/23/2026 09:20:20,var_2,M,3594,men,topwear,t-shirts\n"),
        "TD_Inventory_Data.csv": (
            "Style,Product_id,Size,SKU,Piece Per Unit,Distributor,Stock\n"
            "OR67,prod_1,M,SKU-OR67-M,6,Heera,12\nOR67,prod_1,M,SKU-OR67-M,6,Zealous,0\n"),
        "TD_Sales_Data.csv": (
            "order_id,timestamp,Dispatch Date,Delivered Date,id,product_id,retailer_name,style,size,quantity,"
            "distributor,line_item_amount,total_amount,mode,contact,city,country_code,province,ts_pincode,"
            "gst_number,udyam_number,platform\n"
            "500,2026-11-10 05:00:00.000,2026-11-10,,cus_1,prod_1,Ravi,OR67,M,2,HEERA EXPORTS INC,4312,4612,UPI,"
            "9000000001,bengaluru,in,Karnataka,560064,,,android\n"),
        "TD_Loyality_Point.csv": (
            "customer_id,total_points,Event Date,first_name,business_name,phone,Order Id,Event\n"
            "cus_1,100,05-12-2025,Ravi,RAVI SPORTS,9000000001,,New Customer\n"
            "cus_1,43,10-11-2026,Ravi,RAVI SPORTS,9000000001,500,Points Earned\n"
            "cus_1,50,11-11-2026,Ravi,RAVI SPORTS,9000000001,,Points Redeemed\n"),
    }

    def setUp(self):
        import tempfile
        from pathlib import Path

        self.tmp = tempfile.TemporaryDirectory()
        for name, body in self.FILES.items():
            Path(self.tmp.name, name).write_text(body, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_import(self):
        from decimal import Decimal

        from ingestion.csv_import import CsvImporter
        from warehouse.models import (Distributor, InventorySnapshot, LoyaltyEvent, Order, Product,
                                      ProductVariant, Retailer)

        result = CsvImporter(self.tmp.name).run()
        self.assertEqual(result["warnings"], [])
        heera = Distributor.objects.get(name="Heera Exports Inc")
        self.assertIn("Heera", heera.aliases)
        self.assertEqual(heera.state.name, "Karnataka")
        self.assertEqual(InventorySnapshot.objects.get(distributor=heera).quantity, 12)

        r1, r2 = Retailer.objects.get(source_id="cus_1"), Retailer.objects.get(source_id="cus_2")
        self.assertEqual((r1.kyc_status, r1.distributor_id, r1.state.name), ("approved", heera.id, "Karnataka"))
        self.assertEqual((r2.kyc_status, r2.state), ("not_submitted", None))

        self.assertEqual(Product.objects.filter(style="OR67").count(), 2)  # relaunch reuses the style
        v = ProductVariant.objects.get(source_id="var_1")
        self.assertEqual((v.sku, v.mrp, v.price), ("SKU-OR67-M", Decimal("599.00"), Decimal("359.40")))

        o = Order.objects.get(display_id="500")
        self.assertEqual((o.status, o.is_qualifying, o.units, o.gross_value), ("shipped", True, 12, Decimal("4612")))
        line = o.lines.get()
        self.assertEqual((line.boxes, line.pieces_per_box, line.quantity, line.unit_price),
                         (2, 6, 12, Decimal("359.33")))
        self.assertGreaterEqual(o.shipped_at, o.placed_at)

        pts = dict(LoyaltyEvent.objects.values_list("event_type", "points"))
        self.assertEqual(pts, {"new_customer": 100, "earned": 43, "redeemed": -50})
        self.assertEqual(LoyaltyEvent.objects.get(event_type="earned").order_id, o.id)

        CsvImporter(self.tmp.name).run()  # re-import is idempotent
        self.assertEqual((Order.objects.count(), LoyaltyEvent.objects.count(), Retailer.objects.count()), (1, 3, 2))


class AdoptCsvDistributorTests(TestCase):
    def test_medusa_sync_adopts_csv_distributor(self):
        from ingestion.connectors.medusa import MedusaConnector
        from warehouse.models import Distributor

        d = Distributor.objects.create(code="HEERAEXPOR", name="Heera Exports Inc", source_id="name:heeraexportsinc",
                                       aliases=["Heera"])
        rows = [{"source_id": "tcd_1", "code": "TCD1", "name": "HEERA EXPORTS INC"},
                {"source_id": "tcd_2", "code": "TCD2", "name": "New Distributor"}]
        MedusaConnector._adopt_csv_distributors(rows)
        d.refresh_from_db()
        self.assertEqual((d.source_id, rows[0]["code"], rows[1]["code"]), ("tcd_1", "HEERAEXPOR", "TCD2"))
