import datetime as dt
from collections import defaultdict

from django.conf import settings
from django.db.models import Count, F, Max, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from accounts.permissions import HasPerm
from accounts.scope import DISTRIBUTOR_DIMS, INVENTORY_DIMS
from warehouse.models import Distributor, InventorySnapshot, OrderLine, Product, primary_inventory

from ..export import ExportListMixin
from ..filters import parse_filters
from ..metrics import mkey, num, ratio, share, spark_months
from .base import AnalyticsView
from .funnel import resolve_ordering


def line_qs(f, start, end):
    orders = f.orders(start=start, end=end)
    return OrderLine.objects.filter(order__in=orders).filter(f.lines_q())


class ProductsView(AnalyticsView):
    permission_code = "view_products"
    export_key = "top_articles"

    def compute(self, f, request, **kw):
        p = f.period
        lines = line_qs(f, p.start, p.end)
        total = float(lines.aggregate(s=Sum("total"))["s"] or 0)
        cats = [{
            "code": r["product__category__code"] or "uncategorised",
            "name": r["product__category__name"] or "Uncategorised",
            "sales": num(r["s"]), "units": r["u"] or 0, "share": share(r["s"], total),
            "realisation": ratio(r["s"], r["u"]),
        } for r in lines.values("product__category__code", "product__category__name").annotate(
            s=Sum("total"), u=Sum("quantity")).order_by("-s")]

        months12 = spark_months(p.end)
        mix = [{"month": mkey(r["m"]), "category": r["product__category__name"] or "Uncategorised",
                "sales": num(r["s"])}
               for r in line_qs(f, months12[0], p.end).annotate(m=TruncMonth("order__placed_date")).values(
                   "m", "product__category__name").annotate(s=Sum("total")).order_by("m")]

        arts = list(lines.values("style", "product__name", "product__category__name").annotate(
            s=Sum("total"), u=Sum("quantity"), o=Count("order_id", distinct=True),
            r=Count("order__retailer_id", distinct=True)).order_by("-s"))

        def art(r):
            return {"style": r["style"], "name": r["product__name"], "category": r["product__category__name"],
                    "sales": num(r["s"]), "units": r["u"] or 0, "orders": r["o"], "retailers": r["r"],
                    "share": share(r["s"], total)}

        sold = [a for a in arts if (a["s"] or 0) > 0]
        launch_cut = p.end - dt.timedelta(days=90)
        new_products = Product.objects.filter(launched_on__gte=launch_cut, launched_on__lte=p.end)
        nl = {r["style"]: r for r in OrderLine.objects.filter(
            order__in=f.orders(start=launch_cut, end=p.end), product__in=new_products).values("style").annotate(
            s=Sum("total"), u=Sum("quantity"), r=Count("order__retailer_id", distinct=True))}
        new_launches = sorted([{
            "style": pr.style, "name": pr.name, "launched_on": pr.launched_on.isoformat(),
            "sales": num(nl.get(pr.style, {}).get("s")), "units": nl.get(pr.style, {}).get("u") or 0,
            "retailers": nl.get(pr.style, {}).get("r") or 0,
        } for pr in new_products], key=lambda x: -x["sales"])

        sizes = list(lines.values("size").annotate(u=Sum("quantity")).order_by("-u"))
        tot_u = sum(s["u"] or 0 for s in sizes)
        size_mix = [{"size": s["size"] or "NA", "units": s["u"] or 0, "share": share(s["u"], tot_u)} for s in sizes]

        sales_sorted = [float(a["s"] or 0) for a in sold]
        return {
            "categories": cats, "category_mix_monthly": mix,
            "top_articles": [art(a) for a in sold[:20]],
            "bottom_articles": [art(a) for a in sorted(sold, key=lambda a: a["s"])[:20]],
            "new_launches": new_launches, "size_mix": size_mix,
            "concentration": {"top4_share": share(sum(sales_sorted[:4]), total),
                              "top12_share": share(sum(sales_sorted[:12]), total),
                              "distinct_articles": len(sold)},
        }


TREE_LEVELS = ["category_l1", "category_l2", "category_l3", "style"]


class ProductTreeView(AnalyticsView):
    """Decomposition tree source: line amount + quantity per Category I > II > III > Style.

    Returns flat leaf rows; the client aggregates them up the hierarchy so drill-down needs no extra calls.
    """

    permission_code = "view_products"
    export_key = "rows"

    def compute(self, f, request, **kw):
        p = f.period
        lines = line_qs(f, p.start, p.end)
        rows = []
        for r in lines.values("product__category_l1", "product__category_l2", "product__category_l3",
                              "style", "product__name").annotate(
                s=Sum("total"), u=Sum("quantity"), o=Count("order_id", distinct=True)).order_by("-s"):
            rows.append({
                "l1": (r["product__category_l1"] or "Uncategorised").strip(),
                "l2": (r["product__category_l2"] or "Other").strip(),
                "l3": (r["product__category_l3"] or "Other").strip(),
                "style": r["style"] or "Unknown",
                "name": r["product__name"] or "",
                "amount": num(r["s"]), "quantity": r["u"] or 0, "orders": r["o"],
            })
        return {
            "levels": [{"key": "l1", "label": "Category I"}, {"key": "l2", "label": "Category II"},
                       {"key": "l3", "label": "Category III"}, {"key": "style", "label": "Style"}],
            "total": {"amount": round(sum(x["amount"] for x in rows), 2),
                      "quantity": sum(x["quantity"] for x in rows)},
            "rows": rows,
        }


def latest_inventory(f):
    qs = primary_inventory().filter(is_latest=True).filter(f.dims_q(INVENTORY_DIMS, retailer_field=None))
    if f.articles:
        qs = qs.filter(style__in=f.articles)
    if f.categories:
        qs = qs.filter(product__category__code__in=f.categories)
    return qs


def units_last_30d(f):
    start = f.today - dt.timedelta(days=29)
    return {(r["order__distributor_id"], r["sku"]): r["u"] for r in OrderLine.objects.filter(
        order__in=f.orders(start=start, end=f.today)).values("order__distributor_id", "sku").annotate(
        u=Sum("quantity"))}


class InventoryView(AnalyticsView):
    permission_code = "view_inventory"
    sources = ["channel_konnect", "medusa"]
    export_key = "oos_top_sellers"

    def compute(self, f, request, **kw):
        low = settings.LOW_STOCK_THRESHOLD
        dists = Distributor.objects.filter(f.dims_q(DISTRIBUTOR_DIMS, retailer_field=None), is_active=True)
        inv = latest_inventory(f)
        per = {r["distributor_id"]: r for r in inv.values("distributor_id").annotate(
            last=Max("synced_at"), skus=Count("id"), instock=Count("id", filter=Q(quantity__gt=0)))}
        stale_cut = timezone.now() - dt.timedelta(hours=24)
        sync = []
        for d in dists.order_by("name"):
            r = per.get(d.id)
            last = r["last"] if r else None
            sync.append({
                "distributor_id": d.id, "distributor": d.name,
                "last_sync_at": timezone.localtime(last).isoformat() if last else None,
                "status": "never" if not last else ("ok" if last >= stale_cut else "stale"),
                "skus": r["skus"] if r else 0, "in_stock_skus": r["instock"] if r else 0,
            })
        summary = {
            "live_styles": inv.filter(quantity__gt=0).values("style").distinct().count(),
            "oos_skus": inv.filter(quantity__lte=0).count(),
            "low_stock_skus": inv.filter(quantity__gt=0, quantity__lte=low).count(),
        }
        sold = units_last_30d(f)
        names = dict(dists.values_list("id", "name"))
        oos = []
        for did, sku, style, size, important in inv.filter(quantity__lte=0).values_list(
                "distributor_id", "sku", "style", "size", "product__is_important"):
            u = sold.get((did, sku), 0)
            if u > 0 or important:
                oos.append({"style": style, "size": size, "sku": sku, "distributor_id": did,
                            "distributor": names.get(did), "last_30d_units": u, "important": bool(important)})
        oos.sort(key=lambda x: (-x["last_30d_units"], not x["important"]))
        return {"sync": sync, "summary": summary, "oos_top_sellers": oos[:100]}


class _InvRows:
    def __init__(self, instance, many=False, sold=None, **kw):
        low = settings.LOW_STOCK_THRESHOLD
        sold = sold or {}
        items = instance if many else [instance]
        self.data = [{
            "id": i.id, "distributor_id": i.distributor_id, "distributor": i.distributor.name,
            "style": i.style, "name": i.product.name if i.product_id else None, "size": i.size, "sku": i.sku,
            "quantity": i.quantity,
            "stock_status": "oos" if i.quantity <= 0 else ("low_stock" if i.quantity <= low else "in_stock"),
            "last_30d_units": sold.get((i.distributor_id, i.sku), 0),
            "snapshot_date": i.snapshot_date.isoformat(),
            "synced_at": timezone.localtime(i.synced_at).isoformat(),
        } for i in items]
        if not many:
            self.data = self.data[0]


class InventoryItemsView(ExportListMixin, generics.ListAPIView):
    """Latest stock per distributor x SKU. Extra params: stock_status=oos|low|ok, search, ordering."""

    permission_classes = [IsAuthenticated, HasPerm("view_inventory")]
    export_filename = "inventory"

    def get_queryset(self):
        f = parse_filters(self.request)
        self.filters = f
        q = self.request.query_params
        qs = latest_inventory(f).select_related("distributor", "product")
        st = q.get("stock_status")
        if st == "oos":
            qs = qs.filter(quantity__lte=0)
        elif st in ("low_stock", "low"):
            qs = qs.filter(quantity__gt=0, quantity__lte=settings.LOW_STOCK_THRESHOLD)
        elif st in ("in_stock", "ok"):
            qs = qs.filter(quantity__gt=settings.LOW_STOCK_THRESHOLD)
        if q.get("search"):
            s = q["search"].strip()
            qs = qs.filter(Q(sku__icontains=s) | Q(style__icontains=s) | Q(product__name__icontains=s) |
                           Q(distributor__name__icontains=s))
        fields = {"quantity": "quantity", "style": "style", "size": "size", "sku": "sku", "name": "product__name",
                  "distributor": "distributor__name", "synced_at": "synced_at", "snapshot_date": "snapshot_date",
                  "stock_status": "quantity"}
        order = resolve_ordering(q.get("ordering"), fields, "distributor__name")
        return qs.order_by(*order, "distributor__name", "style", "size")

    def get_serializer(self, *args, **kwargs):
        if not hasattr(self, "_sold"):
            self._sold = units_last_30d(self.filters)
        return _InvRows(*args, sold=self._sold, **kwargs)


__all__ = ["F", "defaultdict"]
