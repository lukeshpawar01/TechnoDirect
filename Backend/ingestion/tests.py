import datetime as dt
import re

from django.test import SimpleTestCase

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
