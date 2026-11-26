import datetime as dt
from collections import defaultdict

from django.conf import settings
from django.db.models import Count, F, Max, Min, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from accounts.permissions import HasPerm
from accounts.scope import DISTRIBUTOR_DIMS, INVENTORY_DIMS
from warehouse.models import Distributor, InventorySnapshot, OrderLine, Product, primary_inventory

from ..export import ExportListMixin
from ..filters import add_months, month_start, parse_filters
from ..styles import base_style, expand
from ..metrics import mkey, num, ratio, share, spark_months
from .base import AnalyticsView
from .funnel import resolve_ordering


def line_qs(f, start, end):
    # the lines are filtered by category / article here, so the orders need not be pre-filtered the same way
    orders = f.orders(start=start, end=end, line_match=False)
    return OrderLine.objects.filter(order__in=orders).filter(f.lines_q())


def style_launches(f):
    """{style: first launch date} from the catalogue, with the page's category / style filters."""
    return {r["style"]: r["first"] for r in Product.objects.filter(f.lines_q(prefix="")).exclude(style="").filter(
        launched_on__isnull=False).values("style").annotate(first=Min("launched_on"))}


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
            return {"style": r["style"], "code": base_style(r["style"]), "name": r["product__name"], "category": r["product__category__name"],
                    "sales": num(r["s"]), "units": r["u"] or 0, "orders": r["o"], "retailers": r["r"],
                    "share": share(r["s"], total), "realisation": ratio(r["s"], r["u"]),
                    "units_per_order": ratio(r["u"], r["o"])}

        sold = [a for a in arts if (a["s"] or 0) > 0]
        # New launches: styles whose FIRST launch date (catalogue launch_date, as for new arrivals in the app) falls in
        # the last 90 days. A style re-listed later (a new product entry for OR89, say) keeps its first launch date.
        launch_cut = p.end - dt.timedelta(days=90)
        firsts = style_launches(f)
        new_styles90 = {st: d for st, d in firsts.items() if launch_cut <= d <= p.end}
        names = dict(Product.objects.filter(style__in=new_styles90).order_by("launched_on").values_list("style", "name"))
        nl = {r["style"]: r for r in OrderLine.objects.filter(
            order__in=f.orders(start=launch_cut, end=p.end), style__in=new_styles90).values("style").annotate(
            s=Sum("total"), u=Sum("quantity"), r=Count("order__retailer_id", distinct=True))}
        new_launches = sorted([{
            "style": st, "name": names.get(st), "launched_on": d.isoformat(),
            "sales": num(nl.get(st, {}).get("s")), "units": nl.get(st, {}).get("u") or 0,
            "retailers": nl.get(st, {}).get("r") or 0,
        } for st, d in new_styles90.items()], key=lambda x: -x["sales"])

        sizes = list(lines.values("size").annotate(u=Sum("quantity")).order_by("-u"))
        tot_u = sum(s["u"] or 0 for s in sizes)
        size_mix = [{"size": s["size"] or "NA", "units": s["u"] or 0, "share": share(s["u"], tot_u)} for s in sizes]

        # Category I x Category II (deck slide 47): value, units, share, realisation, units per order
        category_mix = [{
            "l1": r["product__category_l1"] or "Unclassified", "l2": r["product__category_l2"] or "Unclassified",
            "sales": num(r["s"]), "units": r["u"] or 0, "orders": r["o"], "share": share(r["s"], total),
            "realisation": ratio(r["s"], r["u"]), "units_per_order": ratio(r["u"], r["o"]),
        } for r in lines.values("product__category_l1", "product__category_l2").annotate(
            s=Sum("total"), u=Sum("quantity"), o=Count("order_id", distinct=True)).order_by("-s")]
        mix_l1l2 = [{"month": mkey(r["m"]), "l1": r["product__category_l1"] or "Unclassified",
                     "l2": r["product__category_l2"] or "Unclassified", "sales": num(r["s"])}
                    for r in line_qs(f, months12[0], p.end).annotate(m=TruncMonth("order__placed_date")).values(
                        "m", "product__category_l1", "product__category_l2").annotate(s=Sum("total")).order_by("m")]

        # Category I by region (requirements 4.6: product performance by region): each region's sales of a category
        # and that category's share of the region's sales
        reg_tot = {r["order__region__name"]: float(r["s"] or 0) for r in lines.values("order__region__name")
                   .annotate(s=Sum("total"))}
        category_by_region = [{
            "region": r["order__region__name"] or "Unmapped", "l1": r["product__category_l1"] or "Unclassified",
            "sales": num(r["s"]), "units": r["u"] or 0, "realisation": ratio(r["s"], r["u"]),
            "share_of_region": share(r["s"], reg_tot.get(r["order__region__name"])),
        } for r in lines.values("order__region__name", "product__category_l1").annotate(
            s=Sum("total"), u=Sum("quantity")).order_by("order__region__name", "-s")]

        # New articles: launched in the last 6 months (deck slide 61). "New" follows the product's launch date in the
        # catalogue (new arrivals in the app), not the date it first sold or was synced; same category / style filters.
        six_start = add_months(month_start(p.end), -5)
        new_styles = [st for st, d in firsts.items() if six_start <= d <= p.end]
        win = line_qs(f, six_start, p.end)
        win_total = float(win.aggregate(s=Sum("total"))["s"] or 0)
        new_sales = float(win.filter(style__in=new_styles).aggregate(s=Sum("total"))["s"] or 0)
        new_articles_6m = {"since": six_start.isoformat(), "articles": len(new_styles), "sales": num(new_sales),
                           "share": share(new_sales, win_total)}

        sales_sorted = [float(a["s"] or 0) for a in sold]
        return {
            **style_view(f, months12),
            "categories": cats, "category_mix_monthly": mix,
            "top_articles": [art(a) for a in sold[:20]],
            "bottom_articles": [art(a) for a in sorted(sold, key=lambda a: a["s"])[:20]],
            "new_launches": new_launches, "size_mix": size_mix,
            "category_mix": category_mix, "category_mix_monthly_l1l2": mix_l1l2, "new_articles_6m": new_articles_6m,
            "category_by_region": category_by_region,
            "concentration": {"top4_share": share(sum(sales_sorted[:4]), total),
                              "top12_share": share(sum(sales_sorted[:12]), total),
                              "distinct_articles": len(sold)},
        }


def style_view(f, months12):
    """Style filter on: each selected style this period vs the comparison period, and its last 12 months.

    Line values, so an order with several styles counts only the selected style's lines. Orders and retailers are
    distinct per style (a retailer buying two selected styles counts once for each)."""
    if not f.articles:
        return {"selected_styles": None, "style_monthly": None}
    from ..styles import catalog

    p = f.period
    cat = catalog()

    def period_rows(start, end):
        out = {}
        for r in line_qs(f, start, end).values("style").annotate(
                sales=Sum("total"), units=Sum("quantity")):
            e = out.setdefault(base_style(r["style"]), {"sales": 0.0, "units": 0})
            e["sales"] += float(r["sales"] or 0)
            e["units"] += r["units"] or 0
        # distinct orders / retailers need the base code in the query: count over all variants of each code
        for code in out:
            agg = line_qs(f, start, end).filter(style__in=expand([code])).aggregate(
                o=Count("order_id", distinct=True), r=Count("order__retailer_id", distinct=True))
            out[code].update(orders=agg["o"], retailers=agg["r"])
        return out

    cur = period_rows(p.start, p.end)
    prev = period_rows(p.cmp_start, p.cmp_end) if p.cmp_start and p.cmp_end else {}
    total = float(line_qs(f, p.start, p.end).aggregate(s=Sum("total"))["s"] or 0)
    selected = []
    for code in f.articles:
        c, pv, meta = cur.get(code, {}), prev.get(code), cat.get(code, {})
        sales = c.get("sales", 0.0)
        selected.append({
            "code": code, "name": meta.get("name", ""), "l1": meta.get("l1", ""), "l2": meta.get("l2", ""),
            "l3": meta.get("l3", ""), "known": code in cat,
            "sales": num(sales), "units": c.get("units", 0), "orders": c.get("orders", 0),
            "retailers": c.get("retailers", 0), "share": share(sales, total),
            "realisation": ratio(sales, c.get("units")), "units_per_order": ratio(c.get("units"), c.get("orders")),
            "prev_sales": num(pv["sales"]) if pv else (0 if p.cmp_start else None),
            "prev_units": pv["units"] if pv else (0 if p.cmp_start else None),
        })
    monthly = defaultdict(lambda: {"sales": 0.0, "units": 0})
    for r in line_qs(f, months12[0], p.end).annotate(m=TruncMonth("order__placed_date")).values(
            "m", "style").annotate(s=Sum("total"), u=Sum("quantity")):
        e = monthly[(mkey(r["m"]), base_style(r["style"]))]
        e["sales"] += float(r["s"] or 0)
        e["units"] += r["u"] or 0
    style_monthly = [{"month": mkey(m), "code": code, "sales": num(monthly[(mkey(m), code)]["sales"]),
                      "units": monthly[(mkey(m), code)]["units"]}
                     for m in months12 for code in f.articles]
    return {"selected_styles": selected, "style_monthly": style_monthly}


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
        qs = qs.filter(style__in=expand(f.articles))
    if f.categories:
        qs = qs.filter(product__category_l1__in=f.categories)
    for lvl, vals in ((1, f.cat_l1), (2, f.cat_l2), (3, f.cat_l3)):
        if vals:
            qs = qs.filter(**{f"product__category_l{lvl}__in": vals})
    if f.sizes:
        qs = qs.filter(size__in=f.sizes)
    return qs


SOLD_WINDOWS = (30, 60, 90)


def sold_days(request):
    """The Inventory page's "units sold" window: ?sold_days=30|60|90 (default 30)."""
    raw = request.query_params.get("sold_days") or "30"
    if not raw.isdigit() or int(raw) not in SOLD_WINDOWS:
        raise ValidationError({"sold_days": f"must be one of {SOLD_WINDOWS}"})
    return int(raw)


def units_last_30d(f, days=30):
    """{(distributor_id, sku): units} sold in the last `days` days up to today (IST)."""
    start = f.today - dt.timedelta(days=days - 1)
    return {(r["order__distributor_id"], r["sku"]): r["u"] for r in OrderLine.objects.filter(
        order__in=f.orders(start=start, end=f.today)).values("order__distributor_id", "sku").annotate(
        u=Sum("quantity"))}


class InventoryView(AnalyticsView):
    permission_code = "view_inventory"
    sources = ["channel_konnect", "supabase"]
    export_key = "oos_top_sellers"

    def cache_extra(self, request, **kwargs):
        return f"{super().cache_extra(request, **kwargs)}|sold={sold_days(request)}"

    def compute(self, f, request, **kw):
        days = sold_days(request)
        low = settings.LOW_STOCK_THRESHOLD
        dists = Distributor.objects.filter(f.dims_q(DISTRIBUTOR_DIMS, retailer_field=None), is_active=True,
                                           bo_only=False)
        inv = latest_inventory(f)
        per = {r["distributor_id"]: r for r in inv.values("distributor_id").annotate(
            last=Max("synced_at"), skus=Count("id"), instock=Count("id", filter=Q(quantity__gt=0)))}
        from .. import stocksync

        dlist = list(dists.order_by("name"))
        synced = stocksync.last_sync([d.id for d in dlist])  # sheet "Inventory Updated" date, else import time
        sync = []
        for d in dlist:
            r = per.get(d.id)
            last = synced.get(d.id)
            b = stocksync.bucket(last, f.today)
            sync.append({
                "distributor_id": d.id, "distributor": d.name,
                "last_sync_at": stocksync.iso(last), **stocksync.info(d),
                "status": {"fresh": "ok", "stale": "stale", "never": "never"}[b],
                "skus": r["skus"] if r else 0, "in_stock_skus": r["instock"] if r else 0,
            })
        summary = {
            "live_styles": inv.filter(quantity__gt=0).values("style").distinct().count(),
            "oos_skus": inv.filter(quantity__lte=0).count(),
            "low_stock_skus": inv.filter(quantity__gt=0, quantity__lte=low).count(),
        }
        sold = units_last_30d(f, days)
        names = dict(dists.values_list("id", "name"))
        oos = []
        for did, sku, style, size, important in inv.filter(quantity__lte=0).values_list(
                "distributor_id", "sku", "style", "size", "product__is_important"):
            u = sold.get((did, sku), 0)
            if u > 0 or important:
                oos.append({"style": style, "size": size, "sku": sku, "distributor_id": did,
                            "distributor": names.get(did), "units_sold": u, "important": bool(important)})
        oos.sort(key=lambda x: (-x["units_sold"], not x["important"]))
        return {"sync": sync, "summary": summary, "oos_top_sellers": oos[:100], "sold_days": days}


OOS_STYLES_MAX = 40


class InventoryOosStylesView(AnalyticsView):
    """Top-selling styles that are out of stock somewhere, and at which distributors.

    Ranking: units sold (base style) over the last `sold_days` days in the selected territory. A style is listed when at
    least one distributor carries it (has a stock row) with every unit of a size at zero. Per distributor: the sizes at
    zero, units of the style it sold in the window (demand at that counter), its state / region / ASM / RSM.
    Territory filters come from the card (region / rsm / state / asm), on top of the page filters.
    """

    permission_code = "view_inventory"
    sources = ["channel_konnect", "supabase"]
    export_key = "styles"

    def cache_extra(self, request, **kwargs):
        return f"{super().cache_extra(request, **kwargs)}|sold={sold_days(request)}"

    def compute(self, f, request, **kw):
        from ..rsm import region_rsm_map

        days = sold_days(request)
        start = f.today - dt.timedelta(days=days - 1)
        lines = OrderLine.objects.filter(order__in=f.orders(start=start, end=f.today)).filter(f.lines_q())
        sold_style, sold_dist = defaultdict(int), defaultdict(int)
        for did, style, u in lines.values_list("order__distributor_id", "style").annotate(u=Sum("quantity")).values_list(
                "order__distributor_id", "style", "u"):
            code = base_style(style) or style
            sold_style[code] += u or 0
            sold_dist[(did, code)] += u or 0

        inv = latest_inventory(f)
        carried, oos = defaultdict(set), defaultdict(lambda: defaultdict(list))
        meta = {}
        for did, style, size, qty, name, l3 in inv.values_list("distributor_id", "style", "size", "quantity",
                                                              "product__name", "product__category_l3"):
            code = base_style(style) or style
            carried[code].add(did)
            meta.setdefault(code, (name, l3))
            if qty <= 0:
                oos[code][did].append(size or "-")

        ranked = sorted((c for c in oos if sold_style.get(c)), key=lambda c: -sold_style[c])[:OOS_STYLES_MAX]
        dids = {d for c in ranked for d in oos[c]}
        reg_rsm = region_rsm_map()
        from warehouse.models import Rsm

        rsm_names = dict(Rsm.objects.values_list("id", "name"))
        dinfo = {}
        for d in Distributor.objects.filter(id__in=dids).select_related("state", "region", "asm"):
            rid = d.asm.rsm_id if d.asm_id and d.asm.rsm_id else reg_rsm.get(d.region_id)
            dinfo[d.id] = {"distributor_id": d.id, "distributor": d.name,
                           "state": d.state.name if d.state_id else None, "region": d.region.name if d.region_id else None,
                           "asm": d.asm.name if d.asm_id else None, "rsm": rsm_names.get(rid)}

        def size_key(x):
            order = ["XS", "S", "M", "L", "XL", "XXL", "2XL", "3XL", "4XL", "5XL"]
            return (order.index(x) if x in order else 99, x)

        styles = []
        for code in ranked:
            name, l3 = meta.get(code, (None, None))
            dl = []
            for did, sizes in oos[code].items():
                if did not in dinfo:
                    continue
                dl.append({**dinfo[did], "sizes": sorted(set(sizes), key=size_key),
                           "units_sold": sold_dist.get((did, code), 0)})
            dl.sort(key=lambda x: (-x["units_sold"], -len(x["sizes"]), x["distributor"]))
            styles.append({
                "style": code, "name": name, "category": ((l3 or "").title() if (l3 or "").lower() in ("t-shirts", "gym-vests") else (l3 or "").replace("-", " ").title()) or None,
                "units_sold": sold_style[code], "distributors_carrying": len(carried[code]),
                "distributors_oos": len(dl), "distributors_oos_with_demand": sum(1 for x in dl if x["units_sold"]),
                "oos_lines": sum(len(x["sizes"]) for x in dl), "distributors": dl,
            })
        cats = defaultdict(lambda: {"styles": 0, "distributors": set(), "units": 0})
        for st in styles:
            c = cats[st["category"] or "Uncategorised"]
            c["styles"] += 1
            c["units"] += st["units_sold"]
            c["distributors"].update(x["distributor_id"] for x in st["distributors"])
        by_category = sorted([{"category": k, "styles": v["styles"], "distributors": len(v["distributors"]),
                               "units_sold": v["units"]} for k, v in cats.items()], key=lambda x: -x["units_sold"])
        return {"styles": styles, "by_category": by_category, "sold_days": days}


class _InvRows:
    def __init__(self, instance, many=False, sold=None, **kw):
        low = settings.LOW_STOCK_THRESHOLD
        sold = sold or {}
        items = instance if many else [instance]
        self.data = [{
            "id": i.id, "distributor_id": i.distributor_id, "distributor": i.distributor.name,
            "style": i.style, "name": i.product.name if i.product_id else None, "size": i.size, "sku": i.sku,
            "category": (" · ".join(x for x in (i.product.category_l1, i.product.category_l3 or i.product.category_l2) if x)
                         or None) if i.product_id else None,
            "quantity": i.quantity,
            "stock_status": "oos" if i.quantity <= 0 else ("low_stock" if i.quantity <= low else "in_stock"),
            "units_sold": sold.get((i.distributor_id, i.sku), 0),
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
            self._sold = units_last_30d(self.filters, sold_days(self.request))
        return _InvRows(*args, sold=self._sold, **kwargs)


__all__ = ["F", "defaultdict"]
