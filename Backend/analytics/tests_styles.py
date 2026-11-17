"""Style filter: base codes cover colour / batch / case variants, and sales are the selected styles' line values."""
from decimal import Decimal

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from accounts.models import User
from accounts.testing import jwt_login
from warehouse.models import Order, OrderLine, Product

from .styles import base_style, expand
from .tests import make_world


class BaseStyleTests(SimpleTestCase):
    def test_variants_collapse_to_the_code(self):
        for raw, code in (("OR99", "OR99"), ("OR99/B11", "OR99"), ("OR35 Black", "OR35"), ("or10", "OR10"),
                          ("OR10-old12", "OR10"), ("S101-BLACK,NAVY,GREY", "S101"), ("S103 (WHITE)", "S103"),
                          ("OR09A Navy", "OR09A"), ("CR779  BLACK", "CR779"), (" A101 ", "A101")):
            self.assertEqual(base_style(raw), code, raw)


class StyleFilterTests(TestCase):
    def setUp(self):
        cache.clear()
        self.w = make_world()
        User.objects.create_superuser(email="s@test.local", password="x-Strong-pass1")
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION="Bearer " + jwt_login(self.c, "s@test.local", "x-Strong-pass1")["access"])
        p99 = Product.objects.create(style="OR99", name="OR99 Cargo pant", category_l1="men", category_l3="trackpants")
        p99b = Product.objects.create(style="OR99/B11", name="OR99/B11 Cargo pant plus", category_l1="men")
        p35 = Product.objects.create(style="OR35 Black", name="OR35 Tee", category_l1="men", category_l3="tshirts")
        o1, o2 = Order.objects.order_by("id")[:2]  # ret1's orders: 2 and 40 days ago
        # o1 mixes styles: only OR99 lines may count as OR99 sales
        for o, prod, total, q in ((o1, p99, 1000, 10), (o1, p99b, 500, 5), (o1, p35, 4000, 20), (o2, p99, 300, 3)):
            OrderLine.objects.create(order=o, product=prod, style=prod.style, quantity=q, total=Decimal(total))

    def test_expand_covers_batches(self):
        self.assertEqual(expand(["or99"]), ["OR99", "OR99/B11"])

    def test_options_list_base_codes(self):
        styles = {s["code"]: s for s in self.c.get("/api/meta/filters/").json()["styles"]}
        self.assertIn("OR99", styles)
        self.assertNotIn("OR99/B11", styles)
        self.assertEqual(styles["OR99"]["name"], "OR99 Cargo pant")  # the bare code names it, not a batch
        self.assertIn("OR35", styles)

    def test_products_line_values_for_selected_style(self):
        d = self.c.get("/api/products/?preset=all_time&article=or99").json()["data"]
        (s,) = d["selected_styles"]
        self.assertEqual(s["code"], "OR99")
        self.assertEqual(s["sales"], 1800)  # 1000 + 500 (batch) + 300; the OR35 line in the same order is excluded
        self.assertEqual(s["units"], 18)
        self.assertEqual(s["orders"], 2)
        self.assertEqual(s["retailers"], 1)
        self.assertEqual(sum(a["sales"] for a in d["top_articles"]), 1800)
        self.assertEqual(sum(m["sales"] for m in d["style_monthly"]), 1800)

    def test_no_style_selected(self):
        d = self.c.get("/api/products/?preset=all_time").json()["data"]
        self.assertIsNone(d["selected_styles"])
